"""v0.2.97 — ORGANIC-20260606 #477: the LVS runner must NOT accept an
incomplete / aborted compare as a non-FAIL.

Audited rot (real field case): netgen was killed mid-run → lvs.rpt was
truncated at 'Flattening unmatched ...' with NO terminal verdict token
('Circuits match uniquely' / 'do NOT match' both absent); ext2spice.log
reported a huge extraction error count (observed 106,250,195 errors);
the merged GDS artifact was 0 bytes. NONE of these produced a FAIL.

The fix gives `_run_extraction_lvs` / `step_lvs` three run-completion
honesty checks, each recorded in a named verdict artifact
(reports/phase3/lvs_verdict.json), never silent:

  (a) report missing a terminal verdict token  → FAIL + INCOMPLETE
      verdict + finding LVS_NO_TERMINAL_VERDICT
  (b) 0-byte layout GDS input                   → FAIL + finding
      LVS_INPUT_GDS_EMPTY
  (c) ext2spice 'N errors' above the sane ceiling → FAIL + finding
      LVS_EXTRACTION_ERROR_FLOOD; a small nonzero count → hard WARNING
      surfaced in the verdict artifact (not swallowed)

Acceptance (executed end-to-end below):
  * a defect-artifact fixture (truncated verdict-less lvs.rpt + 0-byte
    merged GDS + ext2spice.log with a huge error count) drives the
    runner's LVS step to FAIL/INCOMPLETE with named findings;
  * a complete clean LVS replica still PASSes;
  * the Step-31 gate consumer (lvs_report_check → eda_report_audit
    --mode lvs) STILL exits 1 on a verdict-less log (regression guard
    for the gate the runner pairs with — #470 owns the gate, this only
    asserts it keeps tripping).

chip-AGNOSTIC: synthetic project + fake docker transcripts; no chip /
vendor / SKU literal used as detection logic.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as runner  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
_SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()


def _pdk():
    return runner.PdkConfig(
        name="sky130A", liberty="/foss/pdks/x.lib", tech_lef="/t.tlef",
        cell_lef="/c.lef", cell_gds=None, site="s", drc_deck=None)


def _proj(tmp_path, def_bytes=b"VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n"):
    # v0.3.13 #508/#509: the LVS layout source is the routed DEF (read
    # directly by Magic), NOT the GDS. The pnr DEF lives under
    # phase3/stage3/pnr/<top>.def.
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_bytes(def_bytes)
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text(
        "module chip_top();\nendmodule\n")
    return tmp_path


def _fake_docker(netgen_transcript, lvs_rpt_body=None,
                 spice_body=".subckt chip_top a b\n.ends\n",
                 ext2spice_log="MAGIC_EXT2SPICE_DONE\n"):
    """Docker stub: tool/tech checks OK; magic writes the extracted
    netlist AND the ext2spice.log; netgen prints the given transcript +
    writes lvs.rpt (body defaults to the transcript)."""
    import re as _re

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return (0, "", "")
        if "magic" in cmd and "SPICE_OUT=" in cmd:
            m = _re.search(r"SPICE_OUT=(\S+)", cmd)
            Path(m.group(1)).write_text(spice_body)
            # The runner tees ext2spice.log into the extracted dir; the
            # extracted dir is the cd target (SPICE_OUT's parent).
            ext_dir = Path(m.group(1)).parent
            ext_dir.mkdir(parents=True, exist_ok=True)
            (ext_dir / "ext2spice.log").write_text(ext2spice_log)
            return (0, ext2spice_log, "")
        if "netgen" in cmd:
            m = _re.search(r"(\S+/lvs\.rpt)", cmd)
            if m:
                rpt = Path(m.group(1))
                rpt.parent.mkdir(parents=True, exist_ok=True)
                body = lvs_rpt_body if lvs_rpt_body is not None \
                    else ("Netgen 1.5\n" + netgen_transcript)
                rpt.write_text(body)
            return (0, netgen_transcript, "")
        return (0, "", "")
    return fake


# --------------------------------------------------------------------------
# (a) verdict-less / truncated report → FAIL + INCOMPLETE verdict
# --------------------------------------------------------------------------
def test_truncated_verdict_less_report_is_incomplete_fail(tmp_path,
                                                          monkeypatch):
    p = _proj(tmp_path)
    # netgen killed mid-run: transcript + rpt truncated at "Flattening
    # unmatched", NO terminal verdict token anywhere.
    truncated = "Netgen 1.5\nReading netlists ...\nFlattening unmatched "
    monkeypatch.setattr(runner, "_docker_exec",
                        _fake_docker(truncated, lvs_rpt_body=truncated))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "FAIL", (r.status, r.detail)
    assert r.extras.get("finding") == "LVS_NO_TERMINAL_VERDICT"
    # The detail must NOT misclaim a conclusive compare; it must say
    # INCOMPLETE.
    assert "INCOMPLETE" in r.detail
    assert "a real compare ran" not in r.detail
    # Named verdict artifact written + machine-readable.
    vpath = p / "reports" / "phase3" / "lvs_verdict.json"
    assert vpath.is_file()
    v = json.loads(vpath.read_text())
    assert v["status"] == "INCOMPLETE"
    assert v["finding"] == "LVS_NO_TERMINAL_VERDICT"


# --------------------------------------------------------------------------
# (b) 0-byte layout GDS input → FAIL before tools even launch
# --------------------------------------------------------------------------
def test_zero_byte_def_input_is_named_fail(tmp_path, monkeypatch):
    p = _proj(tmp_path, def_bytes=b"")  # 0-byte routed/layout DEF
    # Tools all "present"; the size guard must fire before any compare.
    monkeypatch.setattr(runner, "_docker_exec",
                        lambda c, cmd, timeout=0, **_: (0, "", ""))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "FAIL", (r.status, r.detail)
    assert r.extras.get("finding") == "LVS_INPUT_DEF_EMPTY"
    assert "0 bytes" in r.detail
    vpath = p / "reports" / "phase3" / "lvs_verdict.json"
    assert vpath.is_file()
    v = json.loads(vpath.read_text())
    assert v["status"] == "FAIL"
    assert v["finding"] == "LVS_INPUT_DEF_EMPTY"


# --------------------------------------------------------------------------
# (c) ext2spice error flood → FAIL with the count named
# --------------------------------------------------------------------------
def test_ext2spice_error_flood_is_named_fail(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    # Huge extraction error count (the observed 106,250,195) with a
    # netgen transcript that WOULD otherwise "match" — the flood must
    # win and FAIL before trusting the netlist.
    flood_log = ("Magic 8.3\nextract all\n"
                 "ext2spice: 106,250,195 errors were encountered\n")
    monkeypatch.setattr(
        runner, "_docker_exec",
        _fake_docker("Final result: Circuits match uniquely.\n",
                     ext2spice_log=flood_log))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "FAIL", (r.status, r.detail)
    assert r.extras.get("finding") == "LVS_EXTRACTION_ERROR_FLOOD"
    assert r.extras.get("ext2spice_error_count") == 106250195
    vpath = p / "reports" / "phase3" / "lvs_verdict.json"
    assert vpath.is_file()
    v = json.loads(vpath.read_text())
    assert v["status"] == "FAIL"
    assert v["finding"] == "LVS_EXTRACTION_ERROR_FLOOD"
    assert v["ext2spice_error_count"] == 106250195


def test_small_ext2spice_error_count_is_warning_not_fail(tmp_path,
                                                         monkeypatch):
    p = _proj(tmp_path)
    # A handful of extraction warnings (below the FAIL ceiling) on an
    # otherwise-clean match → still PASS, but the warning is surfaced in
    # the verdict artifact + StepResult (never silently swallowed).
    small_log = "Magic 8.3\nextract all\next2spice: 3 errors\n"
    monkeypatch.setattr(
        runner, "_docker_exec",
        _fake_docker("Final result: Circuits match uniquely.\n",
                     ext2spice_log=small_log))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "PASS", (r.status, r.detail)
    assert r.extras.get("ext2spice_warning")
    assert "3" in r.extras["ext2spice_warning"]
    v = json.loads(
        (p / "reports" / "phase3" / "lvs_verdict.json").read_text())
    assert v["status"] == "PASS"
    assert v.get("ext2spice_warning")


# --------------------------------------------------------------------------
# regression: a complete clean LVS replica still PASSes
# --------------------------------------------------------------------------
def test_clean_complete_lvs_still_passes(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    monkeypatch.setattr(
        runner, "_docker_exec",
        _fake_docker("Final result: Circuits match uniquely.\n"))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "PASS", (r.status, r.detail)
    assert (p / "reports" / "phase3" / "lvs.rpt").is_file()
    v = json.loads(
        (p / "reports" / "phase3" / "lvs_verdict.json").read_text())
    assert v["status"] == "PASS"
    assert v["finding"] == "LVS_MATCH"
    # No spurious extraction warning on a clean run (0 errors → None).
    assert not r.extras.get("ext2spice_warning")


# --------------------------------------------------------------------------
# regression: a REAL mismatch still FAILs and keeps the "real compare
# ran" classification (NOT downgraded to INCOMPLETE).
# --------------------------------------------------------------------------
def test_real_mismatch_still_fails_as_conclusive(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    monkeypatch.setattr(
        runner, "_docker_exec",
        _fake_docker("Netlists do not match.\n"))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "FAIL"
    assert r.extras.get("finding") == "LVS_MISMATCH"
    assert "real compare ran" in r.detail
    v = json.loads(
        (p / "reports" / "phase3" / "lvs_verdict.json").read_text())
    assert v["status"] == "FAIL"
    assert v["finding"] == "LVS_MISMATCH"


# --------------------------------------------------------------------------
# the error-count parser: commas tolerated, MAX across lines, None when
# absent.
# --------------------------------------------------------------------------
def test_error_count_parser_behaviour():
    f = runner._parse_ext2spice_error_count
    assert f("ext2spice: 106,250,195 errors were encountered") == 106250195
    assert f("0 errors\nlater: 42 errors") == 42  # MAX, not first
    assert f("1 error\n") == 1
    assert f("extraction complete, no problems") is None
    assert f("") is None


# --------------------------------------------------------------------------
# ACCEPTANCE (end-to-end): the Step-31 gate consumer still exits 1 on a
# verdict-less log. This pairs the runner's own INCOMPLETE status with
# the gate that #470 owns — assert the gate keeps tripping.
# --------------------------------------------------------------------------
def test_gate_consumer_still_exits1_on_verdictless_log(tmp_path):
    rpt_dir = tmp_path / "reports" / "phase3"
    rpt_dir.mkdir(parents=True)
    # large enough to pass the byte floor, has LVS categories, but NO
    # tool signature and NO terminal verdict → LVS_NO_TOOL_SIGNATURE.
    body = ("LVS run report\ninstance net device parameter\n"
            + ("Flattening unmatched subcircuit padding line xxxxxxxxxx\n"
               * 200))
    (rpt_dir / "lvs.rpt").write_text(body)
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / "lvs_report_check.py"),
         str(tmp_path)],
        capture_output=True, text=True)
    assert cp.returncode == 1, (cp.returncode, cp.stdout)
    out = json.loads(cp.stdout)
    assert out["passed"] is False
    rules = [f["rule"] for f in out["findings"]]
    assert "LVS_NO_TOOL_SIGNATURE" in rules


# --------------------------------------------------------------------------
# source-shape guards: the verdict artifact + honesty checks are in the
# source (not just runtime), and the misleading unconditional
# "real compare ran" message is no longer the verdict-less path.
# --------------------------------------------------------------------------
def test_source_carries_honesty_checks():
    assert "_write_lvs_verdict" in _SRC
    assert "LVS_NO_TERMINAL_VERDICT" in _SRC
    # v0.3.13 #508/#509: the layout source is the routed DEF now.
    assert "LVS_INPUT_DEF_EMPTY" in _SRC
    assert "LVS_EXTRACTION_ERROR_FLOOD" in _SRC
    assert "_parse_ext2spice_error_count" in _SRC
    assert "lvs_verdict.json" in _SRC
