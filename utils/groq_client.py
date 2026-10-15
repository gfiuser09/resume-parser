"""Thin wrapper around the Groq chat-completions API.

Kept separate from the prompt-and-parse logic in
:mod:`extractors.case_study_extractor` so client setup and error mapping to
the app's HTTP error types live in one place.
"""

import base64
import json
import logging
import os

from utils.errors import GroqError, GroqNotConfigured

try:
    import groq
except ImportError:  # pragma: no cover
    groq = None

logger = logging.getLogger(__name__)

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
#: Groq's only vision-capable free-tier model as of 2026-10; handles OCR
#: directly from an image, so it replaces local Tesseract OCR for the
#: case-study pipeline (Tesseract is CPU-bound and unusably slow on
#: CPU-throttled hosts like Render's free tier).
GROQ_VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
GROQ_TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", 0.2))
GROQ_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", 1536))
#: Bounds how long a stalled network call can occupy a worker (the SDK has
#: no timeout by default, which turns a stalled connection into a hang).
GROQ_TIMEOUT_SECONDS = float(os.environ.get("GROQ_TIMEOUT_SECONDS", 60))

#: Lazily created and cached; a fresh key set via the environment during
#: tests still takes effect since the cache is only populated on first use.
_client = None


def _get_client():
    global _client
    if groq is None:
        raise GroqNotConfigured("groq package is not installed. Run: pip install groq")

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise GroqNotConfigured()

    if _client is None:
        _client = groq.Groq(api_key=api_key, timeout=GROQ_TIMEOUT_SECONDS)
    return _client


def _create_completion(model, messages):
    """Run a chat completion and return the parsed JSON reply.

    Raises :class:`GroqNotConfigured` if no API key is set, and
    :class:`GroqError` for any other failure (network, rate limit, bad
    response shape).
    """
    client = _get_client()

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=GROQ_TEMPERATURE,
            max_tokens=GROQ_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
    except groq.AuthenticationError as exc:
        raise GroqNotConfigured("Groq API key was rejected") from exc
    except groq.RateLimitError as exc:
        raise GroqError(
            "Summarisation service is rate limited, try again shortly", status_code=429
        ) from exc
    except groq.APITimeoutError as exc:
        logger.warning("Groq request timed out after %ss: %s", GROQ_TIMEOUT_SECONDS, exc)
        raise GroqError("Summarisation service timed out", status_code=504) from exc
    except groq.APIConnectionError as exc:
        logger.warning("Groq connection error: %s", exc)
        raise GroqError("Could not reach the summarisation service", status_code=502) from exc
    except groq.APIStatusError as exc:
        logger.warning("Groq API error: %s", exc)
        raise GroqError("Summarisation service returned an error", status_code=502) from exc

    try:
        content = completion.choices[0].message.content
        return json.loads(content)
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Unexpected Groq response shape: %s", exc)
        raise GroqError("Summarisation service returned an unexpected response") from exc


def chat_json(system_prompt, user_prompt):
    """Send a text-only chat completion request and return the parsed JSON reply."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return _create_completion(GROQ_MODEL, messages)


def chat_json_vision(system_prompt, user_text, images):
    """Send a chat completion request that includes image inputs.

    *images* is a list of ``(mime_type, raw_bytes)`` tuples. Each image is
    base64-encoded as a ``data:`` URL, which is how Groq's OpenAI-compatible
    vision endpoint accepts inline images (no separate upload step).
    """
    content = [{"type": "text", "text": user_text}]
    for mime_type, raw_bytes in images:
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]
    return _create_completion(GROQ_VISION_MODEL, messages)
