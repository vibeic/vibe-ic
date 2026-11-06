"""The DFT steps 11/12/13 cannot name a commercial tool as their blocker.

OWNER DIRECTIVE 2026-09-16, verbatim: "一條開源工具限制 -> what tool? we can fix
all forked tool, so this should be fixed" (RULING R-0915-57).

MEASURED at main bac74aff0 on the shape of SPM run32, which published
`PASS_WITH_OPEN_SOURCE_CONSTRAINTS` deferring

    12: "Post-DFT optimisation (Design Compiler + DFT)"

The chain, every link read off this tree:

  1. The design's own L20 declared NO DFT (`dft_present:false, scan_chains:[],
     bist_mbist:[], jtag_tap:null`), so step 11 stood down on the
     `l_doc_declares` condition it already carried -- correctly, citing L20.
  2. Step 12 therefore had no scan netlist, and `design_one_shot_runner` wrote
     `phase2/stage2/synth/post_dft_not_run.json` carrying
     `capability_flag: cap:post_dft_scan_optimization` -- a claim that the
     OPEN-SOURCE CONTAINER lacks a capability.
  3. `check_step`'s #675 strict sibling promotion honoured the registered flag
     and set `self_skip_disclosed`.
  4. Step id 12 was in `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`, so the step
     entered `oss_blocked_skipped`, the run went FAIL, and the FAIL was
     promoted back out to the deferral tier under a commercial tool's name.

No tool was missing. With no scan chain there is nothing to re-optimise, and
the post-DFT optimisation this flow actually performs is yosys -- run by the
runner itself, eight lines from the marker that claimed it was unavailable.
Design-declared absence had been recorded as a capability gap.

BOTH DIRECTIONS ARE CASES HERE, because a rule that only ever excuses is not a
rule. A design that declares no DFT gets a design-declared N/A citing L20; a
design that DECLARES DFT and produces no scan netlist gets a real MISSING, and
can no longer buy a deferral with any tool's name.

chip-AGNOSTIC: synthetic L20 documents in tmp_path, plus assertions over the
shipped flow yaml and the shipped constants.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

#: The value each L20 field must carry for the design to have declared DFT
#: absent. Step 11 has always used this clause; step 12 now uses the same one.
ABSENT = {"dft_present": False, "scan_chains": [], "bist_mbist": [],
          "jtag_tap": None}

STEP12_OUTPUT = "phase2/stage2/synth/post_dft_netlist.v"




def _R():
    import design_one_shot_runner as R  # noqa: PLC0415
    return R


def _steps():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(FLOW_YAML.read_text(errors="replace"))

    def walk(n):
        if isinstance(n, dict):
            if "id" in n and ("required_outputs" in n or "gate" in n):
                yield n
            for v in n.values():
                yield from walk(v)
        elif isinstance(n, list):
            for v in n:
                yield from walk(v)
    return {str(s["id"]): s for s in walk(doc)}


def _project(tmp_path, fields, marker=None, *, write_l20=True, body=None):
    """A project shaped like the run, with nothing in it but the declaration
    and the runner's own marker."""
    # R-0915-64 — A DESIGN THAT DECLARES NO DFT HAS INPUT DOCUMENTS THAT SAY
    # NOTHING ABOUT DFT, and this fixture used to have no input at all. Since
    # R-0915-64 the declarer requires the design's OWN INPUT to corroborate the
    # L-doc (documents scanned, terms searched, zero hits), because a GENERATED
    # skeleton's initialisers are not an input statement. An empty corpus is a
    # scan with no denominator and declares nothing, so without this the
    # fixture describes a project that cannot exist.
    #
    # ONLY THE FIXTURE MOVES. Every assertion below is untouched: these cases
    # exist to prove the L-DOC half decides, and they still do — the corpus
    # here is deliberately silent about DFT so the L20 fields remain the only
    # thing that varies between them.
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_product_metadata.md").write_text(
        "# Part\nA small core that multiplies two numbers.\n",
        encoding="utf-8")
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if write_l20:
        doc = body if body is not None else {
            "doc_id": "L20", "doc_name": "L20_DFT_SCAN_TOPOLOGY",
            "applicability": "APPLICABLE", "fields": dict(fields)}
        (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(
            doc if isinstance(doc, str) else json.dumps(doc))
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True, exist_ok=True)
    if marker is not None:
        (synth / "post_dft_not_run.json").write_text(json.dumps(
            dict({"verdict": "SKIP", "reason": "(test marker)"}, **marker)))
    return tmp_path


def _is_oss_blocked(F, r) -> bool:
    """The exact predicate `main()` uses to build `oss_blocked_skipped`."""
    return (r.status == "NOT_APPLICABLE" and r.self_skip_disclosed
            and (r.id in F._OPEN_SOURCE_CONTAINER_BLOCKED_STEPS
                 or r.id in F._DFT_SIGNOFF_WITHDRAWN_STEPS))


# ── the three keys are gone, and the tier they left is still alive ────────





# ── step 12 reads the design's own declaration, the same one step 11 reads ─

def test_step_12_carries_step_11s_own_L20_clause_byte_for_byte():
    steps = _steps()
    c11 = (steps["11"].get("condition") or {}).get("l_doc_declares")
    c12 = (steps["12"].get("condition") or {}).get("l_doc_declares")
    assert isinstance(c12, dict), "step 12 carries no l_doc_declares condition"
    assert c12 == c11, (
        "steps 11 and 12 stand down on the SAME declaration; if the clauses "
        "differ, one design can stand 11 down and still owe 12", c11, c12)
    assert c12.get("l_doc") == "L20"
    assert c12.get("all_absent") == ABSENT
    assert steps["12"].get("condition_kind") == "design_dependent"


def test_step_12_still_declares_its_output():
    """The repair is a CONDITION, not a shrunken declaration."""
    outs = [str(o) for o in (_steps()["12"].get("required_outputs") or [])]
    assert outs == [STEP12_OUTPUT], outs




# ── direction 1: the SPM case — declared absence, no commercial excuse ────







# ── direction 2: THE NEGATIVE CONTROL — a design that DOES declare DFT ────







# ── the runner's own predicate, both directions ───────────────────────────



# ── the withdrawn steps keep their VISIBILITY, and lose only the exit ─────





def test_no_producer_still_emits_the_removed_flag():
    """The registry test that scans producer sources would fail-closed on a
    stale literal; this states the same requirement from this ruling's side."""
    hits = []
    for src in PROGRAMS.glob("*.py"):
        for n, line in enumerate(src.read_text(errors="replace").splitlines(),
                                 1):
            if "cap:post_dft_scan_optimization" not in line:
                continue
            # The two files that record WHY it went keep saying its name in
            # prose. A comment is not an emission; a code line is.
            if line.lstrip().startswith("#"):
                continue
            hits.append(f"{src.name}:{n}: {line.strip()}")
    assert hits == [], (
        "the removed flag is still emitted or referenced in code", hits)
