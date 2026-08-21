"""v0.3.24 — ORGANIC #524: the netgen terminal phrase
`Final result: Top level cell failed pin matching.` is a CONCLUSIVE LVS-FAIL,
but the phase3 runner's inline token copy (and mixed-signal / analog-A6 copies)
lacked it, so the verdict was mis-reported as INCOMPLETE ("netgen produced no
terminal verdict token") while the Step-31 gate (#507) called it MISMATCH —
breaking the very gate-vs-runner agreement #507 set out to guarantee.

The fix introduces ONE shared classifier (`programs/lvs_verdict_tokens.py`,
semantics mirroring the in-container-validated mcp-eda netgen_verdict.mjs:
pin-matching fail + property-error fail are terminal FAILs, a mismatch token is
authoritative over `match uniquely`) and points all Python consumers at it.

NEGATIVE no-leak (#507/#477 direction): a genuinely truncated, verdict-less
report must STAY INCOMPLETE — never upgraded to FAIL or PASS.

chip-AGNOSTIC: synthetic netgen report text; the real on-host report is only
an optional extra check.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import lvs_verdict_tokens as T  # noqa: E402
import phase3_one_shot_runner as runner  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

PIN_FAIL_RPT = """\
Netgen 1.5.316
Circuit 1 contains 120 devices, Circuit 2 contains 120 devices.
Netlists match uniquely.
Subcircuit summary:
i_data[3]                                  |i_data[3]
(no pin, node is o_data[7])                |o_word[7]
(no pin, node is o_data[6])                |o_word[6]
---------------------------------------------------------------------------
Cell pin lists for top and top altered to match.
Device classes top and top are equivalent.

