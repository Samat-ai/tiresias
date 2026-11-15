"""Resolve caller handles through the authenticated Chert control plane.

The local worker reads the existing CLI credential; the public web app does not
need it. Neither credentials nor raw caller handles belong in diagnostic logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

import httpx

from tiresias.caller_links import normalize_handle, CallerLinkError


@dataclass(frozen=True)
class ChertCaller:
    call_id: str
    handle: str = field(repr=False)


class ChertCallerResolver:
    def __init__(self,project_id,*,credentials_file=None,transport=None):
        self.project_id=project_id
        self.credentials_file=Path(credentials_file) if credentials_file else Path.home()/'.chert/credentials.json'
        self.transport=transport

    def resolve(self,call_id: str) -> ChertCaller | None:
        try:
            if str(uuid.UUID(call_id))!=call_id or not self.project_id:
                return None
            credentials=json.loads(self.credentials_file.read_text(encoding='utf-8'))
            origin=credentials.get('origin','https://app.trychert.com')
            if (origin not in {'https://app.trychert.com','https://facetime.trychert.com'}
                    or credentials.get('project_id',self.project_id)!=self.project_id
                    or credentials.get('expires_at',0)<=time.time()*1000):
                return None
            with httpx.Client(timeout=3,follow_redirects=False,trust_env=False,transport=self.transport) as client:
                response=client.get(origin+'/api/v1/calls/'+call_id,headers={
                    'Authorization':'Bearer '+credentials['access_token'],'x-chert-project-id':self.project_id})
                if response.status_code!=200 or len(response.content)>1024*1024:
                    return None
                detail=response.json().get('data')
            if not isinstance(detail,dict):
                return None
            if (detail.get('id')!=call_id or detail.get('project_id')!=self.project_id
                    or detail.get('direction')!='inbound'
                    or detail.get('status') not in {'incoming','ringing','answering','accepted','connecting','active','started','in_progress'}):
                return None
            created=datetime.fromisoformat(detail['created_at'].replace('Z','+00:00'))
            age=(datetime.now(timezone.utc)-created).total_seconds()
            if not -30<=age<=600:
                return None
            caller=detail.get('from')
            if not isinstance(caller,dict) or caller.get('type') not in {'phone_number','email'}:
                return None
            kind,handle=normalize_handle(caller.get('value'))
            if kind!=caller['type']:
                return None
            return ChertCaller(call_id=call_id,handle=handle)
        except (OSError,ValueError,TypeError,KeyError,httpx.HTTPError,CallerLinkError):
            return None
