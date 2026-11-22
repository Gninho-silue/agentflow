"""Computed facts and the deterministic report checker.

The CodeAgent's sandbox extracts *indicators* from the pandas objects the code
computed (per-category values). ``build_facts`` turns them into the facts JSON
the Reporter must stick to; ``verify_report`` checks a report against it:

(a) every number in the report exists in the facts (at the report's precision);
(b) every superlative ("highest", "lowest", "le plus élevé"...) tied to an
    indicator names the category that is really its max / min;
(c) no indicator gets contradictory superlatives in the same report.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_MAX_NUMBERS = 1000

# --- Facts ----------------------------------------------------------------------


def build_facts(
    indicators: dict[str, dict[str, float]] | None,
    stdout: str = "",
    file_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Facts JSON: ranked indicators plus every number the run produced."""

    ranked: dict[str, Any] = {}
    numbers: set[float] = set()
    for name, values in (indicators or {}).items():
        clean = {str(label): float(value) for label, value in values.items()}
        if len(clean) < 2:
            continue
        top, bottom = max(clean.values()), min(clean.values())
        ranked[name] = {
            "values": clean,
            "max": next(label for label, value in clean.items() if value == top),
            "min": next(label for label, value in clean.items() if value == bottom),
            "max_all": [label for label, value in clean.items() if value == top],
            "min_all": [label for label, value in clean.items() if value == bottom],
        }
        numbers.update(clean.values())
        numbers.add(float(len(clean)))

    numbers.update(value for value, _, _ in extract_numbers(stdout or ""))
    data = file_data or {}
    if isinstance(data.get("row_count"), (int, float)):
        numbers.add(float(data["row_count"]))
    if isinstance(data.get("columns"), list):
        numbers.add(float(len(data["columns"])))

    return {"indicators": ranked, "numbers": sorted(numbers)[:_MAX_NUMBERS]}


# --- Numbers --------------------------------------------------------------------

_NUMBER = re.compile(
    r"(?<![\w.,])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<pct>\s?%)?(?![\w])"
)
_STRIP = (
    re.compile(r"!\[[^\]]*\]\([^)]*\)"),  # markdown images
    re.compile(r"<img\b[^>]*>", re.IGNORECASE),  # html images
    re.compile(r"\]\([^)]*\)"),  # link targets
    re.compile(r"https?://\S+"),
    re.compile(r"^\s*\d+\.\s", re.MULTILINE),  # numbered list markers
)


def extract_numbers(text: str) -> list[tuple[float, int, bool]]:
    """Numbers in ``text`` as (value, decimals, is_percent), skipping links and list markers."""

    for pattern in _STRIP:
        text = pattern.sub(" ", text)
    found = []
    for match in _NUMBER.finditer(text):
        raw = match.group("num")
        decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
        found.append((float(raw.replace(",", "")), decimals, bool(match.group("pct"))))
    return found


def _known(value: float, decimals: int, percent: bool, numbers: list[float]) -> bool:
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    candidates = [value, value / 100] if percent else [value]
    for candidate in candidates:
        scale = 100 if (percent and candidate == value / 100) else 1
        if any(abs(fact - candidate) <= tolerance / scale for fact in numbers):
            return True
    # Small whole numbers ("top 3", "2 categories") are counting words, not results.
    return not percent and decimals == 0 and value <= 10


# --- Superlatives ---------------------------------------------------------------

_MAX_WORDS = (
    r"highest|largest|biggest|greatest|maximum|best|top|most|"
    r"plus (?:élevée?s?|grande?s?|haute?s?|fort(?:e|s|es)?)|le plus|la plus|les plus|meilleure?s?"
)
_MIN_WORDS = (
    r"lowest|smallest|least|fewest|minimum|worst|bottom|"
    r"plus (?:bas(?:ses?)?|faibles?|petite?s?)|le moins|la moins|les moins|pires?"
)
_MAX_RE = re.compile(rf"\b(?:{_MAX_WORDS})\b", re.IGNORECASE)
_MIN_RE = re.compile(rf"\b(?:{_MIN_WORDS})\b", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<!\d)[.!?](?!\d)|\n")
_CLAUSES = re.compile(r";|\b(?:and|while|whereas|but|et|mais|tandis que|alors que)\b", re.IGNORECASE)
_GENERIC = {
    "avg", "average", "mean", "total", "sum", "count", "nb", "num", "number", "of", "per", "by",
    "the", "moyenne", "moyen", "value", "values",
}


