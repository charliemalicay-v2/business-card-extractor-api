import pytest

from app.services.exceptions import ExtractionServiceUnavailableError
from app.services.llm.model import LlamaCppModel, get_model


def test_llama_cpp_model_raises_when_backend_unavailable():
    """llama-cpp-python is not installed in this environment, so construction must fail
    with our typed exception rather than leaking an ImportError to callers."""
    with pytest.raises(ExtractionServiceUnavailableError):
        LlamaCppModel(model_path="./models/does-not-exist.gguf")


def test_get_model_raises_before_load(monkeypatch):
    import app.services.llm.model as model_module

    monkeypatch.setattr(model_module, "_model", None)

    with pytest.raises(ExtractionServiceUnavailableError):
        get_model()


def test_get_model_returns_loaded_instance(monkeypatch):
    import app.services.llm.model as model_module

    sentinel = object()
    monkeypatch.setattr(model_module, "_model", sentinel)

    assert get_model() is sentinel
