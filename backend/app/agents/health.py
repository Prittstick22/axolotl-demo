"""Gemini reachability - owner: Dev 1 (minimal implementation by Dev 2).

Feeds `gemini` in GET /system/status (SHARED_CONTRACTS §6). This is a REAL check, not a
stub: with no API key it honestly reports unreachable; with a key it asks the API to
describe the configured model, which is the cheapest call that proves both the key and
the model name.

Dev 1 owns the model adapter and prompts; replace this with a call into that adapter when
it exists. Do not add a fake "ok" here (SHARED_CONTRACTS §0.2).
"""

import logging
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

_CACHE: dict[str, Any] | None = None


async def gemini_status(use_cache: bool = True) -> dict[str, Any]:
    """-> {reachable: bool, model: str, detail: str | None}.

    Result is cached for the process lifetime so the status endpoint, which the frontend
    polls, does not spend quota on every call. Pass use_cache=False to force a recheck.
    """
    global _CACHE
    if use_cache and _CACHE is not None:
        return _CACHE

    settings = get_settings()
    result: dict[str, Any]

    from app.agents import replay

    if replay.active():
        # Demo replay needs no key and makes no calls; say exactly that.
        result = {
            "reachable": True,
            "model": replay.model_label(),
            "detail": "replaying recorded Argon turns; no Gemini calls are made",
        }
        _CACHE = result
        return result

    if not settings.gemini_api_key:
        result = {
            "reachable": False,
            "model": settings.gemini_model,
            "detail": "GEMINI_API_KEY is not set",
        }
        _CACHE = result
        return result

    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        model = await client.aio.models.get(model=settings.gemini_model)
        result = {
            "reachable": True,
            "model": getattr(model, "name", settings.gemini_model),
            "detail": None,
        }
    except Exception as exc:  # noqa: BLE001 - reported as a status, never raised
        result = {
            "reachable": False,
            "model": settings.gemini_model,
            "detail": f"{type(exc).__name__}: {exc}"[:300],
        }
        log.info("Gemini unreachable: %s", result["detail"])

    _CACHE = result
    return result


def reset_cache() -> None:
    global _CACHE
    _CACHE = None
