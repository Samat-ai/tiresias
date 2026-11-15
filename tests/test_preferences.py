import uuid

import pytest
from pydantic import ValidationError

from tiresias.db import connect, migrate, reset_test_data
from tiresias.auth import create_user
from tiresias.security import password_hasher
from tiresias.preferences import VoicePreferences, get_preferences, save_preferences, resolve_profile_code, parse_voice_command


@pytest.fixture
def db():
    conn = connect()
    migrate()
    reset_test_data(conn)
    yield conn
    conn.close()


def user(conn):
    return create_user(conn, email=f'{uuid.uuid4()}@example.com', password='a-secure-test-passphrase', role='USER',
                       hasher=password_hasher(memory_kib=8192,time_cost=1,parallelism=1))['id']


def test_preferences_persist_and_are_isolated_by_account(db):
    first, second = user(db), user(db)
    original = get_preferences(db, first)
    save_preferences(db, first, VoicePreferences(voice_id='EXAVITQu4vr4xnSDxMaL', tone='friendly', speed=0.85))
    db.commit()
    with connect() as other:
        saved = get_preferences(other, first)
        assert saved['preferences'].voice_id == 'EXAVITQu4vr4xnSDxMaL'
        assert saved['preferences'].tone == 'friendly'
        assert saved['preferences'].speed == 0.85
        assert get_preferences(other, second)['preferences'].tone == 'calm'
        assert resolve_profile_code(other, original['profile_code'])['user_id'] == first


@pytest.mark.parametrize('values', [{'speed':0.2},{'speed':2},{'voice_id':'arbitrary-provider-id'},{'tone':'unknown'}])
def test_invalid_preferences_are_rejected(values):
    with pytest.raises(ValidationError):
        VoicePreferences(**values)


def test_profile_code_only_resolves_preferences_not_private_identity(db):
    identity=user(db)
    result=get_preferences(db,identity)
    linked=resolve_profile_code(db,result['profile_code'])
    assert set(linked) == {'user_id','preferences'}
    assert resolve_profile_code(db,'not-a-code') is None


def test_voice_commands_do_not_capture_ordinary_questions():
    assert parse_voice_command('Use a female voice.').updates['voice_id'] == 'EXAVITQu4vr4xnSDxMaL'
    assert parse_voice_command('Use a male voice.').updates['voice_id'] == 'JBFqnCBsd6RMkjVDRZzb'
    assert parse_voice_command('Use a friendly tone.').updates['tone'] == 'friendly'
    assert parse_voice_command('Use profile 1234 5678.').profile_code == '12345678'
    assert parse_voice_command('How many people can you see?') is None


def test_tiger_data_connection_alias_is_supported():
    from tiresias.config import Settings
    settings=Settings(_env_file=None,database_url='',timescale_service_url='postgresql://example/db')
    assert settings.database_url=='postgresql://example/db'


def test_spoken_profile_digits_and_polite_voice_request():
    assert parse_voice_command('Use profile one two three four five six seven eight.').profile_code=='12345678'
    assert parse_voice_command('Could you use a female voice?').updates['voice_id']=='EXAVITQu4vr4xnSDxMaL'
    assert parse_voice_command('Change your voice to male.').updates['voice_id']=='JBFqnCBsd6RMkjVDRZzb'


def test_profile_command_without_digits_is_recognized():
    assert parse_voice_command('Use profile.').profile_code == ''
    assert parse_voice_command('Use my profile code.').profile_code == ''
    assert parse_voice_command('Use profile 354...').profile_code == '354'


def test_profile_entry_collects_paused_digit_groups_and_fillers():
    from tiresias.preferences import ProfileCodeEntry
    entry=ProfileCodeEntry()
    assert entry.consume('Use profile.',now=1).profile_code == ''
    assert entry.consume('Uh, three five four...',now=3).profile_code == '354'
    assert entry.consume('zero two three',now=5).profile_code == '354023'
    assert entry.consume('seven four.',now=7).profile_code == '35402374'
    assert entry.consume('123',now=8) is None


def test_profile_entry_can_repeat_full_code_cancel_or_switch_topic():
    from tiresias.preferences import ProfileCodeEntry
    entry=ProfileCodeEntry()
    entry.consume('Use profile 354',now=1)
    assert entry.consume('35402374',now=2).profile_code == '35402374'
    entry.consume('Use profile',now=3)
    assert entry.consume('Cancel.',now=4).cancel_profile
    assert entry.consume('12345678',now=5) is None
    entry.consume('Use profile',now=6)
    assert entry.consume('How many people can you see?',now=7) is None
    assert entry.consume('12345678',now=8) is None


def test_profile_entry_expires_and_never_guesses_extra_digits():
    from tiresias.preferences import ProfileCodeEntry
    entry=ProfileCodeEntry()
    entry.consume('Use profile',now=1)
    assert entry.consume('12345678',now=60) is None
    assert entry.consume('Use profile 123456789',now=61).profile_code == ''
