"""Typer CLI. P1 commands are read-only: doctor, devices, scan."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from reboot.adb import Adb, find_adb
from reboot.analyze import analyze_report
from reboot.db import DatabaseError, load_database
from reboot.device import DeviceEntry, DeviceError, parse_devices, select_device
from reboot.report import build_report, write_report
from reboot.scan import run_scan

app = typer.Typer(
    help="Safely and reversibly disable preinstalled Android bloat.", no_args_is_help=True
)
console = Console()
err = Console(stderr=True)

AdbPathOpt = typer.Option(None, "--adb", help="Path to the adb binary (default: auto-detect).")
SerialOpt = typer.Option(
    None, "--serial", "-s", help="Device serial; required if several are attached."
)


def _require_adb(adb_path: str | None) -> Adb:
    binary = adb_path or find_adb()
    if not binary:
        err.print("[red]adb not found.[/red] Install Android platform-tools or set REBOOT_ADB.")
        raise typer.Exit(2)
    return Adb(binary)


def _attached(adb: Adb) -> list[DeviceEntry]:
    res = adb.run("devices", "-l")
    if not res.ok:
        err.print(f"[red]adb devices failed:[/red] {res.failure()}")
        raise typer.Exit(2)
    return parse_devices(res.stdout)


def _choose(adb: Adb, serial: str | None) -> DeviceEntry:
    try:
        return select_device(_attached(adb), serial)
    except DeviceError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc


@app.command()
def doctor(adb_path: str | None = AdbPathOpt) -> None:
    """Check that adb is present and report its version and attached devices."""
    binary = adb_path or find_adb()
    if not binary:
        err.print("[red]adb: not found.[/red] Install Android platform-tools or set REBOOT_ADB.")
        raise typer.Exit(2)
    adb = Adb(binary)
    ver = adb.run("version")
    match = re.search(r"version\s+(\S+)", ver.stdout)
    if not ver.ok or not match:
        err.print(f"[red]adb at {binary} did not report a version:[/red] {ver.failure()}")
        raise typer.Exit(2)
    console.print(f"adb: {binary} (version {match.group(1)})")
    entries = _attached(adb)
    console.print(f"devices attached: {len(entries)}")
    for e in entries:
        console.print(f"  {e.state}: {e.details.get('model', 'unknown model')}")


@app.command()
def devices(adb_path: str | None = AdbPathOpt) -> None:
    """List attached devices and their state."""
    adb = _require_adb(adb_path)
    entries = _attached(adb)
    if not entries:
        console.print("No devices attached.")
        raise typer.Exit(1)
    table = Table("serial", "state", "model")
    for e in entries:
        table.add_row(e.serial, e.state, e.details.get("model", "unknown"))
    console.print(table)


@app.command()
def scan(
    adb_path: str | None = AdbPathOpt,
    serial: str | None = SerialOpt,
    out: Path = typer.Option(Path("reboot-scan.json"), "--out", "-o", help="Report file to write."),
    include_serial: bool = typer.Option(
        False, "--include-serial", help="Keep the serial in the report."
    ),
) -> None:
    """Read-only inventory of one device. Changes nothing on the phone."""
    adb = _require_adb(adb_path)
    entry = _choose(adb, serial)
    result = run_scan(adb.with_serial(entry.serial))
    report = build_report(result, entry.serial, include_serial)
    try:
        write_report(report, out)
    except OSError as exc:
        err.print(f"[red]could not write report {out}:[/red] {exc}")
        raise typer.Exit(2) from exc

    dev = report["device"]
    console.print(f"{dev['manufacturer']} {dev['model']}, Android {dev['android_release']}")
    counts = report["package_counts"]
    console.print("packages: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if result.errors:
        console.print(
            f"[yellow]{len(result.errors)} field(s) unsupported or failed; see report.[/yellow]"
        )
    console.print(f"report written to {out}")


DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "packages"


@app.command()
def analyze(
    report_file: Path = typer.Argument(..., exists=True, dir_okay=False, help="A scan report."),
    db_dir: Path = typer.Option(DEFAULT_DB, "--db", help="Package database directory."),
) -> None:
    """Join a scan report with the package database. Offline; never touches a phone."""
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
        db = load_database(db_dir)
    except (OSError, ValueError) as exc:
        err.print(f"[red]could not read report:[/red] {exc}")
        raise typer.Exit(2) from exc
    except DatabaseError as exc:
        err.print("[red]package database is invalid:[/red]")
        for problem in exc.problems:
            err.print(f"  {problem}")
        raise typer.Exit(2) from exc

    result = analyze_report(report, db)
    dev = report.get("device", {})
    console.print(
        f"{dev.get('manufacturer')} {dev.get('model')}, Android {dev.get('android_release')}"
    )
    if result.android_major is None:
        console.print(
            "[yellow]Android version unknown: version-limited entries count as unknown.[/yellow]"
        )
    console.print(
        f"protected {len(result.protected)}, "
        + ", ".join(f"{t} {len(rows)}" for t, rows in result.by_tier.items())
        + f", unknown {len(result.unknown)} (system); user apps {result.user_app_count}"
    )
    for tier, rows in result.by_tier.items():
        if not rows:
            continue
        table = Table("package", "state", "confidence", "label", title=tier)
        for r in rows:
            table.add_row(r.entry.id, r.state, r.entry.confidence, r.entry.label)
        console.print(table)
    if result.unknown:
        console.print("[bold]Unknown (never offered for disabling):[/bold]")
        for name in result.unknown:
            console.print(f"  {name}")


if __name__ == "__main__":
    app()
