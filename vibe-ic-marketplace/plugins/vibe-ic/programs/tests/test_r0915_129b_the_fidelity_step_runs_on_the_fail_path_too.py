"""SLT53B handback — step 37.3 produced nothing on the run that needed it most.

THE INPUT, the FULL S arm (spm end-to-end on 0.3.67, the rollback/FAIL path,
DRC 4, step 37 "GDS output only if PV fully clean" FAILs):

    step 37.3  FAIL  missing_artefact      <- and no receipt, no xor artefact,
                                             no log line
    step 37.4  NOT_MEASURED  upstream_failed

while BOTH of 37.3's inputs sat on disk throughout: the retained boundary
`chip_top.prefinish.gds` at 73,850,000 B (the retention added by the previous
commit DID fire) and the shipped GDS at 102,921,972 B.

TWO DEFECTS, and the second is why the first could never have worked.

(1) A VERDICT DEPENDENCY WHERE A FILE DEPENDENCY BELONGED. 37.3 declared
    `blocks_on: [37]`, so a failed PV cascaded it away. But its subject -- does
    the shipped GDS differ from this run's own pre-finishing boundary on the
    design layers -- is answerable from those two artefacts alone. And the run
    where the answer matters MOST is exactly this one: a fidelity defect
    (finishing corrupting design geometry) is a candidate CAUSE of the DRC
    violations that failed PV, so gating the check on PV being clean means it can
    never help diagnose the failure it might explain. R-0915-129's own words: "a
    metric with no producer, not a metric that cannot be produced".
    So the step is now CONDITIONAL on its subject and has no `blocks_on`.

(2) THE STEP'S ONLY PRODUCER WAS ITS OWN GATE CLAUSE, which cannot work:
    compliance reads `required_outputs` BEFORE it runs the clause, so the
    artefact is missing, the step reports FAIL/missing_artefact, and the clause
    that would have written it never runs. REPRODUCED LOCALLY by failing step 37
    on a copy of run21 -- same three rows as the S arm, `gds_xor.json produced:
    False`. The producer is now invoked in `_PRE_AUDIT_PRODUCERS`, which runs on
    EVERY path before the audit reads anything.

AND A TRAP I WALKED INTO WHILE FIXING IT, pinned below because it fails QUIETLY:
the pre-audit hook passes `--pdk-container` to PDK-aware gates. This gate drives
KLayout and takes `--container`. Wired without it, the producer ran, found no
runner, and wrote a NOT_DETERMINED receipt -- on a tree whose runner `covers()`
returns True for. The receipt EXISTED, so "produced" looked satisfied while the
comparison had not run. A produced receipt is not a performed measurement.

MEASURED after both fixes, on a copy of run21 with step 37 forced to FAIL:
    no subject            -> NOT_APPLICABLE (never FAIL/missing_artefact)
    subject + boundary    -> PASS, reference kind `retained`, 38 layer(s)
                             compared, 0 design-layer difference(s)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))


def _flow() -> dict:
    return yaml.safe_load(
        (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text())


def _step(sid: str) -> dict:
    d = _flow()

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o and "stage" in o:
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    return next(s for s in walk(d) if str(s["id"]) == sid)


# ── (1) conditional on its subject, not dependent on a verdict ──────────────

def test_the_fidelity_step_has_no_verdict_dependency_on_stream_out():
    """THE DEFECT. `blocks_on: [37]` cascaded it away on the FAIL path.

    The repair is NOT an empty list, which was this file's second draft.
    `blocks_on` must be present (the flow contract: "every step must declare
    `blocks_on`, even as an empty list") and it must carry the step's REAL data
    dependency, which dimension 5 measures independently: the condition names
    `phase3/stage3/pnr/routed.def`, step 21 produces it, so the edge is [21].

    WHAT IS ASSERTED IS THE PROPERTY, NOT THE LITERAL: step 37 must not be in the
    closure, because the ruling removed the dependency on 37's VERDICT, and the
    closure must be non-empty, because a step that reads another step's output and
    declares no edge is D5-MISSING-EDGE.
    """
    # RE-DERIVED (T109c). ac2104931 made 37.3 read step 37's SHIPPED GDS
    # ("Step 37 supplies the shipped GDS. Both inputs must be named in the
    # dependency closure") and, in the same change, moved physical
    # verification (31) AFTER stream-out (31 blocks_on [.., 34, 37]). So an
    # edge to 37 no longer carries a PV verdict: a DRC/LVS FAIL no longer stops
    # 37 and cannot cascade 37.3 away. The ruling's property is asserted over
    # the closure: no physical-verification verdict upstream of 37.3, and its
    # trigger's producer (21) is a declared edge.
    parents = [str(p) for p in (_step("37.3").get("blocks_on") or [])]
    assert "21" in parents, parents
    steps = _flow()["steps"]
    edges = {str(s["id"]): [str(p) for p in (s.get("blocks_on") or [])]
             for s in steps if isinstance(s, dict) and "id" in s}
    closure, stack = set(), list(parents)
    while stack:
        cur = stack.pop()
        if cur not in closure:
            closure.add(cur)
            stack.extend(edges.get(cur, []))
    pv = {str(s["id"]) for s in steps if isinstance(s, dict)
          and "Physical Verification" in str(s.get("name", ""))
          and "21" in _ancestry(edges, str(s["id"]))}
    assert pv, "no physical-verification step downstream of routing"
    assert not (pv & closure), (
        f"a PV verdict ({sorted(pv & closure)}) is upstream of the fidelity "
        f"step -- that is what cascaded it away on the one run where the "
        f"fidelity answer mattered most")


def _ancestry(edges, sid):
    seen, stack = set(), list(edges.get(sid, []))
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(edges.get(cur, []))
    return seen


def test_the_step_is_not_listed_as_a_dependency_graph_root():
    """The other half of the same fact, in the other file that states it.

    While the step declared `blocks_on: []` it was added to
    `flow_dependency_graph_check.DECLARED_ROOTS`. It has a real predecessor now,
    so listing it there would declare the absence of an ordering constraint that
    exists — and a root list that drifts from the yaml is how an orphan check
    stops checking.
    """
    import flow_dependency_graph_check as G
    assert "37.3" not in G.DECLARED_ROOTS, sorted(G.DECLARED_ROOTS)


def test_the_fidelity_step_is_conditional_on_the_routed_database():
    """THE TRIGGER, and the two answers the matrix refused before this one.

    NOT the route attestation: `flow_condition_reachability_check` calls a trigger
    the flow itself produces whose absence is loud NOWHERE a SELF-DISABLING
    CONDITION, and the runner writes that file only under
    `_chip_path_requests_pad_ring`, so every design off the chip pad-ring path had
    no fidelity check and nothing said so.

    NOT the shipped GDS: it is step 37's required_output, so naming it here IS a
    data dependency on 37 (D5-MISSING-EDGE), and the only thing that satisfies
    that clause is the verdict dependency the ruling removed.

    The routed DEF is the precondition the comparison actually has -- its
    REFERENCE is streamed from that database -- and it belongs to step 21, which
    is upstream of stream-out.
    """
    cond = _step("37.3").get("condition") or {}
    paths = cond.get("files_exist") or []
    assert "phase3/stage3/pnr/routed.def" in paths, cond
    assert "reports/phase3/pad_ring_route_evidence.json" not in paths, (
        "the attestation is the BINDING, not the subject; gating on it silently "
        "disables this step on every design without a chip pad ring")
    assert "phase3/stage4/gds/*.gds" not in paths, (
        "naming step 37's own required_output here is a data dependency on 37, "
        "which D5-MISSING-EDGE reports and only a blocks_on edge to 37 settles")


def test_an_unmet_trigger_names_its_producer_instead_of_going_quiet():
    """`condition_kind`, which the consumer branches on and whose default is the
    benign answer.

    `flow_gate_grid` named the omission when this step had none: "every
    conditional skip falls to the benign default and 'this design legitimately
    has none' cannot be told from 'someone forgot to author the trigger'".

    `dependency_required` is the accurate kind BECAUSE OF WHAT THE TRIGGER IS:
    `routed.def` is not a property of the design, it is an artefact step 21
    produces, so its absence means the producer did not deliver. That kind routes
    the unmet condition through `_resolve_dependency_condition_results`, which
    states it as MISSING plus `blocked-by-upstream(21)` and names the artefact --
    a design_dependent skip would have made a failed route and a design with
    nothing to compare read identically.
    """
    assert _step("37.3").get("condition_kind") == "dependency_required", (
        _step("37.3").get("condition_kind"))
    import flow_compliance_check as FCC
    src = Path(FCC.__file__).read_text()
    assert 'step.get("condition_kind") != "dependency_required"' in src, (
        "the consumer this kind was chosen for no longer reads it; the "
        "classification above would silently become a plain skip")


def test_the_trigger_has_a_loud_absence_and_a_declared_producer():
    """WHY THIS TRIGGER IS ADMISSIBLE, measured through the two indexes the
    reachability checker and dimension 5 actually read.

    A condition may only be gated on an artefact whose disappearance somebody
    reports (T7: a hard `files_exist`), and a step may only read an artefact whose
    producer is in its blocks_on closure. `phase3/stage3/pnr/routed.def` satisfies
    both at the SAME step, 21, which is what makes it the one admissible trigger:
    the route attestation satisfies neither.
    """
    import flow_condition_reachability_check as R
    steps = _flow()["steps"]
    hard = R._build_hard_gate_index(steps)
    assert hard.get("phase3/stage3/pnr/routed.def") == "21", hard.get(
        "phase3/stage3/pnr/routed.def")
    assert "reports/phase3/pad_ring_route_evidence.json" not in hard, (
        "if the attestation ever gains a hard clause this test should be "
        "revisited, not deleted -- the trigger choice was made on this fact")
    assert 21 in (_step("37.3").get("blocks_on") or []), (
        "the trigger's producer must be a declared edge, or the two halves of "
        "this argument are about different steps")


def test_its_sibling_keeps_its_own_dependency():
    """CONTROL: 37.4 aggregates the run's verdicts and IS downstream of 37. This
    change must not widen to it -- only the step whose subject is two files."""
    assert _step("37.4").get("blocks_on") == [37]


# ── (2) the producer runs before the audit reads its output ─────────────────

def test_the_producer_is_invoked_before_the_audit():
    import phase3_one_shot_runner as R
    names = [row[0] for row in R._PRE_AUDIT_PRODUCERS]
    assert "gds_xor" in names, names
    entry = next(r for r in R._PRE_AUDIT_PRODUCERS if r[0] == "gds_xor")
    assert entry[1] == "gds_xor_check.py"
    assert entry[2] == "reports/phase3/gds_xor.json", (
        "the declared output and the produced receipt must be the same path, or "
        "the audit still reads a missing artefact")


def test_a_gate_clause_alone_cannot_produce_its_own_declared_output():
    """WHY (2) IS NECESSARY, stated as the property: 37.3's required_output IS its
    gate's product, and compliance reads required_outputs before running gates.
    Without a pre-audit producer the step can only ever report missing_artefact."""
    s = _step("37.3")
    declared = set(s.get("required_outputs") or [])
    clause = " ".join(str(c) for c in (s.get("gate") or {}).get("all_of") or [])
    assert declared == {"reports/phase3/gds_xor.json"}
    assert "reports/phase3/gds_xor.json" in clause, (
        "the clause writes exactly the artefact the step declares — which is why "
        "something must run it BEFORE the audit looks")


# ── the container trap: a produced receipt is not a measurement ─────────────

def test_the_layout_producer_gets_the_container_by_its_own_flag_name():
    """THE QUIET TRAP. `--pdk-container` names a PDK-view volume for a different
    question; this gate drives KLayout and takes `--container`. Without it the
    producer wrote a NOT_DETERMINED receipt on a tree its runner covers, and the
    existing receipt made "produced" look satisfied."""
    import phase3_one_shot_runner as R
    assert "gds_xor" in R._KLAYOUT_CONTAINER_SIGNOFF_GATES
    assert "gds_xor" not in R._PDK_AWARE_SIGNOFF_GATES, (
        "the two flags are different questions and must not be conflated")
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("for name, program, out_rel, extra_argv in _PRE_AUDIT_PRODUCERS:")
    # the LOOP, to its own `return rows` -- not a fixed character window,
    # which a new branch in the loop (the foundry_handoff admission) pushed
    # the flag out of (T109c)
    body = src[i:src.index("return rows", i)]
    # The actual loop retains this helper call before it invalidates the old
    # output. Follow that reachable producer body, retaining both flag checks.
    if '_run_pre_audit_producer' in body:
        import inspect
        body += inspect.getsource(R._run_pre_audit_producer)
    assert '("--container", container)' in body
    assert body.index("_PDK_AWARE_SIGNOFF_GATES") < body.index(
        "_KLAYOUT_CONTAINER_SIGNOFF_GATES"), "both branches must remain present"


def test_the_gate_still_refuses_when_it_cannot_measure():
    """The teeth that survived, RE-POINTED at the rc the convention gives them.

    A receipt is still not a pass: with no runner the producer writes
    NOT_DETERMINED, which is what "an unrun XOR is not a zero" means. What
    changed is the EXIT CODE, and the reason is measured rather than stylistic.

    This test pinned `rc=1` for every refusal, which made "the tool was not
    reachable" indistinguishable from "the design's geometry changed" — and on
    the SLT53D S arm that published a FAIL over a PASS on all five subjects. rc 2
    is the not-checked convention every other gate in this flow uses and the
    audit maps it to a typed non-verdict. The teeth are not removed, they are
    moved to where a defect is actually measured: a receipt with a design-layer
    difference exits 1, asserted directly in
    `test_a_receipt_with_a_design_layer_difference_still_blocks`.
    """
    src = (PROGRAMS / "gds_xor_check.py").read_text()
    assert 'return finish("NOT_DETERMINED", 2,' in src
    assert 'finish("NOT_DETERMINED", 1,' not in src, (
        "an unreachable tool and a changed layout must not share an exit code")
    assert "an unrun XOR is not a zero" in src
    # And the FAIL path keeps rc 1, so the gate can still refuse a real defect.
    assert 'return finish("FAIL", 1,' in src


# ── the audit JUDGES the producer's receipt; it does not re-measure ─────────

_S_ARM_RECEIPT = {
    # The shape of the receipt the SLT53D S arm actually produced, trimmed to the
    # fields the judge reads. Kept here rather than copied from a run tree so the
    # arms are hermetic.
    "gate": "gds_xor_check", "verdict": "PASS", "rc": 0,
    "layers_compared": 46, "design_layer_differences": [],
    "design__xor_difference__count": 0,
    "reason": "the shipped GDS matches the restreamed pre-finishing reference on "
              "every design layer (0 differences across 46 layer(s) compared)",
    # U15 (2026-09-29): a PASS also carries the shipped bytes' connectivity
    # measurement bound to their sha256; without it the judge reads
    # NOT_MEASURED (test_u15_gds_connectivity_is_measured_on_the_shipped_bytes).
    "shipped_sha256_live": "a" * 64,
    "connectivity": {"verdict": "PASS", "subject_sha256": "a" * 64,
                         "basis": "magic_vs_klayout_stream_xor"},
}


def _receipt(tmp_path, **over):
    import json
    doc = dict(_S_ARM_RECEIPT)
    doc.update(over)
    out = tmp_path / "reports" / "phase3" / "gds_xor.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    return out


def test_the_flow_clause_judges_the_receipt_instead_of_re_running_the_xor():
    """THE DEFECT, and it published a FAIL over a PASS on all five subjects.

    The clause was `gds_xor_check . --json reports/phase3/gds_xor.json`, so the
    completion audit RE-RAN the comparison. On the SLT53D S arm the producer's
    receipt said PASS with 0 design-layer differences across 46 layers (runner
    real-ic-arm-eda:klayout) and the audit's own invocation, seconds later on the
    same host, could not reach KLayout and exited NOT_DETERMINED. The audit
    published the invocation that did not measure.

    R-0915-126's rule is PRODUCER WRITES, GATE READS -- and the receipt redirect
    protects the producer's BYTES while saying nothing about which answer gets
    published, so a clause that re-measures is the trap the redirect was built
    for.
    """
    clause = " ".join(str(c) for c in (_step("37.3").get("gate") or {}).get("all_of") or [])
    assert "--check reports/phase3/gds_xor.json" in clause, clause
    assert "--json" not in clause, (
        "a `--json` clause makes the AUDIT the producer of this step's own "
        "receipt and re-runs the measurement; that is what published a FAIL over "
        "a PASS")


def test_the_judge_reads_the_receipt_and_writes_nothing(tmp_path):
    """PRODUCER WRITES, GATE READS — asserted on the bytes."""
    import hashlib
    import json
    import _physical_current as current
    import gds_xor_check as G
    out = _receipt(tmp_path)
    # A positive read-only consumer fixture includes the current subjects
    # and instrument transcript; a historical zero alone is not accepted.
    files = {
        "shipped": ("phase3/stage4/gds/chip_top.gds", "synthetic shipped bytes"),
        "reference": ("reports/phase3/reference.gds", "synthetic reference bytes"),
        "def": ("phase3/stage3/pnr/routed.def", "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n"),
        "technology": ("reports/phase3/technology_units.json", '{"pdk":"sky130A"}'),
        "recipe": ("reports/phase3/xor.rb", "synthetic instrument recipe\n"),
        "log": ("reports/phase3/xor.log", "XOR_TOOL klayout\n"
                "XOR_TOP shipped=chip_top reference=chip_top\n"
                + "".join(f"XOR_LAYER {layer}/0 0\n" for layer in range(1, 47))
                + "XOR_DONE\n"),
    }
    entries = {}
    for role, (relative, text) in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        entries[role] = current.entry(tmp_path, path)
    doc = json.loads(out.read_text())
    doc["current"] = current.build(
        tmp_path, "37.3", "stage4", "chip_top", "sky130A", "klayout",
        {role: entry for role, entry in entries.items() if role != "log"},
        {"log": entries["log"]}, {"rc": 0, "argv": ["klayout", "synthetic-fixture"]})
    doc["finishing_layer_differences"] = []
    doc["shipped_sha256_live"] = entries["shipped"]["sha256"]
    lvs = tmp_path / G.LVS_VERDICT_REL
    lvs.parent.mkdir(parents=True, exist_ok=True)
    lvs.write_text(json.dumps({
        "status": "PASS", "finding": "synthetic consumer fixture",
        "layout_source": {"kind": "gds", "path": entries["shipped"]["path"],
                          "sha256": entries["shipped"]["sha256"],
                          "extracted_sha256": entries["shipped"]["sha256"]}}))
    doc["connectivity"] = G.gds_connectivity(tmp_path, entries["shipped"]["sha256"])
    out.write_text(json.dumps(doc))
    before = hashlib.sha256(out.read_bytes()).hexdigest()
    rc, line, _ = G.judge_receipt(tmp_path, "reports/phase3/gds_xor.json")
    assert rc == 0, line
    assert hashlib.sha256(out.read_bytes()).hexdigest() == before, (
        "the judge modified the producer's document")


def test_a_receipt_with_a_design_layer_difference_still_blocks(tmp_path):
    """DIMENSION 2'S QUESTION, and it is why the judge is not a rubber stamp: this
    gate must be able to FAIL on something a project DID."""
    import gds_xor_check as G
    _receipt(tmp_path, verdict="FAIL", rc=1,
             design_layer_differences=[{"layer": 50, "datatype": 0,
                                        "differences": 3}],
             design__xor_difference__count=3)
    rc, line, _ = G.judge_receipt(tmp_path, "reports/phase3/gds_xor.json")
    assert rc == 1, line
    assert "50/0=3" in line, line


def test_an_undetermined_receipt_is_not_measured_and_carries_its_own_reason(
        tmp_path):
    """rc 2, the not-checked convention — never rc 1, which the audit reads as a
    defect. And the REASON is the receipt's own: re-deriving it here is how two
    readers come to disagree about one run."""
    import gds_xor_check as G
    why = ("no KLayout runner reaches this project, so the comparison was not "
           "performed; an unrun XOR is not a zero")
    _receipt(tmp_path, verdict="NOT_DETERMINED", rc=2, reason=why,
             design_layer_differences=None, design__xor_difference__count=None)
    rc, line, _ = G.judge_receipt(tmp_path, "reports/phase3/gds_xor.json")
    assert rc == 2, line
    assert why in line, line
    assert "CAPABILITY_ABSENT" in line, line


def test_an_absent_receipt_is_not_measured_not_a_clean_comparison(tmp_path):
    import gds_xor_check as G
    rc, line, _ = G.judge_receipt(tmp_path, "reports/phase3/gds_xor.json")
    assert rc == 2, line
    assert "ASKED_BEFORE_PRODUCER" in line and "does not exist" in line, line


def test_the_classified_line_is_the_first_line_of_stdout(capsys):
    """WHERE A LINE IS PRINTED DECIDES WHO READS IT.

    Every reader of a non-verdict in this flow takes the FIRST line of stdout.
    A `=== gate ===` banner printed first hands all of them the banner —
    MEASURED on a run21 copy, where the row read "gate program signalled
    VACUOUS_PASS (input not applicable)" and the receipt's own reason reached
    nobody.
    """
    import gds_xor_check as G
    rc = G.main([str(PLUGIN), "--check", "nope/absent.json"])
    first = capsys.readouterr().out.splitlines()[0]
    assert rc == 2
    assert first.startswith("NOT_MEASURED ["), first


def test_a_refusal_states_its_reason_class_in_the_receipt(tmp_path):
    """`_flow_reason_taxonomy.report_reason_class` reads this field and
    `_p0_declared_reason_class` prefers it over every prose recogniser, so a
    refusal is typed by the gate that knows rather than by pattern-matching."""
    import json
    import gds_xor_check as G
    out = tmp_path / "reports" / "phase3" / "gds_xor.json"
    rc = G.main([str(tmp_path), "--json", str(out)])
    assert rc == 2, rc
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "NOT_DETERMINED" and doc["rc"] == 2
    assert doc["reason_class"] == "CAPABILITY_ABSENT", doc.get("reason_class")
    import _flow_reason_taxonomy as T
    assert T.report_reason_class(doc) == T.CAPABILITY_ABSENT


def test_the_container_resolver_is_shared_and_reads_the_runs_own_record(tmp_path):
    """THE THIRD DEFECT: one gate, two invocations, two answers, seconds apart.

    The runner passed `--container real-ic-arm-eda` and the XOR ran; the flow's
    static clause carries no `--container` because a per-host container name
    cannot be written into the yaml, so `find_runner(None)` fell through to the
    pinned DEFAULT_CONTAINER — a different container that does not mount that
    project — and the gate said, correctly for what it was given, that no runner
    reached it. The durable identity is the run's OWN receipt.
    """
    import json
    import _klayout_launch as K
    assert K.container_the_run_recorded(tmp_path) is None
    rec = tmp_path / "reports" / "container_image.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"container": "real-ic-arm-eda"}))
    assert K.container_the_run_recorded(tmp_path) == "real-ic-arm-eda"
    # And the gate asks through that one resolver rather than its own copy.
    src = (PROGRAMS / "gds_xor_check.py").read_text()
    assert "find_runner(args.container, project=project)" in src, (
        "the gate must hand the project to the shared resolver, or the audit and "
        "the runner resolve different environments again")
