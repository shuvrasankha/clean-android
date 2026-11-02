"""Execute a plan: re-check, confirm per package, back up first, small batches, verify."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reboot.adb import Adb, AdbResult
from reboot.backup import (
    BackupWriteError,
    backup_path,
    new_record,
    set_status,
    utcnow,
    write_backup,
)
from reboot.commands import disable_args
from reboot.db import Database, Entry
from reboot.names import InvalidPackageName, require_valid_packages
from reboot.plan import PLAN_SCHEMA, assess
from reboot.scan import list_packages

BATCH_SIZE = 5
_LOST_RE = re.compile(
    r"not found|no devices|offline|unauthorized|closed|protocol fault|cannot connect", re.I
)


@dataclass
class ApplyResult:
    backup: Path | None = None
    outcomes: dict[str, str] = field(default_factory=dict)  # package -> final status
    skipped: list[tuple[str, str]] = field(default_factory=list)
    stopped: str | None = None  # why we stopped early, or why nothing ran

    @property
    def complete(self) -> bool:
        return self.stopped is None and all(s == "disabled" for s in self.outcomes.values())


def connection_lost(res: AdbResult) -> bool:
    """Disconnect, timeout or other ambiguous transport failure: stop and do not guess."""
    return res.error is not None or (not res.ok and bool(_LOST_RE.search(res.text)))


def plan_packages(plan: dict[str, Any]) -> list[str]:
    """Package names from a plan file, all-or-nothing validated. File commands are ignored."""
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError("unsupported plan schema_version")
    names = [a["package"] for a in plan["actions"]]
    return list(dict.fromkeys(require_valid_packages(names)))


def apply_plan(
    adb: Adb,
    plan: dict[str, Any],
    db: Database,
    backup_dir: Path,
    confirm: Callable[[Entry], bool],
    batch_size: int = BATCH_SIZE,
) -> ApplyResult:
    result = ApplyResult()
    try:
        packages = plan_packages(plan)
    except (ValueError, KeyError, TypeError, InvalidPackageName) as exc:
        result.stopped = f"plan file refused: {exc}"
        return result

    # Re-assess against live state: the keyboard, home app or package states may have changed.
    assessment = assess(adb, db, packages, bool(plan.get("allow_advanced")))
    result.skipped = list(assessment.skipped)
    if assessment.blocked:
        result.stopped = assessment.blocked
        return result
    planned = plan.get("device", {})
    for key in ("serial", "model", "android_release"):
        if planned.get(key) != assessment.device.get(key):
            result.stopped = f"connected phone does not match the plan ({key} differs)"
            return result

    confirmed: list[str] = []
    for entry in assessment.eligible:
        if confirm(entry):
            confirmed.append(entry.id)
        else:
            result.skipped.append((entry.id, "not confirmed"))
    if not confirmed:
        result.stopped = "nothing confirmed; no changes made"
        return result

    # Back up before any change; stop if it cannot be written.
    now = utcnow()
    path = backup_path(backup_dir, now)
    record = new_record(assessment.device, confirmed, now)
    try:
        write_backup(record, path)
    except BackupWriteError as exc:
        result.stopped = f"{exc}; no changes made"
        return result
    result.backup = path

    for start in range(0, len(confirmed), batch_size):
        batch = confirmed[start : start + batch_size]
        for pkg in batch:
            set_status(record, pkg, "pending")
        try:
            write_backup(record, path)
        except BackupWriteError as exc:
            result.stopped = f"{exc}; stopped before changing {batch[0]}"
            _finalize(result, record)
            return result

        attempted: dict[str, AdbResult] = {}
        for pkg in batch:
            res = adb.shell(*disable_args(pkg))
            attempted[pkg] = res
            if connection_lost(res):
                result.stopped = f"connection lost or ambiguous at {pkg}: {res.failure()}"
                break

        disabled, _ = list_packages(adb, "-d")
        if disabled is None:
            result.stopped = result.stopped or "could not verify the batch; stopping"
        else:
            for pkg, res in attempted.items():
                if pkg in disabled:
                    set_status(record, pkg, "disabled")
                else:
                    status = "failed" if not res.ok else "verify_failed"
                    set_status(record, pkg, status, res.failure() if not res.ok else "")
                    result.stopped = result.stopped or f"{pkg} did not verify as disabled"
        try:
            write_backup(record, path)
        except BackupWriteError as exc:
            result.stopped = result.stopped or f"{exc}; stopping"
        if result.stopped:
            break

    _finalize(result, record)
    return result


def _finalize(result: ApplyResult, record: dict[str, Any]) -> None:
    result.outcomes = {e["package"]: e["status"] for e in record["entries"]}
