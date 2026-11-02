# Project Reboot

Open-source tool that helps owners of budget Android phones remove preinstalled ads and bloat safely
and reversibly, using ADB. Nothing is ever uninstalled.

**Status: pre-release.** Scan, analyze, plan, apply and restore are implemented and tested against a
fake phone only. They have not been verified on a real phone, so do not rely on them yet. See
[docs/tested-devices.md](docs/tested-devices.md) for what is actually tested.

- Setup guide: [docs/setup.md](docs/setup.md)
- Let an AI assistant guide you: [PROMPT.md](PROMPT.md)
- Settings-only ad guides (no computer): [docs/ad-settings](docs/ad-settings/README.md)
- How changes are kept safe: [docs/safety.md](docs/safety.md)
- Principles: `CLAUDE.md`; plan: `implementation-steps.md`

```bash
pip install -e ".[dev]"
reboot doctor
reboot devices
reboot scan --out reboot-scan.json
```

`reboot analyze reboot-scan.json` joins a scan with `data/packages/` (offline) and lists protected,
known and unknown packages. Only `common.yaml` (protected packages) is populated: no brand entries are
added until they are researched and tested on a physical phone. Validate with
`python tools/validate_db.py`.

Serial numbers are redacted from reports unless you pass `--include-serial`.
