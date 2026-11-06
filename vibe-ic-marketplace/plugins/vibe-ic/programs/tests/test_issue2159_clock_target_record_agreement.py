#!/usr/bin/env python3
"""vibe-ic#2159 — ONE RUN, ONE CLOCK-TARGET ANSWER.

MEASURED on `subservient` (lane rbsub6, 8HD-9). Two records of the same run's
clock target named DIFFERENT technologies and DIFFERENT provenance tiers while
agreeing on the number::

    reports/phase3/clock_target_provenance.json
        pdk = gf180mcuD  tier = declared_pdk_table  period_ns = 20.0
        cite = input/docs/L9_constraints_floorplan.md:34

    phase1/generated_docs/L19_CONSTRAINTS_PDK.json  fields.clock_target
        pdk = sky130     tier = l8_declared         period_ns = 20.0

The design's own table, inside the file the first record cites, gives
`sky130_fd_sc_hd -> 10 ns` and `gf180mcu_* -> 20 ns`. So "sky130 -> 20 ns"
contradicts its own source.

BOTH DIRECTIONS ARE ASSERTED HERE, deliberately:
  * an AGREEING run passes, and an L19 that records an explicit absence passes
    (a gate that refuses everything is not a gate — it is an outage); and
  * a PLANTED disagreement is refused BY NAME, with both records named in the
    reason; and
  * the #2091 behaviour is unmoved: a run with no declared period still keeps
    `assumed: True` and its disclosure sentence.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(PROGRAMS))

import clock_target_provenance as ctp                      # noqa: E402
import l19_constraint_token_emit as l19e                   # noqa: E402

GATE_PROGRAM = "clock_target_record_agreement_check.py"
GATE_STEP = "clock_target_agreement"
GATE_OUT_REL = "reports/phase3/clock_target_record_agreement.json"


# ── fixtures ───────────────────────────────────────────────────────────────
def _project(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    return p


def _run_record(project: Path, **rep) -> Path:
    d = project / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "clock_target_provenance.json"
    f.write_text(json.dumps(rep, indent=2) + "\n")
    return f


def _l19(project: Path, clock_target=None, **fields) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "L19_CONSTRAINTS_PDK.json"
    body = {"doc_id": "L19", "fields": dict(fields)}
    if clock_target is not None:
        body["fields"]["clock_target"] = clock_target
    f.write_text(json.dumps(body, indent=2) + "\n")
    return f


#: The design's own table, as the measured input writes it. Two libraries,
#: two DIFFERENT periods — which is the whole point: a period here is only
#: meaningful next to the library it is keyed by.
_PDK_TABLE = (
    "## 9.1.2 the period per library\n\n"
    "| PDK / library | `<PERIOD>` (ns) | frequency |\n"
    "|---|---|---|\n"
    "| `sky130_fd_sc_hd` | **10** | 100 MHz |\n"
    "| `gf180mcu_*` | **20** | 50 MHz |\n"
)


# ===========================================================================
# (1) THE REPRODUCTION — the measured shape is refused, and both are named
# ===========================================================================


def test_the_measured_disagreement_exits_one(tmp_path):
    proj = _project(tmp_path, "measured_cli")
    _run_record(proj, pdk="gf180mcuD", period_ns=20.0,
                tier="declared_pdk_table", assumed=False, cite="doc.md:34")
    _l19(proj, clock_target={"status": "DECLARED", "period_ns": 20.0,
                             "pdk": "sky130", "tier": "l8_declared"})
    r = subprocess.run([sys.executable, str(PROGRAMS / GATE_PROGRAM),
                        str(proj)], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "sky130" in r.stdout and "gf180mcuD" in r.stdout


# ===========================================================================
# (2) THE OTHER DIRECTION — agreement, and explicit absence, both PASS
# ===========================================================================












# ===========================================================================
# (3) THE OTHER TWO DISAGREEMENTS
# ===========================================================================




# ===========================================================================
# (4) ABSENT vs UNREADABLE — two different verdicts, deliberately
# ===========================================================================
def test_a_run_that_publishes_no_run_record_is_not_applicable(tmp_path):
    """No run record is no second claim to contradict — and reporting NOT
    CHECKED here would block every Phase-3-only / analog run for the shape of
    the project rather than for anything about the design."""
    proj = _project(tmp_path, "no_run")
    _l19(proj, clock_target={"status": "DECLARED", "period_ns": 20.0,
                             "pdk": "sky130", "tier": "l8_declared"})
    r = subprocess.run([sys.executable, str(PROGRAMS / GATE_PROGRAM),
                        str(proj)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout






def test_an_unreadable_record_that_exists_is_not_checked(tmp_path):
    """The #1140 case, and the one it really is: the subject is PRESENT and
    this gate could not read it. 'Could not read it' is never 'read it and it
    agreed', and it must never exit 0."""
    proj = _project(tmp_path, "unreadable")
    _run_record(proj, pdk="gf180mcuD", period_ns=20.0,
                tier="declared_pdk_table", assumed=False)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text(
        "{ this is not json")
    r = subprocess.run([sys.executable, str(PROGRAMS / GATE_PROGRAM),
                        str(proj)], capture_output=True, text=True)
    assert r.returncode == 2, r.stdout

    proj2 = _project(tmp_path, "unreadable_run")
    d = proj2 / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "clock_target_provenance.json").write_text("{ nope")
    _l19(proj2, clock_target={"status": "DECLARED", "period_ns": 20.0,
                              "pdk": "sky130", "tier": "l8_declared"})


