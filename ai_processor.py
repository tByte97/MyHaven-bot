from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

DEFAULT_INTENT_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "intent_uk.txt"


class AIProcessor:
    """Обробляє STT-транскрипцію та розбір intent через LLM."""

    def __init__(
        self,
        whisper_model_size: str = "small",
        provider: str = "gemini",
        gemini_api_key: str = "",
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.1:8b",
        prompt_path: str | Path | None = None,
    ) -> None:
        # STT через faster-whisper працює локально.
        self._whisper = WhisperModel(
            whisper_model_size,
            device="cpu",         # "cuda", якщо є Nvidia GPU
            compute_type="int8",  # Економить RAM на CPU
        )
        self._provider = provider.strip().lower()
        self._ollama_url = ollama_url
        self._ollama_model = ollama_model
        self._log_dir = Path(__file__).resolve().parent / "logs"
        self._log_dir.mkdir(exist_ok=True)
        self._intent_prompt_template = self._load_prompt_template(prompt_path)

        if self._provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            self._gemini = genai.GenerativeModel("gemini-2.0-flash")

    def transcribe(self, audio_path: str) -> str:
        # Транскрибує аудіофайл в український текст.
        segments, _ = self._whisper.transcribe(
            audio_path, language="uk", beam_size=5
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def parse_intent(
        self,
        text: str,
        context: str | None = None,
    ) -> dict[str, Any]:
        # Перетворює природну мову на структурований словник intent.
        today = date.today().isoformat()
        prompt = self._intent_prompt_template.format(today=today) + f"\n\nКоманда: {text}"
        if context:
            prompt += f"\n\nКонтекст попереднього уточнення: {context}"

        if self._provider == "gemini":
            return await self._gemini_parse(prompt)
        return await self._ollama_parse(prompt)

    def _load_prompt_template(self, prompt_path: str | Path | None) -> str:
        path = Path(prompt_path) if prompt_path else DEFAULT_INTENT_PROMPT_PATH
        return path.read_text(encoding="utf-8")

    async def _gemini_parse(self, prompt: str) -> dict[str, Any]:
        # Синхронний SDK: виклик в окремому потоці, щоб не блокувати event loop.
        response = await asyncio.to_thread(
            self._gemini.generate_content,
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text)

    async def _ollama_parse(self, prompt: str) -> dict[str, Any]:
        import httpx
        self._log_ollama(
            f"request url={self._ollama_url} model={self._ollama_model} "
            f"prompt_len={len(prompt)}"
        )
        try:
            async with httpx.AsyncClient(timeout=360.0) as client:
                resp = await client.post(
                    f"{self._ollama_url}/api/generate",
                    json={"model": self._ollama_model, "prompt": prompt,
                          "format": "json", "stream": False},
                )
            if resp.status_code != 200:
                body = resp.text
                if len(body) > 500:
                    body = f"{body[:500]}..."
                self._log_ollama(f"error status={resp.status_code} body={body}")
                raise ValueError(f"Ollama error status={resp.status_code}")
            data = resp.json()
            if "response" not in data:
                self._log_ollama(
                    f"error missing_response keys={list(data.keys())}"
                )
                raise ValueError("Ollama response missing 'response'")
            response_text = str(data.get("response", ""))
            self._log_ollama(
                f"response status={resp.status_code} response_len={len(response_text)}"
            )
            return json.loads(response_text)
        except Exception as exc:
            self._log_ollama(
                f"exception type={type(exc).__name__} message={exc}"
            )
            raise

    def _log_ollama(self, message: str) -> None:
        try:
            log_path = self._log_dir / "ollama.log"
            timestamp = datetime.utcnow().isoformat()
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} {message}\n")
        except Exception:
            return
