"""Voice preferences linked by possession of an inbound FaceTime caller ID.

This module never grants web authentication or access to private call evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
import uuid

from tiresias.preferences import VoicePreferences


class CallerLinkError(ValueError):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status


def normalize_handle(value: str) -> tuple[str,str]:
    if not isinstance(value,str) or len(value)>254 or re.search(r'[\r\n\x00]',value):
        raise CallerLinkError('Enter your FaceTime phone number or email.')
    value=value.strip()
    if '@' in value:
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',value):
            raise CallerLinkError('Enter a valid FaceTime email.')
        return 'email',value.lower()
    phone=re.sub(r'[\s().-]','',value)
    if re.fullmatch(r'[2-9][0-9]{9}',phone):
        phone='+1'+phone
    elif re.fullmatch(r'1[0-9]{10}',phone):
        phone='+'+phone
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}',phone):
        raise CallerLinkError('Include the country code, for example +1 214 555 0100.')
    return 'phone_number',phone


def _digest(key,value):
    if len(key)<32:
        raise CallerLinkError('Automatic caller setup is not configured yet.',503)
    return hmac.new(key.encode(),value.encode(),hashlib.sha256).hexdigest()


def _handle(value,key):
    kind,normalized=normalize_handle(value)
    fingerprint=_digest(key,f'caller:{kind}:{normalized}')
    masked='••• ••• '+normalized[-4:] if kind=='phone_number' else normalized[0]+'•••@'+normalized.split('@')[1]
    return kind,fingerprint,masked


def start_link(conn,*,user_id,handle,key,now=None):
    now=now or datetime.now(timezone.utc)
    kind,fingerprint,masked=_handle(handle,key)
    conn.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(user_id,))
    conn.execute('UPDATE voice_link_requests SET cancelled_at=%s WHERE expires_at<=%s AND completed_at IS NULL AND cancelled_at IS NULL',(now,now))
    recent=conn.execute('''SELECT count(*) AS n FROM voice_link_requests
        WHERE created_at>%s AND (user_id=%s OR handle_fingerprint=%s)''',
        (now-timedelta(hours=1),user_id,fingerprint)).fetchone()['n']
    if recent>=5:
        raise CallerLinkError('Too many setup requests. Try again in an hour.',429)
    conflict=conn.execute('''SELECT 1 FROM voice_link_requests WHERE handle_fingerprint=%s
        AND user_id<>%s AND completed_at IS NULL AND cancelled_at IS NULL''',(fingerprint,user_id)).fetchone()
    if conflict:
        raise CallerLinkError('A setup is already in progress for this caller. Try again in a few minutes.',409)
    conn.execute('UPDATE voice_link_requests SET cancelled_at=%s WHERE user_id=%s AND completed_at IS NULL AND cancelled_at IS NULL',(now,user_id))
    request_id=str(uuid.uuid4())
    expires=now+timedelta(minutes=5)
    conn.execute('''INSERT INTO voice_link_requests
        (id,user_id,handle_fingerprint,handle_type,masked_handle,created_at,expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',(request_id,user_id,fingerprint,kind,masked,now,expires))
    return {'request_id':request_id,'masked_handle':masked,'expires_at':expires.isoformat()}


def link_status(conn,*,user_id,now=None):
    now=now or datetime.now(timezone.utc)
    linked=conn.execute('SELECT masked_handle,handle_type,verified_at FROM voice_caller_links WHERE user_id=%s',(user_id,)).fetchone()
    pending=conn.execute('''SELECT id,masked_handle,expires_at,challenge_hash FROM voice_link_requests
        WHERE user_id=%s AND expires_at>%s AND completed_at IS NULL AND cancelled_at IS NULL''',(user_id,now)).fetchone()
    return {'linked':dict(linked) if linked else None,
            'pending':{'request_id':str(pending['id']),'masked_handle':pending['masked_handle'],
                       'expires_at':pending['expires_at'].isoformat(),'ready':bool(pending['challenge_hash'])} if pending else None}


def issue_challenge(conn,*,handle,key,call_id,now=None):
    now=now or datetime.now(timezone.utc)
    _,fingerprint,_=_handle(handle,key)
    row=conn.execute('''SELECT * FROM voice_link_requests WHERE handle_fingerprint=%s
        AND expires_at>%s AND completed_at IS NULL AND cancelled_at IS NULL AND attempts<5 FOR UPDATE''',
        (fingerprint,now)).fetchone()
    if not row or (row['challenge_hash'] and str(row['provider_call_id'])==call_id):
        return None
    code=f'{secrets.randbelow(10000):04d}'
    digest=_digest(key,f"challenge:{row['id']}:{call_id}:{code}")
    conn.execute('UPDATE voice_link_requests SET challenge_hash=%s,provider_call_id=%s WHERE id=%s',
                 (digest,call_id,row['id']))
    return {'request_id':str(row['id']),'code':code}


def confirm_link(conn,*,user_id,request_id,code,key,now=None):
    now=now or datetime.now(timezone.utc)
    failed={'verified':False,'message':'Code not accepted. Check the four spoken digits or start setup again.'}
    try:
        uuid.UUID(str(request_id))
    except (ValueError,TypeError):
        return failed
    # Same lock order as request/unlink: owner first, then its pending request.
    conn.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(user_id,))
    row=conn.execute('SELECT * FROM voice_link_requests WHERE id=%s AND user_id=%s FOR UPDATE',(request_id,user_id)).fetchone()
    if (not row or row['completed_at'] or row['cancelled_at'] or row['expires_at']<=now
            or row['attempts']>=5 or not row['challenge_hash']):
        return failed
    digest=_digest(key,f"challenge:{row['id']}:{row['provider_call_id']}:{code}")
    if not re.fullmatch(r'[0-9]{4}',code) or not hmac.compare_digest(digest,row['challenge_hash']):
        conn.execute('UPDATE voice_link_requests SET attempts=attempts+1 WHERE id=%s',(request_id,))
        # Return a normal result so the request transaction commits the attempt.
        return failed
    conn.execute('DELETE FROM voice_caller_links WHERE user_id=%s',(user_id,))
    conn.execute('''INSERT INTO voice_caller_links
        (id,user_id,handle_fingerprint,handle_type,masked_handle,verified_at) VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT(handle_fingerprint) DO UPDATE SET user_id=EXCLUDED.user_id,verified_at=EXCLUDED.verified_at''',
        (str(uuid.uuid4()),user_id,row['handle_fingerprint'],row['handle_type'],row['masked_handle'],now))
    conn.execute('UPDATE voice_link_requests SET completed_at=%s,challenge_hash=NULL WHERE id=%s',(now,request_id))
    return {'verified':True}


def unlink_caller(conn,*,user_id):
    conn.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(user_id,))
    conn.execute('DELETE FROM voice_caller_links WHERE user_id=%s',(user_id,))
    conn.execute('UPDATE voice_link_requests SET cancelled_at=now() WHERE user_id=%s AND completed_at IS NULL AND cancelled_at IS NULL',(user_id,))


def linked_preferences(conn,*,handle,key):
    _,fingerprint,_=_handle(handle,key)
    row=conn.execute('''SELECT l.user_id,p.voice_id,p.voice_tone,p.speech_speed
        FROM voice_caller_links l JOIN users u ON u.id=l.user_id JOIN profiles p ON p.user_id=l.user_id
        WHERE l.handle_fingerprint=%s AND u.disabled_at IS NULL''',(fingerprint,)).fetchone()
    return {'user_id':str(row['user_id']),'preferences':VoicePreferences(voice_id=row['voice_id'],tone=row['voice_tone'],speed=row['speech_speed'])} if row else None
