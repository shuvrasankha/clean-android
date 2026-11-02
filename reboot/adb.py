"""Thin wrapper around the official `adb` binary. No shell strings, never shell=True."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class AdbResult:
    args: tuple[str, ...]
    returncode: int | None  # None when the process never ran or timed out
    stdout: str = ""
    stderr: str = ""
    error: str | None = None  # launch failure or timeout, never a device-side message

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.error is None

    @property
    def text(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()

    def failure(self) -> str:
        """One-line reason, for error records."""
        if self.error:
            return self.error
        detail = (self.stderr or self.stdout).strip().splitlines()
        return f"exit {self.returncode}: {detail[0]}" if detail else f"exit {self.returncode}"


class Runner(Protocol):
    def __call__(self, argv: Sequence[str], timeout: float) -> AdbResult: ...


def clean_output(raw: bytes | str) -> str:
    """Decode leniently, drop a BOM, and normalise Windows line endings."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.lstrip("﻿")
    return text.replace("\r\r\n", "\n").replace("\r\n", "\n")


def subprocess_runner(argv: Sequence[str], timeout: float) -> AdbResult:
    args = tuple(argv)
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, shell=False
            list(args), shell=False, capture_output=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return AdbResult(args, None, error=f"executable not found: {args[0]}")
    except subprocess.TimeoutExpired:
        return AdbResult(args, None, error=f"timed out after {timeout:g}s")
    except OSError as exc:
        return AdbResult(args, None, error=f"could not run adb: {exc}")
    return AdbResult(args, proc.returncode, clean_output(proc.stdout), clean_output(proc.stderr))


def find_adb() -> str | None:
    """Locate adb: $REBOOT_ADB, then PATH, then an Android SDK platform-tools folder."""
    override = os.environ.get("REBOOT_ADB")
    if override:
        return override if Path(override).is_file() else None
    found = shutil.which("adb")
    if found:
        return found
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(var)
        if not root:
            continue
        for name in ("adb", "adb.exe"):
            candidate = Path(root) / "platform-tools" / name
            if candidate.is_file():
                return str(candidate)
    return None


class Adb:
    """Runs adb commands. Inject `runner` in tests to feed recorded output."""

    def __init__(
        self,
        binary: str = "adb",
        serial: str | None = None,
        runner: Runner | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.binary = binary
        self.serial = serial
        self.timeout = timeout
        self._runner: Runner = runner or subprocess_runner

    def with_serial(self, serial: str) -> Adb:
        return Adb(self.binary, serial, self._runner, self.timeout)

    def run(self, *args: str) -> AdbResult:
        argv = [self.binary]
        if self.serial:
            argv += ["-s", self.serial]
        argv += list(args)
        return self._runner(argv, self.timeout)

    def shell(self, *args: str) -> AdbResult:
        # Exit codes from `adb shell` are unreliable on old devices; callers verify state instead.
        return self.run("shell", *args)
