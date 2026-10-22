from __future__ import annotations

import os
import sys
import time
import urllib.request

from aiutil.ai_client import AIClient
from conf import config as config_module
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from services.agent_service import AgentService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from config.env import ANALYZER_PATH

from . import logger, session_controller

router = APIRouter()

# Cap fetched log content so a huge Jenkins console doesn't blow the token budget.
_LOG_FETCH_MAX_CHARS = 60000

# Default Analyze locale
_DEFAULT_ANALYZE_LOCALE = "en-US"


def _analyze_config() -> dict:
    """Read the `analyze_config` section from config.yml"""
    locale = _DEFAULT_ANALYZE_LOCALE
    prompt_template = ""
    try:
        data = config_module._read_yaml(config_module._yaml_path())
        ac = data.get("analyze_config") or {}
        if ac.get("default_locale"):
            locale = str(ac["default_locale"])
        if ac.get("prompt_template"):
            prompt_template = str(ac["prompt_template"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falling back to default analyze config: %s", exc)
    return {"default_locale": locale, "prompt_template": prompt_template}


def _fetch_log_text(url: str) -> str:
    """Fetch a log URL's text content for analysis."""
    fetch_url = url
    for suffix in ("/consoleFull", "/console"):
        if fetch_url.endswith(suffix):
            fetch_url = fetch_url[: -len(suffix)] + "/consoleText"
            break
    req = urllib.request.Request(fetch_url, headers={"User-Agent": "Zen-Analyzer"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    if len(text) > _LOG_FETCH_MAX_CHARS:
        text = "...(truncated)...\n" + text[-_LOG_FETCH_MAX_CHARS:]
    return text


# Build the singleton AI client + service once at import time.
# If config is incomplete we still expose the routes but fail per-request.
_service: AgentService | None = None
_init_error: str | None = None

try:
    _cfg = config_module.load()
    _service = AgentService(AIClient(_cfg))
except Exception as exc:  # noqa: BLE001
    _init_error = str(exc)
    logger.exception("Failed to initialize AI agent")


def _get_service() -> AgentService:
    if _service is None:
        raise HTTPException(
            status_code=503,
            detail=f"AI agent not configured: {_init_error}",
        )
    return _service


class AgentInfoResponse(BaseModel):
    model: str = Field(..., description="Active model identifier.")
    base_url: str = Field(..., description="AI backend base URL.")
    key_alias: str = Field(..., description="API key alias used for auth.")
    max_tokens: int = Field(..., description="Max tokens allowed per completion.")
    temperature: float = Field(..., description="Sampling temperature.")

    @classmethod
    def from_info(cls, info: dict) -> "AgentInfoResponse":
        return cls(
            model=info["model"],
            base_url=info["base_url"],
            key_alias=info["key_alias"],
            max_tokens=info["max_tokens"],
            temperature=info["temperature"],
        )


class AgentSwitchRequest(BaseModel):
    model: str | None = Field(
        default=None, description="Model identifier to switch to."
    )
    max_tokens: int | None = Field(
        default=None, description="New max_tokens value.", gt=0
    )
    temperature: float | None = Field(
        default=None, description="New sampling temperature (0-2).", ge=0, le=2
    )


class AgentSwitchResponse(BaseModel):
    message: str = Field(..., description="Human readable outcome.")
    agent: AgentInfoResponse = Field(..., description="New active agent.")


@router.get(
    "/v1/agent/info",
    response_model=AgentInfoResponse,
    summary="Return information about the active AI agent",
)
def agent_info() -> AgentInfoResponse:
    return AgentInfoResponse.from_info(_get_service().info())


class AgentModelResponse(BaseModel):
    name: str = Field(..., description="The name of the AI agent model.")
    description: str = Field(..., description="The description of the AI agent model.")
    model: str = Field(..., description="The model identifier.")
    max_tokens: int = Field(..., description="The max tokens allowed per completion.")
    temperature: float = Field(..., description="The sampling temperature.")


@router.get(
    "/v1/agent/models",
    response_model=list[AgentModelResponse],
    summary="Return a list of available AI agent models",
)
def agent_models() -> list[AgentModelResponse]:
    # Read the `agent_model` list straight from the agent config yaml.
    import yaml

    path = config_module._yaml_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Error reading agent models: {exc}"
        ) from exc

    models = data.get("agent_model", []) or []
    return [
        AgentModelResponse(
            name=m.get("name", m.get("model", "")),
            description=m.get("description", ""),
            model=m["model"],
            max_tokens=m.get("max_tokens", 1024),
            temperature=m.get("temperature", 0.3),
        )
        for m in models
    ]


@router.post(
    "/v1/agent/switch",
    response_model=AgentSwitchResponse,
    summary="Switch the active AI agent model or parameters",
)
def agent_switch(req: AgentSwitchRequest) -> AgentSwitchResponse:
    updated = _get_service().switch(
        model=req.model,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    return AgentSwitchResponse(
        message=f"active agent switched to '{updated['model']}'",
        agent=AgentInfoResponse.from_info(updated),
    )


class AgentChatRequest(BaseModel):
    prompt: str = Field(..., description="The prompt to send to the active AI agent.")
    use_internal: bool = Field(
        default=True,
        description="If true, augment the answer with Roku internal data "
        "(JIRA/Confluence/TestRail/GitLab) via search.",
    )
    sources: list[str] | None = Field(
        default=None,
        description="Internal sources to search when use_internal is true "
        "(default: all). e.g. ['JIRA','TESTRAIL'].",
    )
    session_id: str | None = Field(
        default=None,
        description="Conversation session id. When set, prior turns are replayed "
        "for multi-turn context and this turn is appended to the session.",
    )


class AgentChatResponse(BaseModel):
    response: str = Field(..., description="The response from the active AI agent.")
    prompt: str = Field(..., description="The prompt that was sent.")
    model: str = Field(..., description="The model used to generate the response.")
    response_time: float = Field(..., description="Response time in seconds.")


@router.post(
    "/v1/agent/chat",
    response_model=AgentChatResponse,
    summary="Send a message to the active AI agent",
)
async def agent_chat(req: AgentChatRequest) -> AgentChatResponse:
    svc = _get_service()
    start = time.time()
    history = session_controller.get_history(req.session_id) if req.session_id else None
    try:
        answer = await svc.chat(
            req.prompt,
            use_internal=req.use_internal,
            sources=req.sources,
            history=history,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI chat failed")
        raise HTTPException(status_code=502, detail=f"AI chat failed: {exc}") from exc
    if req.session_id:
        try:
            session_controller.append_turn(req.session_id, req.prompt, answer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist session turn: %s", exc)
    return AgentChatResponse(
        response=answer,
        prompt=req.prompt,
        model=svc.info()["model"],
        response_time=round(time.time() - start, 2),
    )


@router.post(
    "/v1/agent/analyze",
    response_model=AgentChatResponse,
    summary="Analyze a message to the active AI agent",
)
async def agent_analyze(
    req: AgentChatRequest,
    profile_name: str = "default",
    locale: str | None = None,
    testrail_case_id: str = "unknown_testrail_case_id",
    case_id: str = "unknown_case_id",
    case_test_result: str = "Failed",
) -> AgentChatResponse:
    # Both the default locale and the prompt template live in config.yml
    # (analyze_config) and are editable from Settings. Read them fresh so edits
    # apply without a restart.
    cfg = _analyze_config()
    # When the caller doesn't pass a locale, use the configured default.
    locale = locale or cfg["default_locale"]

    # The prompt template has no built-in default; it must be set in Settings.
    if not cfg["prompt_template"].strip():
        raise HTTPException(
            status_code=400,
            detail="Analyze prompt template is not configured. Set it in "
            "Settings -> Agent Settings -> Analyze Settings.",
        )

    # The model can't open links, so if the prompt is a URL (e.g. a Jenkins
    # console log), fetch its content server-side and analyze that instead.
    content = req.prompt.strip()
    if content.startswith(("http://", "https://")) and "\n" not in content:
        try:
            content = _fetch_log_text(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch log url for analysis: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Could not fetch log content from {req.prompt}: {exc}",
            ) from exc

    # Language of the returned analysis is driven by `locale`.
    lang = "Chinese (简体中文)" if locale == "zh-CN" else "English"
    req.prompt = (
        cfg["prompt_template"].replace("{lang}", lang).replace("{content}", content)
    )
    response = await agent_chat(req)
    # save the response to a file on analyze_history folder
    analyze_history_folder = ANALYZER_PATH
    if not os.path.exists(analyze_history_folder):
        os.makedirs(analyze_history_folder)

    history_name = f"{testrail_case_id}__{profile_name}__{case_id}__{case_test_result}__{locale}__{time.strftime('%Y-%m-%d_%H-%M-%S')}.md"
    with open(os.path.join(analyze_history_folder, history_name), "w") as f:
        f.write(response.response)

    return AgentChatResponse(
        response=response.response,
        prompt=req.prompt,
        model=response.model,
        response_time=response.response_time,
    )


class AgentSearchRequest(BaseModel):
    query: str = Field(..., description="Search query text.")
    sources: list[str] | None = Field(
        default=None,
        description="Data sources to search, e.g. ['JIRA','CONFLUENCE','TESTRAIL'].",
    )
    limit: int = Field(default=10, description="Max results.", gt=0, le=50)


class AgentSearchResponse(BaseModel):
    query: str = Field(..., description="The query that was searched.")
    sources: list[str] | None = Field(..., description="Sources filter used.")
    count: int = Field(..., description="Number of results.")
    results: list[dict] = Field(..., description="Search results.")


@router.post(
    "/v1/agent/search",
    response_model=AgentSearchResponse,
    summary="Search indexed data (JIRA/Confluence/TestRail/GitLab/...) via ai_hub_search",
)
async def agent_search(req: AgentSearchRequest) -> AgentSearchResponse:
    svc = _get_service()
    try:
        results = await svc.search(req.query, sources=req.sources, limit=req.limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI search failed")
        raise HTTPException(status_code=502, detail=f"AI search failed: {exc}") from exc
    return AgentSearchResponse(
        query=req.query,
        sources=req.sources,
        count=len(results),
        results=results,
    )
