"""Tests for sdc_clock_period_library_basis_check.py.

BIDIRECTIONAL BY CONSTRUCTION. A gate tested only in the direction that makes
it fire is a rubber stamp, and so is one tested only in the direction that
makes it quiet. Every test below is labelled DEFECT-DIRECTION (the defect must
make the gate FAIL) or FIXED-DIRECTION (the clean case must make it PASS/SKIP),
and both classes are non-empty.

The defect this gate exists to catch was measured on spm x ihp-sg13g2 (8HD-8,
plugin 1.5.85 and 1.6.4 alike): the design spec keys its target clock period by
standard-cell library, the physical sign-off ran against a library with no row
in that table, and the SDC nevertheless carried another library's number --
so "setup met at +6.11 ns" was met against a constraint with no basis in the
spec for the library that signed off, and nothing disclosed it.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import sdc_clock_period_library_basis_check as g  # noqa: E402


# The design input that reproduces the measured defect: a period table keyed by
# library, with no row for the library that ends up signing off.
LIBRARY_KEYED_DOC = """\
| field | value |
|---|---|
| Target PDK family | open-source (SKY130 primary, GF180MCU secondary) |
| Target clock period - SKY130 generic | 10 ns (100 MHz) |
| Target clock period - SKY130 high-speed (`sky130_fd_sc_hs`) | 8 ns (125 MHz) |
| Target clock period - GF180MCU | 24 ns (~41.7 MHz) |
"""

# A spec that does NOT key the period by library: one generic target only.
GENERIC_DOC = """\
| field | value |
|---|---|
| Target clock period | 10 ns (100 MHz) |
"""


def _mk(tmp_path: Path, *, doc: str = LIBRARY_KEYED_DOC, period="10.0",
        pdk="ihp-sg13g2", disclosure: str | None = None,
        waiver: str | None = None, sdc: bool = True) -> Path:
    """Build a minimal run dir. Only the inputs the gate reads are created."""
    proj = tmp_path / "run"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L1_product_metadata.md").write_text(doc)

    if sdc:
        d = proj / "phase3" / "stage3" / "pnr"
        d.mkdir(parents=True)
        (d / "constraint.sdc").write_text(
            "# VIBEIC_SDC_PDK_PROVENANCE: %s\n"
            "create_clock -name clk -period %s [get_ports clk]\n" % (pdk, period))

    orch = proj / "reports" / "orchestrator"
    orch.mkdir(parents=True)
    if pdk is not None:
        (orch / "phase3_one_shot.json").write_text(json.dumps({"pdk": pdk}))

    if disclosure is not None:
        (proj / "reports" / "final_summary.md").write_text(disclosure)
    if waiver is not None:
        (proj / "waivers.json").write_text(waiver)
    return proj


# ---------------------------------------------------------------------------
# DEFECT-DIRECTION — the defect must make the gate FAIL
# ---------------------------------------------------------------------------

def test_DEFECT_signoff_library_absent_from_spec_table_FAILS(tmp_path):
    """The measured defect: sign-off on a library the period table never keys."""
    r = g.check(_mk(tmp_path))
    assert r["verdict"] == "FAIL"
    assert "CLOCK_PERIOD_LIBRARY_NOT_IN_SPEC_TABLE" in r["reason"]
    # and it must NAME the row the period was actually taken from
    assert "sky130" in r["reason"]
    assert "10 ns (100 MHz)" in r["reason"]


def test_DEFECT_wrong_row_used_when_own_row_exists_FAILS(tmp_path):
    """A row for the signed-off library EXISTS but the SDC used another's."""
    # gf180mcuD signed off, its row says 24 ns, but the SDC carries sky130's 10.
    r = g.check(_mk(tmp_path, pdk="gf180mcuD", period="10.0"))
    assert r["verdict"] == "FAIL"
    assert "CLOCK_PERIOD_WRONG_ROW" in r["reason"]


def test_DEFECT_disclosure_naming_only_one_side_does_not_count(tmp_path):
    """Half a disclosure is not a disclosure."""
    r = g.check(_mk(tmp_path,
                    disclosure="pdk_substitution: ran on ihp-sg13g2\n"))
    assert r["verdict"] == "FAIL"


def test_DEFECT_prose_naming_both_without_disclose_keyword_does_not_count(tmp_path):
    """Mentioning both PDKs in passing is not an announcement."""
    r = g.check(_mk(tmp_path,
                    disclosure="We built ihp-sg13g2 and once considered sky130.\n"))
    assert r["verdict"] == "FAIL"


def test_DEFECT_empty_disclosure_file_cannot_game_the_gate(tmp_path):
    r = g.check(_mk(tmp_path, disclosure=""))
    assert r["verdict"] == "FAIL"


