"""Regression for ORGANIC #644 — phase1 interface-table extraction emitted an
L9 `top_ports` entry whose NAME contained `/` (an illegal Verilog identifier)
when a power/supply table row PAIRED two rails in one cell (`vccd1 / vssd1`).
This corrupted L9 (the integration contract) and every downstream consumer (TB
gen #643, chip_top wrapper, LEF pin list); a later legality guard then DROPPED
the port entirely, losing both power rails.

Field-agent counter-evidence (the earlier sanitize-only fix went the wrong
way): the slashed name disappeared but `vccd1`/`vssd1` were MISSING from L9
(dropped, not split).

Fix: `_v0_3_2_emit_pins_from_gfm_tables` SPLITs a paired power NAME cell on `/`
into one LEGAL-identifier port per rail (`vccd1` AND `vssd1`), with the row's
direction / width / description applied to each. A single legal name is
unchanged.

ACCEPTANCE (issue): an interface doc with a `VDD / VSS` power-pair cell → L9
emits TWO legal-identifier ports.

NEGATIVE no-leak: a single legal name yields one port; a name with no legal
token yields none (never an illegal id); no emitted name contains `/`.

chip-AGNOSTIC: pure `/`-split + identifier-legality; no chip/vendor/SKU literal.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def _gfm(doc):
    return list(R._v0_3_2_emit_pins_from_gfm_tables(doc))


# ── (1) the acceptance: a power-pair cell → two legal ports ──────────────────

def test_power_pair_cell_splits_into_two_ports():
    doc = ("## Power\n\n| Signal | Direction | Width | Description |\n"
           "|---|---|---|---|\n"
           "| `VDD` / `VSS` | inout | 1 | core power / ground |\n")
    names = [r["name"] for r in _gfm(doc)]
    assert names == ["VDD", "VSS"]
    # both carry the row's direction/width
    for r in _gfm(doc):
        assert r["direction"] == "inout"
        assert r["width"] == "1"


def test_no_slash_in_any_emitted_name():
    doc = ("## Power\n\n| Signal | Direction | Width | Desc |\n|---|---|---|---|\n"
           "| `vccd1` / `vssd1` | inout | 1 | digital |\n"
           "| AVDD/AGND | inout | 1 | analog |\n"
           "| vdda1 | inout | 1 | single |\n")
    recs = _gfm(doc)
    assert all("/" not in r["name"] for r in recs)
    assert all(R._V644_LEGAL_ID_RE.match(r["name"]) for r in recs)
    assert {r["name"] for r in recs} == {
        "vccd1", "vssd1", "AVDD", "AGND", "vdda1"}


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────

def test_single_legal_name_unchanged_NOLEAK():
    doc = ("## Ports\n\n| Signal | Direction | Width | Desc |\n|---|---|---|---|\n"
           "| clk_i | input | 1 | clock |\n")
    assert [r["name"] for r in _gfm(doc)] == ["clk_i"]


@pytest.mark.parametrize("name,expected", [
    ("vccd1 / vssd1", ["vccd1", "vssd1"]),
    ("VDD/VSS", ["VDD", "VSS"]),
    ("`AVDD` / `AGND`", ["AVDD", "AGND"]),
    ("clk_i", ["clk_i"]),
    ("vccd1 / vccd1", ["vccd1"]),          # de-dup
    ("", []),
    ("/", []),                              # nothing legal
    ("a-b / cd", ["cd"]),                   # illegal part dropped, legal kept
    ("N/A", []),                            # NO-LEAK: junk grouping, 1-char
    ("TBD / x", ["TBD"]),                   # 1-char 'x' floored, >=2 'TBD' kept
    ("x", ["x"]),                           # single 1-char port NOT floored
])
def test_split_pair_names_helper(name, expected):
    assert R._v644_split_pair_names(name) == expected


def test_junk_grouping_no_phantom_NOLEAK():
    """A grouping cell whose split parts are all 1-char junk (`N/A`) yields NO
    port — the >=2-char floor on the split branch prevents phantom 1-char ids,
    while a genuine 1-char datapath port (no `/`) still passes."""
    assert R._v644_split_pair_names("N/A") == []
    assert R._v644_split_pair_names("p") == ["p"]      # single 1-char survives


# ── (3) END-TO-END final-L9 axis (the field-verified acceptance) ─────────────
# A GFM-emitter isolation test alone can miss the real failure axis (Step-2.6):
# the split must SURVIVE the full phase1 pipeline into FINAL L9, not just the
# emitter. Drive the whole runner on a tiny self-contained interface fixture
# and assert the FINAL L9 top_ports — this is CI-discoverable and pins the axis
# the issue actually failed on.

_TINY_L3 = (
    "# Tiny Interface\n\n## External Interface\n\n"
    "| Signal | Direction | Width | Description |\n|---|---|---|---|\n"
    "| `clk_i` | input | 1 | clock |\n"
    "| `rst_ni` | input | 1 | active-low reset |\n"
    "| `data_o` | output | 8 | output bus |\n"
    "| `vccd1`/`vssd1` | inout | 1 | core power / ground (USE_POWER_PINS) |\n")


def _final_l9_names(proj):
    import json
    import glob
    l9 = glob.glob(str(proj / "phase1" / "generated_docs" / "L9*.json"))
    assert l9, "phase1 did not emit an L9 spec"
    d = json.load(open(l9[0]))
    return [p.get("name", "") for p in d.get("top_ports", [])]


def test_end_to_end_final_l9_emits_two_legal_rails(tmp_path):
    """Full phase1 runner on a tiny power-pair interface doc → FINAL L9 carries
    BOTH `vccd1` and `vssd1` as legal ports, no `/` name, and the ordinary
    signal ports are unchanged (NO-LEAK: no phantom, count not inflated)."""
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L3_external_interface.md").write_text(_TINY_L3)
    runner = _PROGRAMS / "phase1_one_shot_runner.py"
    r = subprocess.run([sys.executable, str(runner), str(proj)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    names = _final_l9_names(proj)
    lower = {n.lower() for n in names}
    # ACCEPTANCE: power-pair split survives to FINAL L9 as two legal rails
    assert "vccd1" in lower and "vssd1" in lower, names
    # no illegal '/' identifier anywhere
    assert all("/" not in n for n in names), names
    # NO-LEAK: ordinary declared ports present, no phantom inflation
    assert "clk_i" in lower and "rst_ni" in lower and "data_o" in lower, names


def test_real_caravel_source_doc_if_present():
    """End-state on the REAL caravel interface doc (when on disk): the
    `vccd1`/`vssd1` power-pair row yields two legal ports, no '/' name. SKIPs
    off-monorepo."""
    doc = require_corpus("_bench7_caravel_v1034_cleanroom/caravel/"
                         "input/docs/L3_external_interface.md")
    if not doc.is_file():
        pytest.skip("real caravel interface doc not on disk")
    recs = _gfm(doc.read_text(errors="ignore"))
    names = {r["name"] for r in recs}
    assert "vccd1" in names and "vssd1" in names
    assert all("/" not in r["name"] for r in recs)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
