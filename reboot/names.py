"""Package-name validation. Every name is checked before it goes into any `adb shell` command."""

from __future__ import annotations

import re
from collections.abc import Iterable

PACKAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


class InvalidPackageName(ValueError):
    pass


def is_valid_package(name: str) -> bool:
    return PACKAGE_RE.fullmatch(name) is not None


def require_valid_packages(names: Iterable[str]) -> list[str]:
    """Return the names unchanged, or refuse the whole list if any entry is invalid."""
    items = list(names)
    bad = [n for n in items if not is_valid_package(n)]
    if bad:
        raise InvalidPackageName(f"refusing list; invalid package names: {bad!r}")
    return items
