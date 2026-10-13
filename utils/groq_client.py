"""Thin wrapper around the Groq chat-completions API.

Kept separate from the prompt-and-parse logic in
:mod:`extractors.case_study_extractor` so client setup and error mapping to
the app's HTTP error types live in one place.
"""

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
GROQ_TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", 0.2))
GROQ_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", 1536))

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
        _client = groq.Groq(api_key=api_key)
    return _client


def chat_json(system_prompt, user_prompt):
    """Send a chat completion request and return the parsed JSON reply.

    Raises :class:`GroqNotConfigured` if no API key is set, and
    :class:`GroqError` for any other failure (network, rate limit, bad
    response shape).
    """
    client = _get_client()

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
