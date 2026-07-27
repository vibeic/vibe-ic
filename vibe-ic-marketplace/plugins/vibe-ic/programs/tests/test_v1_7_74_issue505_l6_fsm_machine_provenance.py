"""ORGANIC #505 — L6 merged two different state machines into one flat
``fsm_states[]`` and the scaffold gate then counted them as one machine.

Observed on a staged RV-CPU corpus at v1.7.73: ``L6_CONTROL_LOGIC.json``
carried ELEVEN states — ten members of a ``typedef enum`` declared by the
staged HDL package (the controller's machine, ``extraction_strategy =
hdl_typedef_enum_state_v1_7_72``, ``declared_type`` present) plus ONE
state harvested by the prose walker from a single passing sentence in the
load-store-unit chapter ("...until the state machine returns to IDLE"),
which describes a DIFFERENT block's machine and carries no
``declared_type``. ``l6_fsm_scaffold_actionable_check`` reported
``derived_states`` of length 11 and asserted one eleven-state machine
where the input declares a ten-state one and mentions a state of a
second.

A closed enum is the strongest completeness evidence Phase 1 can have.
Diluting it with an inference destroys that property: downstream can no
longer tell "these ten ARE the machine" from "these eleven names were
seen somewhere", and every per-state / coverage / transition-completeness
check inherits the wrong denominator.

Fix (chip-AGNOSTIC — grouping comes from extractor provenance ONLY, never
from a design name, a state-name allow-list or a document-name pattern):

  (1) every emitted state carries ``fsm_machine``, derived from what its
      own extractor knew — ``declared_type`` for the enum harvester, the
      SOURCE DOCUMENT for the inference tiers. No name matching across
      the two sources.
  (2) L6 emits ``fsm_machines[]``: one record per machine. A record whose
      enum declared it is ``closed: true`` and its member list is taken
      from the DECLARATION, so an inferred state can never add a member
      to it.
  (3) a name collision no longer lets an inference SILENTLY REPLACE a
      declared member: the declaration wins, the entry is re-attributed
      to the declaring enum and the inferred evidence is retained under
      ``corroborating_evidence``.
  (4) the gate groups before it reasons and states its findings per
      machine.

NOTHING is dropped: the prose-derived state is real information about a
real (different) machine and stays in ``fsm_states[]``, attributed.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

GATE = PLUGIN / "programs" / "l6_fsm_scaffold_actionable_check.py"

# A staged HDL package declaring a NAMED, CLOSED controller state set.
# Synthetic, vendor-neutral member names.
PKG_SV = """
package core_pkg;
  typedef enum logic [3:0] {
    ST_RESET,
    ST_BOOT,
    ST_WAIT_SLEEP,
    ST_SLEEP,
    ST_FIRST_FETCH,
    ST_DECODE,
    ST_FLUSH,
    ST_IRQ_TAKEN
  } ctrl_fsm_e;
endpackage
"""

# A DIFFERENT block's chapter, mentioning a state of ITS OWN machine in
# passing. `IDLE` is not a member of `ctrl_fsm_e`.
LSU_RST = """
Load-Store Unit
===============

