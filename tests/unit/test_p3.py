import json

import pytest
from typer.testing import CliRunner

from reboot import apply as apply_mod
from reboot import cli
from reboot import restore as restore_mod
from reboot.adb import Adb
from reboot.apply import apply_plan
from reboot.backup import BackupWriteError, read_backup, write_backup
from reboot.db import load_database
from reboot.device import probe_capabilities
from reboot.guards import (
    evaluate_guards,
    parse_components,
    parse_home_process,
    parse_resolve,
    parse_role_holders,
    parse_wifi_creators,
)
from reboot.names import InvalidPackageName
from reboot.plan import assess, build_plan
from reboot.restore import restore_backup
from tests.fakes import FakePhone

NOW = apply_mod.utcnow()

OPTIONAL = ["promo", "ads", "feed", "news", "tips", "weather"]
SPECIAL = ["launcher", "keyboard", "access", "dialer"]


def entry(name: str, tier: str = "optional") -> str:
    return (
        f"- id: com.example.{name}\n  oem: example\n  label: {name}\n  tier: {tier}\n"
        f'  why: because\n  consequences: something\n  sources: ["https://example.com/{name}"]\n'
        f"  confidence: high\n  reviewed: 2026-11-02\n"
    )


@pytest.fixture
def db(tmp_path):
    d = tmp_path / "db"
    d.mkdir()
    (d / "common.yaml").write_text(
        entry("settings")
        .replace("com.example.settings", "com.android.settings")
        .replace("oem: example", "oem: common")
        .replace("tier: optional", "tier: keep")
        + "  protected: true\n",
        encoding="utf-8",
    )
    body = "".join(entry(n) for n in OPTIONAL + SPECIAL) + entry("adv", "advanced")
    body += entry("keepme", "keep")
    (d / "example.yaml").write_text(body, encoding="utf-8")
    return load_database(d)


def make_phone(**kw) -> FakePhone:
    names = [f"com.example.{n}" for n in OPTIONAL + SPECIAL + ["adv", "keepme"]]
    system = names + ["com.android.settings", "com.mystery.thing"]
    return FakePhone(
        system,
        home="com.example.launcher",
        ime="com.example.keyboard/.Ime",
        accessibility="com.example.access/.Svc",
        dialer="com.example.dialer",
        sms="com.example.dialer",
        **kw,
    )


def adb_for(phone: FakePhone) -> Adb:
    return Adb("adb", phone.serial, phone)


def pkgs(names):
    return [f"com.example.{n}" for n in names]


def all_yes(_entry) -> bool:
    return True


# ---- guards ----------------------------------------------------------------------------------


def test_guard_parsers():
    assert parse_components("com.a/.Ime:com.b/com.b.Svc") == ["com.a", "com.b"]
    assert parse_components("null") == []
    assert parse_resolve("priority=0\ncom.launcher/.Main\n") == "com.launcher"
    assert parse_resolve("priority=0\nandroid/com.android.internal.app.ResolverActivity") is None
    assert parse_resolve("No activity found") is None
    assert parse_home_process("mHomeProcess=ProcessRecord{1a2b 99:com.l/u0a5}") == "com.l"
    assert parse_role_holders("com.a.dialer\n") == ["com.a.dialer"]
    assert parse_role_holders("") == []
    assert parse_wifi_creators("x creatorName=com.net.owner y creatorName=bad name") == {
        "com.net.owner"
    }


def test_guards_collect_and_fail_closed():
    phone = make_phone(wifi_creators=("com.example.news",))
    caps, _ = probe_capabilities(adb_for(phone))
    g = evaluate_guards(adb_for(phone), caps, 29)
    assert g.incomplete == []
    assert set(g.protected) >= {
        "com.example.launcher",
        "com.example.keyboard",
        "com.example.access",
        "com.example.dialer",
        "com.example.news",
    }
    phone.fail_settings = True
    g = evaluate_guards(adb_for(phone), caps, 29)
    assert "keyboard" in g.incomplete and "accessibility services" in g.incomplete


def test_guards_old_android_without_cmd_uses_fallbacks():
    phone = make_phone(has_cmd=False, sdk=23)
    caps, _ = probe_capabilities(adb_for(phone))
    g = evaluate_guards(adb_for(phone), caps, 23)
    assert g.incomplete == []
    assert "com.example.launcher" in g.protected  # via dumpsys activity fallback
    assert "com.example.dialer" in g.protected  # via settings key


