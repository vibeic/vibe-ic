#!/usr/bin/env python3
"""Tests for rtl_provenance.py — the provenance ledger that decides whether
``phase2/stage1/rtl/`` may be clobbered by a regeneration (chip-AGNOSTIC).

The module exists because ``step_rtl_gen`` used to destroy hand-authored RTL
on the SECOND re-run while still reporting PASS. These tests pin the four
verdicts and, most importantly, the FAIL-SAFE direction: anything the
generator cannot PROVE it produced must be preserved, never regenerated over.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "rtl_provenance.py"
_spec = importlib.util.spec_from_file_location("rtl_provenance", _PROG)
rtl_provenance = importlib.util.module_from_spec(_spec)
sys.modules["rtl_provenance"] = rtl_provenance
_spec.loader.exec_module(rtl_provenance)

rp = rtl_provenance


# ---- helpers ------------------------------------------------------------
def _rtl(project: Path) -> Path:
    d = project / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(project: Path, name: str, text: str) -> Path:
    p = _rtl(project) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ---- EMPTY --------------------------------------------------------------
def test_empty_when_no_rtl_dir(tmp_path):
    verdict, reason, ev = rp.classify(tmp_path)
    assert verdict == rp.EMPTY
    assert ev["file_count"] == 0


def test_empty_when_dir_exists_but_holds_no_rtl(tmp_path):
    _rtl(tmp_path)
    (_rtl(tmp_path) / "notes.txt").write_text("scratch, not RTL")
    verdict, _, ev = rp.classify(tmp_path)
    assert verdict == rp.EMPTY
    assert ev["file_count"] == 0


# ---- UNKNOWN — RTL present with no ledger is FAIL-SAFE ------------------
def test_unknown_when_rtl_present_without_ledger(tmp_path):
    """An absent ledger is NOT evidence of generator ownership."""
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    verdict, reason, ev = rp.classify(tmp_path)
    assert verdict == rp.UNKNOWN
    assert ev["file_count"] == 1
    assert "no provenance ledger" in reason


def test_unknown_when_vhdl_present_without_ledger(tmp_path):
    """VHDL is authored RTL too; a Verilog generator must not treat it as empty."""
    _write(tmp_path, "top.vhd", "entity top is end entity;\n")
    verdict, reason, ev = rp.classify(tmp_path)
    assert verdict == rp.UNKNOWN
    assert ev["file_count"] == 1
    assert ev["files"] == ["top.vhd"]
    assert "no provenance ledger" in reason


def test_unknown_is_a_preserve_verdict(tmp_path):
    assert rp.UNKNOWN in rp.PRESERVE_VERDICTS
    assert rp.AUTHORED in rp.PRESERVE_VERDICTS
    # The safe-to-clobber verdicts must NOT be preserve verdicts.
    assert rp.GENERATED not in rp.PRESERVE_VERDICTS
    assert rp.EMPTY not in rp.PRESERVE_VERDICTS


def test_corrupt_ledger_degrades_to_unknown_not_generated(tmp_path):
    """A malformed ledger must never read as proof of generation."""
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.ledger_path(tmp_path).write_text("{ not json")
    assert rp.classify(tmp_path)[0] == rp.UNKNOWN


def test_wrong_schema_ledger_degrades_to_unknown(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.ledger_path(tmp_path).write_text(json.dumps(
        {"schema": rp.SCHEMA_VERSION + 99, "files": {}}))
    assert rp.classify(tmp_path)[0] == rp.UNKNOWN


def test_symlinked_ledger_cannot_assert_generator_ownership(
        tmp_path):
    top = _write(tmp_path, "top.v", "module top(); endmodule\n")
    external = tmp_path / "external-ledger.json"
    external.write_text(json.dumps({
        "schema": rp.SCHEMA_VERSION,
        "files": {"top.v": rp.sha256_file(top)},
    }))
    rp.ledger_path(tmp_path).symlink_to(external)

    assert rp.load_ledger(tmp_path) is None
    assert rp.classify(tmp_path)[0] == rp.UNKNOWN


def test_malformed_removed_only_digest_does_not_claim_generated(tmp_path):
    _rtl(tmp_path)
    rp.ledger_path(tmp_path).write_text(json.dumps({
        "schema": rp.SCHEMA_VERSION,
        "files": {"top.v": "not-a-sha256"},
    }))

    assert rp.load_ledger(tmp_path) is None
    verdict, reason, evidence = rp.classify(tmp_path)
    assert verdict == rp.UNKNOWN
    assert evidence == {"file_count": 0, "ledger_present": True,
                        "ledger_valid": False}
    assert "unavailable digests" in reason


# ---- GENERATED — stamped and untouched ---------------------------------
def test_generated_after_stamp(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path, generator="unit-test")
    verdict, reason, ev = rp.classify(tmp_path)
    assert verdict == rp.GENERATED
    assert ev["ledger_generator"] == "unit-test"
    assert ev["file_count"] == 1


def test_ledger_lives_beside_rtl_never_inside(tmp_path):
    """A ledger inside rtl/ would be mistaken for emitted RTL."""
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    lp = rp.ledger_path(tmp_path)
    assert lp.is_file()
    assert lp.parent == (tmp_path / "phase2" / "stage1")
    assert rp.classify(tmp_path)[0] == rp.GENERATED


# ---- AUTHORED — the case that used to be silently destroyed ------------
def test_authored_when_file_modified(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    _write(tmp_path, "top.v", "module top(); // hand-authored fix\nendmodule\n")
    verdict, reason, ev = rp.classify(tmp_path)
    assert verdict == rp.AUTHORED
    assert ev["modified"] == ["top.v"]
    assert "top.v" in reason


def test_authored_when_file_added(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    _write(tmp_path, "alu.sv", "module alu(); endmodule\n")
    verdict, _, ev = rp.classify(tmp_path)
    assert verdict == rp.AUTHORED
    assert ev["added"] == ["alu.sv"]


def test_authored_detects_nested_file(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    _write(tmp_path, "sub/unit.v", "module unit(); endmodule\n")
    verdict, _, ev = rp.classify(tmp_path)
    assert verdict == rp.AUTHORED
    assert ev["added"] == ["sub/unit.v"]


def test_deletion_alone_is_not_authorship(tmp_path):
    """Regeneration restores a deleted file, so nothing is lost — this must
    stay GENERATED or the runner would refuse to regenerate forever."""
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    _write(tmp_path, "alu.v", "module alu(); endmodule\n")
    rp.stamp(tmp_path)
    (_rtl(tmp_path) / "alu.v").unlink()
    verdict, _, ev = rp.classify(tmp_path)
    assert verdict == rp.GENERATED
    assert ev["removed"] == ["alu.v"]


def test_deletion_of_the_only_generated_file_retains_ledger_ownership(
        tmp_path):
    """Removed-only is GENERATED even when no sibling RTL remains on disk."""
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path, generator="unit-test")
    (_rtl(tmp_path) / "top.v").unlink()

    verdict, reason, ev = rp.classify(tmp_path)

    assert verdict == rp.GENERATED
    assert ev["file_count"] == 0
    assert ev["removed"] == ["top.v"]
    assert ev["ledger_generator"] == "unit-test"
    assert "digest-bound restoration" in reason


def test_non_rtl_file_does_not_fake_authorship(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    (_rtl(tmp_path) / "scratch.log").write_text("noise")
    assert rp.classify(tmp_path)[0] == rp.GENERATED


def test_restamp_after_authoring_returns_to_generated(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    _write(tmp_path, "top.v", "module top(); // edited\nendmodule\n")
    assert rp.classify(tmp_path)[0] == rp.AUTHORED
    rp.stamp(tmp_path)
    assert rp.classify(tmp_path)[0] == rp.GENERATED


# ---- the two-re-run scenario the module was written to stop ------------
def test_authored_rtl_survives_repeated_classification(tmp_path):
    """The original defect: the aside survived exactly ONE re-run, so the
    SECOND destroyed the work. classify() must keep saying 'preserve' no
    matter how many times the front door is re-entered."""
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    _write(tmp_path, "top.v", "module top(); // authored by hand\nendmodule\n")
    for _ in range(5):
        assert rp.classify(tmp_path)[0] in rp.PRESERVE_VERDICTS


# ---- preserve() — a backup nothing reclaims ----------------------------
def test_preserve_copies_rtl_and_is_unique_per_call(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    first = rp.preserve(tmp_path)
    second = rp.preserve(tmp_path)
    assert first.is_dir() and second.is_dir()
    assert first != second, "a second override must not overwrite the first"
    assert (first / "top.v").read_text() == "module top(); endmodule\n"
    assert (second / "top.v").is_file()


def test_preserve_is_outside_rtl_so_it_is_not_reclassified(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path)
    dest = rp.preserve(tmp_path)
    assert rp.RTL_SUFFIXES  # sanity
    assert _rtl(tmp_path) not in dest.parents
    # The backup must not make the live tree look authored.
    assert rp.classify(tmp_path)[0] == rp.GENERATED


def test_preserve_keeps_the_ledger_alongside(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    rp.stamp(tmp_path, generator="unit-test")
    dest = rp.preserve(tmp_path)
    sidecar = dest.parent / (dest.name + "." + rp.LEDGER_NAME)
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text())["generator"] == "unit-test"


# ---- ledger content -----------------------------------------------------
def test_stamp_records_digests_for_every_rtl_file(tmp_path):
    _write(tmp_path, "top.v", "module top(); endmodule\n")
    _write(tmp_path, "sub/alu.sv", "module alu(); endmodule\n")
    payload = rp.stamp(tmp_path)
    assert set(payload["files"]) == {"top.v", "sub/alu.sv"}
    assert payload["schema"] == rp.SCHEMA_VERSION
    top = _rtl(tmp_path) / "top.v"
    assert payload["files"]["top.v"] == rp.sha256_file(top)


def test_stamp_records_vhdl_files(tmp_path):
    _write(tmp_path, "top.vhd", "entity top is end entity;\n")
    _write(tmp_path, "sub/unit.vhdl", "entity unit is end entity;\n")
    payload = rp.stamp(tmp_path)
    assert set(payload["files"]) == {"top.vhd", "sub/unit.vhdl"}
    assert rp.classify(tmp_path)[0] == rp.GENERATED


def test_load_ledger_returns_none_when_absent(tmp_path):
    assert rp.load_ledger(tmp_path) is None
