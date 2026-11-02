"""Validate data/packages: schema, duplicates, package names, evidence. Exit 1 on any problem."""

from __future__ import annotations

import sys
from pathlib import Path

from reboot.db import DatabaseError, load_database

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "packages"


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else DEFAULT_DIR
    try:
        db = load_database(directory)
    except DatabaseError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        print(f"{len(exc.problems)} problem(s) in {directory}", file=sys.stderr)
        return 1
    print(f"ok: {len(db.entries)} entries in {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
