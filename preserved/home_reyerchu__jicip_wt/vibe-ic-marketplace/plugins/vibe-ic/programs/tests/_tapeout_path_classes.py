#!/usr/bin/env python3
"""Design classes for the two tape-out paths, built by the flow's OWN producers.

WHY A BUILDER AND NOT A FIXTURE TREE OF HAND-WRITTEN FILES
==========================================================
The router files this flow decides a tape-out path on --
``input/submission_template/slots/*.yaml``, ``NO_TEMPLATE.txt`` and
``SELF_TAPEOUT.txt`` -- are written by step 0.5ic's two programs and by nothing
else. A test that hand-writes them is asserting what the author BELIEVES step
0.5ic does, and the whole class of defect this package exists for is a step
conditioned on the wrong thing: the belief and the behaviour were never the
same, and only the belief was ever tested.

So every class below is produced by invoking, through their real CLIs and in
the order step 0.5ic declares them:

    submission_template_ingest    the OPERATOR's half -- what was published
    tapeout_declaration_gen       the DESIGN's half -- what it says about itself

Nothing here writes a router file. If a class comes out carrying no router at
all, that IS the measured answer for that class and it is reported as such.

WHAT A CLASS IS
===============
Three independent facts, and the flow can distinguish all three:

    deliverable      DIE / HARDMACRO / undeclared  -- the design's own answer
    template         INGESTED / ABSENT / NOT_ATTEMPTED -- the operator's half
    pdk              whether the shuttle registry names a LIVE precheck for it

They are independent: a die can be on a shuttle or tape itself out, an IP can
have looked for a template or (normally) never have, and either can sit on a
PDK with or without a live external authority. The product is the matrix.

CHIP-AGNOSTIC. The only process names here are ``gf180mcuD`` and ``sky130A``,
both OPEN PDKs, and they appear because the shuttle registry's LIVE / RETIRED
split is the fact under test: one PDK must resolve to a live shuttle and one
must not, or the "PDK ships no shuttle precheck" class cannot be built at all.
The slot geometry is synthetic and carries no vendor, SKU or node.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

PROGRAMS = Path(__file__).resolve().parent.parent

# ── the three states a path step can be in, and they are NOT interchangeable ──
#
# MISSING is the whole reason this vocabulary is three words and not two. A step
# that is absent because nobody wired it and a step that is skipped because its
# condition is legitimately unmet read IDENTICALLY in every summary this repo
# has ever printed, and that is the mechanism every defect in this area was
# hiding behind. They are different words here and a cell may never carry the
# wrong one.
RUNS = "RUNS"
SKIPPED_CONDITION = "SKIPPED-CONDITION"
MISSING = "MISSING"
STATES: Tuple[str, ...] = (RUNS, SKIPPED_CONDITION, MISSING)

#: A slot file the operator's template ships. Synthetic; the geometry is
#: self-consistent (die == core grown by the ring width on all four sides) so a
#: class built on it fails for the reason under test and never for its fixture.
SLOT_NAME = "slot_a"
SLOT_YAML = """\
DIE_AREA: [0, 0, 1000, 2000]
CORE_AREA: [26, 26, 974, 1974]
SEAL_RING_WIDTH: 26
FP_SIZING: absolute
pads: [pad_n0, pad_n1, pad_s0]
"""

#: Long enough to clear ``MIN_ABSENT_CONDITION_REASON``; the floor itself is
#: read from the flow's own module by the programs that enforce it, never
#: copied here.
IP_REASON = ("This design is delivered as a hardmacro for an integrator to "
             "place and is never submitted to a shuttle operator.")
DIE_REASON = ("This design is fabricated as a die of its own and no shuttle "
              "operator publishes a template for the run it targets.")

#: The PDK whose registry entry names a LIVE shuttle precheck, and one whose
#: does not. Resolved through the registry at import time by
#: ``pdk_ships_live_shuttle`` below, so a registry change is measured rather
#: than remembered.
PDK_WITH_LIVE_SHUTTLE = "gf180mcuD"
PDK_WITHOUT_LIVE_SHUTTLE = "sky130A"


def pdk_ships_live_shuttle(pdk: Optional[str]) -> bool:
    """Ask the registry, never a literal in this file."""
    if not pdk:
        return False
    sys.path.insert(0, str(PROGRAMS))
    import tapeout_readiness_check as TRC  # noqa: E402
    return TRC.shuttle_for_pdk(pdk) is not None


@dataclass(frozen=True)
class DesignClass:
    """One design class, and the state every path step must be in for it.

    ``expected`` is the CONTRACT, written from the argument in ``why``. It is
    never derived from the flow, because a table derived from the thing under
    test cannot disagree with it.
    """

    name: str
    pdk: Optional[str]
    deliverable: Optional[str]          # "DIE" / "HARDMACRO" / None
    template: Optional[str]             # path handed to the ingest half
    reason: Optional[str]
    expected: Dict[str, str]
    why: str
    #: True when step 0.5ic's OWN gate must refuse this tree. Every class that
    #: ends with no router file at all carries this: the flow yaml's promise is
    #: that a "someone forgot" run is caught by 0.5ic refusing, and not left to
    #: be inferred from a downstream skip. A class that asserts the skips
    #: without asserting the refusal has tested only the half that is easy.
    zero_five_ic_gate_must_refuse: bool = False
    #: True when the class is built by running NEITHER half of 0.5ic.
    skip_producers: bool = False


def _run(args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, timeout=300)


def build(root: Path, dc: DesignClass, template_root: Optional[Path] = None
          ) -> Dict[str, object]:
    """Materialise *dc* under *root* and report what the producers wrote.

    Returns the two producers' return codes and the router files that exist
    afterwards, so a caller can state the measured route rather than assume it.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(exist_ok=True)
    if dc.pdk:
        # The path `declared_pdk_is_the_pdk_used_check.declared_target` probes
        # last and the only one that needs no Phase-1 run behind it.
        (root / "input" / "project.json").write_text(
            json.dumps({"pdk": dc.pdk}) + "\n")

    out: Dict[str, object] = {"ingest_rc": None, "declaration_rc": None}
    if not dc.skip_producers:
        argv = [str(PROGRAMS / "submission_template_ingest.py"), str(root)]
        tmpl = dc.template
        if tmpl == "<ingested>":
            assert template_root is not None
            tmpl = str(template_root)
            argv += ["--slot", SLOT_NAME]
        if tmpl:
            argv += ["--template", tmpl]
        if dc.reason:
            argv += ["--no-template-reason", dc.reason]
        r1 = _run(argv)
        out["ingest_rc"] = r1.returncode
        out["ingest_stderr"] = r1.stderr[-2000:]

        answers = {} if dc.deliverable is None else {
            "deliverable": dc.deliverable}
        af = root / "_answers.json"
        af.write_text(json.dumps(answers) + "\n")
        r2 = _run([str(PROGRAMS / "tapeout_declaration_gen.py"), str(root),
                   "--answers", str(af)])
        out["declaration_rc"] = r2.returncode
        out["declaration_stderr"] = r2.stderr[-2000:]

    st = root / "input" / "submission_template"
    routers = []
    if st.is_dir():
        if any((st / "slots").glob("*.yaml")) if (st / "slots").is_dir() else False:
            routers.append("slots/*.yaml")
        for nm in ("NO_TEMPLATE.txt", "SELF_TAPEOUT.txt"):
            if (st / nm).is_file():
                routers.append(nm)
    out["routers"] = tuple(routers)
    return out


