"""Regression: signoff_audit must parse the svrfdrc SVRF-native sign-off report
(the foundry's OWN Calibre `.rule` deck run on the vibeic KLayout engine) as a
per-rule FAIL count — a 0-FAIL sign-off must credit the tapeout DRC slot, and a
firing rule must FAIL it. Before this fix the report had no 'total violations:'
text, so a genuinely-clean 4533-PASS sign-off was mis-read as UNPARSED and
hard-FAILed the tapeout checklist. Chip-AGNOSTIC (generic rule names)."""
import importlib
from pathlib import Path
sa = importlib.import_module("signoff_audit")


def _mk_report(fails: int, passes: int) -> str:
    lines = ["# SVRF-native DRC via KLayout KLayout 0.30.9",
             f"# 224 layers, 15911 derivations, {fails+passes} rules  |  "
             f"{{'PASS': {passes}}}", ""]
    for i in range(passes):
        lines.append(f"PASS  R_pass_{i}   EXTERNAL a/b < 0.1 -> 0")
    for i in range(fails):
        lines.append(f"FAIL  R_fail_{i}   INTERNAL c < 0.2 -> {i+3}")
    return "\n".join(lines) + "\n"


def _count(tmp_path, text):
    # exercise the exact nested helper via the public tapeout audit path is
    # heavy; re-implement the detection identically here would defeat the test.
    # Instead call the module-level audit on a tiny project tree.
    proj = tmp_path
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / "drc_signoff.rpt").write_text(text)
    # minimal evidence so the DRC branch is reached
    (proj / "a.gds").write_text("gds")
    (proj / "netlist.v").write_text("module m(); endmodule")
    (proj / "t.rpt").write_text("slack 0.1")
    return sa._check_tapeout(Path(proj))


def test_clean_svrf_report_is_zero_violations(tmp_path):
    rep = _count(tmp_path, _mk_report(fails=0, passes=4533))
    assert rep is not None
    drc = [f for f in rep.findings if f.rule.startswith("TAPEOUT_DRC")]
    assert any(f.rule == "TAPEOUT_DRC_CLEAN" for f in drc), [f.rule for f in drc]
    assert rep.summary["evidence"]["drc"] is True


def test_firing_svrf_report_fails_drc(tmp_path):
    rep = _count(tmp_path, _mk_report(fails=3, passes=4530))
    assert rep is not None
    assert rep.summary["evidence"]["drc"] is not True
    assert any(f.rule == "TAPEOUT_DRC_VIOLATIONS" and f.severity == "ERROR"
               for f in rep.findings)
