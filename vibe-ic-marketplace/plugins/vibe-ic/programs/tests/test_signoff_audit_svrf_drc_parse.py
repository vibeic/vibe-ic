"""The native DRC report reader parses the svrfdrc SVRF-native sign-off report
(the foundry's OWN Calibre `.rule` deck run on the vibeic KLayout engine) as a
per-rule FAIL count — a 0-FAIL sign-off must credit the tapeout DRC slot, and a
firing rule contributes a native failure count. Before this fix the report had no 'total violations:'
text, so a genuinely-clean 4533-PASS sign-off was mis-read as UNPARSED and
hard-FAILed the tapeout checklist. Chip-AGNOSTIC (generic rule names)."""
import eda_report_audit as native


def _mk_report(fails: int, passes: int) -> str:
    lines = ["# SVRF-native DRC via KLayout KLayout 0.30.9",
             f"# 224 layers, 15911 derivations, {fails+passes} rules  |  "
             f"{{'PASS': {passes}}}", ""]
    for i in range(passes):
        lines.append(f"PASS  R_pass_{i}   EXTERNAL a/b < 0.1 -> 0")
    for i in range(fails):
        lines.append(f"FAIL  R_fail_{i}   INTERNAL c < 0.2 -> {i+3}")
    return "\n".join(lines) + "\n"


def test_clean_svrf_report_is_zero_violations():
    assert native._drc_real_violation_count(_mk_report(fails=0, passes=4533)) == (0, 0)


def test_firing_svrf_report_fails_drc():
    assert native._drc_real_violation_count(_mk_report(fails=3, passes=4530)) == (3, 0)
