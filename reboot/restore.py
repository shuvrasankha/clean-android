"""Re-enable only what Reboot's backup record shows it may have changed, then verify."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reboot.adb import Adb
from reboot.apply import connection_lost
from reboot.backup import RESTORABLE, BackupWriteError, set_status, write_backup
from reboot.commands import enable_args
from reboot.scan import list_packages


@dataclass
class RestoreResult:
    outcomes: dict[str, str] = field(default_factory=dict)  # package -> restored | restore_failed
    stopped: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.stopped is None and all(s == "restored" for s in self.outcomes.values())


def restorable_packages(record: dict[str, Any]) -> list[str]:
    return [e["package"] for e in record["entries"] if e["status"] in RESTORABLE]


def restore_backup(adb: Adb, record: dict[str, Any], path: Path) -> RestoreResult:
    result = RestoreResult()
    if record["device"].get("serial") != adb.serial:
        result.stopped = "backup belongs to a different phone (serial differs)"
        return result

    targets = restorable_packages(record)
    if not targets:
        result.stopped = "nothing to restore in this backup"
        return result

    disabled, _ = list_packages(adb, "-d")
    if disabled is None:
        result.stopped = "could not read current package state; nothing changed"
        return result

    to_enable = [p for p in targets if p in disabled]
    for pkg in targets:
        if pkg not in disabled:
            set_status(record, pkg, "restored", "already enabled")

    for pkg in to_enable:
        res = adb.shell(*enable_args(pkg))
        if connection_lost(res):
            result.stopped = f"connection lost or ambiguous at {pkg}: {res.failure()}"
            break

    now_disabled, _ = list_packages(adb, "-d")
    if now_disabled is None:
        result.stopped = result.stopped or "could not verify the restore"
    else:
        for pkg in to_enable:
            if pkg in now_disabled:
                set_status(record, pkg, "restore_failed", "still disabled after pm enable")
                result.stopped = result.stopped or f"{pkg} is still disabled"
            else:
                set_status(record, pkg, "restored")

    try:
        write_backup(record, path)
    except BackupWriteError as exc:
        result.warnings.append(str(exc))

    result.outcomes = {
        e["package"]: e["status"] for e in record["entries"] if e["package"] in targets
    }
    return result
