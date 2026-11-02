"""Safety guards: packages that must not be disabled because the phone currently depends on them.

Fail closed: if a guard cannot be determined, it is reported as incomplete and no plan is made.
Commands here are unverified on real phones until the P3 device tests are done (see docs/safety.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reboot.adb import Adb
from reboot.device import DeviceCapabilities
from reboot.names import is_valid_package

ROLE_PREFIX = "android.app.role."
_HOME_PROC_RE = re.compile(r"mHomeProcess=ProcessRecord\{\S+ \d+:([A-Za-z0-9_.]+)/")
_WIFI_CREATOR_RE = re.compile(r"[cC]reatorName=([A-Za-z0-9_.]+)")


@dataclass
class GuardResult:
    protected: dict[str, list[str]] = field(default_factory=dict)
    incomplete: list[str] = field(default_factory=list)

    def add(self, package: str | None, reason: str) -> None:
        if package and is_valid_package(package):
            self.protected.setdefault(package, []).append(reason)


# ---- parsers (pure) --------------------------------------------------------------------------


def parse_components(value: str) -> list[str]:
    """`pkg/.Cls:pkg2/pkg2.Cls` or `pkg` or `null` -> package names."""
    out: list[str] = []
    for part in value.strip().split(":"):
        pkg = part.split("/", 1)[0].strip()
        if is_valid_package(pkg):
            out.append(pkg)
    return out


def parse_resolve(text: str) -> str | None:
    """Package from `cmd package resolve-activity --brief`. The chooser ('android/...') is None."""
    for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
        if "/" in line and " " not in line:
            pkg = line.split("/", 1)[0]
            return pkg if is_valid_package(pkg) else None
    return None


def parse_home_process(text: str) -> str | None:
    m = _HOME_PROC_RE.search(text)
    return m.group(1) if m and is_valid_package(m.group(1)) else None


def parse_role_holders(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", text.strip()) if is_valid_package(t)]


def parse_wifi_creators(text: str) -> set[str]:
    return {m for m in _WIFI_CREATOR_RE.findall(text) if is_valid_package(m)}


# ---- device queries --------------------------------------------------------------------------


def _setting(adb: Adb, key: str) -> str | None:
    """Value of a secure setting; '' when unset; None when the query failed."""
    res = adb.shell("settings", "get", "secure", key)
    if not res.ok:
        return None
    value = res.stdout.strip()
    return "" if value == "null" else value


def evaluate_guards(adb: Adb, caps: DeviceCapabilities, sdk: int | None) -> GuardResult:
    g = GuardResult()

    # Home launcher
    home = None
    if caps.cmd_package:
        res = adb.shell(
            "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
        )  # fmt: skip
        home = parse_resolve(res.stdout) if res.ok else None
    if home is None:
        res = adb.shell("dumpsys", "activity", "activities")
        home = parse_home_process(res.stdout) if res.ok else None
    if home is None:
        g.incomplete.append("home launcher")
    else:
        g.add(home, "current home launcher")

    # Keyboard
    ime = _setting(adb, "default_input_method")
    if ime is None:
        g.incomplete.append("keyboard")
    else:
        for pkg in parse_components(ime):
            g.add(pkg, "active keyboard")

    # Accessibility
    acc = _setting(adb, "enabled_accessibility_services")
    if acc is None:
        g.incomplete.append("accessibility services")
    else:
        for pkg in parse_components(acc):
            g.add(pkg, "active accessibility service")

    # Dialer and SMS: roles on Android 10+, settings keys before that
    use_roles = bool(caps.cmd_package) and (sdk is None or sdk >= 29)
    if use_roles:
        for role, label in (("DIALER", "default dialer"), ("SMS", "default SMS app")):
            res = adb.shell("cmd", "role", "get-role-holders", ROLE_PREFIX + role)
            if not res.ok:
                g.incomplete.append(label)
                continue
            for pkg in parse_role_holders(res.stdout):
                g.add(pkg, label)
    else:
        for key, label in (
            ("sms_default_application", "default SMS app"),
            ("dialer_default_application", "default dialer"),
        ):
            val = _setting(adb, key)
            if val is None:
                g.incomplete.append(label)
            else:
                for pkg in parse_components(val):
                    g.add(pkg, label)

    # Extra best-effort protection: whoever answers DIAL and SMS intents right now
    if caps.cmd_package:
        for label, extra in (
            ("answers dial intents", ["-a", "android.intent.action.DIAL"]),
            ("answers SMS intents", ["-a", "android.intent.action.SENDTO", "-d", "sms:"]),
        ):
            res = adb.shell("cmd", "package", "resolve-activity", "--brief", *extra)
            if res.ok:
                g.add(parse_resolve(res.stdout), label)

    # Saved Wi-Fi networks' owners
    res = adb.shell("dumpsys", "wifi")
    if not res.ok:
        g.incomplete.append("wifi network owners")
    else:
        for pkg in parse_wifi_creators(res.stdout):
            g.add(pkg, "owns a saved Wi-Fi network")

    return g
