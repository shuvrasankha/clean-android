"""Load and validate the package database. Anything not in it is `unknown` and never offered."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from reboot.miniyaml import YamlSubsetError, parse_entries
from reboot.names import is_valid_package

TIERS = ("keep", "optional", "advanced")
CONFIDENCE = ("high", "medium", "low")
REQUIRED = (
    "id",
    "oem",
    "label",
    "tier",
    "why",
    "consequences",
    "sources",
    "confidence",
    "reviewed",
)
OPTIONAL = ("protected", "android_min", "android_max")
COMMON = "common"


class DatabaseError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Entry:
    id: str
    oem: str
    label: str
    tier: str
    why: str
    consequences: str
    sources: tuple[str, ...]
    confidence: str
    reviewed: date
    protected: bool = False
    android_min: int | None = None
    android_max: int | None = None

    def applies_to(self, android_major: int | None) -> bool:
        """True only when the version is known to be in range. Unknown version never matches a
        ranged entry."""
        if self.android_min is None and self.android_max is None:
            return True
        if android_major is None:
            return False
        if self.android_min is not None and android_major < self.android_min:
            return False
        return not (self.android_max is not None and android_major > self.android_max)


@dataclass
class Database:
    entries: dict[str, Entry] = field(default_factory=dict)

    def lookup(self, package: str, android_major: int | None) -> Entry | None:
        entry = self.entries.get(package)
        return entry if entry and entry.applies_to(android_major) else None


def _is_evidence(source: object) -> bool:
    return isinstance(source, str) and (
        source.startswith(("https://", "http://")) or source.startswith("device:")
    )


def validate_entry(raw: dict, where: str) -> tuple[Entry | None, list[str]]:
    problems: list[str] = []

    def bad(msg: str) -> None:
        problems.append(f"{where}: {msg}")

    for key in raw:
        if key not in REQUIRED and key not in OPTIONAL:
            bad(f"unknown field {key!r}")
    for key in REQUIRED:
        if key not in raw:
            bad(f"missing required field {key!r}")
    if problems:
        return None, problems

    for key in ("id", "oem", "label", "why", "consequences"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            bad(f"{key} must be a non-empty string")
    if isinstance(raw["id"], str) and not is_valid_package(raw["id"]):
        bad(f"id {raw['id']!r} is not a valid package name")
    if raw["tier"] not in TIERS:
        bad(f"tier must be one of {TIERS}")
    if raw["confidence"] not in CONFIDENCE:
        bad(f"confidence must be one of {CONFIDENCE}")

    sources = raw["sources"]
    if not isinstance(sources, list) or not sources:
        bad("sources must be a non-empty list (evidence is required)")
    elif not all(_is_evidence(s) for s in sources):
        bad("each source must be an http(s) URL or a 'device:' observation")

    reviewed = None
    if isinstance(raw["reviewed"], str):
        try:
            reviewed = date.fromisoformat(raw["reviewed"])
        except ValueError:
            pass
    if reviewed is None:
        bad("reviewed must be a YYYY-MM-DD date")

    protected = raw.get("protected", False)
    if not isinstance(protected, bool):
        bad("protected must be true or false")
    elif protected and raw["tier"] != "keep":
        bad("protected entries must have tier 'keep'")

    bounds: dict[str, int | None] = {}
    for key in ("android_min", "android_max"):
        val = raw.get(key)
        if val is not None and (isinstance(val, bool) or not isinstance(val, int) or val < 1):
            bad(f"{key} must be a positive integer")
        bounds[key] = val if isinstance(val, int) and not isinstance(val, bool) else None
    lo, hi = bounds["android_min"], bounds["android_max"]
    if lo is not None and hi is not None and lo > hi:
        bad("android_min is greater than android_max")

    if problems:
        return None, problems
    return (
        Entry(
            id=raw["id"],
            oem=raw["oem"],
            label=raw["label"],
            tier=raw["tier"],
            why=raw["why"],
            consequences=raw["consequences"],
            sources=tuple(sources),
            confidence=raw["confidence"],
            reviewed=reviewed,
            protected=protected,
            android_min=lo,
            android_max=hi,
        ),
        [],
    )


def load_database(directory: Path) -> Database:
    """Load every *.yaml in `directory`. Raises DatabaseError listing every problem found."""
    problems: list[str] = []
    db = Database()
    seen_in: dict[str, str] = {}
    files = sorted(directory.glob("*.yaml")) if directory.is_dir() else []
    if not any(f.stem == COMMON for f in files):
        problems.append(f"{directory}: missing {COMMON}.yaml (protected packages)")

    for path in files:
        try:
            raws = parse_entries(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, YamlSubsetError) as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        for i, raw in enumerate(raws, start=1):
            where = f"{path.name} entry {i} ({raw.get('id', '?')})"
            entry, errs = validate_entry(raw, where)
            problems += errs
            if entry is None:
                continue
            if entry.oem != path.stem:
                problems.append(f"{where}: oem {entry.oem!r} does not match file {path.name}")
            if path.stem == COMMON and not entry.protected:
                problems.append(f"{where}: entries in {COMMON}.yaml must be protected: true")
            if entry.id in seen_in:
                problems.append(f"{where}: duplicate id, already defined in {seen_in[entry.id]}")
                continue
            seen_in[entry.id] = path.name
            db.entries[entry.id] = entry

    if problems:
        raise DatabaseError(problems)
    return db
