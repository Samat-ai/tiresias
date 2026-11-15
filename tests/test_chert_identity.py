from datetime import datetime, timezone
import json
import uuid

import httpx
import pytest

from tiresias.chert_identity import ChertCallerResolver


@pytest.fixture
def setup_identity(tmp_path):
    project=str(uuid.uuid4())
    call=str(uuid.uuid4())
    path=tmp_path/'cli.json'
    path.write_text(json.dumps({'access_token':'private-test-token','project_id':project,
                               'origin':'https://app.trychert.com','expires_at':9999999999999}))
    detail={'id':call,'project_id':project,'direction':'inbound','status':'active',
            'created_at':datetime.now(timezone.utc).isoformat(),
            'from':{'type':'phone_number','value':'+12145550100'}}
    return path,project,call,detail


def test_caller_identity_requires_authenticated_exact_call_lookup(setup_identity):
    path,project,call,detail=setup_identity
    requests=[]
    def respond(request):
        requests.append(request)
        assert request.headers['authorization']=='Bearer private-test-token'
        assert request.headers['x-chert-project-id']==project
        return httpx.Response(200,json={'data':detail})
    caller=ChertCallerResolver(project,credentials_file=path,transport=httpx.MockTransport(respond)).resolve(call)
    assert caller.handle=='+12145550100'
    assert caller.call_id==call
    assert str(requests[0].url).endswith('/api/v1/calls/'+call)
    assert caller.handle not in repr(caller)


@pytest.mark.parametrize('update',[
    {'id':str(uuid.uuid4())}, {'project_id':str(uuid.uuid4())}, {'direction':'outbound'},
    {'status':'ended'}, {'from':None}, {'created_at':'2020-01-01T00:00:00+00:00'},
    {'from':{'type':'display_name','value':'+12145550100'}},
])
def test_rejects_forged_stale_or_unavailable_identity(setup_identity,update):
    path,project,call,detail=setup_identity
    detail.update(update)
    resolver=ChertCallerResolver(project,credentials_file=path,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'data':detail})))
    assert resolver.resolve(call) is None


def test_untrusted_origins_and_smoke_ids_never_receive_credentials(setup_identity):
    path,project,call,detail=setup_identity
    credentials=json.loads(path.read_text())
    credentials['origin']='https://attacker.example'
    path.write_text(json.dumps(credentials))
    def unexpected(request):
        raise AssertionError('must not make an HTTP request')
    resolver=ChertCallerResolver(project,credentials_file=path,transport=httpx.MockTransport(unexpected))
    assert resolver.resolve(call) is None
    assert resolver.resolve('smoke-123456') is None
