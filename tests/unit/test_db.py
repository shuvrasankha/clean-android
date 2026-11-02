import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from reboot import cli
from reboot.analyze import analyze_report
from reboot.db import CONFIDENCE, OPTIONAL, REQUIRED, TIERS, DatabaseError, load_database
from reboot.miniyaml import YamlSubsetError, parse_entries
from tools.validate_db import main as validate_main

DATA = Path(__file__).resolve().parents[2] / "data"

GOOD = """\
- id: com.example.promo
  oem: example
  label: Promo feed
  tier: optional
  why: Shows sponsored cards
  consequences: Feed page disappears
  sources: ["https://example.com/note"]
  confidence: medium
  reviewed: 2026-11-02
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def make_dir(tmp_path: Path, example: str = GOOD) -> Path:
    common = GOOD.replace("example", "common").replace("optional", "keep") + "  protected: true\n"
    write(tmp_path, "common.yaml", common.replace("com.common.promo", "com.android.settings"))
    write(tmp_path, "example.yaml", example)
    return tmp_path


# ---- parser ----------------------------------------------------------------------------------


def test_parser_matches_pyyaml_on_shipped_and_sample_data():
    for text in [GOOD, (DATA / "packages" / "common.yaml").read_text(encoding="utf-8")]:
        mine = parse_entries(text)
        theirs = yaml.safe_load(text)
        for m, t in zip(mine, theirs, strict=True):
            t = {k: (str(v) if k == "reviewed" else v) for k, v in t.items()}
            assert m == t


def test_parser_block_list_comments_bom_crlf():
    text = (
        "﻿# header\r\n- id: a.b  # trailing\r\n  sources:\r\n    - https://x.test/#frag\r\n"
        "    - 'device: Redmi'\r\n  android_min: 10\r\n  protected: true\r\n"
    )
    (e,) = parse_entries(text)
    assert e == {
        "id": "a.b",
        "sources": ["https://x.test/#frag", "device: Redmi"],
        "android_min": 10,
        "protected": True,
    }


@pytest.mark.parametrize(
    "text",
    [
        "id: x\n",  # not a list
        "- id: a.b\n\tkey: v\n",  # tab
        "- id: a.b\n    key: v\n",  # bad indent
        "- id: a.b\n  id: c.d\n",  # duplicate key
        "- id: a.b\n  tags: [x, y\n",  # unterminated list
        "- id a.b\n",  # no colon
        "  key: v\n",  # indented before entry
    ],
)
def test_parser_rejects_unsupported(text):
    with pytest.raises(YamlSubsetError):
        parse_entries(text)


# ---- validation ------------------------------------------------------------------------------


def test_shipped_database_is_valid_and_all_protected():
    db = load_database(DATA / "packages")
    assert db.entries
    assert all(e.protected and e.tier == "keep" for e in db.entries.values())
    assert validate_main(["validate_db"]) == 0


def test_valid_database_loads(tmp_path):
    db = load_database(make_dir(tmp_path))
    assert db.entries["com.example.promo"].tier == "optional"


@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        ("tier: optional", "tier: delete", "tier must be"),
        ("confidence: medium", "confidence: sure", "confidence must be"),
        ("reviewed: 2026-11-02", "reviewed: 2026-13-45", "reviewed must be"),
        ("id: com.example.promo", "id: notapackage", "not a valid package name"),
        ('sources: ["https://example.com/note"]', "sources: []", "non-empty list"),
        ('sources: ["https://example.com/note"]', 'sources: ["trust me"]', "http(s) URL"),
        ("tier: optional", "tier: optional\n  protected: true", "must have tier 'keep'"),
        ("tier: optional", "tier: optional\n  android_min: 12\n  android_max: 9", "greater than"),
        ("tier: optional", "tier: optional\n  colour: red", "unknown field"),
        ("oem: example", "oem: other", "does not match file"),
        ("  why: Shows sponsored cards\n", "", "missing required field 'why'"),
    ],
)
def test_validation_problems(tmp_path, old, new, fragment):
    make_dir(tmp_path, GOOD.replace(old, new))
    with pytest.raises(DatabaseError) as exc:
        load_database(tmp_path)
    assert fragment in "\n".join(exc.value.problems)


def test_duplicate_id_across_files_and_missing_common(tmp_path):
    make_dir(tmp_path, GOOD.replace("com.example.promo", "com.android.settings"))
    with pytest.raises(DatabaseError, match="duplicate id"):
        load_database(tmp_path)
    (tmp_path / "common.yaml").unlink()
    with pytest.raises(DatabaseError, match="missing common.yaml"):
        load_database(tmp_path)


def test_common_entries_must_be_protected(tmp_path):
    write(tmp_path, "common.yaml", GOOD.replace("example", "common").replace("optional", "keep"))
    with pytest.raises(DatabaseError, match="must be protected"):
        load_database(tmp_path)


def test_android_range_and_unknown_version(tmp_path):
    ranged = GOOD.replace("tier: optional", "tier: optional\n  android_min: 10\n  android_max: 12")
    entry = load_database(make_dir(tmp_path, ranged)).entries["com.example.promo"]
    assert entry.applies_to(10) and entry.applies_to(12)
    assert not entry.applies_to(9) and not entry.applies_to(13)
    assert not entry.applies_to(None)  # unknown version never matches a ranged entry


def test_schema_json_in_sync_with_validator():
    schema = json.loads((DATA / "schema.json").read_text(encoding="utf-8"))
    assert tuple(schema["required"]) == REQUIRED
    assert set(schema["properties"]) == set(REQUIRED) | set(OPTIONAL)
    assert tuple(schema["properties"]["tier"]["enum"]) == TIERS
    assert tuple(schema["properties"]["confidence"]["enum"]) == CONFIDENCE
    assert schema["additionalProperties"] is False


# ---- analyze ---------------------------------------------------------------------------------


def report(release="10", packages=None):
    return {
        "device": {"manufacturer": "X", "model": "Y", "android_release": release},
        "packages": packages
        or [
            {"id": "com.android.settings", "kind": "system", "state": "enabled"},
            {"id": "com.example.promo", "kind": "system", "state": "enabled"},
            {"id": "com.mystery.thing", "kind": "system", "state": "enabled"},
            {"id": "com.example.game", "kind": "user", "state": "enabled"},
        ],
    }


def test_analyze_buckets_and_unknown_stays_unknown(tmp_path):
    db = load_database(make_dir(tmp_path))
    result = analyze_report(report(), db)
    assert [r.entry.id for r in result.protected] == ["com.android.settings"]
    assert [r.entry.id for r in result.by_tier["optional"]] == ["com.example.promo"]
    assert result.unknown == ["com.mystery.thing"]
    assert result.user_app_count == 1


def test_analyze_out_of_range_or_unknown_android_is_unknown(tmp_path):
    ranged = GOOD.replace("tier: optional", "tier: optional\n  android_min: 11")
    db = load_database(make_dir(tmp_path, ranged))
    assert "com.example.promo" in analyze_report(report("10"), db).unknown
    assert "com.example.promo" in analyze_report(report("unsupported"), db).unknown
    assert "com.example.promo" not in analyze_report(report("12"), db).unknown


def test_cli_analyze(tmp_path):
    db_dir = make_dir(tmp_path / "db") if (tmp_path / "db").mkdir() is None else None
    rep = tmp_path / "scan.json"
    rep.write_text(json.dumps(report()), encoding="utf-8")
    res = CliRunner().invoke(cli.app, ["analyze", str(rep), "--db", str(db_dir)])
    assert res.exit_code == 0, res.output
    assert "com.mystery.thing" in res.output
    bad = CliRunner().invoke(cli.app, ["analyze", str(rep), "--db", str(tmp_path / "nope")])
    assert bad.exit_code == 2
