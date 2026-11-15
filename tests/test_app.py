import pytest
from fastapi.testclient import TestClient

from tiresias.app import create_app
from tiresias.config import Settings
from tiresias.db import connect, migrate, reset_test_data, test_database_url as database_url


@pytest.fixture
def app():
    migrate()
    with connect() as conn:
        reset_test_data(conn)
    settings = Settings(_env_file=None, database_url=database_url(), allow_registration=True,
                        caller_link_secret='test-only-caller-link-secret-at-least-32-characters')
    return create_app(settings)


def register(client, email='person@example.com'):
    client.get('/register')
    csrf=client.cookies.get('tiresias_csrf')
    response=client.post('/register',data={'email':email,'password':'a-long-unique-passphrase','csrf':csrf})
    assert response.status_code == 200
    return client.cookies.get('tiresias_csrf')


def test_account_settings_survive_logout_and_login(app):
    with TestClient(app) as client:
        csrf=register(client)
        preferences={'voice_id':'EXAVITQu4vr4xnSDxMaL','tone':'friendly','speed':0.85}
        assert client.post('/api/preferences',json=preferences,headers={'X-CSRF-Token':csrf}).status_code == 200
        assert client.get('/api/preferences').json()['preferences']==preferences
        assert client.post('/logout',data={'csrf':csrf}).status_code == 200
        client.get('/login')
        client.post('/login',data={'email':'person@example.com','password':'a-long-unique-passphrase',
                                   'csrf':client.cookies.get('tiresias_csrf')})
        assert client.get('/api/preferences').json()['preferences']==preferences


def test_settings_require_authentication_and_csrf(app):
    with TestClient(app) as client:
        assert client.get('/api/preferences').status_code==401
        assert client.post('/api/voice-preview',json={}).status_code==401
        register(client)
        assert client.post('/api/preferences',json={'speed':0.8}).status_code==403
        assert client.get('/api/preferences').json()['preferences']['speed']==1.0


def test_accounts_cannot_change_another_users_preferences(app):
    with TestClient(app) as first, TestClient(app) as second:
        csrf=register(first,'first@example.com')
        register(second,'second@example.com')
        first.post('/api/preferences',json={'tone':'direct'},headers={'X-CSRF-Token':csrf})
        assert second.get('/api/preferences').json()['preferences']['tone']=='calm'


def test_out_of_range_speed_is_rejected_without_overwriting_settings(app):
    with TestClient(app) as client:
        csrf=register(client)
        response=client.post('/api/preferences',json={'speed':4},headers={'X-CSRF-Token':csrf})
        assert response.status_code==422
        assert client.get('/api/preferences').json()['preferences']['speed']==1.0


def test_health_check_and_voice_catalog(app):
    with TestClient(app) as client:
        assert client.get('/healthz').json()['status']=='ok'
        register(client)
        genders={voice['gender'] for voice in client.get('/api/voices').json()['voices']}
        assert {'male','female'}.issubset(genders)


def test_caller_setup_requires_account_csrf_and_real_call_challenge(app):
    from tiresias.caller_links import issue_challenge, linked_preferences
    import uuid
    key='test-only-caller-link-secret-at-least-32-characters'
    with TestClient(app) as client, TestClient(app) as other:
        assert client.get('/api/caller-link').status_code==401
        csrf=register(client)
        other_csrf=register(other,'other@example.com')
        assert client.post('/api/caller-link/request',json={'handle':'+12145550100'}).status_code==403
        request=client.post('/api/caller-link/request',json={'handle':'+12145550100'},headers={'X-CSRF-Token':csrf})
        assert request.status_code==200
        request_id=request.json()['request_id']
        assert client.get('/api/caller-link').json()['pending']['ready'] is False
        with connect() as conn:
            challenge=issue_challenge(conn,handle='+12145550100',key=key,call_id=str(uuid.uuid4()))
        payload={'request_id':request_id,'code':challenge['code']}
        assert other.post('/api/caller-link/confirm',json=payload,headers={'X-CSRF-Token':other_csrf}).status_code==400
        wrong={**payload,'code':'0000' if payload['code']!='0000' else '1111'}
        assert client.post('/api/caller-link/confirm',json=wrong,headers={'X-CSRF-Token':csrf}).status_code==400
        with connect() as conn:
            assert conn.execute('SELECT attempts FROM voice_link_requests WHERE id=%s',(request_id,)).fetchone()['attempts']==1
        assert client.post('/api/caller-link/confirm',json=payload,headers={'X-CSRF-Token':csrf}).status_code==200
        assert client.get('/api/caller-link').json()['linked']['masked_handle'].endswith('0100')
        assert other.get('/api/caller-link').json()['linked'] is None
        assert client.delete('/api/caller-link',headers={'X-CSRF-Token':csrf}).status_code==200
        with connect() as conn:
            assert linked_preferences(conn,handle='+12145550100',key=key) is None


def test_changed_assets_get_new_urls_for_existing_browser_sessions(app,monkeypatch,tmp_path):
    import re
    import shutil
    from tiresias import app as application
    from tiresias.config import Settings
    shutil.copytree(application.ROOT/'static',tmp_path/'static')
    shutil.copytree(application.ROOT/'templates',tmp_path/'templates')
    with TestClient(app) as client:
        register(client)
        first=client.get('/').text
        first_script=re.search(r'src="(/static/app.js\?v=[a-f0-9]+)"',first)
        assert first_script, 'script URL must change when deployed content changes'
        (tmp_path/'static/app.js').write_text('// updated deployment\n',encoding='utf-8')
        monkeypatch.setattr(application,'ROOT',tmp_path)
        next_app=application.create_app(Settings(_env_file=None,database_url=database_url()))
        with TestClient(next_app) as next_client:
            next_client.cookies.update(client.cookies)
            second=next_client.get('/').text
            second_script=re.search(r'src="(/static/app.js\?v=[a-f0-9]+)"',second)
            assert second_script and first_script.group(1)!=second_script.group(1)
            assert '?v=' in second
