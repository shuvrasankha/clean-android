# Setup

You need Python 3.10+, Android platform-tools (`adb`), a USB cable and the phone.
Nothing here uses root, and no data leaves your computer.

## 1. Install Reboot

```bash
git clone <this repository>
cd clean-android
python -m venv .venv
```

Activate the environment, then install:

| OS | Activate |
| --- | --- |
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |
| macOS / Linux | `source .venv/bin/activate` |

```bash
pip install -e .
```

## 2. Install adb

| OS | Install |
| --- | --- |
| Windows | Download "SDK Platform-Tools for Windows" from developer.android.com/tools/releases/platform-tools, unzip, and either add the folder to `PATH` or set `REBOOT_ADB` to the full path of `adb.exe`. |
| macOS | `brew install --cask android-platform-tools`, or download the platform-tools zip as above. |
| Linux | Debian/Ubuntu: `sudo apt install android-tools-adb`. Otherwise download the platform-tools zip. You may need udev rules for your phone's USB vendor. |

Check it:

```bash
reboot doctor
```

## 3. Prepare the phone

1. Open Settings, then About phone, and tap **Build number** seven times to unlock Developer
   options. (The menu names vary by brand; some put Build number under Software information.)
2. Open Developer options and turn on **USB debugging**.
3. Connect the cable. On the phone, accept the "Allow USB debugging?" prompt for this computer.
4. Choose **File transfer** or the default USB mode if adb does not see the phone.

Some brands add a second switch before adb may change apps. Xiaomi/MIUI phones are reported to
need an extra option such as "USB debugging (Security settings)". This is not yet tested here; if
`reboot apply` reports packages that did not verify as disabled, look for such a toggle in Developer
options and report what you found in a device-notes issue.

```bash
reboot devices
```

The state should be `device`. `unauthorized` means the phone prompt was not accepted; `offline` means
reconnect the cable or run `adb kill-server` yourself and retry.

## 4. Scan (read-only)

```bash
reboot scan --out reboot-scan.json
reboot analyze reboot-scan.json
```

Scan reports hide your serial number unless you pass `--include-serial`. Check a report before you
share it anywhere: the package list shows which apps you have installed.

## 5. Plan, apply, restore

```bash
reboot plan --pick com.example.package --out reboot-plan.json
reboot apply reboot-plan.json
reboot restore reboot-backups/<backup-file>.json
```

- `plan` is a dry run and prints the exact commands. It changes nothing.
- `apply` asks you about each package and writes a backup before changing anything.
- `restore` re-enables only what that backup shows Reboot changed.

Keep the backup file until you are sure you do not need to undo. Plans and backups contain your
serial number: do not share them.

## If something goes wrong

- Run `reboot restore` with the newest file in `reboot-backups/`.
- If you cannot run it, on the phone open Settings, Apps, find the app (turn on "show system apps"
  or "disabled apps" if needed) and tap **Enable**.
- Disabled packages stay disabled after reboot; a factory reset re-enables them.

## What is tested

See [tested-devices.md](tested-devices.md). Nothing is claimed beyond what is listed there.
