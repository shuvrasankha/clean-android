# Safety

Reboot only ever runs two commands that change a phone:

- `pm disable-user --user 0 <package>` (apply)
- `pm enable --user 0 <package>` (restore)

Nothing is uninstalled, cleared or rooted. Package names are validated against
`^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$` before they reach any command; one bad name refuses the
whole list. Commands are rebuilt from validated names at apply time; command strings stored in plan or
backup files are for display only and are never executed.

## Flow

1. `reboot plan` is a dry run. It reads live state, applies the guards and prints exact commands.
2. `reboot apply <plan>` re-reads live state and re-checks every guard, then asks for confirmation
   **per package**. There is no "yes to all".
3. The backup record is written and fsynced **before** any change. If it cannot be written, nothing
   runs. It is updated before and after every batch of five.
4. After each batch the disabled list is re-read. A package that is not listed as disabled stops the
   run; exit codes are never trusted alone.
5. `reboot restore <backup>` re-enables only packages whose status shows they may have been changed
   (`pending`, `disabled`, `failed`, `verify_failed`, `restore_failed`), then verifies.

## What is skipped (and why is shown)

| Skipped when | Source |
| --- | --- |
| not in the database for this Android version (unknown) | `data/packages` |
| `protected: true`, or tier `keep` | database |
| tier `advanced` without `--allow-advanced` | plan option |
| not an installed system package, or already disabled | live `pm list packages` |
| current home launcher | `cmd package resolve-activity` (fallback `dumpsys activity`) |
| active keyboard | `settings get secure default_input_method` |
| default dialer and SMS app | `cmd role get-role-holders` (Android 10+), settings keys before that |
| active accessibility service | `settings get secure enabled_accessibility_services` |
| owner of a saved Wi-Fi network | `dumpsys wifi` (`creatorName=`) |

**Fail closed:** if a guard cannot be determined (query fails, or no home launcher is identifiable),
no plan is made and nothing is applied. The phone must also confirm `pm disable-user` support.

## Stop conditions

Apply stops on: disconnect or timeout, a package that does not verify as disabled, a failed batch
verification, or a backup that cannot be updated. Packages not yet touched stay `planned`.

## Not yet verified on real phones

The guard commands and output parsers are tested only against hand-written fixtures. A successful
apply and restore on a physical phone, including after a reboot, is a release blocker for any
version that can disable packages. No phone models are verified yet.

Backups and plans contain the device serial. Keep them local; do not attach them to issues.
