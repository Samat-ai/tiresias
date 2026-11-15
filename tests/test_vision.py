from types import SimpleNamespace

import pytest

from tiresias.agent.vision import VisionClient
from tests.test_policy import frame


def client(response=None, error=None):
    vision = VisionClient.__new__(VisionClient)
    vision.model = 'gemini-3.5-flash-lite'
    vision.timeout_seconds = 12

    def generate_content(**kwargs):
        if error:
            raise error
        return SimpleNamespace(text=response)

    vision._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return vision


def test_gemini_three_uses_supported_low_latency_thinking():
    config = client()._config(timeout=True)
    assert config.thinking_config.thinking_budget is None
    assert config.thinking_config.thinking_level.lower() == 'minimal'


def test_provider_failure_is_not_an_image_quality_observation():
    with pytest.raises(RuntimeError, match='provider offline'):
        client(error=RuntimeError('provider offline')).analyze_frame(frame(), None)


def test_truncated_json_is_not_an_image_quality_observation():
    with pytest.raises(ValueError):
        client(response='{"visible_text":[').analyze_frame(frame(), None)


def test_flagship_models_use_low_instead_of_unsupported_minimal_thinking():
    vision=client()
    vision.model='gemini-3.8-flash'
    assert vision._thinking_config().thinking_level.lower()=='low'


@pytest.mark.parametrize('question,expected',[
    ('How many Pepsi cans can you see?','MEDIA_RESOLUTION_LOW'),
    ('Read the batch code.','MEDIA_RESOLUTION_HIGH'),
    ('What does the sign say?','MEDIA_RESOLUTION_HIGH'),
    ('Какая дата на этикетке?','MEDIA_RESOLUTION_HIGH'),
    ('What is written on this bottle?','MEDIA_RESOLUTION_HIGH'),
    ('When does this expire?','MEDIA_RESOLUTION_HIGH'),
    ('What are the numbers underneath?','MEDIA_RESOLUTION_HIGH'),
    ('And what about that one?','MEDIA_RESOLUTION_HIGH'),
])
def test_scene_and_small_text_use_different_media_resolution(question,expected):
    from tiresias.agent.vision import reading_task
    assert ('MEDIA_RESOLUTION_HIGH' if reading_task(question) else 'MEDIA_RESOLUTION_LOW')==expected


def test_label_checks_explicitly_preserve_high_media_resolution():
    assert client()._config(timeout=True).media_resolution.value=='MEDIA_RESOLUTION_HIGH'


def test_compact_label_response_is_bound_to_the_frame_without_model_echo():
    result=client(response='{"visible_text":["PEPSI"],"quality":"READABLE"}').analyze_frame(frame(),None)
    assert result.frame_id==frame().frame_id
    assert result.visible_text==['PEPSI']


def test_warmup_primes_authentication_once_without_an_inference_request(monkeypatch):
    from tiresias.agent import vision as module
    requests=[]
    models=SimpleNamespace(get=lambda **kw:requests.append(kw),generate_content=lambda **kw:pytest.fail('warmup must not generate content'))
    monkeypatch.setattr(module,'create_client',lambda *args,**kw:SimpleNamespace(models=models))
    vision=VisionClient(api_key='test')
    vision.prewarm()
    vision.prewarm()
    assert len(requests)==1
    assert requests[0]['model']=='gemini-3.5-flash-lite'
