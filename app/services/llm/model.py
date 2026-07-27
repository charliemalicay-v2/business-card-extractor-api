import threading
from pathlib import Path
from typing import Protocol

from app.services.exceptions import ExtractionServiceUnavailableError

GRAMMAR_PATH = Path(__file__).parent / "grammar.gbnf"


class LlmModel(Protocol):
    def generate_json(self, prompt: str) -> str: ...


class LlamaCppModel:
    """Wraps a local llama.cpp model, constrained to schema-conformant JSON output via a GBNF grammar."""

    def __init__(self, model_path: str, grammar_path: Path = GRAMMAR_PATH):
        try:
            from llama_cpp import Llama, LlamaGrammar
        except ImportError as exc:
            raise ExtractionServiceUnavailableError("llama-cpp-python is not installed.") from exc

        try:
            self._llama = Llama(model_path=model_path, n_ctx=2048, verbose=False)
            self._grammar = LlamaGrammar.from_file(str(grammar_path))
        except Exception as exc:
            raise ExtractionServiceUnavailableError(f"Failed to load local LLM model: {exc}") from exc

    def generate_json(self, prompt: str) -> str:
        try:
            result = self._llama.create_completion(
                prompt, grammar=self._grammar, max_tokens=512, temperature=0.0
            )
            return result["choices"][0]["text"]
        except Exception as exc:
            raise ExtractionServiceUnavailableError(f"Local LLM inference failed: {exc}") from exc


_model_lock = threading.Lock()
_model: LlmModel | None = None


def load_model(model_path: str) -> LlmModel:
    """Load (or return the already-loaded) singleton model instance. Intended for app startup."""
    global _model
    with _model_lock:
        if _model is None:
            _model = LlamaCppModel(model_path)
        return _model


def get_model() -> LlmModel:
    """Return the loaded model instance, raising if startup loading has not happened or failed."""
    if _model is None:
        raise ExtractionServiceUnavailableError("LLM model has not been loaded.")
    return _model
