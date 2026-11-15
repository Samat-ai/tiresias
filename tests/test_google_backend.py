from types import SimpleNamespace

import pytest

from tiresias.agent.vision import VisionClient
from tiresias.agent.intent import IntentClassifier


def test_vertex_vision_uses_adc_and_ignores_existing_studio_key(monkeypatch):
    calls = []
    monkeypatch.setattr('tiresias.agent.vision.genai.Client', lambda **kwargs: calls.append(kwargs))
    VisionClient('old-studio-key', vertexai=True, project='demo-project', location='global')
    assert calls[0]['vertexai'] is True
    assert calls[0]['project'] == 'demo-project'
    assert calls[0]['location'] == 'global'
    assert 'api_key' not in calls[0]


def test_vertex_requires_an_explicit_project():
    with pytest.raises(ValueError, match='project'):
        VisionClient('', vertexai=True)


def test_studio_key_still_works(monkeypatch):
    calls = []
    monkeypatch.setattr('tiresias.agent.vision.genai.Client', lambda **kwargs: calls.append(kwargs))
    VisionClient('studio-key')
    assert calls[0]['api_key'] == 'studio-key'
    assert calls[0].get('vertexai') is False


def test_visual_question_does_not_wait_for_an_intent_model(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(
            text='{"kind":"CHECK","confidence":0.9}'
        )))

    monkeypatch.setattr('tiresias.agent.intent.genai.Client', create)
    classifier = IntentClassifier(vertexai=True, project='demo-project')
    assert calls == []  # SDK/ADC initialization stays off the media event loop.
    assert classifier.route('could you inspect the current view for me', None).kind.value == 'CONVERSATION'
    assert calls == []
