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


def make_adb(responses: dict[tuple[str, ...], str | AdbResult], serial: str | None = "ABC123"):
    runner = FakeRunner(responses)
    return Adb("adb", serial, runner), runner
