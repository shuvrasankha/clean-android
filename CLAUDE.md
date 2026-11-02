# CLAUDE.md — Project Reboot

Open-source tool that helps owners of budget Android phones remove preinstalled ads and bloat
safely and reversibly, using ADB and `pm disable-user`. Nothing is ever uninstalled.

Status: planning. This file describes the target layout; create directories as each phase starts.

## Principles (non-negotiable)

1. Read-only by default. Any command that changes the device needs an explicit user-approved plan.
2. Disable, never uninstall. Allowed change: `pm disable-user --user 0 <pkg>`. Restore: `pm enable --user 0 <pkg>`.
3. Never touch an unknown package. Unknown stays unknown; it is not "bloat".
4. Back up original state before every change; verify state after; report partial failure honestly.
5. No root, no flashing, no clearing app data, no `pm uninstall`, no `pm clear`.
6. Local only: no telemetry, no network calls, no accounts. Reports and backups stay on disk.
7. Evidence for every recommendation: source, confidence, last-reviewed date.

## Layout

```
reboot/                 Python package (engine)
  adb.py                subprocess wrapper around the official `adb` binary
  device.py             DeviceInfo + DeviceCapabilities (observed, not inferred from version)
  scan.py               read-only inventory
  db.py                 load and validate the package database
  plan.py               build a dry-run plan from scan + db
  guards.py             safety guards (home, keyboard, dialer, SMS, accessibility, etc.)
  apply.py              execute a plan in small batches, verify each
  backup.py             write/read backup records
  restore.py            re-enable only what Reboot changed
  report.py             JSON + readable report
  cli.py                Typer commands
data/packages/          one YAML file per OEM family, plus common.yaml
data/schema.json        JSON Schema for package entries
tests/                  unit/, fixtures/ (recorded adb output), device/ (manual, real phones)
docs/                   safety.md, architecture.md, device-notes/, brand settings guides
PROMPT.md               AI-guided flow: lets a coding assistant drive the CLI
```

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # unit tests, no phone needed
pytest tests/device -m device   # real-device tests, opt-in
ruff check . && ruff format --check .
python tools/validate_db.py     # schema + duplicate + regex check of data/packages
```

CLI (planned): `reboot doctor | devices | scan | plan | apply | restore | report`.
`plan` is a dry-run and prints exact commands. `apply` requires a plan file and per-package confirmation.

## Coding rules

- Python 3.10+. Type hints everywhere. Runtime dependencies: Typer and Rich only; Pydantic optional.
- Run adb via `subprocess.run([...], shell=False, timeout=...)`. Never build shell strings from data.
- Validate every package name against `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$` before it goes into
  any `adb shell` command. Refuse the whole list if any entry fails.
- Strip BOM and CRLF when reading contributor-supplied lists.
- Make `adb.py` injectable so tests use a fake runner fed from `tests/fixtures/`.
- Every field read from the device may be missing or fail: return an explicit "unsupported" value
  and record the error; never crash the scan and never guess.
- Do not rely on exit codes alone: after each change, re-list disabled packages and compare.
- Do not end the user's existing adb session. Only stop an adb server this tool started.
- Redact serial numbers from shareable reports unless the user opts in.

## Safety guards (see docs/safety.md)

Skip a package, and say why, when disabling it would remove the only:
home launcher, input method (keyboard), default dialer, default SMS app, active accessibility service,
or when it owns saved Wi-Fi networks, is a core framework/SystemUI/telephony/Play Services component,
or is listed `protected: true` in the database. Old Android (below 7) lacks `cmd`; use `dumpsys`/`pm` fallbacks.

## Package database

Entry fields: `id`, `oem`, `label`, `tier` (`keep` | `optional` | `advanced`), `why`, `consequences`,
`sources` (list), `confidence` (`high` | `medium` | `low`), `reviewed` (date), `android_min`/`android_max` if relevant.
Anything not in the database is `unknown` and is never offered for disabling.
Start with two OEM families; add a brand only after it is tested on a physical phone.

## Testing

- Unit tests must pass without a phone. Cover: no device, unauthorized, offline, multiple devices,
  missing adb, unsupported command, already-disabled package, package not installed, protected/unknown
  package, backup write failure, partial failure, restore after success, restore after partial failure.
- A successful restore on a real phone is a release blocker for any version that can disable packages.
- Record which phone models and Android versions were tested in the release notes. Do not claim more.

## Out of scope for v1

Launcher, root, firmware/bootloader changes, automatic or "one-click" debloating, battery or speed
claims, telemetry, and any on-device app (planned for a later phase).

## Working style

- Small commits. Update docs/safety.md in the same change as any safety-relevant behavior.
- When unsure whether a package is safe, leave it enabled and add it to the open-questions list.