def _indicator_patterns(name: str) -> re.Pattern[str]:
    tokens = [t for t in re.split(r"[_\W]+", name.lower()) if t]
    meaningful = [t for t in tokens if t not in _GENERIC] or tokens
    return re.compile("".join(rf"(?=.*\b{re.escape(t)})" for t in meaningful), re.IGNORECASE | re.DOTALL)


def _direction(clause: str) -> str | None:
    # "le plus bas" contains "le plus": test the minimum words first.
    if _MIN_RE.search(clause):
        return "min"
    if _MAX_RE.search(clause):
        return "max"
    return None


def verify_report(report: str, facts: dict[str, Any] | None) -> list[str]:
    """Return human-readable problems; an empty list means the report is consistent."""

    facts = facts or {}
    indicators: dict[str, Any] = facts.get("indicators") or {}
    numbers: list[float] = facts.get("numbers") or []
    if not indicators and not numbers:
        return []

    errors: list[str] = []

    # (a) numbers
    seen: set[str] = set()
    cleaned = report
    for pattern in _STRIP:
        cleaned = pattern.sub(" ", cleaned)
    for match in _NUMBER.finditer(cleaned):
        raw = match.group("num")
        decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
        value = float(raw.replace(",", ""))
        if not _known(value, decimals, bool(match.group("pct")), numbers):
            label = raw + ("%" if match.group("pct") else "")
            if label not in seen:
                seen.add(label)
                errors.append(f"The number {label} does not appear in the computed results.")

    # (b) superlatives and (c) contradictions
    labels = sorted({label for data in indicators.values() for label in data["values"]}, key=len, reverse=True)
    label_res = {label: re.compile(rf"\b{re.escape(label)}\b", re.IGNORECASE) for label in labels}
    indicator_res = {name: _indicator_patterns(name) for name in indicators}
    claims: dict[tuple[str, str], set[str]] = defaultdict(set)

    for sentence in _SENTENCES.split(report):
        sentence_labels = [label for label in labels if label_res[label].search(sentence)]
        subject = sentence_labels[:1]
        direction: str | None = None
        for clause in _CLAUSES.split(sentence):
            clause_labels = [label for label in labels if label_res[label].search(clause)] or subject
            direction = _direction(clause) or direction
            if direction is None or not clause_labels:
                continue
            for name, pattern in indicator_res.items():
                if not pattern.search(clause):
                    continue
                data = indicators[name]
                expected = data[f"{direction}_all"]
                if not set(clause_labels) & set(expected):
                    word = "highest" if direction == "max" else "lowest"
                    for label in clause_labels:
                        message = f"'{label}' is not the {word} for {name}: the {word} is {', '.join(expected)}."
                        if message not in errors:
                            errors.append(message)
                claims[(name, direction)].update(set(clause_labels) & set(expected) or clause_labels)

    for (name, direction), claimed in sorted(claims.items()):
        expected = set(indicators[name][f"{direction}_all"])
        if len(claimed) > 1 and not claimed <= expected:
            word = "highest" if direction == "max" else "lowest"
            errors.append(
                f"Contradiction on {name}: the report calls {', '.join(sorted(claimed))} the {word}."
            )
    for name in indicators:
        both = claims.get((name, "max"), set()) & claims.get((name, "min"), set())
        spread = indicators[name]["max_all"] != indicators[name]["min_all"]
        for label in sorted(both):
            if spread:
                errors.append(f"Contradiction on {name}: '{label}' is called both the highest and the lowest.")

    return errors
