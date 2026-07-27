#!/usr/bin/env python3
"""#504 — the L6 FSM gate's consumer model, and the ONE reused-IP predicate.

TWO HALVES, BOTH LOAD-BEARING, AND THE SECOND IS THE ONE THAT KEEPS THE GATE
HONEST:

  * a REUSED-IP design (registry class with ``rtl_gen: null`` + staged RTL)
    no longer FAILs Part A, because the consumer Part A is stated in terms of
    — ``phase2_scaffold_gen.emit_fsm_v()`` — never authors its RTL; and
  * a SCAFFOLD-GENERATED design with the identical L6 still FAILs, because for
    it the gate is correct.

Every test here DRIVES the real CLI (or the real predicate) and reads the exit
code plus the emitted JSON. Nothing asserts on source text: a test that greps a
program certifies a program that may not run.

The reused-IP outcome is asserted to be DISCLOSED, not passed — verdict
``VACUOUS_PASS``, rc 2 (never rc 0), a ``_gate_denominator`` block that
survives ``disclosure_violations``, and prose that names the states, the
missing transitions and the absent consumer.

FIXTURES ARE SYNTHESIZED NEUTRAL DATA. Invented state names (``ST_A`` …),
invented module text, ``ic_class`` forced through the documented
``reports/ic_class.json`` persistence contract. No real design's files, no
vendor tokens, no PDK names, no chip-name literal anywhere — the predicate is
class + staged-RTL presence, so a chip name would not even be expressible.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _gate_denominator as _gd            # noqa: E402
import _reused_ip_predicate as _reused_ip  # noqa: E402

GATE = PROGRAMS / "l6_fsm_scaffold_actionable_check.py"

#: A registry class whose RTL no deterministic generator authors, and which is
#: NOT in the gate's by-class skip set. Read from the registry rather than
#: asserted, so the fixture follows the registry instead of freezing it.
REUSED_IP_CLASS = "processor_cpu"
#: A registry class that DOES carry a deterministic rtl_gen — the scaffold path
#: owns its RTL, so the gate must keep the FAIL for it.
GENERATED_RTL_CLASS = "aid_class_half_duplex_single_wire"


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------

def _fsm_states_no_transitions() -> list:
    """Exactly #504's shape: several states, zero transitions anywhere."""
    return [{"name": f"ST_{c}", "transitions": []} for c in "ABCDE"]


def _fsm_states_scaffoldable() -> list:
    return [
        {"name": "ST_A", "transitions": [{"to": "ST_B", "condition": "go"}]},
        {"name": "ST_B", "transitions": [{"to": "ST_C", "condition": "done"}]},
        {"name": "ST_C", "transitions": [{"to": "ST_A", "condition": "clr"}]},
    ]


def _mk_project(tmp_path: Path, *, name: str,
                fsm_states: list,
                ic_class: str | None = None,
                vendor_rtl: dict | None = None,
                manifest: dict | None = None,
                reject_rules: list | None = None) -> Path:
    """A minimal project the gate can evaluate.

    ``ic_class`` is forced through ``reports/ic_class.json`` — the documented
    persist-once contract ``detect_ic_class`` honours — so the fixture pins the
    class without depending on what the classifier would infer from two JSON
    files. ``vendor_rtl`` maps relative filename -> text.
    """
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    l6: dict = {"fsm_states": fsm_states,
                "no_fsm_in_input": False,
                "no_fsm_states_in_input": False}
    if reject_rules is not None:
        l6["reject_rules"] = reject_rules
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps(l6),
                                              encoding="utf-8")
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "synth_part", "interface": "uart"}),
        encoding="utf-8")
    if ic_class is not None:
        rep = proj / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "ic_class.json").write_text(
            json.dumps({"ic_class": ic_class}), encoding="utf-8")
    if vendor_rtl:
        vdir = proj / "input" / "vendor_rtl"
        for rel, body in vendor_rtl.items():
            f = vdir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
    if manifest is not None:
        mp = proj / "phase2" / "stage1" / "rtl" / "SOURCE_MANIFEST.json"
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(manifest), encoding="utf-8")
    return proj


def _run(project: Path, report: Path | None = None):
    cmd = [sys.executable, str(GATE), str(project)]
    if report is not None:
        cmd += ["--json", str(report)]
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_json(tmp_path: Path, project: Path):
    rep = tmp_path / f"{project.name}_gate.json"
    r = _run(project, rep)
    data = json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {}
    return r, data


STAGED_RTL = {"impl.sv": "module impl; endmodule\n"}


# ---------------------------------------------------------------------------
# HALF 1 — the scaffold-generated design STILL FAILS.
# This is the paired half. If it ever goes green the fix has become an escape
# hatch and the gate protects nothing.
# ---------------------------------------------------------------------------

