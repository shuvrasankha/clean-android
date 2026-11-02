# Project Reboot

Open-source tool that helps owners of budget Android phones remove preinstalled ads and bloat safely
and reversibly, using ADB. Nothing is ever uninstalled.

**Status: P1 (read-only scan).** The CLI can check adb, list devices and write a read-only scan report.
It cannot change a phone yet. See `CLAUDE.md` for principles and `implementation-steps.md` for the plan.

```bash
pip install -e ".[dev]"
reboot doctor
reboot devices
reboot scan --out reboot-scan.json
```

Serial numbers are redacted from reports unless you pass `--include-serial`.
