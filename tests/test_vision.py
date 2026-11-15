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
