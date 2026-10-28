"""HTTP adapter for the Ollama inference server."""

import json
from urllib import error, request


class OllamaClient:
    """Communicate with Ollama using its HTTP API."""

    def __init__(
        self,
        base_url: str = "http://10.10.1.70:11434",
        model: str = "qwen3.5:9b",
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, str]],
        response_format: dict | None = None,
        options: dict | None = None,
    ) -> str:
        """Send messages to Ollama and return the response."""

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": 8192,
            },
        }

        if options is not None:
            payload["options"].update(options)

        if response_format is not None:
            payload["format"] = response_format

        data = json.dumps(payload).encode("utf-8")

        http_request = request.Request(
            url=f"{self.base_url}/api/chat",
            data=data,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self.timeout,
            ) as response:
                result = json.load(response)

        except error.HTTPError as exc:
            raise RuntimeError(f"Ollama HTTP error: {exc.code}") from exc

        except error.URLError as exc:
            raise ConnectionError(f"Cannot connect to Ollama: {exc.reason}") from exc

        try:
            return result["message"]["content"]

        except (KeyError, TypeError) as exc:
            raise ValueError("Ollama returned an unexpected response") from exc
