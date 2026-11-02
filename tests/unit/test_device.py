import pytest

from reboot.adb import AdbResult, clean_output, find_adb
from reboot.device import (
    UNSUPPORTED,
    DeviceError,
    parse_devices,
    parse_df,
    parse_meminfo,
    probe_capabilities,
    read_device_info,
    select_device,
)
from reboot.names import InvalidPackageName, is_valid_package, require_valid_packages
from tests.fakes import fixture, happy_phone, make_adb

ONE = "List of devices attached\nABC123  device usb:1-1 product:dandelion model:Redmi_9A transport_id:1\n\n"
TWO = ONE + "XYZ789  device usb:1-2 model:Other transport_id:2\n"
UNAUTH = "List of devices attached\nABC123  unauthorized usb:1-1 transport_id:1\n"
OFFLINE = "List of devices attached\nABC123  offline transport_id:1\n"
DAEMON = "* daemon not running; starting now at tcp:5037\n* daemon started successfully\n" + ONE


def test_parse_devices_details():
    (e,) = parse_devices(ONE)
    assert (e.serial, e.state, e.details["model"]) == ("ABC123", "device", "Redmi_9A")


def test_parse_devices_ignores_daemon_noise_and_empty():
    assert len(parse_devices(DAEMON)) == 1
    assert parse_devices("List of devices attached\n\n") == []


def test_select_single_device():
    assert select_device(parse_devices(ONE)).serial == "ABC123"


@pytest.mark.parametrize(
    ("text", "serial", "kind"),
    [
        ("List of devices attached\n", None, "no_device"),
        (TWO, None, "multiple_devices"),
        (TWO, "NOPE", "serial_not_found"),
        (UNAUTH, None, "unauthorized"),
        (OFFLINE, None, "offline"),
    ],
)
def test_select_device_errors(text, serial, kind):
    with pytest.raises(DeviceError) as exc:
        select_device(parse_devices(text), serial)
    assert exc.value.kind == kind


def test_select_with_serial_among_many():
    assert select_device(parse_devices(TWO), "XYZ789").serial == "XYZ789"


def test_parse_meminfo_and_df():
    assert parse_meminfo(fixture("meminfo.txt")) == 1949164
    assert parse_meminfo("garbage") is None
    assert parse_df(fixture("df_data.txt")) == (24421152, 13300000)
    assert parse_df("Filesystem\n") is None
    # wrapped filesystem name on its own line
    wrapped = "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/very/long\n 100 40 60 40% /data\n"
    assert parse_df(wrapped) == (100, 60)


def test_read_device_info_happy():
    adb, _ = make_adb(happy_phone())
    info, errors = read_device_info(adb)
    assert (info.manufacturer, info.model, info.sdk) == ("Xiaomi", "Redmi 9A", 29)
    assert info.ram_total_kb == 1949164
    assert errors == []


def test_read_device_info_missing_fields_are_unsupported_not_crash():
    responses = happy_phone()
    del responses[("shell", "getprop", "ro.product.model")]
    responses[("shell", "getprop", "ro.build.version.sdk")] = "\n"
    responses[("shell", "cat", "/proc/meminfo")] = AdbResult(
        ("x",), None, error="timed out after 30s"
    )
    adb, _ = make_adb(responses)
    info, errors = read_device_info(adb)
    assert info.model == UNSUPPORTED
    assert info.sdk == UNSUPPORTED
    assert info.ram_total_kb == UNSUPPORTED
    assert info.manufacturer == "Xiaomi"
    assert len(errors) == 3


def test_capabilities_observed():
    adb, _ = make_adb(happy_phone())
    caps, errors = probe_capabilities(adb)
    assert caps.cmd_package is True
    assert caps.pm_disable_user is True
    assert errors == []


def test_capabilities_old_android_without_cmd():
    responses = happy_phone()
    responses[("shell", "cmd", "package", "help")] = AdbResult(("x",), 127, stderr="cmd: not found")
    responses[("shell", "pm", "help")] = AdbResult(("x",), 0, stderr="usage: pm list ...\n")
    adb, _ = make_adb(responses)
    caps, _ = probe_capabilities(adb)
    assert caps.cmd_package is False
    assert caps.pm_disable_user is False


def test_capabilities_unknown_when_probe_fails():
    responses = happy_phone()
    responses[("shell", "pm", "help")] = AdbResult(("x",), None, error="timed out after 30s")
    adb, _ = make_adb(responses)
    caps, errors = probe_capabilities(adb)
    assert caps.pm_disable_user is None
    assert errors


def test_clean_output_strips_bom_and_crlf():
    assert clean_output(b"\xef\xbb\xbfa\r\r\nb\r\n") == "a\nb\n"


def test_find_adb_honours_override(monkeypatch, tmp_path):
    fake = tmp_path / "adb"
    fake.write_text("")
    monkeypatch.setenv("REBOOT_ADB", str(fake))
    assert find_adb() == str(fake)
    monkeypatch.setenv("REBOOT_ADB", str(tmp_path / "missing"))
    assert find_adb() is None


def test_package_name_validation():
    assert is_valid_package("com.android.settings")
    for bad in ("settings", "com.x; rm -rf /", "com..x", "1com.x", "com.x\n", ""):
        assert not is_valid_package(bad)
    with pytest.raises(InvalidPackageName):
        require_valid_packages(["com.ok.app", "bad name"])
