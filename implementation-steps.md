# Project Reboot: Implementation Steps

Hours assume solo, part-time work with an AI coding assistant. Do not start a phase until the previous
phase's exit gate passes.

| Phase | Goal | Hours | Exit gate | Release |
| --- | --- | --- | --- | --- |
| P0 Decide | Positioning, brands, test phones | 8–10 | Written answer to "why not Universal Android Debloater?" and two phones in hand | none |
| P1 Scan | Read-only device report | 25–35 | Report is valid JSON on both phones, including with fields missing | v0.1 |
| P2 Database | Schema and reviewed seed data for two brands | 20–30 | Validator passes; every entry has evidence; unknown stays unknown | none |
| P3 Disable and restore | Plan, guards, apply, backup, restore | 35–50 | Apply then restore works on both phones, including after a reboot | v0.2 beta |
| P4 Guided flow and release | `PROMPT.md`, setup docs, CI | 15–25 | A fresh machine follows the docs to a successful scan and restore | v0.3 |
| **Total to v0.3** | | **103–150** | | |

Later, not scheduled: on-device Android app (50–80 h), more brands (ongoing), per-brand settings guides.

---

## P0 Decide (weekend 1)

- [ ] 1. Install Universal Android Debloater on one phone and note what it lacks for your audience.
- [ ] 2. Read CleanYourTV's `PROMPT.md` and `tools/disable.sh`; list the guards worth copying.
- [ ] 3. Pick two OEM families and two test phones: one Android 11+ and one older, low-RAM phone.
- [ ] 4. Write a one-page positioning note. Create the repo with a license and the `CLAUDE.md`.

**Gate:** written answer to "why not Universal Android Debloater?" and two phones in hand.

## P1 Scan (v0.1)

- [ ] 1. Scaffold `pyproject.toml`, the `reboot/` package, ruff, pytest, and CI on push.
- [ ] 2. Write `adb.py`: find the binary, run with a timeout and `shell=False`, return code, stdout and
  stderr. Add a fake runner for tests.
- [ ] 3. `doctor`: adb present, its version, server state.
- [ ] 4. `devices`: parse `adb devices -l`; classify `device`, `unauthorized`, `offline`, none; require
  `--serial` when several are attached.
- [ ] 5. Device identity from `getprop`: `ro.product.manufacturer`, `ro.product.model`,
  `ro.product.device`, `ro.build.version.release`, `ro.build.version.sdk`. RAM from `/proc/meminfo`,
  storage from `df /data`.
- [ ] 6. Package inventory with `pm list packages --user 0`, using `-s` (system), `-3` (user),
  `-d` (disabled), `-e` (enabled).
- [ ] 7. Build `DeviceCapabilities` from probes (does `cmd package` exist, does `pm help` list
  `disable-user`), not from the Android version.
- [ ] 8. Record real `adb` output from both phones into `tests/fixtures/` and unit-test every parser.
- [ ] 9. Write the JSON report with a schema version and explicit "unsupported" fields, plus a short
  terminal summary. Tag v0.1.

**Gate:** report is valid JSON on both phones, including with fields missing.

## P2 Database

- [ ] 1. Write `data/schema.json` and `tools/validate_db.py` (regex, duplicates, required evidence).
- [ ] 2. Seed `common.yaml` with protected packages: framework, SystemUI, telephony, Play Services,
  Play Store, Settings, WebView.
- [ ] 3. For each chosen brand, take your scan and classify each system package as `keep`, `optional`,
  `advanced`, or leave it unknown. Include only what you can explain, with a source and date.
- [ ] 4. Add `reboot analyze`: join scan and database, show counts per tier, list unknowns separately.
- [ ] 5. Add an issue template for device notes and package research.

**Gate:** validator passes; every entry has evidence; unknown stays unknown.

Entry shape (suggested):

```yaml
- id: com.example.promo
  oem: example
  label: Promo feed
  tier: optional          # keep | optional | advanced
  why: Shows sponsored cards on the home screen
  consequences: Home screen feed page disappears
  sources: ["https://example.com/note"]
  confidence: medium      # high | medium | low
  reviewed: 2026-11-02
  protected: false
  android_min: 10
```

## P3 Disable and restore (v0.2 beta)

- [ ] 1. `backup.py`: write the record (device identity, package, prior state, command, timestamps) and
  flush it to disk before any change; stop if the write fails.
- [ ] 2. `guards.py`: implement each guard below, each with a fixture test.
- [ ] 3. `plan`: from the owner's picks, write a plan file with the exact commands. Nothing runs.
- [ ] 4. `apply`: batches of five; run `pm disable-user --user 0 <pkg>`; re-list `pm list packages -d`
  to verify; stop on disconnect or an ambiguous result.
- [ ] 5. `restore`: `pm enable --user 0 <pkg>` only for packages the record shows Reboot changed; verify
  again.
- [ ] 6. On both phones: apply, restore, reboot, check. Also unplug mid-apply and fill the backup disk.
- [ ] 7. Tag v0.2 beta with a table of tested models and Android versions.

**Gate:** apply then restore works on both phones, including after a reboot.

### Safety guards

A package is skipped, with the reason shown, unless it passes every guard. Confirm each command on real
phones before relying on it.

| Guard | How to check | If it fails |
| --- | --- | --- |
| Home launcher | `cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME` | Skip the current home app unless another app can answer HOME |
| Keyboard | `settings get secure default_input_method` | Skip the active keyboard's package |
| Dialer and SMS | `settings get secure sms_default_application`; `cmd role get-role-holders android.app.role.DIALER` (Android 10+) | Skip the holders |
| Accessibility | `settings get secure enabled_accessibility_services` | Skip listed packages |
| Wi-Fi owner | `dumpsys wifi`, owner of saved networks | Skip the owner (CleanYourTV hit this on TVs; check phones) |
| Protected list | `protected: true` in the database | Skip |
| Unknown | Not in the database | Skip; never offered |
| Android below 7 | `cmd` is missing | Use `dumpsys activity` (`mHomeProcess`) as fallback, or scan only |

Every package name is also checked against `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$` before it
enters any shell command.

## P4 Guided flow and release (v0.3)

- [ ] 1. `PROMPT.md`: run `doctor`, `scan`, `plan`; ask per package; never run `apply` without a plan
  the owner approved.
- [ ] 2. Setup docs for Windows, macOS and Linux, developer options, any extra per-brand toggle (for
  example Xiaomi's security setting), and how to restore.
- [ ] 3. Per-brand guides for turning off ad personalization and promo content in Settings (no ADB).
- [ ] 4. CI runs tests and database validation; release notes state tested devices and known limits.
  Tag v0.3.

**Gate:** a fresh machine follows the docs to a successful scan and restore.

---

## Test checklist (before any release that can disable packages)

- [ ] No device, unauthorized, offline, multiple devices, missing adb
- [ ] Unsupported command or missing field
- [ ] Package already disabled; package not installed
- [ ] Protected or unknown package selected
- [ ] Backup write failure
- [ ] Partial failure mid-apply (unplug the phone)
- [ ] Restore after success; restore after partial failure
- [ ] Restore after a phone reboot
- [ ] Release notes list exactly which models and Android versions were tested

## Open decisions

- [ ] Which two brands first?
- [ ] Which two phones do you have for testing?
- [ ] License: MIT, Apache-2.0 or GPL (check licenses of any reused lists)
- [ ] Android app after v0.3, or in place of the CLI?
- [ ] Verify the Universal Android Debloater details (described from memory)
