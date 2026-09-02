"""Step 37's provenance gate must be about the GDS it ships.

The defect
----------
`flow/phase1_phase2_phase3.yaml` step 37 carried the comment

    # Provenance required: GDS must be produced by a real streamer
    # (KLayout def2gds, Magic gds write, etc.). This closes the
    # "rename old .def to .gds" loophole.

over the gate

    program_exit_zero: "provenance_check . --require-entries 1"

`--require-entries` is provenance_check's COARSE mode: it counts exit-0
entries anywhere in the ledger, with NO output-path and NO tool filtering
(provenance_check.py ~124-136). It never looks at the GDS. Of the six
provenance gates in this flow it was the ONLY coarse one — lines
701/1302/1330/1611/1612 all use the strict `--output ... --tool ...` form.

Measured on the completed spm x ihp-sg13g2 run (192.168.1.120,
~/campaign_pr427/spm/converge_ihp-sg13g2):

    coarse  -> `provenance_check: 44 / 1 exit-0 entries OK`, rc=0
    strict  -> rc=1, `hash mismatch: log=sha256:a5f4537a59e...
                       disk=sha256:b8cb431c24d...`

and dumping the ledger: the ONE record naming phase3/stage4/gds/spm.gds is
timestamped 14:52:15Z while the shipped file's mtime is 15:02Z, and
phase3/stage3/pnr/spm.gds — the stream-out DRC and LVS actually verified —
has NO record at all. The coarse gate passed anyway, on 44 unrelated
yosys / openroad / sta / netgen entries.

The fix has two halves and BOTH are needed
------------------------------------------
(a) DECLARATION — the strict form the other five gates already use.
(b) PRODUCER    — `_step37_declare_streamout_gds_provenance`, called on EVERY
    path through the Step-37 alias block, re-hashes and declares both GDS
    paths. Without (b) the honest gate reds every re-run; with it the
    declaration follows the bytes that ship.

Argument-form note (measured, not assumed): the strict form is written with
`--output=`/`--tool=`. flow_compliance_check's `_expand_globs` pre-expands any
argument containing a glob character UNLESS it starts with `-`, using nullglob
semantics — a pattern with no match is DROPPED. With the space-separated form
on a project with no GDS the resolved argv becomes
`['.', '--output', '--tool', 'klayout,...']`, argparse exits 2, and
`_check_program_exit_zero` reads rc 2 as VACUOUS_PASS: silently green. The `=`
form reaches provenance_check intact and its own glob branch FAILs
"no file on disk matches pattern". `test_declaration_form_fails_closed_*`
pins this.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import flow_compliance_check as _fcc                       # noqa: E402
import phase3_one_shot_runner as _runner                   # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_COARSE = "provenance_check . --require-entries 1"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _step37_gate_commands() -> list:
    doc = yaml.safe_load(FLOW.read_text())
    step = next(s for s in doc["steps"] if str(s.get("id")) == "37")
    return [m["program_exit_zero"] for m in step["gate"]["all_of"]
            if isinstance(m, dict) and "program_exit_zero" in m]


def _provenance_command() -> str:
    cmds = [c for c in _step37_gate_commands()
            if c.startswith("provenance_check")]
    assert len(cmds) == 1, f"expected exactly one provenance gate; got {cmds}"
    return cmds[0]


# ── (a) the declaration ─────────────────────────────────────────────────────

def test_step37_provenance_gate_is_not_the_coarse_counter():
    cmd = _provenance_command()
    assert "--require-entries" not in cmd, (
        "step 37 still uses provenance_check's coarse entry counter, which "
        "never looks at the GDS: it passes on any run that logged one "
        f"unrelated exit-0 tool invocation. gate: {cmd!r}")


def test_step37_provenance_gate_names_the_gds_and_its_streamers():
    cmd = _provenance_command()
    assert "phase3/stage4/gds/" in cmd and ".gds" in cmd, cmd
    for tool in ("klayout", "magic", "openroad"):
        assert tool in cmd, f"streamer {tool!r} missing from the gate: {cmd!r}"


def test_step37_provenance_gate_matches_the_other_five_gates_shape():
    """Direction-1 guard on consistency: every provenance gate in the flow now
    names an output and a tool allow-list."""
    text = FLOW.read_text()
    coarse = [ln.strip() for ln in text.splitlines()
              if "provenance_check" in ln and "--require-entries" in ln
              and ln.strip().startswith("-")]
    assert not coarse, (
        f"a coarse provenance gate is still declared in the flow: {coarse}")


# ── the declaration form must fail CLOSED under _expand_globs ───────────────

def _no_gds_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (project / "provenance.jsonl").write_text("")
    return project


def test_declaration_form_fails_closed_when_no_gds_exists(tmp_path):
    """THE nullglob trap. The shipped gate must FAIL, never vacuously pass."""
    project = _no_gds_project(tmp_path)
    passed, out = _fcc._check_program_exit_zero(project, _provenance_command())
    assert not passed, (
        f"step 37's provenance gate passed on a project with no GDS: {out!r}")
    assert "__VACUOUS_HINT__" not in out, (
        "the gate collapsed into a VACUOUS_PASS — the glob was dropped by "
        f"nullglob expansion before argparse saw it: {out!r}")


def test_space_separated_form_still_cannot_reach_the_honest_fail(tmp_path):
    """Why the `=` form: pin the measured failure of the obvious alternative,
    so nobody 'tidies' the declaration back into it.

    THE QUESTION WAS REWRITTEN, NOT THE BEHAVIOUR. This used to require the
    space form to produce `__VACUOUS_HINT__` — vacuously GREEN — because that
    was the only non-FAIL tier rc 2 could reach before `#1978`/`#1980`. The
    nullglob collapse is unchanged and still measured here: argparse never
    sees a value for `--output`, exits 2, and the step does NOT reach the
    honest FAIL that the shipped `=` form reaches on this same project. What
    changed is only the NAME of the tier it lands in instead — INCOMPLETE now,
    a disclosed non-verdict rather than a vacuous pass. Either way the gate
    concluded nothing, which is the whole reason the `=` form is required, so
    the premise this test guards is intact and is now asserted as the
    comparison it always was."""
    project = _no_gds_project(tmp_path)
    space_form = ("provenance_check . --output phase3/stage4/gds/*.gds "
                  "--tool klayout,magic,openroad")
    passed, out = _fcc._check_program_exit_zero(project, space_form)
    assert passed, (
        "premise changed: the space-separated form now FAILs on its own, so "
        f"the `=` form may no longer be required. got: {out!r}")
    cls = (out.split("reason_class=", 1)[1].split(";", 1)[0].strip()
           if "reason_class=" in out else None)
    assert cls not in _reason_taxonomy().SKIP_ELIGIBLE, out
    assert _step_tier(project, space_form) == "INCOMPLETE", out
    # ...against the shipped form on the SAME project, which is the point.
    shipped_passed, _ = _fcc._check_program_exit_zero(
        project, _provenance_command())
    assert not shipped_passed
    assert _step_tier(project, _provenance_command()) == "FAIL"


def _reason_taxonomy():
    import _flow_reason_taxonomy as T
    return T


def _step_tier(project, cmd):
    """The tier the STEP reaches through the slot the canonical flow wires
    `provenance_check` in — read through `check_step`, never re-derived."""
    step = {"id": "probe", "name": "one clause",
            "gate": {"all_of": [{"program_exit_zero": cmd}]}}
    return _fcc.check_step(project, step, {}).status


def test_the_nullglob_collapse_is_not_laundered_by_a_relabel(tmp_path):
    """THE ASSERTION THAT REDDENS IF THE CLASSIFICATION MOVES AGAIN.

    argparse rejecting its own command line is the reference EXECUTION_ERROR.
    If a future recogniser books it skip-eligible, the step certifies again on
    a project with no GDS at all — the exact defect the `=` form was written
    for — so pin the class and the consequence together."""
    T = _reason_taxonomy()
    project = _no_gds_project(tmp_path)
    space_form = ("provenance_check . --output phase3/stage4/gds/*.gds "
                  "--tool klayout,magic,openroad")
    _, out = _fcc._check_program_exit_zero(project, space_form)
    cls = out.split("reason_class=", 1)[1].split(";", 1)[0].strip()
    assert cls == T.EXECUTION_ERROR, out
    assert "expected one argument" in out, out


# ── behavioural discriminators on a fixture that mirrors the real run ───────

def _shipped_project(tmp_path: Path, top: str = "chip_top", *,
                     stale: bool) -> Path:
    """Recreate the measured shape: a stage4 GDS whose declared hash belongs to
    a previous write, and a pnr stream-out with no record at all."""
    project = tmp_path / "proj"
    pnr = project / "phase3" / "stage3" / "pnr"
    gds4 = project / "phase3" / "stage4" / "gds"
    pnr.mkdir(parents=True)
    gds4.mkdir(parents=True)
    old = b"\x00\x06\x00\x02PREVIOUS" + b"\x11" * 300
    new = b"\x00\x06\x00\x02THIS-RUN" + b"\x22" * 600
    (pnr / f"{top}.gds").write_bytes(new)
    (gds4 / f"{top}.gds").write_bytes(new)
    declared = _sha(old) if stale else _sha(new)
    (project / "provenance.jsonl").write_text(json.dumps({
        "tool": "klayout",
        "command": "klayout streamout (canonical GDS)",
        "exit_code": 0, "duration_ms": None, "reconstructed": True,
        "timestamp": "2026-07-26T14:52:15Z",
        "outputs": {f"phase3/stage4/gds/{top}.gds": declared},
    }) + "\n")
    return project


def test_gate_reds_a_gds_whose_declared_hash_is_stale(tmp_path):
    """THE discriminator, and the true finding on the real run."""
    project = _shipped_project(tmp_path, stale=True)
    passed, out = _fcc._check_program_exit_zero(project, _provenance_command())
    assert not passed, out
    assert "hash mismatch" in out, out


def test_coarse_form_would_have_passed_the_same_project(tmp_path):
    """Pin what the OLD declaration did on the same bytes: unrelated entries
    are enough. Without this the fix could be mistaken for a no-op."""
    project = _shipped_project(tmp_path, stale=True)
    with (project / "provenance.jsonl").open("a") as f:
        f.write(json.dumps({"tool": "yosys", "exit_code": 0,
                            "outputs": {}}) + "\n")
    passed, out = _fcc._check_program_exit_zero(project, _COARSE)
    assert passed, (
        f"premise: the coarse counter must pass on this project; got {out!r}")


# ── (b) the producer ────────────────────────────────────────────────────────

def test_producer_restamps_the_shipped_gds_so_the_honest_gate_passes(tmp_path):
    project = _shipped_project(tmp_path, stale=True)
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    passed, out = _fcc._check_program_exit_zero(project, _provenance_command())
    assert passed, (
        f"after the producer re-stamp the honest gate must pass: {out!r}")


def test_producer_declares_the_pnr_streamout_too(tmp_path):
    """phase3/stage3/pnr/<top>.gds is the layout DRC and LVS actually verified
    and had NO record on the real run."""
    project = _shipped_project(tmp_path, stale=True)
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    passed, out = _fcc._check_program_exit_zero(
        project,
        "provenance_check . --output=phase3/stage3/pnr/chip_top.gds "
        "--tool=magic,klayout,openroad")
    assert passed, out


def test_producer_supersedes_a_stale_record_without_amending_it(tmp_path):
    """The producer appends a record of the bytes it just shipped; the stale
    record stays in the ledger as history.

    This used to require patching IN PLACE, on the grounds that appending
    "would trade PROVENANCE_HASH_MISMATCH for PROVENANCE_HASH_INCONSISTENT —
    both FAIL". That was a property of the old checker, and paying for it with
    an in-place edit is what made a tampered artefact indistinguishable from a
    re-emitted one. The checker now judges a path by its NEWEST record."""
    from provenance_output_hash_completeness_check import audit
    project = _shipped_project(tmp_path, stale=True)
    before = (project / "provenance.jsonl").read_text().splitlines()
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    lines = [l for l in (project / "provenance.jsonl")
             .read_text().splitlines() if l.strip()]
    assert lines[:len(before)] == before, "history was amended"
    assert len(lines) > len(before), "no superseding record was appended"
    rel = "phase3/stage4/gds/chip_top.gds"
    declared = [json.loads(l)["outputs"][rel] for l in lines
                if rel in json.loads(l).get("outputs", {})]
    assert declared[-1] != declared[0], (
        "the stale declaration must have been superseded by a newer one")
    assert declared[-1] == "sha256:" + hashlib.sha256(
        (project / rel).read_bytes()).hexdigest(), (
        "the NEWEST declaration must carry the digest of the shipped bytes")
    verdict, findings = audit(project)
    assert not [f for f in findings if f.severity == "ERROR"], findings
    assert verdict == "PASS", [(f.rule, f.detail) for f in findings]


def test_producer_is_idempotent(tmp_path):
    """A second call must add nothing. A producer that appends unconditionally
    would grow the ledger on every pass."""
    project = _shipped_project(tmp_path, stale=True)
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    first = (project / "provenance.jsonl").read_text()
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    second = (project / "provenance.jsonl").read_text()
    assert second == first, "the second call must be a no-op"
    assert first.count("phase3/stage4/gds/chip_top.gds") == 2, (
        "expected the superseded declaration plus the current one")


def test_producer_never_declares_a_file_that_does_not_exist(tmp_path):
    """#365 anti-fabrication: no record may be written for an absent artefact
    — the gate must still FAIL correctly on a run that produced nothing."""
    project = tmp_path / "proj"
    (project / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (project / "provenance.jsonl").write_text("")
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    text = (project / "provenance.jsonl").read_text()
    assert ".gds" not in text, (
        f"a GDS that was never produced must not be declared: {text!r}")
    passed, _ = _fcc._check_program_exit_zero(project, _provenance_command())
    assert not passed


def test_producer_refuses_to_attribute_a_foreign_canonical_gds(tmp_path):
    """Anti-laundering. If the file at the canonical path is NOT byte-identical
    to this pipeline's stream-out, the producer must leave it undeclared and
    let Step 37 FAIL, rather than re-hash whatever is lying around and call it
    a klayout streamout."""
    project = _shipped_project(tmp_path, stale=True)
    (project / "phase3/stage4/gds/chip_top.gds").write_bytes(
        b"\x00\x06\x00\x02FOREIGN-DROP" + b"\x33" * 900)
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    foreign = _sha((project / "phase3/stage4/gds/chip_top.gds").read_bytes())
    text = (project / "provenance.jsonl").read_text()
    assert foreign not in text, (
        "a file the pipeline did not produce must not be declared as its "
        f"stream-out: {text!r}")
    passed, out = _fcc._check_program_exit_zero(project, _provenance_command())
    assert not passed, out


def test_producer_records_are_flagged_reconstructed_with_null_duration(
        tmp_path):
    """#365: a back-filled record must say 'not measured', never `0`."""
    project = _shipped_project(tmp_path, stale=True)
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    recs = [json.loads(l) for l in
            (project / "provenance.jsonl").read_text().splitlines() if l.strip()]
    pnr = [r for r in recs
           if "phase3/stage3/pnr/chip_top.gds" in (r.get("outputs") or {})]
    assert pnr, recs
    assert pnr[0]["reconstructed"] is True
    assert pnr[0]["duration_ms"] is None


