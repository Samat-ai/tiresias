"""Explicit backend selection keeps AI Studio keys separate from Vertex ADC."""
from google import genai
from google.genai import types


def create_client(api_key: str = "", *, vertexai: bool = False, project: str = "", location: str = "global"):
    if vertexai:
        if not project.strip():
            raise ValueError("Google Cloud project is required for Vertex AI")
        return genai.Client(
            vertexai=True, project=project, location=location,
            http_options=types.HttpOptions(api_version="v1"),
        )
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for AI Studio")
    return genai.Client(
        vertexai=False, api_key=api_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
