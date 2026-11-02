"""Typer CLI. Read-only: doctor, devices, scan, analyze, plan. Changes the phone: apply, restore."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from reboot.adb import Adb, find_adb
from reboot.analyze import analyze_report
from reboot.apply import apply_plan
from reboot.backup import BackupReadError, read_backup, utcnow
from reboot.db import DatabaseError, Entry, load_database
from reboot.device import DeviceEntry, DeviceError, parse_devices, select_device
from reboot.names import InvalidPackageName
from reboot.plan import assess, build_plan
from reboot.report import build_report, write_report
from reboot.restore import restorable_packages, restore_backup
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


DbOpt = typer.Option(DEFAULT_DB, "--db", help="Package database directory.")


def _load_db(db_dir: Path):
    try:
        return load_database(db_dir)
    except DatabaseError as exc:
        err.print("[red]package database is invalid:[/red]")
        for problem in exc.problems:
            err.print(f"  {problem}")
        raise typer.Exit(2) from exc


def _read_picks(picks: list[str], pick_file: Path | None) -> list[str]:
    names = [p.strip() for p in picks]
    if pick_file is not None:
        try:
            text = pick_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            err.print(f"[red]could not read {pick_file}:[/red] {exc}")
            raise typer.Exit(2) from exc
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                names.append(line)
    return names


@app.command()
def plan(
    pick: list[str] = typer.Option([], "--pick", "-p", help="Package to consider (repeatable)."),
    pick_file: Path | None = typer.Option(
        None, "--pick-file", help="File with one package per line."
    ),
    allow_advanced: bool = typer.Option(
        False, "--allow-advanced", help="Also offer advanced tier."
    ),
    out: Path = typer.Option(Path("reboot-plan.json"), "--out", "-o", help="Plan file to write."),
    adb_path: str | None = AdbPathOpt,
    serial: str | None = SerialOpt,
    db_dir: Path = DbOpt,
) -> None:
    """Dry run: show exactly what would be disabled and why the rest is skipped. Changes nothing."""
    names = _read_picks(pick, pick_file)
    if not names:
        err.print("[red]nothing to plan:[/red] give packages with --pick or --pick-file.")
        raise typer.Exit(2)
    db = _load_db(db_dir)
    adb = _require_adb(adb_path)
    entry = _choose(adb, serial)
    try:
        a = assess(adb.with_serial(entry.serial), db, names, allow_advanced)
    except InvalidPackageName as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    if a.blocked:
        err.print(f"[red]cannot plan:[/red] {a.blocked}. Nothing was changed.")
        raise typer.Exit(2)

    for pkg, reason in a.skipped:
        console.print(f"[yellow]skip[/yellow] {pkg}: {reason}")
    if not a.eligible:
        console.print("Nothing eligible to disable. No plan written.")
        raise typer.Exit(1)
    plan_doc = build_plan(a, allow_advanced, utcnow())
    for act in plan_doc["actions"]:
        console.print(f"[green]plan[/green] {act['package']} ({act['tier']}): {act['label']}")
        console.print(f"  {act['command']}\n  undo: {act['restore_command']}", markup=False)
    out.write_text(json.dumps(plan_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    console.print(f"Dry run only. Plan written to {out}. Run `reboot apply {out}` to proceed.")


@app.command()
def apply(
    plan_file: Path = typer.Argument(..., exists=True, dir_okay=False, help="A plan file."),
    backup_dir: Path = typer.Option(Path("reboot-backups"), "--backup-dir"),
    adb_path: str | None = AdbPathOpt,
    db_dir: Path = DbOpt,
) -> None:
    """Disable the planned packages after per-package confirmation. Backs up first."""
    try:
        plan_doc = json.loads(plan_file.read_text(encoding="utf-8-sig"))
        serial = plan_doc["device"]["serial"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        err.print(f"[red]could not read plan:[/red] {exc}")
        raise typer.Exit(2) from exc
    db = _load_db(db_dir)
    adb = _require_adb(adb_path)
    entry = _choose(adb, serial)

    def confirm(e: Entry) -> bool:
        console.print(f"\n[bold]{e.id}[/bold] ({e.tier}, confidence {e.confidence}): {e.label}")
        console.print(f"  why: {e.why}\n  if disabled: {e.consequences}")
        return typer.confirm("Disable this package?", default=False)

    result = apply_plan(adb.with_serial(entry.serial), plan_doc, db, backup_dir, confirm)
    for pkg, reason in result.skipped:
        console.print(f"[yellow]skipped[/yellow] {pkg}: {reason}")
    for pkg, status in result.outcomes.items():
        console.print(f"{pkg}: {status}")
    if result.backup:
        console.print(f"backup: {result.backup}")
        console.print(f"undo with: reboot restore {result.backup}")
    if result.stopped:
        err.print(f"[red]stopped:[/red] {result.stopped}")
        raise typer.Exit(1)
    console.print("[green]All confirmed packages were disabled and verified.[/green]")


@app.command()
def restore(
    backup_file: Path = typer.Argument(..., exists=True, dir_okay=False, help="A backup record."),
    adb_path: str | None = AdbPathOpt,
) -> None:
    """Re-enable only the packages this backup shows Reboot may have disabled."""
    try:
        record = read_backup(backup_file)
    except BackupReadError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    targets = restorable_packages(record)
    if not targets:
        console.print("Nothing to restore in this backup.")
        return
    adb = _require_adb(adb_path)
    entry = _choose(adb, record["device"]["serial"])
    console.print("Will re-enable:\n  " + "\n  ".join(targets))
    if not typer.confirm("Restore these packages?", default=True):
        raise typer.Exit(1)
    result = restore_backup(adb.with_serial(entry.serial), record, backup_file)
    for pkg, status in result.outcomes.items():
        console.print(f"{pkg}: {status}")
    for w in result.warnings:
        err.print(f"[yellow]warning:[/yellow] {w}")
    if result.stopped:
        err.print(f"[red]stopped:[/red] {result.stopped}")
        raise typer.Exit(1)
    console.print("[green]All packages restored and verified.[/green]")


if __name__ == "__main__":
    app()
