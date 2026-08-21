"""Tests for opcode_field_width_consistency_check (v0.2.13).

Pins the two checks that would have caught the usb_pd fabricated-opcode bug
(0x11-0x1F on a 4-bit Type field; L3 said 0x11 while L15 said 0x01).
"""
import importlib
import json
from pathlib import Path

mod = importlib.import_module("opcode_field_width_consistency_check")


def _proj(tmp_path, l3, l4=None, l8=None, l15=None):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    if l4 is not None:
        (gd / "L4_REGMAP.json").write_text(json.dumps(l4))
    if l8 is not None:
        (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
    if l15 is not None:
        (gd / "L15_ENCODING_TABLES.json").write_text(json.dumps(l15))
    return tmp_path


def test_clean_project_passes(tmp_path):
    l3 = {"opcodes": [{"hex": "0x01", "name": "GoodCRC"},
                      {"hex": "0x0F", "name": "Vendor_Defined"}]}
    l15 = {"fields": {"t": {"rows": [["0x01", "GoodCRC"], ["0x0F", "Vendor_Defined"]]}}}
    assert mod.check_project(_proj(tmp_path, l3, l15=l15)) == []


def test_field_width_overflow_flagged(tmp_path):
    # The usb_pd bug: a 4-bit Message Type field but an opcode hex 0x11 (>0xF).
    l3 = {"opcodes": [{"hex": "0x11", "name": "Source_Capabilities"}]}
    l4 = {"registers": [{"name": "Message Header",
                         "fields": "Message Type [3:0], Number of Data Objects [14:12]"}]}
    findings = mod.check_project(_proj(tmp_path, l3, l4=l4))
    kinds = {f["kind"] for f in findings}
    assert "FIELD_WIDTH_OVERFLOW" in kinds

    # And no overflow when the hex fits the field.
    l3ok = {"opcodes": [{"hex": "0x01", "name": "Source_Capabilities"}]}
    assert not any(f["kind"] == "FIELD_WIDTH_OVERFLOW"
                   for f in mod.check_project(_proj(tmp_path / "ok", l3ok, l4=l4)))


def test_l3_l15_hex_mismatch_flagged(tmp_path):
    # L3 says Source_Capabilities=0x11 but L15 says 0x01 (the usb_pd contradiction).
    l3 = {"opcodes": [{"hex": "0x11", "name": "Source_Capabilities"}]}
    l15 = {"fields": {"data_message_table": {
        "rows": [["0x01", "Source_Capabilities"]]}}}
    findings = mod.check_project(_proj(tmp_path, l3, l15=l15))
    assert any(f["kind"] == "L3_L15_HEX_MISMATCH"
               and f["mnemonic"] == "source_capabilities" for f in findings)


def test_l3_l15_agreement_passes(tmp_path):
    l3 = {"opcodes": [{"hex": "0x01", "name": "Source_Capabilities"}]}
    l15 = {"fields": {"data_message_table": {
        "rows": [["0x01", "Source_Capabilities"]]}}}
    assert not any(f["kind"] == "L3_L15_HEX_MISMATCH"
                   for f in mod.check_project(_proj(tmp_path, l3, l15=l15)))


def test_no_opcodes_is_noop(tmp_path):
    # Bus protocol with no command opcodes -> nothing to check.
    l3 = {"opcodes": [], "no_opcodes_in_input": True}
    assert mod.check_project(_proj(tmp_path, l3)) == []


# --- the CLI layer, and three ways it used to report a pass on nothing

def _mod():
    import opcode_field_width_consistency_check as M
    return M


def _project(tmp_path, l3, l8=None):
    gd = tmp_path / "proj" / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    if l8:
        (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
    return tmp_path / "proj"


def test_an_overflowing_opcode_exits_1(tmp_path):
    """The five tests above drive `check_project()` and assert on the findings
    list. None reached `main()`, so the findings -> exit-code mapping was never
    measured — and the flow reads the exit code. The mutation probe neutered
    the CLI and all five stayed green.

    Real defect: the usb_pd benchmark shipped opcodes 0x11-0x1F against a 4-bit
    Message Type field. That is what this gate exists to stop, driven the way
    the flow drives it.
    """
    M = _mod()
    proj = _project(
        tmp_path,
        {"opcodes": [{"name": "GET_STATUS", "hex": "0x1F"}]},
        {"width_parameters": {"MESSAGE_TYPE_BITS": {"width_bits": 4}}})
    assert M.main([str(proj)]) == 1


def test_a_consistent_project_exits_0(tmp_path):
    """…or the test above is satisfied by a gate that always returns 1."""
    M = _mod()
    proj = _project(
        tmp_path,
        {"opcodes": [{"name": "GET_STATUS", "hex": "0x0F"}]},
        {"width_parameters": {"MESSAGE_TYPE_BITS": {"width_bits": 4}}})
    assert M.main([str(proj)]) == 0


def test_a_project_that_is_not_there_is_not_a_pass(tmp_path):
    """MEASURED, then fixed, in the same round that added this file.

    `main(["/nonexistent/project"])` printed "checked 1 project(s) — ALL_PASS"
    and returned 0. A path typo was indistinguishable from a clean chip, and
    the clean answer is the one a caller acts on. This gate had, at its own CLI
    boundary, the class of defect the whole round was about.
    """
    M = _mod()
    assert M.main([str(tmp_path / "no-such-project")]) == 2


def test_a_sweep_root_that_is_not_there_is_not_a_pass(tmp_path):
    """The same hole via the other entry point."""
    M = _mod()
    assert M.main(["--benchmark-dir", str(tmp_path / "no-such-root")]) == 2


def test_a_sweep_that_opened_nothing_is_not_a_pass(tmp_path):
    """And the third exit from that room: the root exists but holds no project,
    so zero were checked — which printed ALL_PASS."""
    M = _mod()
    (tmp_path / "root" / "not-a-project").mkdir(parents=True)
    assert M.main(["--benchmark-dir", str(tmp_path / "root")]) == 2


def test_an_unreadable_entry_does_not_take_the_sweep_down(tmp_path,
                                                          monkeypatch):
    """One unreadable directory used to abort the whole survey.

    Measured against a real sweep root: a PermissionError on
    /tmp/snap-private-tmp propagated out of the comprehension as a traceback,
    so every other benchmark under the root went unexamined and the operator
    saw a crash instead of a verdict. It is now skipped loudly and the sweep
    continues — which this test proves by leaving one good project behind the
    bad entry.
    """
    M = _mod()
    root = tmp_path / "root"
    root.mkdir()
    good = root / "good"
    (good / "phase1" / "generated_docs").mkdir(parents=True)
    (good / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({"opcodes": [{"name": "NOP", "hex": "0x01"}]}))
    bad = root / "bad"
    bad.mkdir()

    real_is_dir = Path.is_dir

    def fake_is_dir(self):
        if str(self).startswith(str(bad)):
            raise PermissionError(13, "Permission denied")
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    assert M.main(["--benchmark-dir", str(root)]) == 0
