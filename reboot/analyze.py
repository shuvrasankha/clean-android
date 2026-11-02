"""Join a scan report with the database. Offline and read-only: it never touches a device."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reboot.db import TIERS, Database, Entry


@dataclass
class Row:
    entry: Entry
    state: str  # enabled | disabled | unsupported


@dataclass
class Analysis:
    android_major: int | None
    protected: list[Row] = field(default_factory=list)
    by_tier: dict[str, list[Row]] = field(default_factory=lambda: {t: [] for t in TIERS})
    unknown: list[str] = field(default_factory=list)  # system packages not in the database
    user_app_count: int = 0


def android_major(report: dict[str, Any]) -> int | None:
    release = str(report.get("device", {}).get("android_release", ""))
    m = re.match(r"\d+", release)
    return int(m.group()) if m else None


def analyze_report(report: dict[str, Any], db: Database) -> Analysis:
    major = android_major(report)
    result = Analysis(major)
    for pkg in report.get("packages", []):
        if pkg.get("kind") == "user":
            result.user_app_count += 1
            continue
        entry = db.lookup(pkg["id"], major)
        if entry is None:
            result.unknown.append(pkg["id"])
        elif entry.protected:
            result.protected.append(Row(entry, pkg["state"]))
        else:
            result.by_tier[entry.tier].append(Row(entry, pkg["state"]))
    result.unknown.sort()
    return result