# ---- plan ------------------------------------------------------------------------------------


def test_assess_eligible_and_skip_reasons(db):
    phone = make_phone(disabled={"com.example.tips"})
    picks = pkgs(OPTIONAL + SPECIAL + ["adv", "keepme"]) + [
        "com.android.settings",
        "com.mystery.thing",
        "com.example.notinstalled",
    ]
    a = assess(adb_for(phone), db, picks, allow_advanced=False)
    assert a.blocked is None
    assert [e.id for e in a.eligible] == pkgs(["promo", "ads", "feed", "news", "weather"])
    reasons = dict(a.skipped)
    assert "already disabled" in reasons["com.example.tips"]
    assert "guard: current home launcher" in reasons["com.example.launcher"]
    assert "active keyboard" in reasons["com.example.keyboard"]
    assert "accessibility" in reasons["com.example.access"]
    assert "dialer" in reasons["com.example.dialer"]
    assert "advanced" in reasons["com.example.adv"]
    assert "keep" in reasons["com.example.keepme"]
    assert reasons["com.android.settings"] == "protected"
    assert reasons["com.mystery.thing"].startswith("unknown")
    assert reasons["com.example.notinstalled"].startswith("unknown")


def test_assess_allow_advanced(db):
    a = assess(adb_for(make_phone()), db, pkgs(["adv"]), allow_advanced=True)
    assert [e.id for e in a.eligible] == pkgs(["adv"])


def test_invalid_name_refuses_whole_list_and_runs_nothing(db):
    phone = make_phone()
    with pytest.raises(InvalidPackageName):
        assess(adb_for(phone), db, ["com.example.promo", "bad name; reboot"], False)
    assert phone.calls == []


def test_plan_blocked_when_guard_unknown_or_unsupported(db):
    phone = make_phone()
    phone.fail_settings = True
    a = assess(adb_for(phone), db, pkgs(["promo"]), False)
    assert a.blocked and "keyboard" in a.blocked and not a.eligible

    class NoDisable(FakePhone):
        pass

    phone2 = make_phone()
    phone2.has_cmd = True
    phone2.__class__ = type(
        "P",
        (FakePhone,),
        {
            "__call__": lambda s, argv, t: (
                FakePhone.__call__(s, argv, t)
                if tuple(argv[-2:]) != ("pm", "help")
                else apply_mod.AdbResult(tuple(argv), 1, stderr="usage: pm")
            )
        },
    )
    a = assess(adb_for(phone2), db, pkgs(["promo"]), False)
    assert a.blocked and "disable-user" in a.blocked


def test_plan_makes_no_changes(db):
    phone = make_phone()
    a = assess(adb_for(phone), db, pkgs(OPTIONAL), False)
    plan = build_plan(a, False, NOW)
    assert plan["dry_run"] is True
    assert plan["actions"][0]["command"] == "adb shell pm disable-user --user 0 com.example.promo"
    assert phone.changes() == [] and phone.disabled == set()


# ---- apply and restore -----------------------------------------------------------------------


def make_plan(db, phone, picks=None, **kw):
    a = assess(adb_for(phone), db, picks or pkgs(OPTIONAL), kw.get("allow_advanced", False))
    return build_plan(a, kw.get("allow_advanced", False), NOW)


def test_apply_success_then_restore_after_reboot(db, tmp_path):
    phone = make_phone(disabled={"com.example.tips"})  # disabled before Reboot: must stay so
    plan = make_plan(db, phone)
    res = apply_plan(adb_for(phone), plan, db, tmp_path / "bk", all_yes, batch_size=2)
    assert res.complete and res.stopped is None
    assert phone.disabled == set(pkgs(OPTIONAL))  # tips was already disabled before
    record = read_backup(res.backup)
    assert {e["status"] for e in record["entries"]} == {"disabled"}
    assert "com.example.tips" not in {e["package"] for e in record["entries"]}

    # "reboot": disabled state persists on the phone; restore from the file on disk
    rr = restore_backup(adb_for(phone), read_backup(res.backup), res.backup)
    assert rr.complete
    assert phone.disabled == {"com.example.tips"}
    assert {e["status"] for e in read_backup(res.backup)["entries"]} == {"restored"}


