"""Backup records: written and fsynced to disk before any change, updated after every batch.

Statuses: planned (not touched), pending (command about to run / outcome unknown), disabled,
failed, verify_failed, restored, restore_failed.
Backups contain the device serial: keep them local, do not share them.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reboot import __version__
from reboot.commands import disable_args, enable_args
from reboot.names import require_valid_packages

BACKUP_SCHEMA = 1
# A package in one of these states may currently be disabled by Reboot, so restore must check it.
RESTORABLE = ("pending", "disabled", "failed", "verify_failed", "restore_failed")


class BackupWriteError(Exception):
    pass


class BackupReadError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def backup_path(directory: Path, now: datetime) -> Path:
    return directory / f"backup-{now.strftime('%Y%m%dT%H%M%SZ')}.json"


def new_record(device: dict[str, Any], packages: list[str], now: datetime) -> dict[str, Any]:
    return {
        "schema_version": BACKUP_SCHEMA,
        "tool_version": __version__,
        "created_at": now.isoformat(timespec="seconds"),
        "device": device,
        "entries": [
            {
                "package": p,
                "prior_state": "enabled",
                "command": " ".join(disable_args(p)),
                "restore_command": " ".join(enable_args(p)),
                "status": "planned",
                "detail": "",
                "updated_at": now.isoformat(timespec="seconds"),
            }
            for p in packages
        ],
    }


def set_status(record: dict[str, Any], package: str, status: str, detail: str = "") -> None:
    for entry in record["entries"]:
        if entry["package"] == package:
            entry["status"] = status
            entry["detail"] = detail
            entry["updated_at"] = utcnow().isoformat(timespec="seconds")
            return
    raise KeyError(package)


def write_backup(record: dict[str, Any], path: Path) -> None:
    """Atomic write: temp file, flush, fsync, replace. Raises BackupWriteError on any failure."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        raise BackupWriteError(f"could not write backup {path}: {exc}") from exc


def read_backup(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
        if record.get("schema_version") != BACKUP_SCHEMA:
            raise BackupReadError(f"unsupported backup schema in {path}")
        require_valid_packages(e["package"] for e in record["entries"])
        record["device"]["serial"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BackupReadError(f"could not read backup {path}: {exc}") from exc
    return record
