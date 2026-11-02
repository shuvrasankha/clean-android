"""Device discovery, identity and observed capabilities. Missing fields are never guessed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reboot.adb import Adb

UNSUPPORTED = "unsupported"


# ---- discovery -------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceEntry:
    serial: str
    state: str  # device | unauthorized | offline | no permissions | ...
    details: dict[str, str] = field(default_factory=dict)


class DeviceError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def parse_devices(text: str) -> list[DeviceEntry]:
    """Parse `adb devices -l`."""
    entries: list[DeviceEntry] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("List of devices", "* daemon", "adb server")):
            continue
        if "no permissions" in line:
            serial = line.split()[0]
            entries.append(DeviceEntry(serial, "no permissions"))
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        details = dict(t.split(":", 1) for t in tokens[2:] if ":" in t)
        entries.append(DeviceEntry(tokens[0], tokens[1], details))
    return entries


def select_device(entries: list[DeviceEntry], serial: str | None = None) -> DeviceEntry:
    """Pick the one device to work on, or raise DeviceError saying exactly why not."""
    if serial is not None:
        match = [e for e in entries if e.serial == serial]
        if not match:
            raise DeviceError("serial_not_found", f"no attached device with serial {serial!r}")
        chosen = match[0]
    elif not entries:
        raise DeviceError("no_device", "no device attached; enable USB debugging and connect one")
    elif len(entries) > 1:
        raise DeviceError("multiple_devices", "several devices attached; choose one with --serial")
    else:
        chosen = entries[0]

    if chosen.state == "unauthorized":
        raise DeviceError("unauthorized", "device is unauthorized; accept the USB debugging prompt")
    if chosen.state == "offline":
        raise DeviceError("offline", "device is offline; reconnect the cable or restart adb")
    if chosen.state != "device":
        raise DeviceError("bad_state", f"device is in state {chosen.state!r}, expected 'device'")
    return chosen


# ---- identity --------------------------------------------------------------------------------

PROPS = {
    "manufacturer": "ro.product.manufacturer",
    "model": "ro.product.model",
    "device": "ro.product.device",
    "android_release": "ro.build.version.release",
    "sdk": "ro.build.version.sdk",
}


@dataclass
class DeviceInfo:
    manufacturer: str = UNSUPPORTED
    model: str = UNSUPPORTED
    device: str = UNSUPPORTED
    android_release: str = UNSUPPORTED
    sdk: int | str = UNSUPPORTED
    ram_total_kb: int | str = UNSUPPORTED
    storage_total_kb: int | str = UNSUPPORTED
    storage_available_kb: int | str = UNSUPPORTED


_MEMTOTAL_RE = re.compile(r"^MemTotal:\s+(\d+)\s*kB", re.MULTILINE)


def parse_meminfo(text: str) -> int | None:
    m = _MEMTOTAL_RE.search(text)
    return int(m.group(1)) if m else None


def parse_df(text: str) -> tuple[int, int] | None:
    """Parse `df -k /data` into (total_kb, available_kb). Tolerates a wrapped filesystem name."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    tokens = " ".join(lines[1:]).split()
    if len(tokens) < 6 or not tokens[-1].startswith("/"):
        return None
    try:
        return int(tokens[-5]), int(tokens[-3])
    except ValueError:
        return None


def read_device_info(adb: Adb) -> tuple[DeviceInfo, list[str]]:
    info = DeviceInfo()
    errors: list[str] = []

    for attr, prop in PROPS.items():
        res = adb.shell("getprop", prop)
        value = res.stdout.strip()
        if not res.ok:
            errors.append(f"{prop}: {res.failure()}")
        elif not value:
            errors.append(f"{prop}: empty")
        elif attr == "sdk":
            info.sdk = int(value) if value.isdigit() else UNSUPPORTED
            if info.sdk == UNSUPPORTED:
                errors.append(f"{prop}: not a number: {value!r}")
        else:
            setattr(info, attr, value)

    res = adb.shell("cat", "/proc/meminfo")
    ram = parse_meminfo(res.stdout) if res.ok else None
    if ram is None:
        errors.append(f"/proc/meminfo: {res.failure() if not res.ok else 'no MemTotal line'}")
    else:
        info.ram_total_kb = ram

    res = adb.shell("df", "-k", "/data")
    df = parse_df(res.stdout) if res.ok else None
    if df is None:
        errors.append(f"df /data: {res.failure() if not res.ok else 'unparseable output'}")
    else:
        info.storage_total_kb, info.storage_available_kb = df

    return info, errors


# ---- capabilities ----------------------------------------------------------------------------


@dataclass
class DeviceCapabilities:
    """Observed by probing. None means the probe itself failed, so the answer is unknown."""

    cmd_package: bool | None = None
    pm_disable_user: bool | None = None


def probe_capabilities(adb: Adb) -> tuple[DeviceCapabilities, list[str]]:
    caps = DeviceCapabilities()
    errors: list[str] = []

    res = adb.shell("cmd", "package", "help")
    if res.ok and res.text:
        caps.cmd_package = True
    elif not res.error and "not found" in res.text:
        caps.cmd_package = False
    else:
        errors.append(f"probe cmd package: {res.failure()}")

    res = adb.shell("pm", "help")
    if "disable-user" in res.text:
        caps.pm_disable_user = True
    elif res.ok and res.text:
        caps.pm_disable_user = False
    else:
        errors.append(f"probe pm help: {res.failure()}")

    return caps, errors