The LSU is busy handling a request; the core stalls until the state
machine returns to IDLE and the response has been accepted.
"""


def _gen_l6(docs):
    proj = Path(tempfile.mkdtemp())
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = P.gen_l6_control_logic(proj, docs)
    return proj, json.loads(Path(res.path).read_text(encoding="utf-8"))


def _by_name(l6):
    return {s.get("name"): s for s in (l6.get("fsm_states") or [])
            if isinstance(s, dict)}


def _machine(l6, machine_id):
    for m in l6.get("fsm_machines") or []:
        if m.get("machine_id") == machine_id:
            return m
    return None


# ---------------------------------------------------------------------------
# (1) states carry which machine they belong to
# ---------------------------------------------------------------------------

def test_states_carry_their_machine_from_their_own_provenance():
    _, l6 = _gen_l6({"core_pkg.sv": PKG_SV, "lsu.rst": LSU_RST})
    states = _by_name(l6)
    assert "IDLE" in states, (
        "the prose-derived state must be RETAINED, not deleted to make a "
        f"count come out right: {sorted(states)}")
    assert "ST_DECODE" in states, sorted(states)

    # The enum harvester knew the declaring type name.
    assert states["ST_DECODE"]["fsm_machine"] == "ctrl_fsm_e"
    # The prose walker knew only the document it read.
    assert states["IDLE"]["fsm_machine"] != "ctrl_fsm_e"
    assert "lsu.rst" in states["IDLE"]["fsm_machine"], states["IDLE"]

    # Two machines, not one.
    assert l6.get("fsm_machine_count") == 2, l6.get("fsm_machines")


def test_closed_enum_member_list_is_exactly_the_declaration():
    _, l6 = _gen_l6({"core_pkg.sv": PKG_SV, "lsu.rst": LSU_RST})
    m = _machine(l6, "ctrl_fsm_e")
    assert m is not None, l6.get("fsm_machines")
    assert m["closed"] is True
    assert m["states"] == ["ST_RESET", "ST_BOOT", "ST_WAIT_SLEEP",
                           "ST_SLEEP", "ST_FIRST_FETCH", "ST_DECODE",
                           "ST_FLUSH", "ST_IRQ_TAKEN"], m["states"]
    # THE defect: the prose mention must not be a member of the machine
    # the typedef enum declares.
    assert "IDLE" not in m["states"], (
        "a prose mention added an eleventh member to a closed enum")
    assert m["state_count"] == 8


def test_prose_machine_is_open_and_keeps_its_state():
    _, l6 = _gen_l6({"core_pkg.sv": PKG_SV, "lsu.rst": LSU_RST})
    prose = [m for m in l6["fsm_machines"] if not m["closed"]]
    assert len(prose) == 1, l6["fsm_machines"]
    assert prose[0]["states"] == ["IDLE"], prose[0]
    assert prose[0]["declared_type"] is None
    assert "lsu.rst" in (prose[0]["source"] or ""), prose[0]


# ---------------------------------------------------------------------------
# (2) a closed enum stays closed — in BOTH directions
# ---------------------------------------------------------------------------

def test_prose_mention_never_adds_a_member_to_a_declared_machine():
    """Every state attributed to a closed machine must be a member the
    declaration actually names."""
    _, l6 = _gen_l6({"core_pkg.sv": PKG_SV, "lsu.rst": LSU_RST})
    declared = set(_machine(l6, "ctrl_fsm_e")["states"])
    attributed = {s["name"] for s in l6["fsm_states"]
                  if s.get("fsm_machine") == "ctrl_fsm_e"}
    assert attributed <= declared, attributed - declared


def test_prose_mention_of_a_declared_member_does_not_steal_it():
    """A document that MENTIONS a name the enum DECLARES must not leave
    that member attributed to the document.

    Before the fix the enum harvester skipped any member name an
    inference tier had already emitted, so the declared member kept the
    inferred attribution and the closed machine effectively lost it."""
    collide = LSU_RST.replace("returns to IDLE", "returns to ST_DECODE")
    _, l6 = _gen_l6({"core_pkg.sv": PKG_SV, "lsu.rst": collide})
    st = _by_name(l6).get("ST_DECODE")
    assert st is not None, sorted(_by_name(l6))
    assert st.get("declared_type") == "ctrl_fsm_e", st
    assert st.get("fsm_machine") == "ctrl_fsm_e", st
    assert st.get("extraction_strategy") == "hdl_typedef_enum_state_v1_7_72"
    # The declared machine is still complete.
    assert _machine(l6, "ctrl_fsm_e")["states"].count("ST_DECODE") == 1
    assert len(_machine(l6, "ctrl_fsm_e")["states"]) == 8
    # And the inferred evidence is retained, not discarded.
    corr = st.get("corroborating_evidence") or []
    assert any("lsu.rst" in str(c) for c in corr), st


def test_pipeline_stage_of_the_same_name_does_not_suppress_the_member():
    """A pipeline stage and an enum member that share a name are
    different objects in different lists. The stage must neither absorb
    the declaration nor keep it out of the closed machine."""
    pkg = PKG_SV.replace("ST_FLUSH", "MEM")
    doc = ("Pipeline\n========\n\n"
           "The MEM stage accesses data memory.\n")
    _, l6 = _gen_l6({"core_pkg.sv": pkg, "pipe.rst": doc})
    machine = _machine(l6, "ctrl_fsm_e")
    assert machine is not None and "MEM" in machine["states"], machine
    fsm = _by_name(l6)
    assert fsm.get("MEM", {}).get("declared_type") == "ctrl_fsm_e", fsm
    # ...and the pipeline stage stays a pipeline stage.
    stages = {s.get("name") for s in (l6.get("pipeline_stages") or [])}
    assert "MEM" in stages, l6.get("pipeline_stages")
    assert all(s.get("declared_type") is None
               for s in (l6.get("pipeline_stages") or []))


def test_no_state_is_dropped():
    _, l6 = _gen_l6({"core_pkg.sv": PKG_SV, "lsu.rst": LSU_RST})
    names = {s["name"] for s in l6["fsm_states"]}
    assert names == {"IDLE", "ST_RESET", "ST_BOOT", "ST_WAIT_SLEEP",
                     "ST_SLEEP", "ST_FIRST_FETCH", "ST_DECODE",
                     "ST_FLUSH", "ST_IRQ_TAKEN"}, sorted(names)
    total = sum(m["emitted_state_count"] for m in l6["fsm_machines"])
    assert total == len(names), l6["fsm_machines"]


# ---------------------------------------------------------------------------
# (3) chip-AGNOSTIC — grouping is provenance, not names
# ---------------------------------------------------------------------------

def test_grouping_survives_renaming_everything():
    """Rename the design, the documents, the type and every state: the
    grouping is identical because it reads provenance, not names."""
    pkg = (PKG_SV.replace("core_pkg", "widget_defs")
           .replace("ctrl_fsm_e", "seq_state_t")
           .replace("ST_", "Q"))
    doc = LSU_RST.replace("IDLE", "SETTLE")
    _, l6 = _gen_l6({"widget_defs.sv": pkg, "engine_notes.rst": doc})
    assert l6["fsm_machine_count"] == 2, l6["fsm_machines"]
    closed = _machine(l6, "seq_state_t")
    assert closed is not None and closed["closed"] is True
    assert len(closed["states"]) == 8, closed["states"]
    assert "SETTLE" not in closed["states"], closed["states"]
    opened = [m for m in l6["fsm_machines"] if not m["closed"]][0]
    assert opened["states"] == ["SETTLE"], opened


def test_single_machine_input_still_reports_one_machine():
    """NO-LEAK: a design with only a declared machine gets exactly one
    record, and one with only inferred states gets one record too."""
    _, only_enum = _gen_l6({"core_pkg.sv": PKG_SV})
    assert only_enum["fsm_machine_count"] == 1, only_enum["fsm_machines"]
    assert only_enum["fsm_machines"][0]["closed"] is True

    _, only_prose = _gen_l6({"lsu.rst": LSU_RST})
    assert only_prose["fsm_machine_count"] == 1, only_prose["fsm_machines"]
    assert only_prose["fsm_machines"][0]["closed"] is False


def test_no_fsm_input_emits_an_empty_machine_list():
    _, l6 = _gen_l6({"readme.rst": "This block is purely combinational.\n"})
    assert l6["fsm_machines"] == []
    assert l6["fsm_machine_count"] == 0


# ---------------------------------------------------------------------------
# (4) the gate reasons per machine
# ---------------------------------------------------------------------------

def _run_gate(l6_doc):
    proj = Path(tempfile.mkdtemp())
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L6_CONTROL_LOGIC.json").write_text(
        json.dumps(l6_doc), encoding="utf-8")
    out = proj / "gate.json"
    r = subprocess.run(
        [sys.executable, str(GATE), str(proj), "--json", str(out)],
        capture_output=True, text=True)
    res = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return r, res


def test_gate_reports_the_two_machines_separately():
    proj, l6 = _gen_l6({"core_pkg.sv": PKG_SV, "lsu.rst": LSU_RST})
    r, res = _run_gate(l6)
    ids = [m["machine_id"] for m in res.get("machines") or []]
    assert "ctrl_fsm_e" in ids, res.get("machines")
    assert len(ids) == 2, ids
    closed = [m for m in res["machines"] if m["closed"]]
    assert len(closed) == 1 and len(closed[0]["states"]) == 8, closed
    # No finding may size a machine by the UNION of both machines.
    union = len(res["derived_states"])
    assert union == 9, res["derived_states"]
    blob = " ".join(res.get("failures") or []) + " " + " ".join(
        res.get("warnings") or [])
    assert f"{union} state" not in blob, blob
    assert "ctrl_fsm_e [closed typedef enum, 8 state(s)]" in blob, blob
    assert "DISTINCT state machines" in blob, blob
    assert "NOT counted as an incomplete machine of its own" in blob, blob


def test_gate_groups_a_legacy_l6_from_per_state_attribution():
    """A layer written before ``fsm_machines[]`` existed still groups —
    from the per-state ``declared_type`` / evidence it already carried."""
    legacy = {
        "schema_version": 2, "doc_class": "control_logic",
        "no_fsm_in_input": False, "no_fsm_states_in_input": False,
        "reject_rules": [],
        "fsm_states": [
            {"name": "IDLE", "transitions": [], "actions": [],
             "evidence": "input/docs/lsu.rst (prose transition v1.6.484)",
             "extraction_strategy": "l6_fsm_prose_walker_v1_6_484"},
            {"name": "ST_DECODE", "transitions": [], "actions": [],
             "evidence": "input/docs/core_pkg.sv (typedef enum ctrl_fsm_e)",
             "extraction_strategy": "hdl_typedef_enum_state_v1_7_72",
             "declared_type": "ctrl_fsm_e"},
        ],
    }
    _, res = _run_gate(legacy)
    ids = sorted(m["machine_id"] for m in res.get("machines") or [])
    assert len(ids) == 2, ids
    assert "ctrl_fsm_e" in ids, ids


def test_l9_mirror_carries_the_attribution():
    """The L9 mirror is the state-coverage consumers' input. If it
    re-flattens the machines they inherit the wrong denominator again."""
    docs = {"core_pkg.sv": PKG_SV, "lsu.rst": LSU_RST}
    proj, _ = _gen_l6(docs)
    res = P.gen_l9_integration_spec(proj, docs, {})
    l9 = json.loads(Path(res.path).read_text(encoding="utf-8"))
    assert l9.get("fsm_machine_count") == 2, l9.get("fsm_machines")
    closed = [m for m in l9["fsm_machines"] if m.get("closed")]
    assert len(closed) == 1, l9["fsm_machines"]
    assert "IDLE" not in closed[0]["states"], closed[0]
    mirrored = {s["name"]: s for s in l9["fsm_states"]}
    assert mirrored["ST_DECODE"]["fsm_machine"] == "ctrl_fsm_e"
    assert mirrored["IDLE"]["fsm_machine"] != "ctrl_fsm_e"


def test_gate_verdict_policy_is_unchanged():
    """NO-LEAK: grouping changes the REPORT, not the exit-code policy.
    A well-formed single machine with transitions still passes."""
    good = {
        "schema_version": 2, "doc_class": "control_logic",
        "no_fsm_in_input": False, "no_fsm_states_in_input": False,
        "reject_rules": [],
        "fsm_states": [
            {"name": "S_IDLE", "declared_type": "ctrl_fsm_e",
             "fsm_machine": "ctrl_fsm_e",
             "transitions": [{"to": "S_RUN", "condition": "start"}]},
            {"name": "S_RUN", "declared_type": "ctrl_fsm_e",
             "fsm_machine": "ctrl_fsm_e",
             "transitions": [{"to": "S_IDLE", "condition": "done"}]},
        ],
        "fsm_machines": [
            {"machine_id": "ctrl_fsm_e", "declared_type": "ctrl_fsm_e",
             "closed": True, "source": "input/docs/core_pkg.sv",
             "states": ["S_IDLE", "S_RUN"], "state_count": 2,
             "emitted_state_count": 2},
        ],
        "fsm_machine_count": 1,
    }
    r, res = _run_gate(good)
    assert r.returncode == 0, r.stdout + r.stderr
    assert res["verdict"] == "PASS", res

    bad = json.loads(json.dumps(good))
    for st in bad["fsm_states"]:
        st["transitions"] = []
    r2, res2 = _run_gate(bad)
    assert r2.returncode == 1, r2.stdout + r2.stderr
    assert "0 transitions" in r2.stdout, r2.stdout
