# PROMPT.md: guided flow for a coding assistant

Paste this file (or point your assistant at it) to have it drive Project Reboot with you. You stay in
control: the assistant runs read-only steps and explains results, and **you** approve and confirm
every change.

## Rules for the assistant (non-negotiable)

1. Start read-only. Run `reboot doctor`, `reboot devices`, `reboot scan`, `reboot analyze`,
   `reboot plan` freely. These never change the phone.
2. Never run `reboot apply` or `reboot restore` yourself. They ask the owner a yes/no question for
   each package. Tell the owner the exact command and let them run it and answer in their own
   terminal. Never pipe, echo or script answers into those prompts, and never add a "yes to all".
3. Never run `adb` commands directly to change the phone. The only allowed changes are the ones
   `reboot apply` (`pm disable-user --user 0`) and `reboot restore` (`pm enable --user 0`) make.
4. No uninstalling, clearing app data, `pm clear`, rooting, flashing or editing system files.
5. Only offer packages that `reboot analyze` lists as `optional` (or `advanced` if the owner opts in
   to `--allow-advanced`). Anything listed as **unknown** stays unknown: do not guess, do not suggest
   disabling it, and do not use web searches to talk the owner into it. Add it to the open-questions
   list instead.
6. Never edit `data/packages/` to make a package disable-able during a session. Database changes need
   a source and a review, and new brands need a tested physical phone.
7. Report honestly. If a step fails, partly succeeds or cannot be verified, say so with the output.
   Do not claim speed or battery gains.
8. Keep everything local. Scan reports hide the serial by default; plans and backups contain it, so
   do not paste them into issues or chats.

## Flow

1. **Check the setup**
   ```bash
   reboot doctor
   reboot devices
   ```
   If adb is missing or the phone is `unauthorized`, follow `docs/setup.md`. If several phones are
   attached, ask which one and pass `--serial`.

2. **Scan (read-only)**
   ```bash
   reboot scan --out reboot-scan.json
   reboot analyze reboot-scan.json
   ```
   Summarize: the phone, how many packages are protected, optional, advanced and unknown. Mention any
   fields reported as `unsupported`. Show the owner the optional packages with their `why` and
   `consequences`.

3. **Ask the owner what they want gone.** Per package, never in bulk. Put only their choices in a
   pick list. If the database has nothing for their phone's brand, say so plainly: the tool cannot
   help with that brand yet, and the manual settings guides in `docs/ad-settings/` still apply.

4. **Plan (dry run)**
   ```bash
   reboot plan --pick com.example.package --pick com.example.other --out reboot-plan.json
   ```
   Read the output to the owner: what would be disabled, what was skipped and why (guards: home
   launcher, keyboard, dialer, SMS, accessibility, Wi-Fi owner, protected, unknown). If `plan` says
   it cannot determine a guard, stop; do not work around it.

5. **Owner approval.** Ask: "Do you approve this plan?" Wait for a clear yes in chat. A yes to one
   plan does not cover a different or edited plan.

6. **Apply (owner runs it)**
   Tell the owner to run this in their terminal and answer each prompt:
   ```bash
   reboot apply reboot-plan.json
   ```
   When they paste the result back, check that every package shows `disabled` and note the backup
   path. If it says `stopped`, explain why, and offer restore before anything else.

7. **Check the phone together.** Ask the owner to use the phone normally for a while: calls, SMS,
   keyboard, home screen, the apps they depend on.

8. **Undo if anything is wrong or unexpected**
   ```bash
   reboot restore reboot-backups/<backup-file>.json
   ```
   Again the owner runs it. Afterwards confirm that every package shows `restored`.

## Open-questions list

Keep a running list of packages the owner asked about that are unknown or that you were unsure about.
Leave them enabled. At the end, give the owner the list so they can open a package-research issue
with evidence.
