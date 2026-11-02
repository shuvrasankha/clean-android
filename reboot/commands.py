"""The only two device-changing commands Reboot may issue. Built from validated names, never from
strings read out of a plan or backup file."""

from __future__ import annotations

from reboot.names import require_valid_packages


def disable_args(package: str) -> list[str]:
    (pkg,) = require_valid_packages([package])
    return ["pm", "disable-user", "--user", "0", pkg]


def enable_args(package: str) -> list[str]:
    (pkg,) = require_valid_packages([package])
    return ["pm", "enable", "--user", "0", pkg]