def test_scaffold_generated_design_with_no_transitions_still_fails(tmp_path):
    """An FSM, zero transitions, NO staged RTL: the scaffold emitter really is
    what builds this design, so the '// TODO transition body' consequence is
    real and the gate must block."""
    proj = _mk_project(tmp_path, name="scaffolded",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS)   # eligible CLASS, no RTL
    assert not (proj / "input" / "vendor_rtl").exists()
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert data["verdict"] == "FAIL"
    assert data["scaffold_consumer_runs"] is True
    assert data["deferred_to_staged_rtl"] == []
    assert any("0 transitions" in f for f in data["failures"])
    assert "VACUOUS_PASS" not in r.stdout


def test_generated_rtl_class_with_staged_rtl_still_fails(tmp_path):
    """Half (a) alone is not enough: a class the registry gives a deterministic
    ``rtl_gen`` keeps the FAIL even with staged RTL sitting there."""
    proj = _mk_project(tmp_path, name="gen_class",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=GENERATED_RTL_CLASS,
                       vendor_rtl=STAGED_RTL)
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert data["verdict"] == "FAIL"
    assert data["scaffold_consumer_runs"] is True


def test_unclassifiable_design_with_staged_rtl_still_fails(tmp_path):
    """Fail-closed on the class we could not resolve — an unclassified design
    with a stray staged .sv earns no deferral."""
    proj = _mk_project(tmp_path, name="unknown_class",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class="unknown",
                       vendor_rtl=STAGED_RTL)
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert data["verdict"] == "FAIL"


def test_vendor_dir_without_rtl_still_fails(tmp_path):
    """Half (b) means STAGED RTL, not a directory. A vendor_rtl/ holding only
    prose does not make a design reused IP."""
    proj = _mk_project(tmp_path, name="vendor_prose_only",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS,
                       vendor_rtl={"README.txt": "no rtl here\n"})
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert data["verdict"] == "FAIL"


def test_manifest_reused_ip_false_still_fails(tmp_path):
    """The manifest route is keyed on a positive ``true``; ``false`` is a
    design that authored its own RTL and keeps the FAIL."""
    proj = _mk_project(tmp_path, name="manifest_false",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS,
                       manifest={"reused_ip": False})
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert data["verdict"] == "FAIL"


def test_single_state_scaffold_generated_still_fails(tmp_path):
    """A1 is a consumer claim too, and it also still binds when the consumer
    runs: one state gives emit_fsm_v a register that cannot change."""
    proj = _mk_project(tmp_path, name="one_state",
                       fsm_states=[{"name": "ST_A", "transitions": []}],
                       ic_class=REUSED_IP_CLASS)
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert any("1 FSM state" in f for f in data["failures"])


# ---------------------------------------------------------------------------
# HALF 2 — the reused-IP design is DISCLOSED, not passed.
# ---------------------------------------------------------------------------

def test_reused_ip_is_vacuous_pass_not_pass(tmp_path):
    proj = _mk_project(tmp_path, name="reused",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS,
                       vendor_rtl=STAGED_RTL)
    r, data = _run_json(tmp_path, proj)
    # rc 2, and emphatically NOT rc 0 — a reader cannot confuse this with a
    # gate that verified the FSM.
    assert r.returncode == 2, r.stdout + r.stderr
    assert data["verdict"] == "VACUOUS_PASS"
    assert data["scaffold_consumer_runs"] is False
    assert data["failures"] == []
    assert len(data["deferred_to_staged_rtl"]) == 1
    # It must never render as a plain PASS.
    assert "[PASS]" not in r.stdout
    assert "FSM is actionable" not in r.stdout


def test_reused_ip_disclosure_states_what_it_did_not_check(tmp_path):
    """The written reason has to carry the three facts, or the disclosure is
    worse than the FAIL it replaced: which states exist, that the transitions
    do not, and which consumer's absence is the reason."""
    proj = _mk_project(tmp_path, name="reused_disclose",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS,
                       vendor_rtl=STAGED_RTL)
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 2
    reason = data["denominator"]["not_applicable_reason"]
    assert "ST_A" in reason and "ST_E" in reason      # the states it found
    assert "0 declared transition(s)" in reason       # what is absent
    assert "phase2_scaffold_gen.emit_fsm_v()" in reason   # the consumer
    assert "NOT a sign-off" in reason
    # Visible to a human on BOTH channels the runners read: the first stdout
    # line (which phase1_doc_one_shot_runner echoes) and the stderr token
    # flow_compliance_check._stdout_signals_vacuous scans for.
    assert r.stdout.splitlines()[0].startswith("[VACUOUS_PASS]")
    assert any(ln.startswith("VACUOUS_PASS:")
               for ln in r.stderr.splitlines())


