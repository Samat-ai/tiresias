from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Verified against the account's ElevenLabs catalog, November 15, 2026.
VOICES = [
    {"id": "JBFqnCBsd6RMkjVDRZzb", "name": "George", "gender": "male", "description": "Warm British storyteller"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "gender": "female", "description": "Reassuring American voice"},
    {"id": "CwhRBWXzGAHq8TQ4Fs17", "name": "Roger", "gender": "male", "description": "Relaxed American conversation"},
    {"id": "hpp4J3VqNfWAUOO0d1Us", "name": "Bella", "gender": "female", "description": "Bright, warm American voice"},
    {"id": "SAz9YHcvj6GT2YYXdXww", "name": "River", "gender": "neutral", "description": "Calm, neutral American voice"},
    {"id": "Xb7hH8MSUJpSbSDYk0k2", "name": "Alice", "gender": "female", "description": "Clear British narration"},
]
VOICE_BY_ID = {voice['id']: voice for voice in VOICES}
TONES = {
    "calm": {"stability": 0.65, "similarity_boost": 0.8, "style": 0.0},
    "friendly": {"stability": 0.35, "similarity_boost": 0.8, "style": 0.2},
    "direct": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.0},
}


class VoicePreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    voice_id: str = 'JBFqnCBsd6RMkjVDRZzb'
    tone: Literal['calm', 'friendly', 'direct'] = 'calm'
    speed: float = Field(default=0.95, ge=0.7, le=1.2)

    @field_validator('voice_id')
    @classmethod
    def supported_voice(cls, value):
        if value not in VOICE_BY_ID:
            raise ValueError('Choose a voice from the available catalog')
        return value

    def tts_options(self) -> dict:
        return {**TONES[self.tone], 'speed': self.speed}


def _preferences(row) -> VoicePreferences:
    return VoicePreferences(voice_id=row['voice_id'], tone=row['voice_tone'], speed=row['speech_speed'])


def get_preferences(conn, user_id: str) -> dict:
    row = conn.execute('SELECT * FROM profiles WHERE user_id=%s FOR UPDATE', (user_id,)).fetchone()
    if row is None:
        raise KeyError('profile not found')
    if not row['voice_profile_code']:
        for _ in range(5):
            code = str(secrets.randbelow(90_000_000) + 10_000_000)
            if conn.execute('SELECT 1 FROM profiles WHERE voice_profile_code=%s', (code,)).fetchone():
                continue
            row = conn.execute('UPDATE profiles SET voice_profile_code=%s WHERE user_id=%s RETURNING *',
                               (code, user_id)).fetchone()
            break
        else:
            raise RuntimeError('could not allocate profile code')
    return {'profile_code': row['voice_profile_code'], 'preferences': _preferences(row)}


def save_preferences(conn, user_id: str, preferences: VoicePreferences) -> dict:
    row = conn.execute(
        'UPDATE profiles SET voice_id=%s, voice_tone=%s, speech_speed=%s WHERE user_id=%s RETURNING user_id',
        (preferences.voice_id, preferences.tone, preferences.speed, user_id),
    ).fetchone()
    if row is None:
        raise KeyError('profile not found')
    return get_preferences(conn, user_id)


def resolve_profile_code(conn, code: str) -> dict | None:
    if not re.fullmatch(r'\d{8}', code):
        return None
    row = conn.execute('SELECT p.* FROM profiles p JOIN users u ON u.id=p.user_id '
                       'WHERE voice_profile_code=%s AND u.disabled_at IS NULL', (code,)).fetchone()
    return {'user_id': str(row['user_id']), 'preferences': _preferences(row)} if row else None


@dataclass
class VoiceCommand:
    profile_code: str | None = None
    updates: dict = field(default_factory=dict)
    cancel_profile: bool = False


def _profile_digits(text: str) -> str | None:
    value=text.lower().strip(' .!?')
    value=re.sub(r'^(?:(?:uh|um|erm)[, ]*|(?:the code is|my code is|it is|it\'s) )+', '', value)
    words={'zero':'0','oh':'0','one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9'}
    for word,digit in words.items():
        value=re.sub(r'\b'+word+r'\b',digit,value)
    if re.search(r'[^0-9\s,.;:!?-]',value):
        return None
    return re.sub(r'\D','',value)


class ProfileCodeEntry:
    """Collect only explicitly requested profile digits across completed turns."""

    def __init__(self):
        self.digits=''
        self.deadline=0.0

    def consume(self,text: str,*,now: float | None = None) -> VoiceCommand | None:
        now=time.monotonic() if now is None else now
        command=parse_voice_command(text)
        if command is not None and command.profile_code is not None:
            digits=command.profile_code
        elif self.deadline and now<self.deadline:
            if text.lower().strip(' .!?') in {'cancel','cancel profile','never mind','nevermind','stop'}:
                self.deadline=0
                self.digits=''
                return VoiceCommand(cancel_profile=True)
            chunk=_profile_digits(text)
            if command is not None or chunk is None:
                self.deadline=0
                self.digits=''
                return command
            digits=chunk if len(chunk)==8 else self.digits+chunk
        else:
            self.deadline=0
            self.digits=''
            return command
        if len(digits)>8:
            digits=''
        self.digits=digits
        self.deadline=0 if len(digits)==8 else now+45
        return VoiceCommand(profile_code=digits)


def parse_voice_command(text: str) -> VoiceCommand | None:
    norm = re.sub(r'\s+', ' ', text.lower()).strip(' .!?')
    norm = re.sub(r'^(?:(?:can|could|would) you |please )+', '', norm)
    code = re.fullmatch(r'(?:use(?: my)?|load(?: my)?|my) (?:voice )?profile(?: code)?(?:[ :]+(.*))?', norm)
    if code:
        return VoiceCommand(profile_code=_profile_digits(code.group(1) or '') or '')
    if not re.match(r'^(?:use|switch to|change (?:your |the )?(?:voice|tone) to|speak|sound|be)\b', norm):
        return None
    for voice in VOICES:
        if re.search(r'\b' + voice['name'].lower() + r"(?:'s)?\b", norm):
            return VoiceCommand(updates={'voice_id': voice['id']})
    if 'voice' in norm and re.search(r'\bfemale\b', norm):
        return VoiceCommand(updates={'voice_id': 'EXAVITQu4vr4xnSDxMaL'})
    if 'voice' in norm and re.search(r'\bmale\b', norm):
        return VoiceCommand(updates={'voice_id': 'JBFqnCBsd6RMkjVDRZzb'})
    for tone, terms in {'calm':['calm','calmly'], 'friendly':['friendly','friendlier'], 'direct':['direct','directly']}.items():
        if any(re.search(r'\b'+term+r'\b', norm) for term in terms):
            return VoiceCommand(updates={'tone':tone})
    return None
