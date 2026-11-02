"""JSON scan report. Serial numbers are redacted unless the owner opts in."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reboot import __version__
from reboot.device import UNSUPPORTED
from reboot.scan import Inventory, ScanResult

SCHEMA_VERSION = 1
REDACTED = "redacted"


def _unsupported_if_none(value: Any) -> Any:
    return UNSUPPORTED if value is None else value


def _package_rows(inv: Inventory) -> list[dict[str, str]]:
    disabled = set(inv.disabled or [])
    enabled = set(inv.enabled or [])
    rows: list[dict[str, str]] = []
    for kind, names in (("system", inv.system), ("user", inv.user)):
        for name in names or []:
            if name in disabled:
                state = "disabled"
            elif inv.enabled is not None and name in enabled:
                state = "enabled"
            else:
                state = UNSUPPORTED
            rows.append({"id": name, "kind": kind, "state": state})
    return rows


def build_report(
    scan: ScanResult,
    serial: str,
    include_serial: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    inv = scan.inventory
    counts = {
        label: UNSUPPORTED if getattr(inv, label) is None else len(getattr(inv, label))
        for label in ("system", "user", "disabled", "enabled")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "read_only": True,
        "device": {"serial": serial if include_serial else REDACTED, **asdict(scan.device)},
        "capabilities": {k: _unsupported_if_none(v) for k, v in asdict(scan.capabilities).items()},
        "package_counts": counts,
        "packages": _package_rows(inv),
        "errors": list(scan.errors),
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