def test_reused_ip_denominator_satisfies_the_disclosure_contract(tmp_path):
    """No PASS without a denominator — checked by the shared contract checker,
    not by re-stating its rules here."""
    proj = _mk_project(tmp_path, name="reused_denom",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS,
                       vendor_rtl=STAGED_RTL)
    _r, data = _run_json(tmp_path, proj)
    assert _gd.disclosure_violations(data) == []
    denom = data["denominator"]
    assert denom["examined"] == 0
    assert denom["considered"] == 5      # the states WERE derived and counted
    assert denom["details"]["consumer_runs"] is False


def test_reused_ip_via_source_manifest_flag(tmp_path):
    """The second staging route: no ``input/vendor_rtl/`` at all, but the
    staged tree's manifest declares the RTL reused."""
    proj = _mk_project(tmp_path, name="reused_manifest",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS,
                       manifest={"reused_ip": True})
    assert not (proj / "input" / "vendor_rtl").exists()
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert data["verdict"] == "VACUOUS_PASS"


def test_reused_ip_with_scaffoldable_fsm_still_plain_passes(tmp_path):
    """DISTINGUISHABLE AT THE EXIT CODE. A reused-IP design whose L6 IS
    actionable is verified on merit and exits 0 — the deferral is only ever
    reached once Part A has already failed."""
    proj = _mk_project(tmp_path, name="reused_good_fsm",
                       fsm_states=_fsm_states_scaffoldable(),
                       ic_class=REUSED_IP_CLASS,
                       vendor_rtl=STAGED_RTL)
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert data["verdict"] == "PASS"
    assert data["scaffold_consumer_runs"] is True
    assert "denominator" not in data


