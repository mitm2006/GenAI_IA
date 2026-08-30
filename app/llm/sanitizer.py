"""
Reasoning sanitizer — the last line of defence against chain-of-thought leakage.

Reasoning-capable models such as ``openai/gpt-oss-20b`` emit their deliberation on
a separate channel from their answer. Groq is asked to drop that channel entirely
(``reasoning_format="hidden"``), and the provider parser only ever reads
``message.content``. This module exists because neither of those guarantees is
absolute: a provider default can change, a proxy can be misconfigured, a model can
be prompted into emitting ``<think>`` markup inside ``content`` itself.

So every string that leaves the LLM layer passes through :func:`strip_reasoning`
first. The module never reconstructs, summarises or exposes hidden reasoning — it
only *removes* it. If a response turns out to be reasoning end to end, the result
is an empty string and the caller fails the request rather than shipping the
deliberation to a browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Tag names that reasoning-capable models use to wrap internal deliberation.
_REASONING_TAGS = (
    "think",
    "thinking",
    "thought",
    "thoughts",
    "reason",
    "reasoning",
    "reflection",
    "analysis",
    "scratchpad",
    "internal",
    "monologue",
)

_TAG_ALTERNATION = "|".join(_REASONING_TAGS)

# <think> ... </think>  (balanced, any casing, spanning newlines)
_BALANCED_BLOCK = re.compile(
    rf"<\s*({_TAG_ALTERNATION})\s*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)

# A block that was opened but never closed — the model was truncated mid-thought.
# Everything from the opening tag onwards is deliberation, so it all goes.
_DANGLING_OPEN = re.compile(
    rf"<\s*({_TAG_ALTERNATION})\s*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)

# An orphan closing tag: reasoning preceded it, so drop the head as well.
_DANGLING_CLOSE = re.compile(
    rf"\A.*?<\s*/\s*({_TAG_ALTERNATION})\s*>",
    re.IGNORECASE | re.DOTALL,
)

# Harmony-format control tokens (gpt-oss): <|start|>, <|channel|>, <|message|>, ...
_HARMONY_FINAL = re.compile(
    r"<\|channel\|>\s*final\s*<\|message\|>",
    re.IGNORECASE,
)
_HARMONY_NON_FINAL_BLOCK = re.compile(
    r"<\|channel\|>\s*(?!final)\w+\s*<\|message\|>.*?(?=<\|(?:end|return|start|channel)\|>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_HARMONY_CONTROL_TOKEN = re.compile(r"<\|[^|>]{0,64}\|>")

# Harmony markers that survived detokenisation as plain words:
#   "analysisWe should ... assistantfinalHere is the answer"
_PLAINTEXT_FINAL = re.compile(r"assistant\s*final", re.IGNORECASE)

# Markdown-style headings some models use to announce a reasoning section.
_MARKDOWN_REASONING_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s*(chain[- ]of[- ]thought|reasoning|thinking|internal (?:analysis|monologue))\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_MULTI_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class SanitizedText:
    """Outcome of a sanitation pass."""

    text: str
    was_modified: bool

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return bool(self.text)


def contains_reasoning_markers(text: str) -> bool:
    """True if ``text`` still shows any sign of reasoning markup."""
    if not text:
        return False
    return bool(
        _BALANCED_BLOCK.search(text)
        or re.search(rf"<\s*/?\s*({_TAG_ALTERNATION})\s*>", text, re.IGNORECASE)
        or _HARMONY_CONTROL_TOKEN.search(text)
        or _PLAINTEXT_FINAL.search(text)
    )


def strip_reasoning(text: str | None) -> SanitizedText:
    """
    Remove any internal reasoning from a model completion.

    The transformation is purely subtractive: reasoning content is discarded, and
    only the final user-facing answer survives. An empty result means the whole
    completion was deliberation and there is no answer to show.
    """
    if not text:
        return SanitizedText("", False)

    original = text
    cleaned = text

    # 1. Harmony: if an explicit final channel exists, keep only what follows the
    #    last one. Everything before it is analysis/commentary by construction.
    final_marker = None
    for final_marker in _HARMONY_FINAL.finditer(cleaned):
        pass
    if final_marker is not None:
        cleaned = cleaned[final_marker.end():]

    # 2. Same idea for the detokenised "assistantfinal" spelling.
    plain_marker = None
    for plain_marker in _PLAINTEXT_FINAL.finditer(cleaned):
        pass
    if plain_marker is not None:
        cleaned = cleaned[plain_marker.end():]

    # 3. Drop remaining non-final harmony channels and any leftover control tokens.
    cleaned = _HARMONY_NON_FINAL_BLOCK.sub("", cleaned)
    cleaned = _HARMONY_CONTROL_TOKEN.sub("", cleaned)

    # 4. Remove balanced <think>…</think> style blocks, repeatedly, so that
    #    nested or sequential blocks cannot survive a single pass.
    for _ in range(8):
        collapsed = _BALANCED_BLOCK.sub("", cleaned)
        if collapsed == cleaned:
            break
        cleaned = collapsed

    # 5. An orphan </think> means the head of the string was reasoning.
    cleaned = _DANGLING_CLOSE.sub("", cleaned)

    # 6. An orphan <think> means the tail is reasoning (truncated generation).
    cleaned = _DANGLING_OPEN.sub("", cleaned)

    # 7. Strip explicit reasoning headings without touching the prose under them,
    #    then tidy the whitespace the removals left behind.
    cleaned = _MARKDOWN_REASONING_HEADING.sub("", cleaned)
    cleaned = _MULTI_BLANK_LINES.sub("\n\n", cleaned).strip()

    return SanitizedText(cleaned, cleaned != original.strip())
