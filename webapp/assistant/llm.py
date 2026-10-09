"""Client Ollama minimal (API HTTP locale), sans dependance supplementaire."""
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"


@dataclass
class Reply:
    text: str
    model: str
    latency_ms: int


class OllamaUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(self, url: str | None = None, model: str | None = None, timeout: float = 120):
        self.url = (url or os.environ.get("OLLAMA_URL", DEFAULT_URL)).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(f"{self.url}{path}", data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise OllamaUnavailable(str(exc)) from exc

    def status(self) -> dict:
        """Ollama repond-il, et le modele est-il telecharge ?"""
        try:
            models = [m["name"] for m in self._request("/api/tags", timeout=2).get("models", [])]
        except OllamaUnavailable:
            return {"online": False, "model": self.model, "installed": False}
        installed = any(m == self.model or m.split(":")[0] == self.model for m in models)
        return {"online": True, "model": self.model, "installed": installed}

    def chat(self, messages: list[dict]) -> Reply:
        started = time.perf_counter()
        body = self._request("/api/chat", {
            "model": self.model, "messages": messages, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0.1, "num_ctx": 4096},
        })
        if "error" in body:
            raise OllamaUnavailable(body["error"])
        return Reply(text=body["message"]["content"].strip(), model=self.model,
                     latency_ms=int(1000 * (time.perf_counter() - started)))
