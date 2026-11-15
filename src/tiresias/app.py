from __future__ import annotations

import hmac
import hashlib
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

from tiresias.auth import AuthError, create_user, login, logout, session_user
from tiresias.config import Settings
from tiresias.db import connect
from tiresias.preferences import VOICES, TONES, VoicePreferences, get_preferences, save_preferences
from tiresias.security import csrf_matches, new_token, password_hasher
from tiresias.caller_links import CallerLinkError, start_link, link_status, confirm_link, unlink_caller

ROOT = Path(__file__).parent


class CallerLinkRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    handle: str=Field(min_length=1,max_length=254)


class CallerLinkConfirmation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID
    code: str=Field(pattern=r'^[0-9]{4}$')


class RateLimit:
    def __init__(self):
        self._entries = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key, limit=20):
        now = time.monotonic()
        with self._lock:
            if len(self._entries) > 2048:
                self._entries = defaultdict(deque, {k:v for k,v in self._entries.items() if v and now-v[-1]<60})
            entries = self._entries[key]
            while entries and now-entries[0]>60:
                entries.popleft()
            if len(entries)>=limit:
                raise HTTPException(429, 'Please wait a moment before trying again.')
            entries.append(now)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title='Tiresias', docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(ROOT/'templates'))
    templates.env.globals['asset_version']=hashlib.sha256(
        (ROOT/'static/app.js').read_bytes()+(ROOT/'static/app.css').read_bytes()).hexdigest()[:12]
    app.mount('/static', StaticFiles(directory=str(ROOT/'static')), name='static')
    hasher = password_hasher(memory_kib=settings.argon2_memory_kib, time_cost=settings.argon2_time_cost,
                             parallelism=settings.argon2_parallelism)
    limiter = RateLimit()
    preview_cache = {}
    preview_lock = threading.Lock()

    def database():
        if not settings.database_url:
            raise HTTPException(503, 'The database is not configured yet.')
        with connect(settings.database_url) as conn:
            yield conn

    def identity(request: Request, conn=Depends(database)):
        user = session_user(conn, request.cookies.get('tiresias_session',''))
        if user is None:
            raise HTTPException(401, 'Please sign in.')
        return user

    def check_csrf(request, user, token=None):
        if not csrf_matches(token or request.headers.get('X-CSRF-Token'), user['csrf_hash']):
            raise HTTPException(403, 'Please reload the page and try again.')

    def render(request, name, context=None, status_code=200):
        return templates.TemplateResponse(request=request, name=name, context=context or {}, status_code=status_code)

    def auth_page(request, mode, error=None, status_code=200):
        token = request.cookies.get('tiresias_csrf') or new_token()
        response = render(request, 'auth.html', {'mode':mode,'csrf':token,'error':error,
                                                'allow_registration':settings.allow_registration},status_code)
        response.set_cookie('tiresias_csrf',token,httponly=True,secure=settings.app_env=='production',samesite='lax')
        return response

    def auth_csrf(request, token):
        expected=request.cookies.get('tiresias_csrf','')
        if not expected or not token or not hmac.compare_digest(expected,token):
            raise HTTPException(403,'Please reload the page and try again.')

    def signed_in(result):
        response=RedirectResponse('/',status_code=303)
        options={'httponly':True,'secure':settings.app_env=='production','samesite':'lax','max_age':86400}
        response.set_cookie('tiresias_session',result['token'],**options)
        response.set_cookie('tiresias_csrf',result['csrf'],**options)
        return response

    @app.middleware('http')
    async def headers(request, call_next):
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; media-src 'self' blob:; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'"
        if not request.url.path.startswith('/static/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(AuthError)
    async def auth_error(request, error):
        return auth_page(request,'login',error='Email or password was not recognized.',status_code=error.status)

    @app.exception_handler(CallerLinkError)
    async def caller_link_error(request,error):
        return JSONResponse({'detail':str(error)},status_code=error.status)

    @app.get('/healthz')
    def health(conn=Depends(database)):
        conn.execute('SELECT 1')
        return {'status':'ok'}

    @app.get('/login')
    def login_form(request: Request):
        return auth_page(request,'login')

    @app.get('/register')
    def register_form(request: Request):
        if not settings.allow_registration:
            raise HTTPException(403,'Registration is closed.')
        return auth_page(request,'register')

    @app.post('/register')
    def register(request: Request, email: str=Form(), password: str=Form(), csrf: str=Form(), conn=Depends(database)):
        if not settings.allow_registration:
            raise HTTPException(403,'Registration is closed.')
        auth_csrf(request,csrf)
        limiter.check(('register',request.client.host),10)
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(email)>254:
            return auth_page(request,'register','Enter a valid email address.',400)
        try:
            create_user(conn,email=email,password=password,role='USER',hasher=hasher)
        except ValueError as error:
            return auth_page(request,'register',str(error),400)
        except UniqueViolation:
            conn.rollback()
            return auth_page(request,'register','That email is already registered. Sign in instead.',400)
        result=login(conn,email=email,password=password,hasher=hasher,csrf=None,expected_csrf=None)
        return signed_in(result)

    @app.post('/login')
    def sign_in(request: Request, email: str=Form(), password: str=Form(), csrf: str=Form(), conn=Depends(database)):
        auth_csrf(request,csrf)
        limiter.check(('login',request.client.host),15)
        return signed_in(login(conn,email=email,password=password,hasher=hasher,csrf=None,expected_csrf=None))

    @app.post('/logout')
    def sign_out(request: Request, csrf: str=Form(), user=Depends(identity), conn=Depends(database)):
        check_csrf(request,user,csrf)
        logout(conn,request.cookies.get('tiresias_session',''))
        response=RedirectResponse('/login',status_code=303)
        response.delete_cookie('tiresias_session')
        response.delete_cookie('tiresias_csrf')
        return response

    @app.get('/')
    def home(request: Request, conn=Depends(database)):
        user=session_user(conn,request.cookies.get('tiresias_session',''))
        if user is None:
            return RedirectResponse('/login',status_code=303)
        profile=get_preferences(conn,str(user['user_id']))
        return render(request,'index.html',{'profile':profile,'voices':VOICES,'tones':TONES,
                                            'csrf':request.cookies.get('tiresias_csrf',''),
                                            'caller_link_enabled':len(settings.caller_link_secret)>=32})

    @app.get('/api/caller-link')
    def caller_link_state(user=Depends(identity),conn=Depends(database)):
        return link_status(conn,user_id=str(user['user_id']))

    @app.post('/api/caller-link/request')
    def request_caller_link(request: Request, body: CallerLinkRequest,user=Depends(identity),conn=Depends(database)):
        check_csrf(request,user)
        limiter.check(('caller-link',str(user['user_id'])),5)
        try:
            return start_link(conn,user_id=str(user['user_id']),handle=body.handle,key=settings.caller_link_secret)
        except UniqueViolation:
            conn.rollback()
            raise CallerLinkError('A setup is already in progress. Try again shortly.',409) from None

    @app.post('/api/caller-link/confirm')
    def confirm_caller_link(request: Request,body: CallerLinkConfirmation,user=Depends(identity),conn=Depends(database)):
        check_csrf(request,user)
        limiter.check(('caller-confirm',str(user['user_id'])),10)
        result=confirm_link(conn,user_id=str(user['user_id']),request_id=str(body.request_id),code=body.code,key=settings.caller_link_secret)
        return JSONResponse(result,status_code=200 if result['verified'] else 400)

    @app.delete('/api/caller-link')
    def remove_caller_link(request: Request,user=Depends(identity),conn=Depends(database)):
        check_csrf(request,user)
        unlink_caller(conn,user_id=str(user['user_id']))
        return {'unlinked':True}

    @app.get('/api/voices')
    def voices(user=Depends(identity)):
        return {'voices':VOICES,'tones':list(TONES)}

    @app.get('/api/preferences')
    def preferences(user=Depends(identity),conn=Depends(database)):
        result=get_preferences(conn,str(user['user_id']))
        return {'profile_code':result['profile_code'],'preferences':result['preferences'].model_dump()}

    @app.post('/api/preferences')
    def save(request: Request, preferences: VoicePreferences, user=Depends(identity),conn=Depends(database)):
        check_csrf(request,user)
        result=save_preferences(conn,str(user['user_id']),preferences)
        return {'profile_code':result['profile_code'],'preferences':result['preferences'].model_dump()}

    @app.post('/api/voice-preview')
    def preview(request: Request, preferences: VoicePreferences,user=Depends(identity)):
        check_csrf(request,user)
        limiter.check(('preview',str(user['user_id'])),20)
        cache_key=(preferences.voice_id,preferences.tone,preferences.speed)
        with preview_lock:
            cached=preview_cache.get(cache_key)
        if cached and time.monotonic()-cached[0]<300:
            return Response(cached[1],media_type='audio/mpeg')
        if not settings.elevenlabs_key():
            raise HTTPException(503,'Voice preview is not configured yet.')
        try:
            with httpx.Client(timeout=10) as client:
                result=client.post(f'https://api.elevenlabs.io/v1/text-to-speech/{preferences.voice_id}',
                    params={'output_format':'mp3_22050_32'},headers={'xi-api-key':settings.elevenlabs_key()},
                    json={'text':"Hello, I'm Tiresias. Let's take a look together.",
                          'model_id':settings.elevenlabs_tts_model,'voice_settings':preferences.tts_options()})
                result.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502,'The voice preview is unavailable. Please try again shortly.') from None
        with preview_lock:
            if len(preview_cache)>=64:
                preview_cache.clear()
            preview_cache[cache_key]=(time.monotonic(),result.content)
        return Response(result.content,media_type='audio/mpeg')

    def performance_data(conn):
        rows=conn.execute("""SELECT stage, count(*) AS count,
            round(avg(duration_ms))::int AS average_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::int AS p95_ms,
            count(*) FILTER (WHERE outcome<>'ok') AS errors
            FROM stage_events WHERE event_ts>now()-interval '30 minutes'
            GROUP BY stage ORDER BY stage""").fetchall()
        timescale=bool(conn.execute("SELECT 1 FROM pg_extension WHERE extname='timescaledb'").fetchone())
        return {'stages':list(rows),'timescale':timescale,'total':sum(row['count'] for row in rows)}

    @app.get('/api/performance')
    def performance_api(user=Depends(identity),conn=Depends(database)):
        return performance_data(conn)

    @app.get('/performance')
    def performance_page(request: Request,user=Depends(identity),conn=Depends(database)):
        return render(request,'performance.html',{'metrics':performance_data(conn),
                      'csrf':request.cookies.get('tiresias_csrf','')})

    return app


def main():
    import uvicorn
    uvicorn.run(create_app(),host='127.0.0.1',port=8000)


if __name__=='__main__':
    main()
