#!/usr/bin/env python3
"""HTTP client for calling an OpenAI-compatible chat completion endpoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
from conf.config import Config

from . import logger


class AIClientError(Exception):
    """Raised when the AI backend returns an error or an unexpected response."""


# Models that reject a custom temperature (only temperature=1, i.e. omit it).
_TEMPERATURE_UNSUPPORTED_PREFIXES: tuple[str, ...] = (
    "claude-4.",
    "claude-opus-4-",
    "gpt-5-codex",
    # Claude 5 family (opus/sonnet, any vendor suffix) only supports temperature=1.
    "claude-5-",
    "claude-opus-5",
    "claude-sonnet-5",
    # Reasoning GPT models only support temperature=1 while reasoning is active.
    "gpt-5.5",
    "gpt-5.6",
    "gpt-6",
)


def _model_supports_temperature(model: str) -> bool:
    return not model.startswith(_TEMPERATURE_UNSUPPORTED_PREFIXES)


@dataclass
class AgentSettings:
    """Mutable runtime settings for the active AI agent."""

    model: str
    max_tokens: int
    temperature: float

    @property
    def supports_temperature(self) -> bool:
        return _model_supports_temperature(self.model)


class AIClient:
    """Thin async wrapper around an OpenAI-compatible /chat/completions endpoint."""

    _DEFAULT_SYSTEM_PROMPT = (
        "You are a concise, accurate assistant. Answer the user's question directly."
    )

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._settings = AgentSettings(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
        )
        base = cfg.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=cfg.timeout_sec,
            headers=self._auth_headers(cfg),
        )
        # MCP endpoints live at the gateway ROOT (outside the /v1 base), e.g.
        # https://.../mcp-rest/tools/call . Strip a trailing /v1 to get the root.
        self._gateway_root = base.removesuffix("/v1")

    @staticmethod
    def _auth_headers(cfg: Config) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }
        if cfg.key_id:
            headers["X-Api-Key-Id"] = cfg.key_id
        if cfg.key_alias:
            headers["X-Api-Key-Alias"] = cfg.key_alias
        return headers

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def settings(self) -> AgentSettings:
        return self._settings

    @property
    def base_url(self) -> str:
        return self._cfg.base_url

    @property
    def key_alias(self) -> str:
        return self._cfg.key_alias

    def update_settings(
        self,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AgentSettings:
        """Update the active agent settings in place and return the new snapshot."""
        if model is not None:
            m = model.strip()
            if not m:
                raise ValueError("model must not be empty")
            self._settings.model = m
        if max_tokens is not None:
            if max_tokens <= 0:
                raise ValueError("max_tokens must be positive")
            self._settings.max_tokens = max_tokens
        if temperature is not None:
            if temperature < 0 or temperature > 2:
                raise ValueError("temperature must be between 0 and 2")
            self._settings.temperature = temperature
        return self._settings

    _RAG_SYSTEM_PROMPT = (
        "You are a Roku QA assistant with access to Roku's internal knowledge "
        "(JIRA, Confluence, TestRail, GitLab), provided below as CONTEXT. "
        "Answer the user's question using that context when relevant, and cite the "
        "document ids/links you used. If the context does not contain the answer, "
        "say so and answer from general knowledge."
    )

    async def chat(
        self,
        question: str,
        *,
        system_prompt: str | None = None,
        use_internal: bool = False,
        sources: list[str] | None = None,
        context_limit: int = 6,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Send the question to the AI backend and return the assistant text reply.

        :param use_internal: if True, first search Roku internal data (JIRA etc.)
            and inject the results as context so the model can answer about them.
        :param sources: which internal sources to search (default: all).
        :param context_limit: max internal documents to inject.
        :param history: prior conversation turns [{role, content}, ...] replayed
            before the current question so the model has multi-turn context. RAG
            context is only injected into the current question, not the history.
        """
        sys_prompt = system_prompt or self._DEFAULT_SYSTEM_PROMPT
        user_content = question

        if use_internal:
            sys_prompt = self._RAG_SYSTEM_PROMPT
            context = None

            # 1) Structured JIRA path. Questions like "the tickets I closed last
            #    week" are structured queries (assignee/status/date) that semantic
            #    search cannot answer, so first try to translate to JQL and run it.
            try:
                jql = await self._maybe_jql(question)
            except Exception as exc:  # noqa: BLE001
                jql = None
                logger.warning("JQL translation failed: %s", exc)

            if jql:
                try:
                    from aiutil import jira_client

                    issues = await jira_client.search_jql(jql, max_results=25)
                    context = (
                        f"JQL executed: {jql}\n\n"
                        f"JIRA issues ({len(issues)}):\n"
                        f"{jira_client.format_issues(issues)}"
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("JIRA JQL query failed: %s", exc)

            # 2) Semantic-search fallback. The gateway occasionally returns
            #    transient 5xx; retry a couple times.
            if context is None:
                results: list[dict[str, Any]] = []
                search_failed = False
                for attempt in range(3):
                    try:
                        results = await self.search(
                            question, sources=sources, limit=context_limit
                        )
                        search_failed = False
                        break
                    except AIClientError as exc:
                        search_failed = True
                        logger.warning(
                            "Internal search attempt %d failed: %s", attempt + 1, exc
                        )
                # ALWAYS keep the RAG system prompt when internal access was
                # requested, even when nothing came back. Otherwise the model
                # silently falls back to a generic assistant and tells the user
                # it "cannot access Roku internal systems" — the original bug.
                if results:
                    context = _format_context(results)
                elif search_failed:
                    context = (
                        "(Internal search was temporarily unavailable — the "
                        "gateway did not respond after several retries. Tell the "
                        "user you could not reach Roku internal data this time and "
                        "suggest retrying; do NOT claim you lack internal access.)"
                    )
                else:
                    context = (
                        "(No matching internal documents were found for this "
                        "query. Say so plainly and offer to refine the search; do "
                        "NOT claim you lack internal access.)"
                    )
            user_content = (
                f"CONTEXT (Roku internal data):\n{context}\n\nQUESTION:\n{question}"
            )

        return await self._complete(sys_prompt, user_content, history=history)

    async def _complete(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Low-level completion against /chat/completions.

        When ``history`` is given, prior turns are replayed between the system
        prompt and the current user message for multi-turn context.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for turn in history or []:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_content})

        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "max_tokens": max_tokens or self._settings.max_tokens,
        }
        if self._settings.supports_temperature:
            payload["temperature"] = self._settings.temperature

        try:
            resp = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            logger.exception("AI request transport failure")
            raise AIClientError(f"AI transport error: {exc}") from exc

        if resp.status_code >= 400:
            logger.error("AI backend returned %s: %s", resp.status_code, resp.text)
            raise AIClientError(f"AI backend {resp.status_code}: {resp.text[:500]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise AIClientError("AI backend returned non-JSON response") from exc

        return _extract_message(data)

    _JQL_SYSTEM_PROMPT = (
        "You translate a user's request into a single JIRA JQL query, or decline. "
        "Only produce JQL when the request is a STRUCTURED issue query — it refers "
        "to a person (me/my/mine/currentUser/someone), a time window, a status "
        "(open/closed/done/resolved/in progress), a project key, an assignee, a "
        "reporter, a sprint, or asks to 'list/find tickets/issues/bugs' with such "
        "filters. For a vague topic/keyword lookup with none of those, decline.\n"
        "Output ONLY the JQL on a single line, with no markdown, quotes, or "
        "explanation. If you cannot build a structured query, output exactly NONE."
    )

    async def _maybe_jql(self, question: str) -> str | None:
        """Ask the model to turn the question into JQL, or return None.

        Returns a JQL string when the question is a structured issue query,
        otherwise None (caller falls back to semantic search).
        """
        from aiutil import jira_client

        prompt = (
            f"{jira_client.jql_context()}\n\n"
            f"User request:\n{question}\n\n"
            "JQL (or NONE):"
        )
        try:
            raw = await self._complete(self._JQL_SYSTEM_PROMPT, prompt, max_tokens=200)
        except AIClientError as exc:
            logger.warning("JQL generation call failed: %s", exc)
            return None

        jql = raw.strip().strip("`").strip()
        # Strip a leading "jql:" label or code-fence remnants the model may add.
        if jql.lower().startswith("jql"):
            jql = jql.split(":", 1)[-1].strip() if ":" in jql else jql
        if not jql or jql.upper() == "NONE" or "NONE" == jql.split()[0].upper():
            return None
        # Sanity check: a real JQL query references a field/operator.
        if not any(
            tok in jql.lower()
            for tok in ("=", "~", " in ", "currentuser", "during", "changed")
        ):
            return None
        return jql

    async def search(
        self,
        query: str,
        *,
        sources: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Call the ai_hub_search MCP tool and return the parsed result list.

        :param query: search query text
        :param sources: e.g. ["JIRA"], ["CONFLUENCE"], ["TESTRAIL"] ...
        :param limit: max results
        """
        arguments: dict[str, Any] = {"query": query, "limit": limit}
        if sources:
            arguments["sources"] = sources

        url = f"{self._gateway_root}/mcp-rest/tools/call"
        # The correct tool name is "<server_id>-<tool>" = "ai_hub_search-search"
        # with server_id "ai_hub_search". The bare "search" name is kept only as
        # a defensive secondary.
        #
        # Probed 2026-09-25: the gateway is FLAKY — the SAME valid payload returns
        # 200 on some calls and 500 "Tool search not found" on others (~1-in-5
        # success in a burst). So retry the whole attempt several times; a 500 is
        # transient here, not a permanent "wrong tool name" signal.
        names = ("ai_hub_search-search", "search")
        last_resp = None
        max_attempts = 6
        for attempt in range(max_attempts):
            for tool_name in names:
                payload = {
                    "name": tool_name,
                    "server_id": "ai_hub_search",
                    "arguments": arguments,
                }
                try:
                    resp = await self._client.post(url, json=payload)
                except httpx.HTTPError as exc:
                    logger.exception("MCP search transport failure")
                    raise AIClientError(f"MCP transport error: {exc}") from exc

                last_resp = resp
                if resp.status_code < 400:
                    try:
                        return _extract_search_results(resp.json())
                    except ValueError as exc:
                        raise AIClientError(
                            "MCP search returned non-JSON response"
                        ) from exc

                # A non-"not found" 4xx/5xx is a real error — stop the inner loop
                # and let the outer retry decide (it may still be transient).
                if "not found" not in resp.text.lower():
                    break

            if attempt < max_attempts - 1:
                logger.warning(
                    "MCP search attempt %d/%d failed (%s); retrying",
                    attempt + 1,
                    max_attempts,
                    last_resp.status_code if last_resp is not None else "?",
                )
                await asyncio.sleep(0.4 * (attempt + 1))

        detail = last_resp.text[:500] if last_resp is not None else "no response"
        logger.error("MCP search failed: %s", detail)
        raise AIClientError(f"MCP search failed: {detail}")


def _format_context(results: list[dict[str, Any]], *, max_chars: int = 12000) -> str:
    """Turn search results into a compact context block for the model."""
    lines: list[str] = []
    total = 0
    for i, r in enumerate(results, 1):
        doc = r.get("document_id", "")
        content = (r.get("content") or "").strip()
        entry = f"[{i}] {doc}\n{content}"
        if total + len(entry) > max_chars:
            break
        lines.append(entry)
        total += len(entry)
    return "\n\n".join(lines)


def _extract_search_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the results list out of an MCP tools/call response.

    The MCP envelope wraps a JSON string in content[].text, e.g.
    {"content":[{"type":"text","text":"{\\"results\\":[...]}"}], "isError":false}
    """
    import json

    if data.get("isError"):
        raise AIClientError(f"MCP tool error: {str(data)[:500]}")

    text = ""
    for part in data.get("content", []):
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text", "")
            break

    if not text:
        # Fall back to structuredContent.result if present.
        sc = data.get("structuredContent") or {}
        text = sc.get("result", "")

    if not text:
        return []

    try:
        parsed = json.loads(text)
    except ValueError:
        # Not JSON — return the raw text as a single result.
        return [{"content": text}]

    if isinstance(parsed, dict):
        return parsed.get("results", [])
    if isinstance(parsed, list):
        return parsed
    return []


def _extract_message(data: dict[str, Any]) -> str:
    """Pull assistant text out of an OpenAI-compatible response envelope."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIClientError("AI response missing 'choices'")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise AIClientError("AI response missing 'choices[0].message'")

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()

    # Some backends return content as a list of parts.
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        if parts:
            return "".join(parts).strip()

    raise AIClientError("AI response message has no textual content")
