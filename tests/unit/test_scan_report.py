import json
from datetime import datetime, timezone

from typer.testing import CliRunner

from reboot import cli
from reboot.adb import Adb, AdbResult
from reboot.report import REDACTED, build_report, write_report
from reboot.scan import parse_package_list, run_scan
from tests.fakes import FakeRunner, happy_phone, make_adb

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def test_parse_package_list_rejects_bad_lines():
    names, rejected = parse_package_list(
        "package:com.a.b\r\npackage:bad name\nnoise\n\npackage:com.a.b\n"
    )
    assert names == ["com.a.b"]
    assert len(rejected) == 2


def test_scan_happy_report_is_json_and_redacts_serial(tmp_path):
    adb, runner = make_adb(happy_phone())
    result = run_scan(adb)
    report = build_report(result, "ABC123", now=NOW)
    out = tmp_path / "r.json"
    write_report(report, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["device"]["serial"] == REDACTED
    assert "ABC123" not in out.read_text(encoding="utf-8")
    assert data["package_counts"] == {"system": 4, "user": 1, "disabled": 1, "enabled": 4}
    states = {p["id"]: p["state"] for p in data["packages"]}
    assert states["com.miui.msa.global"] == "disabled"
    assert states["com.android.settings"] == "enabled"
    assert data["read_only"] is True


def test_scan_only_issues_read_commands():
    adb, runner = make_adb(happy_phone())
    run_scan(adb)
    forbidden = {"disable-user", "enable", "uninstall", "clear", "disable"}
    for call in runner.calls:
        assert not forbidden & set(call), call


def test_include_serial_opt_in():
    adb, _ = make_adb(happy_phone())
    report = build_report(run_scan(adb), "ABC123", include_serial=True, now=NOW)
    assert report["device"]["serial"] == "ABC123"


def test_scan_with_everything_failing_still_valid_json():
    runner = FakeRunner({})  # every command fails
    result = run_scan(Adb("adb", "ABC123", runner))
    report = build_report(result, "ABC123", now=NOW)
    json.dumps(report)
    assert report["device"]["model"] == "unsupported"
    assert report["package_counts"]["system"] == "unsupported"
    assert report["packages"] == []
    assert report["capabilities"]["pm_disable_user"] == "unsupported"
    assert report["errors"]


def test_pm_user_flag_fallback_for_old_android():
    responses = happy_phone()
    flag = "-s"
    del responses[("shell", "pm", "list", "packages", "--user", "0", flag)]
    responses[("shell", "pm", "list", "packages", flag)] = "package:com.android.settings\n"
    adb, _ = make_adb(responses)
    result = run_scan(adb)
    assert result.inventory.system == ["com.android.settings"]
    assert any("--user 0 -s" in e for e in result.errors)


def test_failed_enabled_list_marks_state_unsupported():
    responses = happy_phone()
    responses[("shell", "pm", "list", "packages", "--user", "0", "-e")] = AdbResult(
        ("x",), 1, stderr="boom"
    )
    adb, _ = make_adb(responses)
    report = build_report(run_scan(adb), "ABC123", now=NOW)
    states = {p["id"]: p["state"] for p in report["packages"]}
    assert states["com.android.settings"] == "unsupported"
    assert states["com.miui.msa.global"] == "disabled"


# ---- CLI -------------------------------------------------------------------------------------

DEVICES = "List of devices attached\nABC123  device model:Redmi_9A transport_id:1\n"


def _patch_adb(monkeypatch, responses):
    runner = FakeRunner(responses)
    monkeypatch.setattr(cli, "find_adb", lambda: "adb")
    orig = cli.Adb
    monkeypatch.setattr(cli, "Adb", lambda binary: orig(binary, runner=runner))


def test_cli_scan_writes_report(monkeypatch, tmp_path):
    responses = happy_phone()
    responses[("devices", "-l")] = DEVICES
    _patch_adb(monkeypatch, responses)
    out = tmp_path / "scan.json"
    res = CliRunner().invoke(cli.app, ["scan", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert json.loads(out.read_text(encoding="utf-8"))["device"]["model"] == "Redmi 9A"


def test_cli_scan_refuses_without_device(monkeypatch, tmp_path):
    _patch_adb(monkeypatch, {("devices", "-l"): "List of devices attached\n"})
    out = tmp_path / "scan.json"
    res = CliRunner().invoke(cli.app, ["scan", "--out", str(out)])
    assert res.exit_code == 2
    assert not out.exists()


def test_cli_missing_adb(monkeypatch):
    monkeypatch.setattr(cli, "find_adb", lambda: None)
    res = CliRunner().invoke(cli.app, ["doctor"])
    assert res.exit_code == 2
