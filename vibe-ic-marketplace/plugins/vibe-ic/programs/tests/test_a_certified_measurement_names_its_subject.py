"""test_a_certified_measurement_names_its_subject.py — the four that still
read a library topology as a designed one.

WHAT WAS ALREADY TRUE, AND WHERE IT STOPPED
===========================================
The ordering below holds at the gate of record and in the consumers wired
before this round:

    design-bound   >   structure-only (disclosed)   >   undisclosed
                                                    >   invented content

The round that established it enumerated rather than sampled: every program in
the tree was run against three trees identical in every artefact except the one
recorded `design_content` value. FOUR came back certifying a library topology
as a designed one, and none of the four read the field at all:

  * the strict PVT-margin gate re-derived the strictest claim in the repo —
    ≥ 27 corners, ≥ 10 % margin on EVERY corner — and answered `[PASS]` rc 0
    with a BYTE-IDENTICAL `--json` summary on the design-bound tree and the
    structure-only one;
  * the Liberty non-degeneracy gate signed off the model INTEGRATION STA WILL
    CONSUME on a tree whose corner artefact records `structure_only`;
  * the post-layout re-sim gate answered `PASS: 2/2 block(s) clean`, identical
    JSON on all three, certifying a re-simulation of a library topology — and
    it is LOAD-BEARING, a step of the A-track runner;
  * the final report rendered the SILENT tree identically to the design-bound
    one. The whole `final_summary.md` differed only in project name and
    timestamp, and the AUDIT DIGEST was the same sha256 — a digest quoted as
    proof that cannot tell a designed run from a silent one.

THE RULES UNDER TEST, with no tool, step or block name in them:

    A gate that certifies a measurement is certifying a claim about the thing
    measured. It must read what that thing is.

    An artefact that declines to say what it contains must not certify the
    step it is the evidence for. Declining is not only omitting the field: a
    record that says it HAS no record is an honest statement of ignorance and
    still not a statement of content.

    A digest quoted beside a set of counts claims to identify the run those
    counts describe. It must move when what the counted artefacts say they
    contain moves — and must NOT move between two runs over one tree.

ORDERING, defended by a control in every section: the certification question
is asked LAST, after the value rules and after the rule the filesystem
decides. "Your 14th corner is 5 % below the floor" and "the artefact you claim
to have measured does not exist" name a deeper cause and answer "what did you
measure?" as a side effect; the reverse is not true. A reader sent to fix the
disclosure of a run that is already failing on its numbers fixes the wrong
thing first.

Every assertion here is written so that it fails on a wrong CERTIFICATION or a
wrong RENDERING — never on a missing symbol.

Every fixture is synthetic: invented block names, library nominal geometries,
no design content, no PDK SKU, no part number.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

MARGIN_GATE = PROGRAMS / "analog_corner_margin_check.py"
LIBERTY_GATE = PROGRAMS / "analog_liberty_nonzero_delay_check.py"
A7_GATE = PROGRAMS / "analog_a7_post_layout_resim_check.py"
FINAL_REPORT = PROGRAMS / "final_report_generate.py"

STRUCTURE_ONLY = "structure_only"
SIZED = "structure_and_geometry"
#: The token a producer writes when the upstream shipped no record. It is a
#: non-empty string, so a rule keyed on "is the field present?" accepts it —
#: which is exactly how silence comes back under a new name.
NO_RECORD = "undeclared"

BLOCKS = ("blk_alpha", "blk_beta")


# ── the tree, and the ONE field that varies across it ──────────────────────

def _corners(margin_pct: float = 22.5) -> list:
    """A full 27-corner PVT cube (3 process × 3 temp × 3 voltage), every
    corner comfortably above the 10 % margin floor, so nothing in this fixture
    fails for a VALUE reason and every assertion below is about content."""
    out = []
    for p in ("ss", "tt", "ff"):
        for t in (-40, 27, 125):
            for v in (1.62, 1.80, 1.98):
                out.append({"name": f"{p}_{t}c_{v}v", "simulator_run": True,
                            "process": p, "temp_c": t, "vdd_v": v,
                            "margin_pct": margin_pct})
    return out


_LIB = """library({b}_lib) {{
  cell({b}) {{
    area : 10000 ;
    cell_rise : 0.42 ;
    cell_fall : 0.39 ;
    cell_leakage_power : 0.0031 ;
  }}
}}
"""


def _project(root: Path, design_content, blocks=BLOCKS,
             margin_pct: float = 22.5, corner_count: int = 27) -> Path:
    """A complete analog tree carrying every artefact the four consumers read.
    `design_content` is the ONLY thing any test varies.

    `None` builds THE PRE-DISCLOSURE SHAPE, and it is built by DELETION on
    purpose: the whole disclosure set goes — the upstream sidecar, the
    `netlist_provenance` claim, `netlist_source`, `design_traceable`,
    `design_content` and its meaning. That is what an artefact written before
    the fields existed looks like, and what a stale one looks like.

    Everything a value rule could catch is deliberately CLEAN: 27 corners, a
    22.5 % margin on every one, a non-degenerate Liberty, a post-layout drift
    of 1 %, and the upstream netlist present on disk. So no assertion below
    can be satisfied by a gate failing for some other reason.
    """
    adir = root / "phase3" / "analog"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": b, "type": "ldo"} for b in blocks]}, indent=2))
    for b in blocks:
        d = adir / b
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps({"block": b, "specs": []}))
        (d / "topology.md").write_text("# topology\nlibrary topology\n")
        (d / f"{b}.sp").write_text(
            f"* {b} — synthetic block netlist for this fixture\n"
            f"* every geometry below is a library nominal, on purpose\n"
            f".subckt {b} vdd vss vin vout\n"
            f"xm1 vout vin vss vss nch w=8 l=1\n"
            f".ends {b}\n")
        if design_content is not None:
            (d / "netlist_provenance.json").write_text(json.dumps({
                "block": b,
                "_provenance": {"producer": "synthetic-fixture",
                                "design_content": design_content,
                                "spec_bound_params": [],
                                "library_nominal_params": ["m1.w"]}},
                indent=2))
        corners = _corners(margin_pct)[:corner_count]
        doc = {
            "block": b, "_provenance": "real_ngspice",
            "simulator": "ngspice (docker)",
            "corners_executed": len(corners),
            "full_pvt_sweep_executed": True,
            "total_corners": len(corners),
            "corners": corners,
            "spec_results": [{"name": "vout", "status": "PASS"}],
        }
        if design_content is not None:
            doc["netlist_provenance"] = "a3_netlist"
            doc["netlist_source"] = f"phase3/analog/{b}/{b}.sp"
            doc["design_traceable"] = True
            doc["design_content"] = design_content
            doc["design_content_meaning"] = "see the producer record"
        (d / "corner_results.json").write_text(json.dumps(doc, indent=2))
        (d / "pre_vs_post.json").write_text(json.dumps({
            "block": b,
            "specs": [{"name": "vout", "pre_value": 1.80, "post_value": 1.78},
                      {"name": "iq", "pre_value": 20.0, "post_value": 20.2}],
        }, indent=2))
        hm = adir / "hardmacro" / b
        hm.mkdir(parents=True, exist_ok=True)
        # Keep the subject/tier controls clean under the existing native loader.
        from test_analog_liberty_nonzero_delay_check import _native_measurement
        _native_measurement(root, b, ("nmos",), 0.0031e-6)
        (hm / f"{b}.lib").write_text(
            _LIB.format(b=b).replace("{", '{ leakage_power_unit : "1uW";', 1))
    return root


def _run(prog: Path, project: Path, *args) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True)


def _both(cp) -> str:
    return (cp.stdout or "") + (cp.stderr or "")


def _json_summary(prog: Path, project: Path, out: Path) -> str:
    """The `--json` document a machine consumer reads, as text. Two trees that
    a reader can tell apart from the one line but not from this document are
    only half-distinguished."""
    _run(prog, project, "--json", str(out))
    return out.read_text()


# ═══ 1. THE STRICTEST PVT CLAIM IN THE REPO ════════════════════════════════











def _mixed(root: Path) -> Path:
    """One design-bound block and one library-default block in one project —
    the shape a real run reaches first, and the one a per-project verdict word
    cannot describe on its own."""
    project = _project(root, SIZED)
    d = project / "phase3" / "analog" / "blk_beta"
    for fname, keys in (("corner_results.json", ("design_content",)),
                        ("netlist_provenance.json",
                         ("_provenance", "design_content"))):
        p = d / fname
        doc = json.loads(p.read_text())
        tgt = doc
        for k in keys[:-1]:
            tgt = tgt[k]
        tgt[keys[-1]] = STRUCTURE_ONLY
        p.write_text(json.dumps(doc, indent=2))
    return project


@pytest.mark.parametrize("gate", [LIBERTY_GATE, A7_GATE],
                         ids=lambda g: g.stem)
def test_one_library_default_block_does_not_erase_a_design_bound_one(
        gate, tmp_path):
    """The tier goes on the verdict word only when there is NO design-bound
    result to report — the same ranking the sibling corner gates already use.

    Both halves matter and they pull in opposite directions. If the word
    flipped, one library-default block would describe a whole project that
    also closed a designed one. If the disclosure were dropped because the
    word stayed `PASS`, the library-default block would vanish — which is the
    original defect, restricted to mixed projects.
    """
    cp = _run(gate, _mixed(tmp_path))
    out = _both(cp)
    assert cp.returncode == 0, out
    # The bare sentinel line is `STRUCTURE_ONLY: …`, which does not contain
    # the tier WORD, so this substring test reads the verdict and not the
    # disclosure.
    assert "PASS_STRUCTURE_ONLY" not in out, (
        f"one library-default block out of two took the whole project's "
        f"verdict word, hiding that a design-bound block also cleared:\n{out}")
    sentinel = [ln for ln in out.splitlines()
                if ln.startswith("STRUCTURE_ONLY:")]
    assert sentinel, (
        f"the library-default block was not disclosed at all because the "
        f"project as a whole read PASS:\n{out}")
    assert "blk_beta" in sentinel[0] and "blk_alpha" not in sentinel[0], (
        f"the disclosure does not name the subset it applies to: "
        f"{sentinel[0]}")


# ═══ 2. THE MODEL INTEGRATION STA WILL CONSUME ═════════════════════════════

def test_the_liberty_gate_names_what_the_delays_model(tmp_path):
    """A non-zero delay taken from a library nominal is a real number about a
    library nominal. Pre-fix this gate reported `corner provenance=
    real_ngspice` — true of the simulator, silent about the subject, which is
    the defect this whole track started from, one field along."""
    bound = _run(LIBERTY_GATE, _project(tmp_path / "d", SIZED))
    so = _run(LIBERTY_GATE, _project(tmp_path / "s", STRUCTURE_ONLY))
    silent = _run(LIBERTY_GATE, _project(tmp_path / "n", None))

    assert bound.returncode == 0, _both(bound)
    assert "[PASS]" in bound.stdout, bound.stdout

    assert so.returncode == 0, _both(so)
    assert "[PASS_STRUCTURE_ONLY]" in so.stdout, (
        f"a Liberty modelling a LIBRARY TOPOLOGY was signed off for "
        f"integration STA in the same tier as a designed macro:\n{so.stdout}")
    assert "STRUCTURE_ONLY:" in _both(so)

    assert silent.returncode == 1, (
        f"the Liberty integration STA will consume was signed off "
        f"(rc={silent.returncode}) with nothing anywhere saying what circuit "
        f"its delays model")
    assert "LIB_SUBJECT_UNDECLARED" in _both(silent)


def test_a_liberty_with_no_corner_artefact_at_all_does_not_certify(tmp_path):
    """The strongest form of the same silence: the artefact that would say
    what these delays describe does not exist. Deleting the record is not a
    way through the rule that reads it."""
    root = _project(tmp_path, SIZED)
    for b in BLOCKS:
        (root / "phase3" / "analog" / b / "corner_results.json").unlink()
        (root / "phase3" / "analog" / b / "netlist_provenance.json").unlink()
    cp = _run(LIBERTY_GATE, root)
    assert cp.returncode == 1, (
        f"a Liberty was signed off for STA with no corner artefact on disk to "
        f"say what it models (rc={cp.returncode})")
    assert "LIB_SUBJECT_UNDECLARED" in _both(cp)


def test_a_zero_delay_liberty_is_still_a_zero_delay_liberty(tmp_path):
    """ORDERING CONTROL. The documented defect this gate exists for — every
    delay 0, so STA passes vacuously — is diagnosed as itself even on a tree
    that also says nothing about its subject. Holds pre-fix and post-fix."""
    root = _project(tmp_path, None)
    for b in BLOCKS:
        (root / "phase3" / "analog" / "hardmacro" / b / f"{b}.lib").write_text(
            f"library({b}_lib) {{\n  cell({b}) {{\n"
            f"    cell_rise : 0.0 ;\n    cell_fall : 0 ;\n  }}\n}}\n")
    cp = _run(LIBERTY_GATE, root)
    assert cp.returncode == 1
    out = _both(cp)
    assert "LIB_ZERO_DELAY" in out, out
    assert "LIB_SUBJECT_UNDECLARED" not in out, out


# ═══ 3. THE LOAD-BEARING ONE — A STEP OF THE A-TRACK RUNNER ════════════════

def test_the_post_layout_resim_gate_names_what_it_resimulated(tmp_path):
    """Pre-fix: `PASS: 2/2 block(s) clean`, identical JSON on all three trees,
    certifying a post-layout re-simulation of a library topology."""
    bound = _run(A7_GATE, _project(tmp_path / "d", SIZED))
    so = _run(A7_GATE, _project(tmp_path / "s", STRUCTURE_ONLY))
    silent = _run(A7_GATE, _project(tmp_path / "n", None))

    assert bound.returncode == 0, _both(bound)
    assert bound.stdout.startswith("PASS:"), bound.stdout

    assert so.returncode == 0, _both(so)
    assert "PASS_STRUCTURE_ONLY:" in so.stdout, (
        f"a post-layout re-simulation OF A LIBRARY TOPOLOGY was certified in "
        f"the same tier as a design's:\n{so.stdout}")
    assert "STRUCTURE_ONLY:" in _both(so)

    assert silent.returncode == 1, (
        f"a post-layout re-simulation certified (rc={silent.returncode}) with "
        f"nothing anywhere saying what circuit was re-simulated")
    assert "A7_DESIGN_CONTENT_UNDECLARED" in _both(silent)


def test_the_a_track_runner_records_the_tier_for_this_step(tmp_path):
    """THE LOAD-BEARING HALF. This gate is a step of `analog_one_shot_runner`,
    so whatever it certifies is what the run record inherits. The runner reads
    the disclosure sentinel the same way it already reads the vacuous one, and
    the step's extras must carry the content AND the artefact it was read
    from: a step recorded PASS_STRUCTURE_ONLY with empty extras is the same
    defect one layer down."""
    import analog_one_shot_runner as R

    project = _project(tmp_path, STRUCTURE_ONLY, blocks=("blk_alpha",))
    res = R.step_for_block(project, {"name": "blk_alpha", "type": "ldo"},
                           "A7_post_layout_resim")
    assert res.status == "PASS_WITH_WAIVERS", (res.status, res.detail)
    assert res.extras.get("design_content") == STRUCTURE_ONLY, res.extras
    assert res.extras.get("structure_only") is True, res.extras
    assert (res.extras.get("design_content_source") or "").endswith(
        "corner_results.json"), res.extras


def test_the_runner_records_the_content_of_a_design_bound_resim_too(tmp_path):
    """The other half of the same wiring, and the negative control on the
    tier: this is a DISCLOSURE requirement, not a blanket refusal, so a
    design-bound re-sim must still be a plain `PASS`.

    It also fails pre-fix, on the second assertion rather than the first: the
    runner recorded the right STATUS and empty EXTRAS, so its own run record
    said nothing about what the step contained even when the tree said it
    plainly.
    """
    import analog_one_shot_runner as R

    project = _project(tmp_path, SIZED, blocks=("blk_alpha",))
    res = R.step_for_block(project, {"name": "blk_alpha", "type": "ldo"},
                           "A7_post_layout_resim")
    assert res.status == "PASS", (res.status, res.detail)
    assert res.extras.get("design_content") == SIZED, res.extras
    assert res.extras.get("structure_only") is False, res.extras


def test_a_drift_over_budget_is_still_a_drift_failure(tmp_path):
    """ORDERING CONTROL. A comparison whose post-layout drift blows the budget
    is diagnosed as that, even on a tree that also says nothing about what was
    compared. Holds pre-fix and post-fix."""
    root = _project(tmp_path, None)
    for b in BLOCKS:
        (root / "phase3" / "analog" / b / "pre_vs_post.json").write_text(
            json.dumps({"specs": [{"name": "vout", "pre_value": 1.80,
                                   "post_value": 1.40}]}))
    cp = _run(A7_GATE, root)
    assert cp.returncode == 1
    out = _both(cp)
    assert "A7_POSTSIM_DELTA_TOO_BIG" in out, out
    assert "A7_DESIGN_CONTENT_UNDECLARED" not in out, out


def test_a_pre_layout_baseline_that_never_ran_is_still_that(tmp_path):
    """The other ordering control, and the one the filesystem-adjacent rule
    owns: you cannot have a credible post-layout re-sim if pre-layout SPICE
    never ran, and THAT is the finding — it answers "what did you
    re-simulate?" as a side effect."""
    root = _project(tmp_path, None)
    for b in BLOCKS:
        p = root / "phase3" / "analog" / b / "corner_results.json"
        doc = json.loads(p.read_text())
        for c in doc["corners"]:
            c["simulator_run"] = False
        p.write_text(json.dumps(doc))
    cp = _run(A7_GATE, root)
    assert cp.returncode == 1
    out = _both(cp)
    assert "A7_POSTSIM_NO_A4_SIM" in out, out
    assert "A7_DESIGN_CONTENT_UNDECLARED" not in out, out


# ═══ 4. THE DOCUMENT A REVIEWER READS FIRST ════════════════════════════════



















if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
