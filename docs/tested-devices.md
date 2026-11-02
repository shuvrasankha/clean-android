# Tested devices

Release notes may only claim what is in this table. A row needs a real phone and a successful
apply, reboot and restore (see `implementation-steps.md`, test checklist).

| Phone model | Android | Reboot version | Scan | Apply | Restore | After reboot | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| *none yet* | | | | | | | All behavior so far is tested against recorded or hand-written fixtures only. |

## Known limits

- The guard commands (home, keyboard, dialer, SMS, accessibility, Wi-Fi owner) have not been
  confirmed on a real phone.
- The package database contains only protected packages. No brand has been researched, so `plan`
  will skip every pick as unknown until entries exist.
- Android below 7 uses `dumpsys`/`pm` fallbacks that are untested.

## Release notes template

```
## vX.Y.Z

Tested on: <model, Android version> (list every phone; nothing else is claimed)
Changes: ...
Known limits: ...
```
