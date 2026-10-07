"""Heuristic prompt-injection detector, sentence-level redaction, and untrusted-data wrapping."""

import re
from dataclasses import dataclass

PATTERNS = [
    r"ignore (all )?(previous|prior|above) (instructions|prompts)",
    r"(system|developer) (override|prompt|message)",
    r"you are now",
    r"(admin|developer|god) mode",
    r"jailbreak",
    r"(mark|set) .{0,40}(approved|compliance)",
    r"do not (mention|reveal|tell)",
    r"</?(system|instructions?)>",
    r"act as (an?|the) ",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in PATTERNS]
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TAG = re.compile(r"</?untrusted_data[^>]*>", re.IGNORECASE)
REDACTED = "[REDACTED: suspected embedded instruction]"


@dataclass(frozen=True)
class InjectionHit:
    pattern: str
    excerpt: str


def detect(text: str) -> list[InjectionHit]:
    return [
        InjectionHit(p.pattern, text[max(0, m.start() - 40) : m.end() + 40][:120])
        for p in _COMPILED
        if (m := p.search(text))
    ]


def redact(text: str) -> str:
    """Replace every sentence that triggers a pattern with the REDACTED marker."""
    out = [REDACTED if detect(s) else s for s in _SENTENCE.split(text)]
    return " ".join(out)


def wrap(text: str, source: str, id: str, date: str | None = None) -> str:
    """Wrap untrusted text in a data tag after stripping any tag break-out from the text itself."""
    attrs = f'source="{source}" id="{id}"' + (f' date="{date}"' if date else "")
    return f"<untrusted_data {attrs}>{_TAG.sub('', text)}</untrusted_data>"
