from datetime import datetime, timedelta, timezone
import uuid

import pytest

from tests.test_preferences import db, user
from tiresias.caller_links import (
    normalize_handle, start_link, issue_challenge, confirm_link, link_status,
    unlink_caller, linked_preferences, CallerLinkError,
)

KEY='test-only-caller-link-secret-at-least-32-characters'
NOW=datetime(2026,11,15,9,tzinfo=timezone.utc)


def test_normalizes_phone_and_facetime_email_without_accepting_bad_handles():
    assert normalize_handle('(214) 555-0100') == ('phone_number','+12145550100')
    assert normalize_handle('+44 7700 900123') == ('phone_number','+447700900123')
    assert normalize_handle('Person@Example.com') == ('email','person@example.com')
    for value in ['123','', '+000000000','hello', 'a@', 'a\n@example.com']:
        with pytest.raises(CallerLinkError): normalize_handle(value)


def test_call_challenge_links_saved_preferences_for_later_calls(db):
    owner=user(db)
    request=start_link(db,user_id=owner,handle='+12145550100',key=KEY,now=NOW)
    assert 'code' not in request
    assert not link_status(db,user_id=owner,now=NOW)['pending']['ready']
    assert linked_preferences(db,handle='+12145550100',key=KEY) is None
    challenge=issue_challenge(db,handle='+12145550100',key=KEY,call_id=str(uuid.uuid4()),now=NOW)
    assert len(challenge['code'])==4
    assert link_status(db,user_id=owner,now=NOW)['pending']['ready']
    assert confirm_link(db,user_id=owner,request_id=request['request_id'],code=challenge['code'],key=KEY,now=NOW)['verified']
    db.commit()
    from tiresias.db import connect
    with connect() as another_call:
        assert linked_preferences(another_call,handle='+12145550100',key=KEY)['user_id']==owner
    status=link_status(db,user_id=owner,now=NOW)
    assert status['linked']['masked_handle'].endswith('0100')
    assert status['pending'] is None
    assert '+12145550100' not in str(status)


def test_only_call_holder_and_request_owner_can_verify_and_replay_fails(db):
    owner,other=user(db),user(db)
    request=start_link(db,user_id=owner,handle='+12145550100',key=KEY,now=NOW)
    assert not confirm_link(db,user_id=owner,request_id=request['request_id'],code='0000',key=KEY,now=NOW)['verified']
    challenge=issue_challenge(db,handle='+12145550100',key=KEY,call_id=str(uuid.uuid4()),now=NOW)
    assert not confirm_link(db,user_id=other,request_id=request['request_id'],code=challenge['code'],key=KEY,now=NOW)['verified']
    assert confirm_link(db,user_id=owner,request_id=request['request_id'],code=challenge['code'],key=KEY,now=NOW)['verified']
    assert not confirm_link(db,user_id=owner,request_id=request['request_id'],code=challenge['code'],key=KEY,now=NOW)['verified']


def test_wrong_codes_expiry_and_unlink_prevent_auto_loading(db):
    owner=user(db)
    request=start_link(db,user_id=owner,handle='+12145550100',key=KEY,now=NOW)
    challenge=issue_challenge(db,handle='+12145550100',key=KEY,call_id=str(uuid.uuid4()),now=NOW)
    wrong='0000' if challenge['code']!='0000' else '1111'
    for _ in range(5):
        assert not confirm_link(db,user_id=owner,request_id=request['request_id'],code=wrong,key=KEY,now=NOW)['verified']
    assert not confirm_link(db,user_id=owner,request_id=request['request_id'],code=challenge['code'],key=KEY,now=NOW)['verified']
    assert issue_challenge(db,handle='+12145550100',key=KEY,call_id=str(uuid.uuid4()),now=NOW+timedelta(minutes=6)) is None
    request=start_link(db,user_id=owner,handle='+12145550100',key=KEY,now=NOW+timedelta(minutes=7))
    challenge=issue_challenge(db,handle='+12145550100',key=KEY,call_id=str(uuid.uuid4()),now=NOW+timedelta(minutes=7))
    assert confirm_link(db,user_id=owner,request_id=request['request_id'],code=challenge['code'],key=KEY,now=NOW+timedelta(minutes=7))['verified']
    unlink_caller(db,user_id=owner)
    assert linked_preferences(db,handle='+12145550100',key=KEY) is None


def test_pending_link_is_bounded_and_caller_numbers_are_not_stored(db):
    owner,other=user(db),user(db)
    request=start_link(db,user_id=owner,handle='+12145550100',key=KEY,now=NOW)
    with pytest.raises(CallerLinkError):
        start_link(db,user_id=other,handle='+12145550100',key=KEY,now=NOW)
    row=db.execute('SELECT * FROM voice_link_requests WHERE id=%s',(request['request_id'],)).fetchone()
    assert '+12145550100' not in str(row)
    assert row['challenge_hash'] is None


def test_unlink_waits_for_inflight_confirmation_and_removes_its_link(db,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    from tiresias import caller_links
    from tiresias.db import connect
    owner=user(db)
    request=start_link(db,user_id=owner,handle='+12145550100',key=KEY,now=NOW)
    challenge=issue_challenge(db,handle='+12145550100',key=KEY,call_id=str(uuid.uuid4()),now=NOW)
    db.commit()
    locked,release=threading.Event(),threading.Event()
    original=caller_links._digest
    def delayed(key,value):
        if threading.current_thread().name.startswith('confirm') and value.startswith('challenge:'):
            locked.set()
            assert release.wait(5)
        return original(key,value)
    monkeypatch.setattr(caller_links,'_digest',delayed)
    def confirm():
        with connect() as conn:
            return confirm_link(conn,user_id=owner,request_id=request['request_id'],code=challenge['code'],key=KEY,now=NOW)
    with connect() as removing, ThreadPoolExecutor(1,thread_name_prefix='confirm') as verifier, ThreadPoolExecutor(1) as remover:
        future=verifier.submit(confirm)
        try:
            assert locked.wait(2)
            def remove():
                unlink_caller(removing,user_id=owner)
                removing.commit()
            removal=remover.submit(remove)
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                waiting=db.execute('SELECT 1 FROM pg_locks WHERE pid=%s AND NOT granted',(removing.info.backend_pid,)).fetchone()
                if waiting: break
                time.sleep(0.01)
            assert waiting, 'unlink should serialize against in-flight confirmation'
        finally:
            release.set()
        assert future.result(timeout=3)['verified']
        removal.result(timeout=3)
    assert linked_preferences(db,handle='+12145550100',key=KEY) is None