def test_DEFECT_unrelated_waiver_does_not_cover_it(tmp_path):
    """An FPGA cap-gap waiver is not a clock-period-basis waiver."""
    r = g.check(_mk(tmp_path, waiver=json.dumps(
        {"waived_steps": [{"id": 39, "reason": "ENV_UNAVAILABLE (fpga-board)"}]})))
    assert r["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# FIXED-DIRECTION — the clean case must PASS (or SKIP), never FAIL
# ---------------------------------------------------------------------------

def test_FIXED_own_row_matched_PASSES(tmp_path):
    """sky130A signed off and the SDC carries sky130's own 10 ns row."""
    r = g.check(_mk(tmp_path, pdk="sky130A", period="10.0"))
    assert r["verdict"] == "PASS"
    assert "input/docs/L1_product_metadata.md" in r["reason"]


def test_FIXED_own_row_matched_for_the_other_family_PASSES(tmp_path):
    """gf180mcuD signed off at its own 24 ns row."""
    r = g.check(_mk(tmp_path, pdk="gf180mcuD", period="24"))
    assert r["verdict"] == "PASS"


def test_FIXED_honest_disclosure_naming_both_PASSES(tmp_path):
    r = g.check(_mk(tmp_path, disclosure=(
        "pdk_substitution: signed off on ihp-sg13g2; the 10 ns period is the "
        "sky130 row, which this library has no row for.\n")))
    assert r["verdict"] == "PASS_WITH_DISCLOSURE"
    assert r["disclosure"] == "reports/final_summary.md"


def test_FIXED_documented_waiver_PASSES(tmp_path):
    r = g.check(_mk(tmp_path, waiver=json.dumps({"waived_steps": [
        {"id": 1, "reason": "CLOCK_PERIOD_BASIS: no sg13g2 row in the spec",
         "approver": "field-agent-attest", "review_required": True}]})))
    assert r["verdict"] == "PASS_WITH_DISCLOSURE"


def test_FIXED_spec_not_library_keyed_SKIPS(tmp_path):
    """One generic target and no per-library table: nothing to enforce."""
    r = g.check(_mk(tmp_path, doc=GENERIC_DOC))
    assert r["verdict"] == "SKIP"
    assert "do not key the clock period by library" in r["reason"]


def test_FIXED_no_signoff_sdc_SKIPS(tmp_path):
    r = g.check(_mk(tmp_path, sdc=False))
    assert r["verdict"] == "SKIP"


def test_FIXED_no_resolved_pdk_SKIPS(tmp_path):
    proj = _mk(tmp_path)
    (proj / "reports" / "orchestrator" / "phase3_one_shot.json").unlink()
    # strip the SDC provenance stamp too, so neither source resolves a PDK
    sdc = proj / "phase3" / "stage3" / "pnr" / "constraint.sdc"
    sdc.write_text("create_clock -name clk -period 10.0 [get_ports clk]\n")
    r = g.check(proj)
    assert r["verdict"] == "SKIP"


# ---------------------------------------------------------------------------
# Unit — family tokenisation. Both directions.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pdk,expected_member", [
    ("ihp-sg13g2", "sg13g2"),
    ("IHP SG13G2", "sg13g2"),
    ("sky130A", "sky130"),
    ("gf180mcuD", "gf180mcu"),
])
def test_UNIT_resolved_families_recognises_the_family(pdk, expected_member):
    assert expected_member in g._resolved_families(pdk)


@pytest.mark.parametrize("pdk,absent", [
    ("ihp-sg13g2", "sky130"),
    ("sky130A", "sg13g2"),
    ("gf180mcuD", "sky130"),
])
def test_UNIT_resolved_families_does_not_over_match(pdk, absent):
    assert absent not in g._resolved_families(pdk)


def test_UNIT_unregistered_pdk_still_gets_a_token(tmp_path):
    """An unknown PDK must not normalise to the empty set and match anything."""
    fams = g._resolved_families("some-new-foundry-pdk")
    assert fams and fams != set()


# ---------------------------------------------------------------------------
# End-to-end CLI: exit code must be 1 on FAIL and 0 otherwise, and NEVER 2
# (flow_compliance_check turns rc==2 into a VACUOUS_PASS counted in the PASS
# numerator; a period with no basis for the signed-off library must not land
# in that numerator).
# ---------------------------------------------------------------------------

def test_CLI_rc_is_1_on_defect(tmp_path, capsys):
    rc = g.main([str(_mk(tmp_path))])
    assert rc == 1
    first = capsys.readouterr().out.splitlines()[0]
    # The umbrella quotes this FIRST line into the human report — it must be a
    # verdict, not a bare "{" from indented JSON.
    assert first.startswith("FAIL: CLOCK_PERIOD_LIBRARY_NOT_IN_SPEC_TABLE")


def test_CLI_rc_is_0_on_clean(tmp_path, capsys):
    rc = g.main([str(_mk(tmp_path, pdk="sky130A", period="10.0"))])
    assert rc == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("PASS: ")


def test_CLI_json_out_still_written(tmp_path):
    out = tmp_path / "rep.json"
    g.main([str(_mk(tmp_path)), "--json", str(out)])
    assert json.loads(out.read_text())["verdict"] == "FAIL"


def test_CLI_never_returns_2(tmp_path):
    """rc==2 would be converted into a VACUOUS_PASS. It must never happen."""
    for kw in ({}, {"pdk": "sky130A", "period": "10.0"},
               {"doc": GENERIC_DOC}, {"sdc": False}):
        assert g.main([str(_mk(tmp_path / str(abs(hash(str(kw)))), **kw))]) in (0, 1)
