"""Fake adb runner fed from tests/fixtures/. Keys are the adb args after any `-s <serial>`."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from reboot.adb import Adb, AdbResult

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], str | AdbResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str], timeout: float) -> AdbResult:
        args = tuple(argv[1:])
        if args[:1] == ("-s",):
            args = args[2:]
        self.calls.append(args)
        resp = self.responses.get(args)
        if resp is None:
            return AdbResult(tuple(argv), 1, stderr=f"fake: no response for {args}")
        if isinstance(resp, str):
            return AdbResult(tuple(argv), 0, stdout=resp)
        return resp


def _pm(flag: str, fixture_name: str) -> tuple[tuple[str, ...], str]:
    return ("shell", "pm", "list", "packages", "--user", "0", flag), fixture(fixture_name)


def happy_phone() -> dict[tuple[str, ...], str | AdbResult]:
    props = {
        "ro.product.manufacturer": "Xiaomi",
        "ro.product.model": "Redmi 9A",
        "ro.product.device": "dandelion",
        "ro.build.version.release": "10",
        "ro.build.version.sdk": "29",
    }
    r: dict[tuple[str, ...], str | AdbResult] = {
        ("shell", "getprop", k): v + "\n" for k, v in props.items()
    }
    r[("shell", "cat", "/proc/meminfo")] = fixture("meminfo.txt")
    r[("shell", "df", "-k", "/data")] = fixture("df_data.txt")
    r[("shell", "cmd", "package", "help")] = "Package manager (package) commands:\n  help\n"
    r[("shell", "pm", "help")] = fixture("pm_help.txt")
    for flag, name in (
        ("-s", "pm_list_system.txt"),
        ("-3", "pm_list_user.txt"),
        ("-d", "pm_list_disabled.txt"),
        ("-e", "pm_list_enabled.txt"),
    ):
        key, val = _pm(flag, name)
        r[key] = val
    return r


class FakePhone:
    """Stateful fake phone: disabled packages persist, so a 'reboot' is just carrying on."""

    def __init__(
        self,
        system: list[str],
        disabled: set[str] | None = None,
        *,
        serial: str = "ABC123",
        sdk: int = 29,
        has_cmd: bool = True,
        home: str = "com.example.launcher",
        ime: str = "com.example.keyboard/.Ime",
        accessibility: str = "null",
        dialer: str = "com.example.dialer",
        sms: str = "com.example.dialer",
        wifi_creators: tuple[str, ...] = (),
    ) -> None:
        self.system = list(system)
        self.disabled = set(disabled or ())
        self.serial = serial
        self.sdk = sdk
        self.has_cmd = has_cmd
        self.home, self.ime, self.accessibility = home, ime, accessibility
        self.dialer, self.sms = dialer, sms
        self.wifi_creators = wifi_creators
        self.fail_disable: set[str] = set()
        self.ignore_disable: set[str] = set()
        self.fail_settings = False
        self.disconnect_after: int | None = None  # allow N disable commands, then drop off
        self.disconnected = False
        self.calls: list[tuple[str, ...]] = []
        self._disables = 0

    def changes(self) -> list[tuple[str, ...]]:
        return [
            c
            for c in self.calls
            if c[:2] in (("shell", "pm"),) and c[2] in ("disable-user", "enable")
        ]

    def __call__(self, argv: Sequence[str], timeout: float) -> AdbResult:
        full = tuple(argv)
        args = tuple(argv[1:])
        if args[:1] == ("-s",):
            args = args[2:]
        self.calls.append(args)

        def ok(out: str = "") -> AdbResult:
            return AdbResult(full, 0, stdout=out)

        def fail(msg: str, code: int = 1) -> AdbResult:
            return AdbResult(full, code, stderr=msg)

        if args == ("devices", "-l"):
            return ok(f"List of devices attached\n{self.serial}  device model:Redmi_9A\n")
        if self.disconnected:
            return fail(f"error: device '{self.serial}' not found")
        if args[:1] != ("shell",):
            return fail("fake: unsupported")
        cmd = args[1:]

        if cmd[0] == "getprop":
            props = {
                "ro.product.manufacturer": "Xiaomi",
                "ro.product.model": "Redmi 9A",
                "ro.product.device": "dandelion",
                "ro.build.version.release": "10",
                "ro.build.version.sdk": str(self.sdk),
            }
            return ok(props.get(cmd[1], "") + "\n")
        if cmd[:2] == ("cat", "/proc/meminfo"):
            return ok(fixture("meminfo.txt"))
        if cmd[:3] == ("df", "-k", "/data"):
            return ok(fixture("df_data.txt"))
        if cmd[:3] == ("cmd", "package", "help"):
            return ok("Package manager commands\n") if self.has_cmd else fail("cmd: not found", 127)
        if cmd[:2] == ("pm", "help"):
            return ok(fixture("pm_help.txt"))
        if cmd[:3] == ("pm", "list", "packages"):
            flag = cmd[-1]
            allp = set(self.system)
            sel = {
                "-s": allp,
                "-3": set(),
                "-d": allp & self.disabled,
                "-e": allp - self.disabled,
            }[flag]
            return ok("".join(f"package:{p}\n" for p in sorted(sel)))
        if cmd[:3] == ("pm", "disable-user", "--user"):
            pkg = cmd[4]
            if self.disconnect_after is not None and self._disables >= self.disconnect_after:
                self.disconnected = True
                return fail(f"error: device '{self.serial}' not found")
            self._disables += 1
            if pkg in self.fail_disable:
                return fail("Exception: Unknown package")
            if pkg not in self.ignore_disable:
                self.disabled.add(pkg)
            return ok(f"Package {pkg} new state: disabled-user\n")
        if cmd[:3] == ("pm", "enable", "--user"):
            self.disabled.discard(cmd[4])
            return ok(f"Package {cmd[4]} new state: enabled\n")
        if cmd[:3] == ("settings", "get", "secure"):
            if self.fail_settings:
                return fail("Error: settings unavailable")
            values = {
                "default_input_method": self.ime,
                "enabled_accessibility_services": self.accessibility,
                "sms_default_application": self.sms,
                "dialer_default_application": self.dialer,
            }
            return ok(values.get(cmd[3], "null") + "\n")
        if cmd[:3] == ("cmd", "package", "resolve-activity"):
            if "android.intent.category.HOME" in cmd:
                return ok(f"priority=0 isDefault=true\n{self.home}/.Launcher\n")
            if "android.intent.action.DIAL" in cmd:
                return ok(f"priority=0\n{self.dialer}/.Dialer\n")
            return ok(f"priority=0\n{self.sms}/.Compose\n")
        if cmd[:3] == ("cmd", "role", "get-role-holders"):
            holder = self.dialer if cmd[3].endswith("DIALER") else self.sms
            return ok(holder + "\n")
        if cmd[:2] == ("dumpsys", "wifi"):
            return ok(
                "".join(f"  creatorName={c}\n" for c in self.wifi_creators) or "Wi-Fi is enabled\n"
            )
        if cmd[:2] == ("dumpsys", "activity"):
            return ok(f"mHomeProcess=ProcessRecord{{abc 123:{self.home}/u0a1}}\n")
        return fail(f"fake: no handler for {cmd}")


def make_adb(responses: dict[tuple[str, ...], str | AdbResult], serial: str | None = "ABC123"):
    runner = FakeRunner(responses)
    return Adb("adb", serial, runner), runner