def test_part_b_failure_survives_the_part_a_deferral(tmp_path):
    """The deferral covers Part A ONLY. Part B's consumer
    (l11_sequence_covers_l6_reject_rules_check) runs whatever authored the
    RTL, so a reject-rule failure still blocks at rc 1 — and the Part-A
    disclosure is printed alongside, never swallowed by it."""
    proj = _mk_project(tmp_path, name="reused_bad_rule",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS,
                       vendor_rtl=STAGED_RTL,
                       reject_rules=[{"name": "R_ANON", "condition": ""}])
    r, data = _run_json(tmp_path, proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert data["verdict"] == "FAIL"
    assert data["failures"], "the reject-rule failure must survive"
    assert data["scaffold_consumer_runs"] is False
    assert len(data["deferred_to_staged_rtl"]) == 1
    # #509 reworded the label counterfactually — the oracle runs for NO
    # design, so "does not run" could not distinguish this one. The pin is
    # unchanged in strength: the deferred Part-A item is still printed
    # alongside the Part-B FAIL.
    assert ("NOT CHECKED (scaffold contract does not bind this design)"
            in r.stdout)


def test_honest_no_fsm_declaration_is_untouched(tmp_path):
    """Regression guard on the pre-existing honest escape: it still SKIPs, and
    the #504 path did not quietly become its replacement."""
    proj = _mk_project(tmp_path, name="no_fsm",
                       fsm_states=[],
                       ic_class=REUSED_IP_CLASS,
                       vendor_rtl=STAGED_RTL)
    l6 = proj / "phase1" / "generated_docs" / "L6_CONTROL_LOGIC.json"
    data = json.loads(l6.read_text())
    data["no_fsm_in_input"] = True
    data["no_fsm_states_in_input"] = True
    l6.write_text(json.dumps(data), encoding="utf-8")
    r, out = _run_json(tmp_path, proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert out["verdict"] == "SKIP"
    assert out["deferred_to_staged_rtl"] == []


# ---------------------------------------------------------------------------
# ONE PREDICATE, ONE READER — driven, across all three consumers.
# ---------------------------------------------------------------------------

def _all_three_readers(project: Path) -> dict:
    """Ask the same question through each gate's own door."""
    import flow_compliance_check as F
    import l_doc_structured_field_count_check as L
    import l6_fsm_scaffold_actionable_check as G
    ic_class = _reused_ip.detected_ic_class(project)
    return {
        "flow_composite":
            F._detected_class_rtl_gen_null_and_vendor_rtl(project),
        "l_doc_class_half": L._class_rtl_gen_null(ic_class),
        "l_doc_staged_half": L._staged_vendor_rtl_text(project) is not None,
        "l6_gate": G._scaffold_consumer_is_bypassed(project),
        "shared":
            _reused_ip.detected_class_rtl_gen_null_and_vendor_rtl(project),
    }


@pytest.mark.parametrize(
    "ic_class,vendor,manifest,expected",
    [
        (REUSED_IP_CLASS, STAGED_RTL, None, True),
        (REUSED_IP_CLASS, None, {"reused_ip": True}, True),
        (REUSED_IP_CLASS, None, None, False),
        (REUSED_IP_CLASS, {"n.txt": "x\n"}, None, False),
        (GENERATED_RTL_CLASS, STAGED_RTL, None, False),
        ("unknown", STAGED_RTL, None, False),
        ("unknown_protocol_class", STAGED_RTL, None, False),
        ("no_such_class_at_all", STAGED_RTL, None, False),
    ],
)
def test_every_reader_gives_the_same_answer(tmp_path, ic_class, vendor,
                                            manifest, expected):
    """The whole point of collapsing the copies: drive the predicate through
    all three gates and the shared module, and get one answer. A future edit
    that reintroduces a private copy diverges here."""
    proj = _mk_project(tmp_path, name=f"agree_{abs(hash(ic_class))}",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=ic_class, vendor_rtl=vendor,
                       manifest=manifest)
    answers = _all_three_readers(proj)
    assert answers["shared"] is expected
    assert answers["flow_composite"] is expected
    assert answers["l6_gate"] is expected


def test_the_duplicated_copies_are_gone_not_shadowed(tmp_path):
    """Both former copies are now the SHARED function object itself — object
    identity, so a re-introduced private re-implementation fails here even if
    it happens to agree on today's fixtures."""
    import flow_compliance_check as F
    import l_doc_structured_field_count_check as L
    assert (F._detected_class_rtl_gen_null_and_vendor_rtl
            is _reused_ip.detected_class_rtl_gen_null_and_vendor_rtl)
    assert L._staged_vendor_rtl_text is _reused_ip.staged_vendor_rtl_text


def test_l_doc_keeps_its_own_bare_fpga_rejection(tmp_path):
    """The per-caller difference is PRESERVED, not averaged away: the L-doc
    gate rejects ``bare_fpga`` (its floors are protocol floors); the composite
    predicate, which asks a different question, does not."""
    import l_doc_structured_field_count_check as L
    assert L._class_rtl_gen_null("bare_fpga") is False
    assert _reused_ip.class_rtl_gen_null("bare_fpga") is True
    assert L._class_rtl_gen_null(REUSED_IP_CLASS) is True


def test_shared_predicate_is_fail_closed_on_a_broken_registry(tmp_path,
                                                              monkeypatch):
    """An unreadable registry answers False everywhere — a design we cannot
    classify never earns a relaxation."""
    monkeypatch.setattr(_reused_ip, "REGISTRY_PATH",
                        tmp_path / "no_such_registry.json")
    assert _reused_ip.registry_entry(REUSED_IP_CLASS) is None
    assert _reused_ip.class_rtl_gen_null(REUSED_IP_CLASS) is False
    proj = _mk_project(tmp_path, name="broken_reg",
                       fsm_states=_fsm_states_no_transitions(),
                       ic_class=REUSED_IP_CLASS, vendor_rtl=STAGED_RTL)
    assert _reused_ip.detected_class_rtl_gen_null_and_vendor_rtl(proj) is False


def test_staged_rtl_harvest_order_is_dot_v_then_dot_sv(tmp_path):
    """Pinned because the harvested text is fed to a parser downstream:
    the ``.v`` group first, then the ``.sv`` group, each sorted by FULL PATH
    (so a top-level ``b.sv`` precedes a nested ``sub/a.sv``). This is the
    pre-#504 order, reproduced deliberately — reordering it would change what
    the #748 FSM-enum harvester sees without anyone asking for that."""
    proj = tmp_path / "order"
    vdir = proj / "input" / "vendor_rtl"
    (vdir / "sub").mkdir(parents=True)
    (vdir / "b.sv").write_text("SV_B\n")
    (vdir / "sub" / "a.sv").write_text("SV_A\n")
    (vdir / "z.v").write_text("V_Z\n")
    rels = [str(p.relative_to(vdir)) for p
            in _reused_ip.staged_vendor_rtl_files(proj)]
    assert rels == ["z.v", "b.sv", "sub/a.sv"]
    text = _reused_ip.staged_vendor_rtl_text(proj)
    assert text.index("V_Z") < text.index("SV_B") < text.index("SV_A")


def test_staged_rtl_probe_degenerate_inputs():
    assert _reused_ip.staged_vendor_rtl_text(None) is None
    assert _reused_ip.staged_vendor_rtl_files(None) == []
    assert _reused_ip.has_staged_vendor_rtl(None) is False
    assert _reused_ip.manifest_declares_reused_ip(None) is False
    assert _reused_ip.detected_ic_class(Path("/no/such/project")) in (
        "", "unknown")
