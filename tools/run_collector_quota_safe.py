"""
Quota-safe launcher for collector.py.

Purpose:
- preserve collector.py as the main implementation;
- intercept only Gemini ARTICLE-SELECTION requests;
- stop immediately on ANY 429 response from Gemini article selection;
- let collector.py save ai_article_selection_cache.json and exit safely with code 75;
- avoid retry storms that waste Free Tier requests and time.
"""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import collector


_ORIGINAL_POST = collector.requests.post


def _flatten_error_payload(response):
    parts = []

    try:
        payload = response.json()
    except Exception:
        payload = None

    if payload is not None:
        try:
            parts.append(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        except Exception:
            parts.append(str(payload))

    try:
        parts.append(response.text or "")
    except Exception:
        pass

    return " ".join(parts).strip()


def _is_article_selection_request(kwargs):
    body = kwargs.get("json")

    if not isinstance(body, dict):
        return False

    instruction = str(
        body.get(
            "system_instruction",
            "",
        )
        or
        ""
    ).lower()

    if "final editorial relevance filter" in instruction:
        return True

    response_format = body.get("response_format")
    if not isinstance(response_format, dict):
        return False

    schema = response_format.get("schema")
    if not isinstance(schema, dict):
        return False

    properties = schema.get("properties")
    return (
        isinstance(properties, dict)
        and
        "results" in properties
    )


def quota_safe_post(url, *args, **kwargs):
    response = _ORIGINAL_POST(
        url,
        *args,
        **kwargs,
    )

    if (
        "generativelanguage.googleapis.com" in str(url)
        and
        _is_article_selection_request(kwargs)
        and
        getattr(response, "status_code", None) == 429
    ):
        detail = _flatten_error_payload(response)
        detail = " ".join(detail.split())[:500]

        print(
            "   AI selection 429 detected; stopping immediately "
            "without retry storm."
        )

        if detail:
            print(
                f"   Gemini 429 detail: {detail}"
            )

        raise collector.AISelectionQuotaError(
            "Gemini article-selection returned 429. "
            "The run is stopping immediately; cached progress is preserved."
        )

    return response


collector.requests.post = quota_safe_post


if __name__ == "__main__":
    collector.main()
