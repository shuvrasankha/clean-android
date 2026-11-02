"""Read-only inventory. Runs only `getprop`, `cat`, `df`, `pm list` and `pm help`-style queries."""

from __future__ import annotations

from dataclasses import dataclass, field

from reboot.adb import Adb
from reboot.device import (
    DeviceCapabilities,
    DeviceInfo,
    probe_capabilities,
    read_device_info,
)
from reboot.names import is_valid_package

# Label -> `pm list packages` filter flag
PACKAGE_FILTERS = {"system": "-s", "user": "-3", "disabled": "-d", "enabled": "-e"}


@dataclass
class Inventory:
    """Each list is None when the query failed, so 'none installed' and 'unknown' stay distinct."""

    system: list[str] | None = None
    user: list[str] | None = None
    disabled: list[str] | None = None
    enabled: list[str] | None = None


@dataclass
class ScanResult:
    device: DeviceInfo
    capabilities: DeviceCapabilities
    inventory: Inventory
    errors: list[str] = field(default_factory=list)


def parse_package_list(text: str) -> tuple[list[str], list[str]]:
    """Parse `pm list packages`. Returns (sorted valid names, rejected lines)."""
    names: set[str] = set()
    rejected: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        name = line.removeprefix("package:") if line.startswith("package:") else ""
        if is_valid_package(name):
            names.add(name)
        else:
            rejected.append(line)
    return sorted(names), rejected


def list_packages(adb: Adb, flag: str) -> tuple[list[str] | None, list[str]]:
    errors: list[str] = []
    res = adb.shell("pm", "list", "packages", "--user", "0", flag)
    if not res.ok:
        errors.append(f"pm list packages --user 0 {flag}: {res.failure()}")
        res = adb.shell("pm", "list", "packages", flag)  # very old pm has no --user
        if not res.ok:
            errors.append(f"pm list packages {flag}: {res.failure()}")
            return None, errors
    names, rejected = parse_package_list(res.stdout)
    if not names and res.stdout.strip():
        errors.append(f"pm list packages {flag}: no parseable package lines")
        return None, errors
    errors += [f"pm list packages {flag}: ignored line {ln!r}" for ln in rejected]
    return names, errors


def run_scan(adb: Adb) -> ScanResult:
    info, errors = read_device_info(adb)
    caps, cap_errors = probe_capabilities(adb)
    errors += cap_errors

    inventory = Inventory()
    for label, flag in PACKAGE_FILTERS.items():
        names, errs = list_packages(adb, flag)
        setattr(inventory, label, names)
        errors += errs

    return ScanResult(info, caps, inventory, errors)
