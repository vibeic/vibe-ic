#!/usr/bin/env python3
"""flow_step_execution_coverage_check.py — enforce "every applicable step ran, in order".

`flow_compliance_check.py` already classifies each canonical step
(PASS / FAIL / MISSING / SKIPPED-CONDITION / WAIVED / VACUOUS-PASS) by inspecting
its `required_outputs`. What it does NOT do — and what this gate adds — is enforce
the three invariants an author actually cares about:

  1. NO-SKIP COMPLETENESS. Every *applicable* step (i.e. not legitimately
     SKIPPED-CONDITION / WAIVED / DEFERRED) must have actually run and produced
     output. An applicable step whose status is MISSING is a silently-skipped
     step — the exact "中間漏步驟" failure: the runner never drove it.

  2. ORDERING GUARD. No step may be marked done (PASS / VACUOUS-PASS) while an
     applicable step it declares it depends on has not truly PASSed. This is
     enforced two ways, and the code is wider than the name "terminal guard"
     suggests:

       * PRIMARY (graph): for EVERY step claimed done, walk its transitive
         `blocks_on` ancestry from the flow yaml and flag any applicable
         ancestor that is MISSING / FAIL — or VACUOUS-PASS when a vacuous
         ancestor is not an acceptable predecessor (see `_blocks_when_vacuous`).
         This is not restricted to terminal steps or to sign-off ancestors.
       * FALLBACK (name): a terminal hand-off step (GDSII output / Foundry
         Handoff / Tapeout checklist) that ships NO `blocks_on` edges at all is
         still guarded against every applicable sign-off step (Physical
         Verification / DRC / LVS / ERC / post-route STA / parasitic extraction
         / antenna / IR-drop / SI). Producing a GDS or ticking "ready for
         foundry" while DRC never ran is an integrity violation, not a warning.

  3. NO SELF-VACUOUS CERTIFICATE. This gate refuses to certify a run it could not
     actually inspect. Both inputs — the compliance report and the `blocks_on`
     graph — are load-checked, every `counts` field carries the DENOMINATOR the
     verdict was computed over, and any state in which the ordering invariant was
     not enforced over at least one edge exits 2 (NOT CHECKED), never 0. Before
     this, a missing / corrupt flow yaml was swallowed by a bare
     `except Exception: return {}`, the gate checked ZERO edges, and it printed a
     counts line byte-identical to a healthy all-PASS run. That is the same class
     of false certificate invariant 2 exists to stop, so it may not live here.

Ordering edges come from the flow yaml's own `blocks_on` field (`load_blocks_on`);
the *roles* used by the name-based fallback and by the vacuous-ancestor rule are
derived from the step NAME and `stage` (universal flow-stage vocabulary), NOT from a
per-chip allow-list — so the guard is chip-AGNOSTIC and survives flow-yaml
renumbering.

Usage:
    python3 flow_step_execution_coverage_check.py <project_dir> [--json report.json]
                                                  [--compliance-json <precomputed.json>]
    exit 0 = PASS        — every applicable step ran AND no step outran a step it
                           blocks_on, over a disclosed non-zero denominator
    exit 1 = FAIL        — one or more applicable steps MISSING, or an
                           ORDERING-VIOLATION
    exit 2 = NOT CHECKED — the gate could not look: unreadable/unparseable
                           compliance report or flow yaml, PyYAML absent, a flow
                           yaml that declares zero `blocks_on` edges, a report
                           with zero steps or zero applicable steps, or a
                           mistyped CLI flag. "I could not look" NEVER reads the
                           same as "I looked and it was fine".

The compliance classification is reused verbatim: this gate runs
`flow_compliance_check.py --json` itself (or consumes a precomputed report via
--compliance-json) so there is exactly ONE source of per-step verdicts.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_FLOW = _HERE.parent / "flow" / "phase1_phase2_phase3.yaml"

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# vibe-ic#634 — the producer and this guard read the SAME classification of
# verdict words, so a tier added on one side cannot be unknown on the other.
import _flow_verdict_tiers as _T                           # noqa: E402

# Exit codes. 2 = NOT CHECKED is a first-class verdict, not an error code: it is
# what the gate must return whenever it could not actually inspect the run.
VERDICT_RC = {"PASS": 0, "FAIL": 1, "NOT-CHECKED": 2}

# ── role classification by universal flow-stage name ─────────────────────────
# Terminal hand-off steps: emitting/ticking these asserts the design is done.
_TERMINAL_RE = re.compile(
    r"gdsii|gds\s*out|gds\s*ii|foundry\s*hand[- ]?off|tape\s*-?out\s*checklist",
    re.IGNORECASE)
# Sign-off predecessors: physical/timing sign-off that MUST pass before hand-off.
_SIGNOFF_RE = re.compile(
    r"physical\s*verification|(?<![a-z])drc(?![a-z])|(?<![a-z])lvs(?![a-z])"
    r"|(?<![a-z])erc(?![a-z])|post-?route\s*sta|post-?layout.*\bsta\b"
    r"|parasitic\s*extraction|antenna|signal\s*integrity|ir\s*drop"
    r"|post-?layout\s*spice|spice\s*(?:correlation|verification)|(?<![a-z])perc(?![a-z])",
    re.IGNORECASE)

# Silicon / manufacturing attestation steps (flow stage 5). These do not verify a
# design property — they attest that a PHYSICAL EVENT happened: the mask set and
# wafer lot came back from the foundry, wafers were sorted, parts were packaged,
# final-tested, reliability-qualified. Classified by the flow's own `stage` field
# first (declarative, immune to rewording) with a name fallback for reports that
# carry no stage.
_SILICON_STAGE_PREFIX = "stage5"
_SILICON_ATTEST_RE = re.compile(
    r"fabrication|wafer\s*(?:sort|fab|lot|probe)|probe\s*test|packaging"
    r"|final\s*test|burn-?in|reliability\s*qual|(?<![a-z])htol(?![a-z])",
    re.IGNORECASE)

# A step is "legitimately not run" (does NOT count as a skip) in these states —
# exactly what the producer subtracts from `total_required` (vibe-ic#634).
_NOT_APPLICABLE = _T.EXCUSED
# A real PASS always satisfies a predecessor.
_REAL_DONE = {_T.FULL_PASS}
# VACUOUS-PASS = the gate RAN and legitimately had nothing applicable to check
# (rc=2 "input not applicable", e.g. the synthesis-handoff gate on a design with
# no hi/lo tie cells or no yosys-script template). For an ordinary design PROCESS
# step that is an acceptable predecessor — it ran, it did not fail, it was not
# silently MISSING. It is NOT acceptable for a step whose whole job is to CERTIFY
# something: a SIGN-OFF (DRC/LVS/PERC/SPICE/…) that verified nothing, a TERMINAL
# hand-off (GDSII output / Foundry Handoff / Tapeout checklist) that handed off
# nothing, or a stage-5 SILICON ATTESTATION (fab intake / wafer sort / packaging
# / final test / reliability qual) that attested to nothing. All three must still
# block a downstream done-claim — you cannot wafer-sort a lot the foundry never
# delivered, and the downstream step's own PASS asserts the upstream event
# occurred. See `_blocks_when_vacuous`, applied in analyze().
# vibe-ic#634 — DERIVED, not enumerated. Every done-claim that is not a full
# PASS gets this treatment: VACUOUS-PASS, and since v1.9.48 also STRUCTURE-ONLY
# (#632) and INCOMPLETE (#599), both of which used to be in NO set here and so
# escaped the ordering guard entirely while the producer's own arithmetic
# counted them done. A tier added tomorrow lands here by construction.
_VACUOUS = _T.is_qualified_done


def _blocks_when_vacuous(step: dict) -> bool:
    """True when a VACUOUS-PASS on `step` must STILL block a downstream done-claim.

    Sign-off steps, TERMINAL hand-off steps and stage-5 silicon attestations all
    certify something; a vacuous verdict on any of them means nothing was
    certified, so a successor may not be credited as done on top of it. Ordinary
    process steps return False — they ran and did not fail, which is a legitimate
    predecessor state.

    The terminal limb closes a hole the module's own docstring already forbade:
    `_TERMINAL_RE` identifies GDSII output / Foundry Handoff / Tapeout checklist
    as the steps whose emission ASSERTS the design is done, and invariant 2 says
    producing a GDS while DRC never ran is an integrity violation — yet a VACUOUS
    hand-off used to be waved through as an acceptable predecessor, so a foundry
    handoff that verified nothing still credited Fabrication and everything after
    it. Same reasoning as the sign-off limb, same class of false certificate.
    """
    name = step.get("name", "") or ""
    stage = str(step.get("stage") or "")
    return bool(_SIGNOFF_RE.search(name)
                or _TERMINAL_RE.search(name)
                or stage.startswith(_SILICON_STAGE_PREFIX)
                or _SILICON_ATTEST_RE.search(name))


def _norm(status: str) -> str:
    return str(status or "").upper().replace("_", "-").strip()


class NotChecked(Exception):
    """The gate could not inspect its input. Never degrades into a PASS."""


def _run_compliance(project: Path) -> dict:
    out = Path(tempfile.mkstemp(suffix="_compliance.json")[1])
    prog = _HERE / "flow_compliance_check.py"
    cp = subprocess.run(
        [sys.executable, str(prog), str(project), "--json", str(out)],
        capture_output=True, text=True)
    # flow_compliance_check exits 1 on FAIL/MISSING; that is expected — we only
    # need the JSON it writes, not its exit code. But if it wrote NO usable JSON
    # we have no per-step verdicts at all, and inventing an empty report here
    # would manufacture exactly the false certificate this gate exists to stop.
    try:
        raw = out.read_text()
    except OSError as exc:
        raise NotChecked(
            f"flow_compliance_check produced no report ({exc.__class__.__name__}); "
            f"rc={cp.returncode}") from exc
    finally:
        try:
            out.unlink()
        except OSError:
            pass
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        tail = (cp.stderr or cp.stdout or "").strip().splitlines()[-1:] or [""]
        raise NotChecked(
            f"flow_compliance_check wrote no parseable JSON for {project} "
            f"(rc={cp.returncode}, {exc.__class__.__name__}): {tail[0][:200]}"
        ) from exc


def load_blocks_on(flow_path: Path) -> tuple:
    """Build the {step_id: [parent_id,...]} dependency graph from the flow yaml's
    declared `blocks_on` edges — the SAME edges flow_compliance_check consumes.
    Ids are stringified for uniform lookup.

    Returns (graph, provenance). `provenance` is "LOADED" only when the yaml
    parsed AND declared at least one edge; otherwise it names the reason the
    ordering invariant cannot be enforced from this yaml. Callers must surface it
    — this used to be a bare `except Exception: return {}`, which turned "the
    flow yaml is missing/corrupt" into a silent zero-edge run that still printed
    PASS with a counts line indistinguishable from a healthy one."""
    try:
        import yaml
    except Exception as exc:            # pragma: no cover - env without PyYAML
        return {}, f"NO-PYYAML ({exc.__class__.__name__}: {exc})"
    try:
        text = Path(flow_path).read_text()
    except OSError as exc:
        return {}, f"UNREADABLE ({exc.__class__.__name__}: {flow_path})"
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:
        return {}, f"UNPARSEABLE ({exc.__class__.__name__}: {flow_path})"
    graph: dict = {}

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and ("name" in o or "blocks_on" in o):
                edges = o.get("blocks_on") or []
                if isinstance(edges, (list, tuple)):
                    graph[str(o["id"])] = [str(e) for e in edges]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    if not _edge_count(graph):
        return graph, f"NO-EDGES (flow yaml declares no blocks_on: {flow_path})"
    return graph, "LOADED"


def _load_blocks_on(flow_path: Path) -> dict:
    """Back-compat shim: the graph alone, provenance discarded. Do NOT use it to
    decide a verdict — use `load_blocks_on` and surface the provenance."""
    return load_blocks_on(flow_path)[0]


def _edge_count(graph: dict) -> int:
    """Number of (child, parent) blocks_on edges — the ordering check's raw
    denominator. A graph can be non-empty (every step present) and still carry
    ZERO edges, in which case nothing is enforceable."""
    return sum(len(v or []) for v in (graph or {}).values())


def _ancestors(sid: str, graph: dict) -> list:
    """Transitive blocks_on ancestry of sid (BFS, cycle-safe)."""
    out, queue, seen = [], list(graph.get(sid, [])), set()
    while queue:
        p = queue.pop(0)
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        queue.extend(graph.get(p, []))
    return out


def analyze(report: dict, graph: dict | None = None,
            graph_provenance: str | None = None) -> dict:
    graph = graph or {}
    steps = report.get("steps", [])
    by_id = {str(s.get("id")): s for s in steps}
    status_of = {sid: _norm(s.get("status")) for sid, s in by_id.items()}

    applicable_missing = []
    signoff_steps = []
    terminal_steps = []
    steps_applicable = 0
    for s in steps:
        name = s.get("name", "")
        st = _norm(s.get("status"))
        if st not in _NOT_APPLICABLE:
            steps_applicable += 1
        if st not in _NOT_APPLICABLE and st == "MISSING":
            applicable_missing.append(s)
        if _SIGNOFF_RE.search(name):
            signoff_steps.append(s)
        if _TERMINAL_RE.search(name):
            terminal_steps.append(s)

    ordering_violations = []
    seen_pairs = set()
    # DENOMINATOR of the ordering invariant: how many (done-step, applicable
    # ancestor) pairs were actually adjudicated. A PASS that adjudicated zero
    # pairs asserts nothing, and must not be reported the same way as a PASS that
    # adjudicated hundreds.
    ancestor_edges_checked = 0

    def _emit(term, anc_id):
        anc = by_id.get(str(anc_id))
        key = (str(term.get("id")), str(anc_id))
        if anc is None or key in seen_pairs:
            return
        seen_pairs.add(key)
        ordering_violations.append({
            "terminal_id": term.get("id"), "terminal": term.get("name"),
            "terminal_status": _norm(term.get("status")),
            "signoff_id": anc.get("id"), "signoff": anc.get("name"),
            "signoff_status": _norm(anc.get("status")),
        })

    # ── PRIMARY: graph-based. Any step claimed done (PASS/VACUOUS-PASS) whose
    # transitive blocks_on ancestry reaches an APPLICABLE step that has not truly
    # PASSed (MISSING / FAIL / VACUOUS-PASS) is out of order — it was marked done
    # before a step it declares it depends on. Uses the flow's own edges, so it
    # is precise (no cross-track false positives).
    for s in steps:
        if not _T.is_done_claim(s.get("status")):
            continue
        for anc_id in _ancestors(str(s.get("id")), graph):
            ast = status_of.get(anc_id)
            if ast is None or ast in _NOT_APPLICABLE:
                continue
            ancestor_edges_checked += 1
            if ast in _REAL_DONE:
                continue
            # VACUOUS-PASS ancestor: acceptable UNLESS the ancestor's job was to
            # certify something — a sign-off that verified nothing, a TERMINAL
            # hand-off that handed off nothing, or a stage-5 silicon attestation
            # that attested to nothing must all still block. A vacuous PROCESS
            # step (e.g. synth-handoff with no tie-cells to check) ran and did not
            # fail — it is not a silent MISSING and does not break ordering.
            if _VACUOUS(ast):
                anc = by_id.get(anc_id)
                if anc and not _blocks_when_vacuous(anc):
                    continue
            _emit(s, anc_id)

    # ── FALLBACK: name-based terminal guard, for terminal hand-off steps that
    # declare NO blocks_on edges at all (the exact data bug where GDSII/handoff
    # ship `blocks_on: []`). Guards them against every applicable sign-off step.
    for t in terminal_steps:
        if not _T.is_done_claim(t.get("status")):
            continue
        if graph.get(str(t.get("id"))):
            continue  # has real edges → already covered by the graph pass
        for sg in signoff_steps:
            sst = _norm(sg.get("status"))
            if sst in _NOT_APPLICABLE or sst in _REAL_DONE:
                continue
            _emit(t, sg.get("id"))

    # ── NOT-CHECKED: every way the gate can have inspected nothing. Each one
    # used to render as an ordinary PASS with a counts line indistinguishable
    # from a healthy run. FAIL still wins over NOT-CHECKED — a violation found
    # over a partial view is still a violation.
    blocks_on_edges = _edge_count(graph)
    provenance = graph_provenance or (
        "LOADED" if blocks_on_edges else
        "NO-EDGES (caller supplied a graph with no blocks_on edges)")
    not_checked = []
    if not steps:
        not_checked.append(
            "compliance report declares 0 steps — nothing to enforce")
    elif not steps_applicable:
        not_checked.append(
            f"all {len(steps)} steps are SKIPPED / WAIVED / DEFERRED — 0 "
            f"applicable steps, so no completeness claim was tested")
    if not blocks_on_edges:
        not_checked.append(
            f"blocks_on graph carries 0 edges, so the ordering invariant was "
            f"never enforced: {provenance}")

    if applicable_missing or ordering_violations:
        verdict = "FAIL"
    elif not_checked:
        verdict = "NOT-CHECKED"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "not_checked": not_checked,
        "graph_provenance": provenance,
        "applicable_missing": [
            {"id": s.get("id"), "name": s.get("name"), "stage": s.get("stage")}
            for s in applicable_missing],
        "ordering_violations": ordering_violations,
        "counts": {
            "steps_total": len(steps),
            "steps_applicable": steps_applicable,
            "applicable_missing": len(applicable_missing),
            "signoff_steps": len(signoff_steps),
            "terminal_steps": len(terminal_steps),
            # DENOMINATORS — a PASS is only as strong as these.
            "blocks_on_edges_loaded": blocks_on_edges,
            "ancestor_edges_checked": ancestor_edges_checked,
            "ordering_violations": len(ordering_violations),
        },
    }


def _load_report(args) -> dict:
    """The compliance report, or NotChecked. Never a silently-empty dict."""
    project = Path(args.project).resolve()
    if args.compliance_json:
        src = Path(args.compliance_json)
        try:
            raw = src.read_text()
        except OSError as exc:
            raise NotChecked(
                f"--compliance-json is unreadable "
                f"({exc.__class__.__name__}: {src})") from exc
        try:
            report = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise NotChecked(
                f"--compliance-json is not parseable JSON "
                f"({exc.__class__.__name__}: {src})") from exc
    else:
        if not project.is_dir():
            raise NotChecked(f"project directory does not exist: {project}")
        report = _run_compliance(project)
    if not isinstance(report, dict) or not isinstance(report.get("steps"), list):
        raise NotChecked(
            "compliance report has no `steps` list — wrong file, or a report "
            "shape this gate cannot read")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        # A mistyped flag must ERROR, never silently bind to a different option
        # by prefix (`--flow` → `--flow-def`) and never be ignored. argparse's
        # own error path exits 2, which is this gate's NOT-CHECKED code.
        allow_abbrev=False)
    ap.add_argument("project")
    ap.add_argument("--json", help="write this gate's report here")
    ap.add_argument("--compliance-json",
                    help="reuse a precomputed flow_compliance_check --json report")
    ap.add_argument("--flow-def", default=str(_DEFAULT_FLOW),
                    help="flow yaml providing blocks_on dependency edges")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    graph, provenance = load_blocks_on(Path(args.flow_def))
    try:
        report = _load_report(args)
    except NotChecked as exc:
        print(f"=== flow step-execution coverage — {project.name} ===")
        print(f"\nNOT CHECKED — {exc}")
        print(f"flow-graph: {provenance}  "
              f"blocks-on-edges={_edge_count(graph)}")
        if args.json:
            Path(args.json).write_text(json.dumps(
                {"verdict": "NOT-CHECKED", "not_checked": [str(exc)],
                 "graph_provenance": provenance, "project": str(project),
                 "counts": {"steps_total": 0, "steps_applicable": 0,
                            "applicable_missing": 0, "signoff_steps": 0,
                            "terminal_steps": 0,
                            "blocks_on_edges_loaded": _edge_count(graph),
                            "ancestor_edges_checked": 0,
                            "ordering_violations": 0},
                 "applicable_missing": [], "ordering_violations": []},
                indent=2, ensure_ascii=False))
        print("\nVERDICT: NOT-CHECKED")
        return VERDICT_RC["NOT-CHECKED"]

    res = analyze(report, graph, provenance)
    res["project"] = str(project)
    res["compliance_overall"] = report.get("overall")

    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2, ensure_ascii=False))

    print(f"=== flow step-execution coverage — {project.name} ===")
    c = res["counts"]
    print(f"steps={c['steps_total']}  applicable={c['steps_applicable']}"
          f"  applicable-MISSING={c['applicable_missing']}"
          f"  sign-off-steps={c['signoff_steps']}  terminal-steps={c['terminal_steps']}"
          f"  ordering-violations={c['ordering_violations']}")
    # The denominator the verdict rests on — printed on EVERY run, so a PASS can
    # never look the same as a run that inspected nothing.
    print(f"denominators: blocks-on-edges-loaded={c['blocks_on_edges_loaded']}"
          f"  ancestor-edges-checked={c['ancestor_edges_checked']}"
          f"  flow-graph={res['graph_provenance']}")
    if res["not_checked"]:
        print("\nNOT CHECKED (the gate could not inspect this):")
        for why in res["not_checked"]:
            print(f"  - {why}")
    if res["applicable_missing"]:
        print("\nSILENTLY-SKIPPED (applicable step never produced output):")
        for s in res["applicable_missing"]:
            print(f"  MISSING  [{s['id']}] {s['name']}")
    if res["ordering_violations"]:
        # NB the JSON keys are historical: `terminal_*` is the step CLAIMED DONE
        # (any step, not only a terminal hand-off) and `signoff_*` is the
        # PREDECESSOR that had not PASSed (any applicable ancestor, not only a
        # sign-off). The keys are kept for report consumers; the wording here
        # describes what the check actually emits.
        print("\nORDERING-VIOLATION (step marked done before a step it depends on passed):")
        for v in res["ordering_violations"]:
            print(f"  [{v['terminal_id']}] {v['terminal']} = {v['terminal_status']}"
                  f"  ⟵ but  [{v['signoff_id']}] {v['signoff']} = {v['signoff_status']}")
    print(f"\nVERDICT: {res['verdict']}")
    return VERDICT_RC.get(res["verdict"], VERDICT_RC["FAIL"])


if __name__ == "__main__":
    sys.exit(main())
