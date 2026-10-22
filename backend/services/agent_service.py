from __future__ import annotations

from aiutil.ai_client import AIClient
from fastapi import HTTPException

from . import logger


class AgentService:
    def __init__(self, ai: AIClient) -> None:
        self._ai = ai

    def info(self) -> dict:
        return {
            "model": self._ai.settings.model,
            "base_url": self._ai.base_url,
            "key_alias": self._ai.key_alias,
            "max_tokens": self._ai.settings.max_tokens,
            "temperature": self._ai.settings.temperature,
        }

    async def chat(
        self,
        prompt: str,
        *,
        use_internal: bool = False,
        sources: list[str] | None = None,
        history: list[dict] | None = None,
    ) -> str:
        return await self._ai.chat(
            prompt, use_internal=use_internal, sources=sources, history=history
        )

    async def search(
        self, query: str, *, sources: list[str] | None = None, limit: int = 10
    ) -> list[dict]:
        return await self._ai.search(query, sources=sources, limit=limit)

    def switch(
        self,
        *,
        model: str | None,
        max_tokens: int | None,
        temperature: float | None,
    ) -> dict:
        if model is None and max_tokens is None and temperature is None:
            raise HTTPException(
                status_code=400,
                detail="At least one of 'model', 'max_tokens', 'temperature' is required",
            )
        try:
            self._ai.update_settings(
                model=model, max_tokens=max_tokens, temperature=temperature
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Error switching AI agent: {exc}"
            ) from exc

        logger.info(
            "switched AI agent (model=%s, max_tokens=%d, temperature=%s)",
            self._ai.settings.model,
            self._ai.settings.max_tokens,
            self._ai.settings.temperature,
        )
        return self.info()