# ===========================================================================
# (5) THE EMITTER SIDE — L19 never stamps a PDK the tier did not key on
# ===========================================================================
def _emit_l19(proj: Path) -> dict:
    l19e.run(proj)
    return json.loads((proj / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
                       ).read_text())["fields"]["clock_target"]


def test_l19_does_not_stamp_the_document_pdk_on_a_pdk_independent_tier(tmp_path):
    """FAILS ON THE PRE-FIX TREE. This is the exact `subservient` fixture: L19
    declares `pdk_target: sky130`, the only period available comes from L8
    (a PDK-INDEPENDENT tier) and the design's table gives sky130 a DIFFERENT
    number. The pre-fix emitter wrote `pdk: sky130` next to the L8 number."""
    proj = _project(tmp_path, "l19_pdk_independent")
    (proj / "input" / "docs" / "L9_constraints.md").write_text(_PDK_TABLE)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"clock_mhz": 50}))
    _l19(proj, pdk_target="sky130")
    ct = _emit_l19(proj)
    assert ct["status"] == "DECLARED" and ct["period_ns"] == 20.0, ct
    assert ct["tier"] == "l8_declared", ct
    # THE FIX: no technology is named beside a number no technology keyed.
    assert ct["pdk"] is None, ct
    assert ct["pdk_source"] == "NOT_STATED", ct
    # The document's intent is preserved, under a name no reader can mistake
    # for "the PDK this number belongs to".
    assert ct["pdk_target_declared"] == "sky130", ct


def test_l19_names_the_pdk_when_the_pdk_keyed_tier_answered(tmp_path):
    """The control: when the technology DID key the row, naming it is honest —
    and the number is that technology's own row, not another's."""
    proj = _project(tmp_path, "l19_pdk_keyed")
    (proj / "input" / "docs" / "L9_constraints.md").write_text(_PDK_TABLE)
    _l19(proj, pdk_target="gf180mcuD")
    ct = _emit_l19(proj)
    assert ct["tier"] == "declared_pdk_table", ct
    assert ct["pdk"] == "gf180mcuD", ct
    assert ct["period_ns"] == 20.0, ct
    assert ct["pdk_source"] == "declared_pdk_table_match", ct