def test_producer_rehashes_never_copies_an_old_digest(tmp_path):
    """The declared hash must be recomputed from disk. If it were copied from
    the stale record the gate would still fail — assert the actual bytes."""
    project = _shipped_project(tmp_path, stale=True)
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    shipped = (project / "phase3/stage4/gds/chip_top.gds").read_bytes()
    assert _sha(shipped) in (project / "provenance.jsonl").read_text()


def test_producer_is_wired_into_step_canonicalize_artefacts():
    """Every behavioural test above calls the helper directly, so all of them
    pass even if the runner never calls it. The wiring is what ships."""
    import ast
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef)
               and n.name == "step_canonicalize_artefacts"), None)
    assert fn is not None, "premise: the canonicalisation step was renamed"
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_step37_declare_streamout_gds_provenance"
               for n in ast.walk(fn)), (
        "step_canonicalize_artefacts must declare Step 37's GDS provenance on "
        "every path through the alias block, not only when it just copied")


# ── direction-1 guards ─────────────────────────────────────────────────────

def test_guard_coarse_mode_remains_a_public_api(tmp_path):
    """`--require-entries` is still provenance_check's documented coarse mode
    and is used by its own tests; removing the gate must not remove the mode."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "provenance.jsonl").write_text(json.dumps(
        {"tool": "yosys", "exit_code": 0, "outputs": {}}) + "\n")
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "provenance_check.py"), str(project),
         "--require-entries", "1"], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "exit-0 entries OK" in cp.stdout


def test_guard_an_honest_run_still_passes(tmp_path):
    """A run whose declared hash already matches must stay green under the
    shipped gate. Passes on BOTH trees."""
    project = _shipped_project(tmp_path, stale=False)
    passed, out = _fcc._check_program_exit_zero(project, _provenance_command())
    assert passed, out


def test_producer_leaves_an_already_honest_run_green(tmp_path):
    """NOT a direction-1 guard — calls the new helper, so it correctly fails on
    the base tree. Asserts the producer is a no-op on a correct ledger."""
    project = _shipped_project(tmp_path, stale=False)
    before = (project / "provenance.jsonl").read_text()
    _runner._step37_declare_streamout_gds_provenance(project, "chip_top")
    passed, out = _fcc._check_program_exit_zero(project, _provenance_command())
    assert passed, out
    after = (project / "provenance.jsonl").read_text()
    assert after.count("phase3/stage4/gds/chip_top.gds") == \
        before.count("phase3/stage4/gds/chip_top.gds") == 1


def test_guard_wrong_tool_attribution_still_fails(tmp_path):
    """The tool allow-list must remain load-bearing."""
    project = _shipped_project(tmp_path, stale=False)
    passed, out = _fcc._check_program_exit_zero(
        project,
        "provenance_check . --output=phase3/stage4/gds/*.gds --tool=netgen")
    assert not passed, out


def test_guard_original_restamp_helper_still_works(tmp_path):
    """`_step37_restamp_canon_gds_provenance` keeps its signature and effect —
    test_canonical_gds_provenance_restamp.py calls it directly."""
    project = _shipped_project(tmp_path, stale=True)
    canon = project / "phase3/stage4/gds/chip_top.gds"
    _runner._step37_restamp_canon_gds_provenance(project, "chip_top", canon)
    assert _sha(canon.read_bytes()) in \
        (project / "provenance.jsonl").read_text()
