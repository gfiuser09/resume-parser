"""Resume extraction layer.

``extract_resume_data(text)`` is the only function the Flask layer calls. It
delegates to the engine registered under :data:`DEFAULT_ENGINE` (overridable
with the ``EXTRACTION_ENGINE`` environment variable), which keeps the HTTP API
stable while the extraction strategy evolves.

Registering a smarter engine later::

    from extractors import ExtractionEngine, register_engine

    class LLMEngine(ExtractionEngine):
        name = "llm"

        def extract(self, text):
            ...  # call a model, return the same dictionary shape

    register_engine(LLMEngine)
"""

import os

from .education import extract_education
from .experience import extract_experience
from .resume_extractor import (
    EMPTY_RESULT,
    ExtractionEngine,
    RuleBasedEngine,
    extract_email,
    extract_name,
)
from .skills import extract_skills

#: engine name -> engine class
ENGINES = {RuleBasedEngine.name: RuleBasedEngine}

DEFAULT_ENGINE = os.environ.get("EXTRACTION_ENGINE", RuleBasedEngine.name)


def register_engine(engine_class, name=None):
    """Make *engine_class* selectable by name. Returns the registered name."""
    key = name or engine_class.name
    ENGINES[key] = engine_class
    return key


def get_engine(name=None):
    """Instantiate the engine called *name* (falls back to the rule-based one)."""
    key = name or DEFAULT_ENGINE
    engine_class = ENGINES.get(key, RuleBasedEngine)
    return engine_class()


def extract_resume_data(text, engine=None):
    """Extract structured candidate data from already-extracted resume *text*.

    *engine* may be an engine name, an :class:`ExtractionEngine` instance, or
    ``None`` to use the default.
    """
    if isinstance(engine, ExtractionEngine):
        return engine.extract(text)
    return get_engine(engine).extract(text)


__all__ = [
    "DEFAULT_ENGINE",
    "EMPTY_RESULT",
    "ENGINES",
    "ExtractionEngine",
    "RuleBasedEngine",
    "extract_education",
    "extract_email",
    "extract_experience",
    "extract_name",
    "extract_resume_data",
    "extract_skills",
    "get_engine",
    "register_engine",
]