Final result: Top level cell failed pin matching.
"""

TRUNCATED_RPT = "Netgen 1.5\nReading netlists ...\nFlattening unmatched "

CLEAN_RPT = """\
Netgen 1.5.316
Subcircuit summary — all cells matched.
Final result: Circuits match uniquely.
"""

PROPERTY_RPT = """\
Netgen 1.5.316
Netlists match uniquely with property errors.
width of M1 = 2.0 vs 1.0
Final result: Circuits match uniquely.
Property errors were found.
"""


# ── shared classifier ──────────────────────────────────────────────────────

def test_failed_pin_matching_is_terminal_mismatch():
    assert T.classify(PIN_FAIL_RPT) == "MISMATCH"


def test_truncated_report_stays_incomplete():
    # NEGATIVE no-leak: incomplete is never upgraded to a conclusive verdict.
    assert T.classify(TRUNCATED_RPT) == "INCOMPLETE"


def test_clean_match_is_match():
    assert T.classify(CLEAN_RPT) == "MATCH"


def test_property_errors_fail_even_with_match_uniquely():
    # the in-container-validated netgen behavior: a property delta prints BOTH
    # 'Circuits match uniquely.' AND 'Property errors were found.' — the
    # property error is the real verdict (mismatch is authoritative).
    assert T.classify(PROPERTY_RPT) == "MISMATCH"


def test_pin_mismatch_evidence_extracted():
    ev = T.pin_mismatch_evidence(PIN_FAIL_RPT)
    assert any("o_data[7]" in line for line in ev), ev
    assert any("o_word[7]" in line for line in ev), ev
    # only the mismatch lines, not the clean correspondence rows
    assert not any("i_data[3]" in line for line in ev), ev


def test_cli_pin_fail_exit_one_with_mismatch_verdict(tmp_path):
    rpt = tmp_path / "lvs.rpt"
    rpt.write_text(PIN_FAIL_RPT)
    rc = T.main([str(rpt), "--json", str(tmp_path / "v.json")])
    assert rc == 1
    v = json.loads((tmp_path / "v.json").read_text())
    assert v["verdict"] == "MISMATCH"
    assert v["pin_mismatch_evidence"]


def test_cli_clean_exit_zero(tmp_path):
    rpt = tmp_path / "lvs.rpt"
    rpt.write_text(CLEAN_RPT)
    assert T.main([str(rpt)]) == 0


# ── runner step_lvs: pin-fail now a conclusive FAIL, not INCOMPLETE ────────

def _pdk():
    return runner.PdkConfig(
        name="sky130A", liberty="/foss/pdks/x.lib", tech_lef="/t.tlef",
        cell_lef="/c.lef", cell_gds=None, site="s", drc_deck=None)


def _proj(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_bytes(
        b"VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    return tmp_path


def _fake_docker(netgen_transcript, lvs_rpt_body):
    import re as _re

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return (0, "", "")
        if "magic" in cmd and "SPICE_OUT=" in cmd:
            m = _re.search(r"SPICE_OUT=(\S+)", cmd)
            Path(m.group(1)).write_text(".subckt chip_top a b\n.ends\n")
            # A REAL extraction always writes the feedback dump: the recipe ends
            # `feedback save $env(FEEDBACK_OUT)` (phase3_one_shot_runner.py:27902,
            # lvs_power_aware_extract_tcl.py:333) and magic writes a 0-byte file when
            # `feedback count` is 0. Modelling the netlist but not the feedback channel
            # made this stub an extraction that cannot happen, and
            # magic_illegal_overlap_check correctly refused it (EXTRACTION_FEEDBACK_ABSENT:
            # "an absent file is not a measured zero, it is an unmeasured nothing").
            _fb = _re.search(r"FEEDBACK_OUT=(\S+)", cmd)
            if _fb:
                Path(_fb.group(1)).parent.mkdir(parents=True, exist_ok=True)
                Path(_fb.group(1)).write_text("")
            ext_dir = Path(m.group(1)).parent
            ext_dir.mkdir(parents=True, exist_ok=True)
            (ext_dir / "ext2spice.log").write_text("MAGIC_EXT2SPICE_DONE\n")
            return (0, "MAGIC_EXT2SPICE_DONE\n", "")
        if "netgen" in cmd:
            m = _re.search(r"(\S+/lvs\.rpt)", cmd)
            if m:
                rpt = Path(m.group(1))
                rpt.parent.mkdir(parents=True, exist_ok=True)
                rpt.write_text(lvs_rpt_body)
            return (0, netgen_transcript, "")
        return (0, "", "")
    return fake


def test_runner_pin_fail_is_conclusive_mismatch_not_incomplete(
        tmp_path, monkeypatch):
    # #524 binding shape: transcript itself carries no verdict; lvs.rpt's only
    # terminal line is 'Final result: Top level cell failed pin matching.'
    p = _proj(tmp_path)
    monkeypatch.setattr(runner, "_docker_exec",
                        _fake_docker("Netgen 1.5\nrunning ...\n",
                                     lvs_rpt_body=PIN_FAIL_RPT))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "FAIL", (r.status, r.detail)
    # the conclusive-mismatch finding, NOT the incomplete one
    assert r.extras.get("finding") == "LVS_MISMATCH", r.extras
    assert "INCOMPLETE" not in r.detail
    # readable pin evidence surfaced for close-loop triage
    ev = r.extras.get("pin_mismatch_evidence") or []
    assert any("o_data[7]" in line for line in ev), ev
    v = json.loads(
        (p / "reports" / "phase3" / "lvs_verdict.json").read_text())
    assert v["status"] == "FAIL"
    assert v["finding"] == "LVS_MISMATCH"


def test_runner_truncated_still_incomplete(tmp_path, monkeypatch):
    # NEGATIVE no-leak (#477 regression guard): a truly verdict-less truncated
    # report keeps the INCOMPLETE classification after the #524 token change.
    p = _proj(tmp_path)
    monkeypatch.setattr(runner, "_docker_exec",
                        _fake_docker(TRUNCATED_RPT,
                                     lvs_rpt_body=TRUNCATED_RPT))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "FAIL"
    assert r.extras.get("finding") == "LVS_NO_TERMINAL_VERDICT"
    assert "INCOMPLETE" in r.detail


# ── Step-31 gate (lvs_report_check → eda_report_audit) stays in agreement ──

def test_gate_pin_fail_is_mismatch_not_incomplete(tmp_path):
    import eda_report_audit as A
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "lvs.rpt").write_text(PIN_FAIL_RPT)
    rc = A.main([str(proj), "--mode", "lvs",
                 "--json", str(tmp_path / "audit.json")])
    assert rc == 1
    out = json.loads((tmp_path / "audit.json").read_text())
    assert out["summary"]["terminal_verdict"] == "MISMATCH"
    rules = [f["rule"] for f in out["findings"]]
    assert "LVS_NETLISTS_DO_NOT_MATCH" in rules
    assert "LVS_NO_TERMINAL_VERDICT" not in rules


# ── secondary consumer sites use the shared tokens / phrase ────────────────

def test_mixed_signal_site_uses_shared_tokens():
    src = (PROGRAMS / "mixed_signal_top_lvs_run.py").read_text()
    assert "_lvt.classify" in src
    # no leftover inline verdict regex
    assert 'r"do not match|NET MISMATCH' not in src


def test_runner_site_uses_shared_tokens():
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "_lvt.classify" in src
    assert 'r"do not match|NET MISMATCH' not in src


def test_analog_a6_recognizes_failed_pin_matching():
    import analog_a6_block_pv_check as A6
    assert A6._parse_lvs_match(
        "Final result: Top level cell failed pin matching.") is False


def test_truncated_hierarchical_subcell_match_is_incomplete():
    # adversarial-review finding (mirrors the netgen_verdict.mjs guard): a
    # hierarchical run killed AFTER a per-subcell 'Netlists match uniquely.'
    # line but BEFORE the top-level compare has a match token and NO
    # 'Final result:' line — it must classify INCOMPLETE, never MATCH.
    trunc_hier = ("Netgen 1.5\nCircuit sub_a ...\n"
                  "Netlists match uniquely.\nFlattening next cell ...")
    assert T.classify(trunc_hier) == "INCOMPLETE"


def test_evidence_prefers_top_level_node_rows_over_subcell_noise():
    # adversarial-review finding: clean sky130 reports carry hundreds of
    # benign subcell `(no matching pin)` power-pin rows at the FRONT; the
    # genuine top-level failing rows are the `(no pin, node is …)` shape at
    # the TAIL. Evidence must surface the latter, not the noise.
    noise = ("VGND     |(no matching pin)\n"
             "VPWR     |(no matching pin)\n") * 50
    blob = noise + PIN_FAIL_RPT
    ev = T.pin_mismatch_evidence(blob)
    assert ev, "evidence expected"
    assert all("(no pin, node is" in line for line in ev), ev
    assert any("o_word[7]" in line for line in ev), ev


def test_real_on_host_pin_fail_report_classifies_mismatch():
    # the host corpus is LIVE (field-agent runs overwrite these reports), so
    # gate on CONTENT, not existence: only assert when the report currently
    # carries the #524 failing shape.
    candidates = [
        require_corpus("subservient_e2e_v0323/reports/phase3/lvs.rpt"),
        require_corpus("_spm_signoff/lvs/spm_lvs5.out"),
    ]
    blob = None
    for real in candidates:
        if real.is_file():
            txt = real.read_text(errors="replace")
            if "failed pin matching" in txt.lower():
                blob = txt
                break
    if blob is None:
        pytest.skip("no on-host report currently in the #524 failing shape")
    assert T.classify(blob) == "MISMATCH"


# ───────────────────────────────────────────────────────────────────────────
# ORGANIC (GAP-E2E-9) — mismatch_class() sub-classification.
# The 7-IC end-to-end sweep hit `Top level cell failed pin matching` (→ MISMATCH)
# on EVERY sky130 OSS run because the yosys gate netlist has no power ports while
# the extracted layout carries per-cell VPWR/VGND — a benign power-unaware-netlist
# SETUP artifact (measured: caravel + subservient LVS carry ONLY power rows).
# mismatch_class() is TRIAGE metadata; it does NOT change the MATCH/MISMATCH
# verdict. §4.05 NO-LEAK is the load-bearing half: anything with real signal-net
# evidence MUST stay SIGNAL_NET_MISMATCH (measured: aes 517 + ibex 256 top-level
# `(no pin, node is …)` rows must NOT be waved through).
# ───────────────────────────────────────────────────────────────────────────

# A power-pin-only MISMATCH (the benign OSS setup class) — caravel/subservient shape.
_POWER_ONLY_RPT = (
    "Subcircuit pins:\n"
    "Circuit 1: user_project_wrapper       |Circuit 2: user_project_wrapper\n"
    "VGND                                       |(no matching pin)\n"
    "VNB                                        |(no matching pin)\n"
    "VPB                                        |(no matching pin)\n"
    "VPWR                                       |(no matching pin)\n"
    "HI                                         |(no matching pin)\n"
    "Cell sky130_fd_sc_hd__inv_1 (0) disconnected node: VPWR\n"
    "Cell sky130_fd_sc_hd__inv_1 (0) disconnected node: VGND\n"
    "Final result: Top level cell failed pin matching.\n"
)

# A power-pin-only report that ALSO has benign sub-cell PIN rows (Y/A/B), which
# are NOT signal evidence — must still classify POWER_PIN_ONLY.
_POWER_PLUS_CELLPIN_RPT = (
    "VGND                                       |(no matching pin)\n"
    "VPWR                                       |(no matching pin)\n"
    "Y                                          |(no matching pin)\n"
    "A                                          |(no matching pin)\n"
    "B                                          |(no matching pin)\n"
    "Final result: Top level cell failed pin matching.\n"
)

# NEGATIVE no-leak fixtures — REAL signal-net defects that must STAY real:
# (1) top-level `(no pin, node is …)` signal rows (aes/ibex shape).
_SIGNAL_NODE_RPT = (
    "VGND                                       |(no matching pin)\n"
    "(no pin, node is _54440_/Y)                |alert_fatal_o\n"
    "(no pin, node is _54440_/Y)                |data_out[7]\n"
    "Final result: Top level cell failed pin matching.\n"
)
# (2) a device property-error fail (real, even with a topology 'match uniquely').
_PROPERTY_ERR_RPT = (
    "VPWR                                       |(no matching pin)\n"
    "Circuits match uniquely with property errors.\n"
    "Property errors were found.\n"
    "Final result: Circuits match uniquely.\n"
)
# (3) a MISMATCH with NO recognizable benign power evidence → conservative real.
_BARE_MISMATCH_RPT = (
    "Net NET MISMATCH between circuit 1 and circuit 2\n"
    "Final result: Netlists do not match.\n"
)


def test_mismatch_class_power_pin_only_is_benign():
    assert T.classify(_POWER_ONLY_RPT) == "MISMATCH"
    assert T.mismatch_class(_POWER_ONLY_RPT) == "POWER_PIN_ONLY"


def test_mismatch_class_ignores_benign_cell_pin_rows():
    # Y/A/B `(no matching pin)` are sub-cell pins, NOT signal-port evidence.
    assert T.mismatch_class(_POWER_PLUS_CELLPIN_RPT) == "POWER_PIN_ONLY"


def test_mismatch_class_signal_node_rows_stay_real():
    # §4.05 NO-LEAK: a `(no pin, node is …)` top-level signal row is NEVER benign.
    assert T.mismatch_class(_SIGNAL_NODE_RPT) == "SIGNAL_NET_MISMATCH"


def test_mismatch_class_property_error_stays_real():
    assert T.mismatch_class(_PROPERTY_ERR_RPT) == "SIGNAL_NET_MISMATCH"


def test_mismatch_class_bare_mismatch_stays_real_conservative():
    # A mismatch with no recognizable power-setup shape must NOT be called benign.
    assert T.mismatch_class(_BARE_MISMATCH_RPT) == "SIGNAL_NET_MISMATCH"


def test_mismatch_class_none_on_match_and_incomplete():
    assert T.mismatch_class(CLEAN_RPT) == "NONE"       # a clean MATCH
    assert T.mismatch_class(TRUNCATED_RPT) == "NONE"   # an INCOMPLETE run


def test_mismatch_class_verdict_unchanged():
    # The authoritative verdict is NOT altered by the sub-class (no gate relaxation).
    assert T.classify(_POWER_ONLY_RPT) == "MISMATCH"
    assert T.classify(_SIGNAL_NODE_RPT) == "MISMATCH"