def test_l19_mirrors_the_runs_own_record_when_one_exists(tmp_path):
    """The authoritative record names the PDK the run BUILT AGAINST (#2136's
    ruling, applied to the clock target). When it exists, L19 repeats it."""
    proj = _project(tmp_path, "l19_mirror")
    (proj / "input" / "docs" / "L9_constraints.md").write_text(_PDK_TABLE)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"clock_mhz": 50}))
    _run_record(proj, pdk="gf180mcuD", period_ns=20.0,
                tier="declared_pdk_table", assumed=False,
                cite=str(proj / "input/docs/L9_constraints.md") + ":6")
    _l19(proj, pdk_target="sky130")
    ct = _emit_l19(proj)
    assert ct["pdk"] == "gf180mcuD" and ct["tier"] == "declared_pdk_table", ct
    assert ct["pdk_source"] == "run_provenance", ct
    # An L document is diffed across runs: its provenance stays project-
    # relative, never an absolute path recording this checkout and machine.
    assert not str(ct["evidence"]).startswith("/"), ct
    # And the two records now agree, by construction.


# ===========================================================================
# (6) #2091 IS UNMOVED — an undeclared period is still ASSUMED and disclosed
# ===========================================================================
def test_a_run_with_no_declared_period_keeps_assumed_and_its_disclosure(tmp_path):
    proj = _project(tmp_path, "still_assumed")
    (proj / "input" / "docs" / "L1_overview.md").write_text(
        "# Overview\n\n- rates from 343 Mbit/s to 0.042 Mbit/s (at 100 MHz).\n")
    rep = ctp.emit_report(proj, pdk="gf180mcuD", applied_period_ns=20.0)
    assert rep["assumed"] is True and rep["tier"] == "plugin_default", rep
    assert ctp.ASSUMED_DISCLOSURE in rep["disclosure"], rep
    _l19(proj, pdk_target="gf180mcuD")
    ct = _emit_l19(proj)
    # L19 mirrors the run: the number is the run's, and it is marked ASSUMED.
    assert ct["assumed"] is True, ct
    assert ct["period_ns"] == 20.0 and ct["pdk"] == "gf180mcuD", ct
    # The agreement gate has no opinion that could hide the assumption.


# ===========================================================================
# (7) DECLARED — in both of the flow's declaration surfaces, by name
# ===========================================================================
def test_the_runner_table_declares_the_gate_by_name():
    import phase3_one_shot_runner as R
    rows = [g for g in R._DECLARED_SIGNOFF_GATES if g[1] == GATE_PROGRAM]
    assert len(rows) == 1, rows
    name, program, out_rel, extra_argv = rows[0]
    assert name == GATE_STEP and out_rel == GATE_OUT_REL, rows[0]
    assert tuple(extra_argv) == (), extra_argv


def test_the_flow_yaml_declares_the_same_invocation():
    text = _FLOW.read_text(errors="replace")
    clause = (f'program_exit_zero: "clock_target_record_agreement_check . '
              f'--json {GATE_OUT_REL}"')
    assert text.count(clause) == 1, text.count(clause)


def test_the_step_name_reaches_the_declared_step_names_exactly_once():
    import phase3_one_shot_runner as R
    assert R.DECLARED_SIGNOFF_STEP_NAMES.count(GATE_STEP) == 1, (
        R.DECLARED_SIGNOFF_STEP_NAMES)


def test_the_disclosure_gate_is_still_the_last_declared_row():
    """#2126's ordering constraint: the disclosure gate reads records stamped
    immediately before it, so it must stay last. This row goes BEFORE it."""
    import phase3_one_shot_runner as R
    names = [g[0] for g in R._DECLARED_SIGNOFF_GATES]
    assert names[-1] == R._ASSUMED_CLOCK_DISCLOSURE_STEP, names[-3:]
    assert names.index(GATE_STEP) < names.index(
        R._ASSUMED_CLOCK_DISCLOSURE_STEP), names