def make_template(root: Path) -> Path:
    """An operator template with one slot, on disk, for the ingest half."""
    slots = root / "slots"
    slots.mkdir(parents=True, exist_ok=True)
    (slots / f"{SLOT_NAME}.yaml").write_text(SLOT_YAML)
    return root


# ─────────────────────────────────────────────────────────────────────────────
# THE CLASSES
#
# The expectation in each row is an argument about SILICON, not about the yaml:
#
#   a pad ring and a seal ring are properties of being a DIE. A die that is
#   fabricated must be bondable and must carry its scribe protection whether or
#   not a shuttle operator published a template for it -- the operator's
#   template supplies the GEOMETRY those steps consume, and its absence changes
#   WHERE the geometry comes from (0.5ic's own declaration, whose 2B_pad_ring
#   and 2C_seal_ring sections name `pad_ring_gen` and the die-finishing step as
#   their consumers), never WHETHER the step runs.
#
#   an IP is delivered as a hardmacro and placed by somebody else. It has no
#   die of its own, so it correctly has no pad ring, no seal ring and no
#   tape-out precheck; its terminal is the hardmacro kit.
# ─────────────────────────────────────────────────────────────────────────────
_CHIP = {"0.5ic": RUNS, "15.5ic": RUNS, "26.5ic": RUNS,
         "37.5ic": RUNS, "37.5ip": SKIPPED_CONDITION}
_IP = {"0.5ic": RUNS, "15.5ic": SKIPPED_CONDITION,
       "26.5ic": SKIPPED_CONDITION, "37.5ic": SKIPPED_CONDITION,
       "37.5ip": RUNS}