def test_apply_requires_per_package_confirmation(db, tmp_path):
    phone = make_phone()
    plan = make_plan(db, phone)
    res = apply_plan(adb_for(phone), plan, db, tmp_path, lambda e: e.id.endswith(".ads"))
    assert phone.disabled == {"com.example.ads"}
    assert ("com.example.promo", "not confirmed") in res.skipped

    phone2 = make_phone()
    res = apply_plan(adb_for(phone2), plan, db, tmp_path, lambda e: False)
    assert res.backup is None and phone2.changes() == []


def test_apply_ignores_commands_in_plan_and_refuses_bad_names(db, tmp_path):
    phone = make_phone()
    plan = make_plan(db, phone, pkgs(["promo"]))
    plan["actions"][0]["command"] = "adb shell rm -rf /sdcard"
    res = apply_plan(adb_for(phone), plan, db, tmp_path, all_yes)
    assert res.complete
    assert all("rm" not in c for call in phone.calls for c in call)

    phone2 = make_phone()
    plan["actions"].append({"package": "com.example.x; reboot"})
    res = apply_plan(adb_for(phone2), plan, db, tmp_path, all_yes)
    assert "plan file refused" in res.stopped and phone2.changes() == []


def test_apply_rechecks_guards_at_apply_time(db, tmp_path):
    phone = make_phone()
    plan = make_plan(db, phone)
    phone.ime = "com.example.promo/.Ime"  # owner switched keyboard after planning
    res = apply_plan(adb_for(phone), plan, db, tmp_path, all_yes)
    assert "com.example.promo" not in phone.disabled
    assert any(p == "com.example.promo" and "keyboard" in r for p, r in res.skipped)


def test_apply_refuses_other_phone(db, tmp_path):
    phone = make_phone()
    plan = make_plan(db, phone)
    other = make_phone(serial="OTHER9")
    res = apply_plan(adb_for(other), plan, db, tmp_path, all_yes)
    assert "does not match" in res.stopped and other.changes() == []


def test_backup_write_failure_means_no_changes(db, tmp_path, monkeypatch):
    phone = make_phone()
    plan = make_plan(db, phone)

    def boom(record, path):
        raise BackupWriteError("disk full")

    monkeypatch.setattr(apply_mod, "write_backup", boom)
    res = apply_plan(adb_for(phone), plan, db, tmp_path, all_yes)
    assert "no changes made" in res.stopped
    assert phone.changes() == [] and res.backup is None


def test_backup_write_failure_mid_run_stops_before_next_batch(db, tmp_path, monkeypatch):
    phone = make_phone()
    plan = make_plan(db, phone)
    real = apply_mod.write_backup
    count = {"n": 0}

    def flaky(record, path):
        count["n"] += 1
        if count["n"] == 4:  # initial, pending#1, post-batch#1 ok; pending#2 fails
            raise BackupWriteError("disk full")
        real(record, path)

    monkeypatch.setattr(apply_mod, "write_backup", flaky)
    res = apply_plan(adb_for(phone), plan, db, tmp_path, all_yes, batch_size=2)
    assert "disk full" in res.stopped
    assert len(phone.disabled) == 2  # second batch never ran


def test_partial_failure_unplugged_then_restore(db, tmp_path):
    phone = make_phone()
    plan = make_plan(db, phone)
    phone.disconnect_after = 2
    res = apply_plan(adb_for(phone), plan, db, tmp_path, all_yes, batch_size=5)
    assert not res.complete and "connection lost" in res.stopped
    record = read_backup(res.backup)
    statuses = {e["package"]: e["status"] for e in record["entries"]}
    assert list(statuses.values()).count("pending") == 5  # outcome unknown, so still restorable
    assert list(statuses.values()).count("planned") == 1  # never touched
    assert len(phone.disabled) == 2

    phone.disconnected = False  # plug back in
    rr = restore_backup(adb_for(phone), read_backup(res.backup), res.backup)
    assert rr.complete and phone.disabled == set()
    final = {e["package"]: e["status"] for e in read_backup(res.backup)["entries"]}
    assert "planned" in final.values() and "pending" not in final.values()


def test_unverified_and_failed_commands_stop_the_run(db, tmp_path):
    phone = make_phone()
    plan = make_plan(db, phone)
    phone.ignore_disable = {"com.example.ads"}  # exit 0 but nothing changed
    res = apply_plan(adb_for(phone), plan, db, tmp_path, all_yes, batch_size=1)
    assert "did not verify" in res.stopped
    assert res.outcomes["com.example.ads"] == "verify_failed"
    assert res.outcomes["com.example.feed"] == "planned"

    phone2 = make_phone()
    phone2.fail_disable = {"com.example.promo"}
    res = apply_plan(adb_for(phone2), plan, db, tmp_path, all_yes, batch_size=5)
    assert res.outcomes["com.example.promo"] == "failed" and res.stopped


