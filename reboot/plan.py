"""Dry-run planning. Nothing here changes the phone: it reads state, applies guards, and returns
the exact commands that `apply` would run after per-package confirmation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reboot import __version__
from reboot.adb import Adb
from reboot.commands import disable_args, enable_args
from reboot.db import Database, Entry
from reboot.device import probe_capabilities, read_device_info
from reboot.guards import evaluate_guards
from reboot.names import require_valid_packages
from reboot.scan import list_packages

PLAN_SCHEMA = 1
OFFERED_TIERS = ("optional", "advanced")


@dataclass
class Assessment:
    device: dict[str, Any]
    eligible: list[Entry] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    blocked: str | None = None  # set when nothing may be planned or applied


def _major(release: str) -> int | None:
    m = re.match(r"\d+", release)
    return int(m.group()) if m else None


def assess(adb: Adb, db: Database, picks: list[str], allow_advanced: bool) -> Assessment:
    """Decide, from live device state, which picks may be disabled. Read-only.

    Raises InvalidPackageName if any pick is malformed (the whole list is refused).
    """
    names = list(dict.fromkeys(require_valid_packages(picks)))
    info, _ = read_device_info(adb)
    device = {
        "serial": adb.serial,
        "manufacturer": info.manufacturer,
        "model": info.model,
        "android_release": info.android_release,
    }
    result = Assessment(device)

    caps, _ = probe_capabilities(adb)
    if caps.pm_disable_user is not True:
        result.blocked = "could not confirm that this phone supports `pm disable-user`"
        return result
    system, _ = list_packages(adb, "-s")
    disabled, _ = list_packages(adb, "-d")
    if system is None or disabled is None:
        result.blocked = "could not read the package list; refusing to guess"
        return result
    sdk = info.sdk if isinstance(info.sdk, int) else None
    guards = evaluate_guards(adb, caps, sdk)
    if guards.incomplete:
        result.blocked = "could not determine: " + ", ".join(guards.incomplete)
        return result

    major = _major(str(info.android_release))
    for pkg in names:
        entry = db.lookup(pkg, major)
        if entry is None:
            result.skipped.append((pkg, "unknown: not in the database for this Android version"))
        elif entry.protected:
            result.skipped.append((pkg, "protected"))
        elif entry.tier not in OFFERED_TIERS:
            result.skipped.append((pkg, f"tier is {entry.tier}"))
        elif entry.tier == "advanced" and not allow_advanced:
            result.skipped.append((pkg, "advanced tier needs --allow-advanced"))
        elif pkg not in system:
            result.skipped.append((pkg, "not installed as a system package"))
        elif pkg in disabled:
            result.skipped.append((pkg, "already disabled"))
        elif pkg in guards.protected:
            result.skipped.append((pkg, "guard: " + "; ".join(guards.protected[pkg])))
        else:
            result.eligible.append(entry)
    return result


def build_plan(assessment: Assessment, allow_advanced: bool, now: datetime) -> dict[str, Any]:
    return {
        "schema_version": PLAN_SCHEMA,
        "tool_version": __version__,
        "created_at": now.isoformat(timespec="seconds"),
        "dry_run": True,
        "allow_advanced": allow_advanced,
        "device": assessment.device,
        "actions": [
            {
                "package": e.id,
                "label": e.label,
                "tier": e.tier,
                "confidence": e.confidence,
                "why": e.why,
                "consequences": e.consequences,
                # Display only: apply rebuilds commands from the validated package name.
                "command": "adb shell " + " ".join(disable_args(e.id)),
                "restore_command": "adb shell " + " ".join(enable_args(e.id)),
            }
            for e in assessment.eligible
        ],
        "skipped": [{"package": p, "reason": r} for p, r in assessment.skipped],
    }
