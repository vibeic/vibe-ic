"""tests/test_analog_a7_post_layout_resim_check.py — A7 (renumbered from A6)"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a7_post_layout_resim_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


#: What the re-simulated circuit contains. Written by the two HAPPY-PATH
#: fixtures below and by nothing else: this gate stopped certifying a
#: post-layout re-simulation whose subject nothing on the tree names, so a
#: happy-path fixture that omitted the field would be asserting that a
#: comparison of an unattributable circuit still certifies A7 — which is the
#: inverted incentive the rule exists to remove. The FAILING fixtures are left
#: exactly as they were: each already fails for its own value reason, and the
#: gate asks the content question LAST, so adding the field to them would
#: prove nothing and could mask which rule fired.
#:
#: WHERE IT IS WRITTEN MOVED, and the move is the point. These two fixtures
#: used to write the field into `pre_vs_post.json` and ship NO corner artefact
#: at all, because the gate read the derived file FIRST. That is the exact
#: shape the ceiling rule now refuses: `pre_vs_post.json` is authored by the
#: `analog-extraction-resim` SKILL — an AI step — and nothing deterministic
#: writes the field into it, so a fixture that bought a design-bound PASS with
#: it was asserting that an AI-authored claim outranks the deterministic
#: record. The record belongs to the pre-layout corner result, which is also
#: the A4 gate of record's own subject; a comparison cannot be more
#: design-bound than the thing it is compared against.
DESIGN_BOUND = "structure_and_geometry"


def _baseline(project: Path, block: str, design_content=DESIGN_BOUND) -> None:
    """The pre-layout corner result this comparison is measured against."""
    doc = {"corners": [{"process": "TT", "simulator_run": True}]}
    if design_content is not None:
        doc["design_content"] = design_content
    _corners(project, block, doc)


def _resim(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "pre_vs_post.json").write_text(json.dumps(doc))


def _corners(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "corner_results.json").write_text(json.dumps(doc))


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path_specs(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _baseline(tmp_path, "ldo")
    _resim(tmp_path, "ldo", {
        "specs": [
            {"name": "vout", "pre_value": 1.8, "post_value": 1.78,
             "delta_pct": -1.1},
            {"name": "psrr", "pre_value": 60, "post_value": 58,
             "delta_pct": -3.3},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"
    assert rpt["blocks_design_bound_pass"] == 1


def test_happy_path_pre_post_dict(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _baseline(tmp_path, "ldo")
    _resim(tmp_path, "ldo", {
        "pre": {"vout": 1.8, "psrr": 60},
        "post": {"vout": 1.78, "psrr": 58},
    })
    r = _run(tmp_path)
    assert r.returncode == 0


def test_a_derived_claim_cannot_outrank_the_gate_of_records_own_subject(
        tmp_path: Path) -> None:
    """THE CEILING. `pre_vs_post.json` carries the design-bound token — the
    shape the two happy paths above used to have — and the corner artefact it
    is compared against says nothing.

    Measured before the fix: `analog_a4_corner_sweep_check` rc 1 FAIL on this
    tree and THIS gate rc 0 plain PASS with no sentinel, because the chain was
    ordered nearest-first and the nearest link is the one an AI skill authors.
    """
    _block_list(tmp_path, ["ldo"])
    _baseline(tmp_path, "ldo", design_content=None)
    _resim(tmp_path, "ldo", {
        "design_content": DESIGN_BOUND,
        "pre": {"vout": 1.8, "psrr": 60},
        "post": {"vout": 1.78, "psrr": 58},
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_DESIGN_CONTENT_UNDECLARED" in f["rule"]
               for f in rpt["findings"])


def test_a_derived_claim_cannot_upgrade_a_disclosed_default(
        tmp_path: Path) -> None:
    """The subtler half, and the one a mere RE-ORDERING of the chain would
    still have missed: the baseline discloses a library default and the
    derived artefact claims design-bound. It certifies — in the disclosed
    tier, bounded by its baseline — never as a plain pass."""
    _block_list(tmp_path, ["ldo"])
    _baseline(tmp_path, "ldo", design_content="structure_only")
    _resim(tmp_path, "ldo", {
        "design_content": DESIGN_BOUND,
        "pre": {"vout": 1.8, "psrr": 60},
        "post": {"vout": 1.78, "psrr": 58},
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS_STRUCTURE_ONLY"
    assert rpt["blocks_design_bound_pass"] == 0
    assert "STRUCTURE_ONLY:" in r.stdout, r.stdout


def test_a_derived_artefact_may_still_disclose_something_weaker(
        tmp_path: Path) -> None:
    """NEGATIVE CONTROL: it is a CEILING, not a lock. A producer disclosing
    something weaker than its baseline entitled it to claim still certifies,
    in the disclosed tier. Refusing that would make honesty cost again."""
    _block_list(tmp_path, ["ldo"])
    _baseline(tmp_path, "ldo")
    _resim(tmp_path, "ldo", {
        "design_content": "structure_only",
        "pre": {"vout": 1.8, "psrr": 60},
        "post": {"vout": 1.78, "psrr": 58},
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS_STRUCTURE_ONLY"


def test_a_comparison_that_names_no_circuit_does_not_certify(
        tmp_path: Path) -> None:
    """The rule the two happy paths above now state. A post-layout comparison
    of a library topology and one of a design sized to its spec are
    indistinguishable in every other field of `pre_vs_post.json`, and this
    gate is a step of the A-track runner — whatever it certifies is what the
    run record inherits."""
    _block_list(tmp_path, ["ldo"])
    _resim(tmp_path, "ldo", {
        "pre": {"vout": 1.8, "psrr": 60},
        "post": {"vout": 1.78, "psrr": 58},
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_DESIGN_CONTENT_UNDECLARED" in f["rule"]
               for f in rpt["findings"])


def test_a_disclosed_library_default_certifies_in_its_own_tier(
        tmp_path: Path) -> None:
    """Only silence costs. The record is INHERITED from the pre-layout corner
    result here — the artefact this comparison is against, and the one the A4
    gate of record reads — because no producer writes the field into
    `pre_vs_post.json`."""
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        "design_content": "structure_only",
        "corners": [{"process": "TT", "simulator_run": True}]})
    _resim(tmp_path, "ldo", {
        "pre": {"vout": 1.8, "psrr": 60},
        "post": {"vout": 1.78, "psrr": 58},
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS_STRUCTURE_ONLY"
    assert rpt["structure_only_blocks"] == ["ldo"]
    assert rpt["blocks_design_bound_pass"] == 0
    assert "STRUCTURE_ONLY:" in r.stdout, r.stdout


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-extraction-resim"


def test_delta_too_big_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _resim(tmp_path, "ldo", {
        "specs": [
            {"name": "vout", "pre_value": 1.8, "post_value": 1.5,
             "delta_pct": -16.7},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_POSTSIM_DELTA_TOO_BIG" in f["rule"]
               for f in rpt["findings"])


def test_a4_no_simulator_run_forces_a6_fail(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        "corners": [{"process": "TT", "simulator_run": False}]})
    _resim(tmp_path, "ldo", {
        "specs": [
            {"name": "vout", "pre_value": 1.8, "post_value": 1.78,
             "delta_pct": -1.1},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_POSTSIM_NO_A4_SIM" in f["rule"]
               for f in rpt["findings"])


def test_no_specs_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _resim(tmp_path, "ldo", {"comment": "nothing useful"})
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_POSTSIM_NO_SPECS" in f["rule"]
               for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