def test_restore_after_partial_failure_with_failed_status(db, tmp_path):
    phone = make_phone()
    plan = make_plan(db, phone)
    phone.ignore_disable = {"com.example.ads"}
    res = apply_plan(adb_for(phone), plan, db, tmp_path, all_yes, batch_size=1)
    rr = restore_backup(adb_for(phone), read_backup(res.backup), res.backup)
    assert rr.complete and phone.disabled == set()


def test_restore_refuses_wrong_phone_and_survives_backup_write_failure(db, tmp_path, monkeypatch):
    phone = make_phone()
    res = apply_plan(adb_for(phone), make_plan(db, phone), db, tmp_path, all_yes)
    record = read_backup(res.backup)

    other = make_phone(serial="OTHER9")
    other.disabled = set(phone.disabled)
    rr = restore_backup(adb_for(other), record, res.backup)
    assert "different phone" in rr.stopped and other.disabled == set(pkgs(OPTIONAL))

    def boom(record, path):
        raise BackupWriteError("disk full")

    monkeypatch.setattr(restore_mod, "write_backup", boom)
    rr = restore_backup(adb_for(phone), record, res.backup)
    assert rr.complete is True and rr.warnings and phone.disabled == set()


def test_restore_reports_still_disabled(db, tmp_path):
    phone = make_phone()
    res = apply_plan(adb_for(phone), make_plan(db, phone), db, tmp_path, all_yes)
    real = phone.__class__.__call__

    def stubborn(self, argv, timeout):
        if "enable" in argv:  # pm enable silently does nothing
            return apply_mod.AdbResult(tuple(argv), 0, stdout="ok")
        return real(self, argv, timeout)

    phone.__class__ = type("Stubborn", (FakePhone,), {"__call__": stubborn})
    rr = restore_backup(adb_for(phone), read_backup(res.backup), res.backup)
    assert not rr.complete and set(rr.outcomes.values()) == {"restore_failed"}


def test_atomic_backup_write_leaves_no_temp(tmp_path):
    p = tmp_path / "sub" / "b.json"
    write_backup({"schema_version": 1}, p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"schema_version": 1}
    assert [f.name for f in p.parent.iterdir()] == ["b.json"]


# ---- CLI -------------------------------------------------------------------------------------


def _patch_phone(monkeypatch, phone):
    monkeypatch.setattr(cli, "find_adb", lambda: "adb")
    monkeypatch.setattr(cli, "Adb", lambda binary: Adb(binary, runner=phone))


def test_cli_plan_apply_restore_roundtrip(db, tmp_path, monkeypatch):
    phone = make_phone()
    _patch_phone(monkeypatch, phone)
    db_dir = tmp_path / "db"  # written by the `db` fixture
    runner = CliRunner()
    picks = []
    for p in pkgs(["promo", "ads", "launcher"]):
        picks += ["--pick", p]
    plan_file = tmp_path / "plan.json"
    res = runner.invoke(cli.app, ["plan", *picks, "--out", str(plan_file), "--db", str(db_dir)])
    assert res.exit_code == 0, res.output
    assert "Dry run only" in res.output and phone.changes() == []
    assert "skip" in res.output and "com.example.launcher" in res.output

    bk = tmp_path / "bk"
    res = runner.invoke(
        cli.app,
        ["apply", str(plan_file), "--backup-dir", str(bk), "--db", str(db_dir)],
        input="y\nn\n",
    )
    assert res.exit_code == 0, res.output
    assert phone.disabled == {"com.example.promo"}  # second package declined
    (backup_file,) = list(bk.glob("backup-*.json"))

    res = runner.invoke(cli.app, ["restore", str(backup_file)], input="y\n")
    assert res.exit_code == 0, res.output
    assert phone.disabled == set()


def test_cli_plan_rejects_invalid_name(db, tmp_path, monkeypatch):
    phone = make_phone()
    _patch_phone(monkeypatch, phone)
    res = CliRunner().invoke(
        cli.app, ["plan", "--pick", "bad name", "--out", str(tmp_path / "p.json")]
    )
    assert res.exit_code == 2 and phone.changes() == []