_NO_ROUTE = {"0.5ic": RUNS, "15.5ic": SKIPPED_CONDITION,
             "26.5ic": SKIPPED_CONDITION, "37.5ic": SKIPPED_CONDITION,
             "37.5ip": SKIPPED_CONDITION}

CLASSES: Tuple[DesignClass, ...] = (
    DesignClass(
        name="self_tapeout_pdk_ships_no_precheck",
        pdk=PDK_WITHOUT_LIVE_SHUTTLE, deliverable="DIE",
        template="/nonexistent/operator_template", reason=DIE_REASON,
        expected=dict(_CHIP),
        why="A die doing its own tape-out on a PDK whose registry names no "
            "LIVE shuttle precheck. It is a die: it needs a pad ring and a "
            "seal ring. Its tape-out precheck runs with ONE arm -- ours -- "
            "and one fewer arm is not a different route.",
    ),
    DesignClass(
        name="self_tapeout_pdk_ships_a_precheck",
        pdk=PDK_WITH_LIVE_SHUTTLE, deliverable="DIE",
        template="/nonexistent/operator_template", reason=DIE_REASON,
        expected=dict(_CHIP),
        why="The same die on a PDK whose registry DOES name a live shuttle "
            "precheck, with that operator's template never fetched. Same "
            "path, same steps; what differs is that 37.5ic's operator arm is "
            "NOT_DETERMINED rather than legitimately absent.",
    ),
    DesignClass(
        name="shuttle_chip_slots_present",
        pdk=PDK_WITH_LIVE_SHUTTLE, deliverable="DIE",
        template="<ingested>", reason=None,
        expected=dict(_CHIP),
        why="The operator's template was fetched and a slot declared, so the "
            "chip path runs with BOTH arms.",
    ),
    DesignClass(
        name="shuttle_chip_template_not_fetched",
        pdk=PDK_WITH_LIVE_SHUTTLE, deliverable="DIE",
        template="/nonexistent/operator_template", reason=DIE_REASON,
        expected=dict(_CHIP),
        why="A chip that went looking for the operator's template and did not "
            "find it. The design is unchanged -- still a die -- so every "
            "chip-path step is still owed. This is the class the whole area "
            "was conditioned wrongly for.",
    ),
    DesignClass(
        name="ip_hardmacro_searched_and_declared",
        pdk=PDK_WITHOUT_LIVE_SHUTTLE, deliverable="HARDMACRO",
        template="/nonexistent/operator_template", reason=IP_REASON,
        expected=dict(_IP),
        why="The IP terminal. No die, so no pad ring, no seal ring and no "
            "tape-out precheck; it is delivered as a macro.",
    ),
    DesignClass(
        name="ip_hardmacro_never_looked_for_a_template",
        pdk=PDK_WITHOUT_LIVE_SHUTTLE, deliverable="HARDMACRO",
        template=None, reason=None,
        expected=dict(_NO_ROUTE),
        zero_five_ic_gate_must_refuse=True,
        why="An IP that never went looking for a shuttle template -- which is "
            "the ordinary case for an IP. No router file is written, so its "
            "OWN terminal (37.5ip) is skipped along with everything else. "
            "That skip is only honest because 0.5ic's gate refuses the tree; "
            "this row asserts BOTH halves, because the skip alone reads "
            "exactly like a correct not-applicable.",
    ),
    DesignClass(
        name="deliverable_undeclared",
        pdk=PDK_WITH_LIVE_SHUTTLE, deliverable=None,
        template=None, reason=None,
        expected=dict(_NO_ROUTE),
        zero_five_ic_gate_must_refuse=True,
        why="0.5ic ran and the design said nothing about what it is. No route "
            "is selected, on purpose -- a design that has not said what it is "
            "must not be given a path. Every terminal skips, and 0.5ic's own "
            "gate is the thing that stops that being a silent pass.",
    ),
    DesignClass(
        name="zero_five_ic_never_ran",
        pdk=PDK_WITH_LIVE_SHUTTLE, deliverable=None,
        template=None, reason=None, skip_producers=True,
        expected=dict(_NO_ROUTE),
        zero_five_ic_gate_must_refuse=True,
        why="Nobody ran step 0.5ic at all. Every path step skips by condition "
            "-- the state that is indistinguishable from a correct "
            "not-applicable unless 0.5ic itself refuses.",
    ),
)

CLASSES_BY_NAME: Dict[str, DesignClass] = {c.name: c for c in CLASSES}
