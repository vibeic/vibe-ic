"""vibe-ic#538 — MERGE_OK must not be answered over 5 of 34 hygiene gates.

`gatekeeper_review` is what a maintainer runs before every push, and MERGE_OK
reads as "this will land green". Measured at v1.7.92 it was not:

    tools/ci/repo_hygiene_gates.sh wires        34 gate invocations
    gatekeeper_review.review() ran              17 gates of its own
    present in BOTH                              5
    in CI and invisible to the merge gate       29

Twice in one day the verdict was wrong. v1.7.89 was MERGE_OK and main went RED
on `published_record_staleness_check`. v1.7.92 was MERGE_OK while `INDEX.md`
was stale, and was caught only because the maintainer had by then taken to
running the hygiene script BY HAND — a step that appears in no skill, runbook
or agent file.

WHAT THESE TESTS PIN, AND WHAT THEY DELIBERATELY DO NOT
=======================================================
The repair is that the merge gate INVOKES the hygiene script instead of
carrying a second copy of its gate list. So the tests here never assert a
LITERAL COUNT of gates — a test that said `34` would have to be edited every
time CI grows a gate, which is the same hand-maintained-list defect one level
up. Every count below is DERIVED on both sides and compared:

    the record the script emits  ==  the `run` lines a parser finds in it

Adding a gate to CI moves both numbers together and no test needs touching;
wiring a gate through some new wrapper that skips the recording moves only one,
and that is red.

They also pin the OTHER direction, which is NOT a hole: the ten gates that
judge the LANDING rather than the tree (is this exactly one commit ahead of
main, is the version bump monotonic, does any commit message carry an NDA
token) stay merge-only. CI cannot meaningfully ask those questions, and
"fixing" that asymmetry would be a regression.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_test_module(name: str):
    """Import a sibling TEST module for its fixture builders (not its tests)."""
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


GR = _load("gatekeeper_review")
#: The parser `gate_discloses_denominator_check` and `gate_host_independence_
#: check` already use over this same script. Imported rather than re-written so
#: this file does not become a third copy of it.
GD = _load("gate_discloses_denominator_check")


# --------------------------------------------------------------------------
# fixture helpers — a throwaway hygiene script that sources the REAL dispatch
# library, so these tests exercise the recording code that actually runs in CI
# rather than a copy of it.
# --------------------------------------------------------------------------
def _fixture_script(root: Path, gate_lines: str) -> Path:
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        PLUGIN="{_PROGRAMS.parent}"
        PG="{_PROGRAMS}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + gate_lines + "\ngate_dispatch_finish\n")
    return script


def _code_only(path: Path) -> str:
    """The module's executable substance: identifiers and non-docstring string
    literals, with comments and docstrings removed."""
    import ast
    tree = ast.parse(path.read_text())
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_nodes.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in doc_nodes:
                out.append(node.value)
        elif isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            out.append(node.name)
    return "\n".join(out)


def _probe(root: Path, name: str, body: str) -> Path:
    p = root / f"{name}.py"
    p.write_text(textwrap.dedent(body))
    return p


# ==========================================================================
# 1. THE COVERAGE IS DERIVED, NOT DUPLICATED
# ==========================================================================
def test_the_scripts_own_record_enumerates_every_gate_a_parser_finds():
    """The denominator the merge gate reports == the gate list in the script.

    This is the anti-drift assertion, and it is why nothing here says "34":
    both sides are derived from the same file by different means — one by
    EXECUTING it (`--list`, which records through the same `_dispatch` every
    real run goes through) and one by PARSING it. A gate wired through a
    wrapper that bypassed the recording would appear on the parser side only.
    """
    parsed = {label for label, _wd, _cmd in GD.parse_gates(_SCRIPT)}
    assert parsed, "the parser found no gates in the real hygiene script"

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "record.json"
        # A real file, not `/dev/stdout`: `--list` also prints the labels, and
        # recovering the document by slicing at the first "{" would break the
        # moment a gate label contained one.
        out = subprocess.run(
            ["bash", str(_SCRIPT), "--list", "--summary-json", str(rec)],
            cwd=str(_REPO), capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        doc = json.loads(rec.read_text())
    recorded = {g["label"] for g in doc["gates"]}

    assert recorded == parsed, (
        "the hygiene script's own coverage record and its `run` lines "
        f"disagree; only-recorded={sorted(recorded - parsed)} "
        f"only-parsed={sorted(parsed - recorded)}")
    assert doc["declared"] == len(parsed)


def test_a_gate_added_to_ci_is_covered_with_no_edit_to_the_merge_gate():
    """The point of invoking rather than re-listing.

    A brand-new gate nobody told `gatekeeper_review` about must still be able
    to turn the verdict red. If this ever needed an edit to the merge gate,
    the second hand-maintained list would be back.
    """
    assert "repo_hygiene_gates.sh" in GR.__doc__
    # Judged on CODE, not on prose. The module deliberately NAMES the two
    # incidents in its comments — `published_record_staleness_check` is why
    # v1.7.89 went red — and a rule that could not tell an explanation from a
    # duplicated list would push the next author to delete the explanation.
    # Comments never reach the AST; docstrings are dropped explicitly; every
    # other string literal and identifier stays, which is the shape a real
    # copied gate list would take (`_PROGRAMS_DIR / "<name>.py"`).
    src = _code_only(_PROGRAMS / "gatekeeper_review.py")
    # The merge gate must not name the hygiene gates one by one. It legitimately
    # runs five of them itself against `--plugin-root`; anything BEYOND those
    # would be the copied list.
    own = {"source_chip_agnostic_check", "shipped_path_portability_check",
           "loop_watchdog_compliance_check", "marketplace_version_sync_check",
           "plugin_full_audit"}
    hygiene_programs = set()
    for _label, _wd, cmd in GD.parse_gates(_SCRIPT):
        for tok in cmd.split():
            # Unquote FIRST. The repo-root gates are written `"$PG/x.py"`, so a
            # suffix test before stripping sees a trailing quote and collects
            # only the eight plugin-relative gates — which left this assertion
            # blind to 26 of the 34 and let a mutation walk straight through it.
            tok = tok.strip('"')
            if tok.endswith(".py"):
                hygiene_programs.add(Path(tok).stem)
    assert len(hygiene_programs) >= 25, (
        f"only {len(hygiene_programs)} hygiene program name(s) recovered from "
        "the script — this assertion would be near-vacuous")
    leaked = sorted(p for p in (hygiene_programs - own) if p in src)
    assert not leaked, (
        "gatekeeper_review names hygiene gate program(s) directly instead of "
        f"invoking the script: {leaked} — that is the duplicated list #538 "
        "exists to remove")


def test_the_merge_gate_really_EXECUTES_the_script():
    """Proof of invocation, not of a plausible-looking summary.

    A gate that fabricated a record would pass every count assertion above.
    This one makes the fixture gate leave a side effect on disk.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        witness = root / "the_gate_ran"
        _probe(root, "p_touch", f"""
            from pathlib import Path
            Path({str(witness)!r}).write_text("ran")
            print("PASS (1 item(s) examined)")
        """)
        script = _fixture_script(
            root, f'run "touch" "$ROOT" python3 "{root}/p_touch.py"\n')
        res = GR.repo_hygiene_gate(root, script=script)
        # Read INSIDE the context manager: the witness lives under the
        # temporary directory, which is removed on exit.
        assert res.rc == 0, res.summary
        assert witness.read_text() == "ran", \
            "the hygiene script was never executed"


# ==========================================================================
# 2. A RED HYGIENE GATE REFUSES THE LANDING
# ==========================================================================
#: The minimal plugin tree `test_gatekeeper_review` already builds so the
#: file-walking gates report PASS quickly. Imported rather than re-created:
#: it has to track `plugin_full_audit`'s D2 guard list, and a second copy
#: would silently stop tracking it.
_TGR = _load_test_module("test_gatekeeper_review")


def _review_over(repo: Path, plugin: Path, script: Path):
    """Drive the full `review()` with a synthetic change-set, so the assertion
    is about the VERDICT a maintainer reads, not about one gate in isolation.

    `plugin_root` is the SYNTHETIC tree, not the real one: against the real
    plugin each of these took ~40s (`plugin_full_audit` alone is 52s there),
    and CI allows 180s per test on runners slower than this box. What is being
    asserted is `review()`'s aggregation of gate results into a verdict, which
    the synthetic root exercises identically.
    """
    return GR.review("HEAD", "HEAD", repo=repo, plugin_root=plugin,
                     override_files=["README.md"], override_cur=None,
                     override_prev=None, hygiene_script=script)


def test_a_failing_hygiene_gate_makes_the_verdict_REQUEST_CHANGES(tmp_path):
    root, plugin = _TGR._build_clean_plugin(tmp_path)
    _probe(root, "p_bad", """
        import sys
        print("found a defect")
        sys.exit(1)
    """)
    script = _fixture_script(
        root, f'run "a red gate" "$ROOT" python3 "{root}/p_bad.py"\n')
    v = _review_over(root, plugin, script)
    assert v.verdict == "REQUEST_CHANGES", v.gates
    assert any("repo_hygiene_gates" in b and "a red gate" in b
               for b in v.blocking), v.blocking


def test_a_clean_tree_still_returns_MERGE_OK(tmp_path):
    """No false alarm: the gate must not be a permanent red that gets ignored."""
    root, plugin = _TGR._build_clean_plugin(tmp_path)
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    script = _fixture_script(
        root, f'run "a green gate" "$ROOT" python3 "{root}/p_ok.py"\n')
    v = _review_over(root, plugin, script)
    hyg = [g for g in v.gates if g.name == "repo_hygiene_gates"]
    assert len(hyg) == 1 and hyg[0].rc == 0, [(g.name, g.rc) for g in v.gates]
    assert v.verdict == "MERGE_OK", v.blocking


# ==========================================================================
# 3. THE VERDICT SAYS WHAT IT DID NOT RUN
# ==========================================================================
def test_a_gate_that_refused_is_reported_apart_from_the_ones_that_passed(tmp_path):
    """`NOT_CHECKED` is never folded into the pass count.

    `run_tolerating_uncheckable` exists because a probe needing a clean tree
    must not fail a developer whose tree has scratch in it — but "I could not
    look" must not reach a reader as "I looked and it was clean". This is the
    `_vacuous_exit` convention applied to the hygiene set as a whole.
    """
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    _probe(root, "p_refuse", """
        import sys
        print("cannot look: the tree is dirty")
        sys.exit(2)
    """)
    script = _fixture_script(root, (
        f'run "a green gate" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run_tolerating_uncheckable "a refusing gate" "$ROOT" '
        f'python3 "{root}/p_refuse.py"\n'))
    res = GR.repo_hygiene_gate(root, script=script)
    assert res.rc == 0                      # non-blocking, as CI treats it
    assert "NOT CHECKED" in res.summary and "a refusing gate" in res.summary, \
        res.summary
    assert "not a pass" in res.summary


def test_the_summary_always_states_its_denominator(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (0 item(s) examined)")\n')
    script = _fixture_script(root, (
        f'run "one" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run "two" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run "three" "$ROOT" python3 "{root}/p_ok.py"\n'))
    res = GR.repo_hygiene_gate(root, script=script)
    assert "3/3" in res.summary, res.summary


def test_a_hygiene_script_that_wires_NOTHING_is_not_a_pass(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    script = _fixture_script(root, "# no gates at all\n")
    res = GR.repo_hygiene_gate(root, script=script)
    assert res.rc == 2 and not GR.GateResult("x", res.rc, "").green, res.summary
    assert "0 gates" in res.summary


def test_a_missing_hygiene_script_says_it_consulted_zero_gates(tmp_path):
    res = GR.repo_hygiene_gate(tmp_path / "no-such-tree")
    assert res.rc == -1
    assert "0 gate(s) consulted" in res.summary, res.summary


def test_a_run_that_never_finished_is_an_ERROR_not_a_pass(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_slow", "import time; time.sleep(60)\n")
    script = _fixture_script(
        root, f'run "slow" "$ROOT" python3 "{root}/p_slow.py"\n')
    res = GR.repo_hygiene_gate(root, script=script, timeout=2)
    assert res.rc == 2 and "did not finish" in res.summary, res.summary


# ==========================================================================
# 4. NO SKIP BUTTON
# ==========================================================================
def test_the_cli_offers_no_way_to_skip_the_hygiene_set():
    """The seam that points at a fixture script is a function kwarg only.

    A command-line flag to skip or redirect the hygiene set would be a skip
    button on the one gate whose entire purpose is that it cannot be
    forgotten — which is how v1.7.92 nearly went red twice.
    """
    out = subprocess.run([sys.executable,
                          str(_PROGRAMS / "gatekeeper_review.py"), "--help"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for forbidden in ("--hygiene", "--skip-hygiene", "--no-hygiene"):
        assert forbidden not in out.stdout, (
            f"{forbidden} is reachable from the CLI — that is a skip button")


# ==========================================================================
# 5. THE OTHER DIRECTION IS NOT A HOLE
# ==========================================================================
#: Gates that judge the LANDING, not the tree. CI cannot meaningfully ask "is
#: this exactly one commit ahead of main", so these are merge-gate-only BY
#: DESIGN. Listed here so that "fixing" the asymmetry — pushing them into the
#: repo-hygiene script, where they would be vacuous — turns a test red instead
#: of looking like an improvement.
_LANDING_ONLY = (
    "landing_is_one_commit_check", "version_bump_monotonic_check",
    "gatekeeper_stale_branch_check", "nda_diff_scan_check",
    "commit_msg_nda_check", "acceptance_control_check", "blindness_audit",
    "full_suite_run_check", "run_output_completeness_check",
    "real_artefact_test_backing_check",
)


@pytest.mark.parametrize("gate", _LANDING_ONLY)
def test_landing_shaped_gates_stay_out_of_the_repo_hygiene_lane(gate):
    body = _SCRIPT.read_text()
    for label, _wd, cmd in GD.parse_gates(_SCRIPT):
        assert gate not in cmd, (
            f"{gate} judges the LANDING (a base..head range), not the tree; "
            f"wired into the repo-hygiene lane as {label!r} it would have no "
            f"range to judge and would report a vacuous clean result")
    assert body  # the script was actually read


# ==========================================================================
# 6. THE v1.7.92 INCIDENT, REPRODUCED AGAINST THE REAL TREE
# ==========================================================================
def test_a_new_program_without_a_regenerated_index_is_refused():
    """The v1.7.92 state, end to end through the merge gate.

    A program is added and `INDEX.md` is not regenerated — exactly what
    happened, and exactly what `gatekeeper_review` answered MERGE_OK over. The
    gate that catches it (`tools/gen_programs_index.py --check`) is one of the
    six in the hygiene set whose filename ends in neither `_check` nor
    `_audit`, so it is invisible to a name-shaped derivation of the gate list;
    only invoking the script reaches it.

    Uses the REAL gate against the REAL tree — the probe program is written
    into the live `programs/` directory and removed in `finally`, which is the
    technique `test_gate_discloses_denominator.py` already uses for the same
    reason: a fixture cannot prove a gate reads the artefacts it ships to read.
    """
    import tempfile
    # NOT `_probe_…`: `gen_programs_index._is_helper` skips any name starting
    # with an underscore, so the underscore-prefixed probe the neighbouring
    # denominator test uses would leave the index legitimately fresh and this
    # test would pass while proving nothing. Caught by the (a) control below,
    # which is the reason it is there.
    probe = _PROGRAMS / "probe_issue538_unindexed_throwaway.py"
    line = ('run "programs index fresh" "$ROOT" '
            f'python3 "{_REPO}/tools/gen_programs_index.py" --check\n')
    try:
        with tempfile.TemporaryDirectory() as td:
            script = _fixture_script(Path(td), line)

            # (a) control — before the program exists, the index is fresh.
            before = GR.repo_hygiene_gate(_REPO, script=script)
            assert before.rc == 0, (
                "the index was ALREADY stale before this test touched "
                f"anything, so it proves nothing: {before.summary}")

            # (b) the incident — a new program, no regenerated index.
            probe.write_text('"""throwaway (vibe-ic#538 test)."""\n')
            after = GR.repo_hygiene_gate(_REPO, script=script)
    finally:
        if probe.exists():
            probe.unlink()

    assert after.rc == 1, (
        "the merge gate did NOT refuse a landing that adds a program without "
        f"regenerating INDEX.md — this is the v1.7.92 state: {after.summary}")
    assert "programs index fresh" in after.summary


# ==========================================================================
# 7. vibe-ic#539 — THE ROLL-UP MUST NOT PRINT A SENTENCE THAT IS FALSE
# ==========================================================================
def _run_fixture_script(root: Path, gate_lines: str):
    script = _fixture_script(root, gate_lines)
    return subprocess.run(["bash", str(script)], cwd=str(root),
                          capture_output=True, text=True, timeout=60)


def test_the_rollup_does_not_claim_all_passed_when_a_gate_refused(tmp_path):
    """#539: `gate_host_independence_check` said, in those words, "This is not
    a pass" and exited 2, and the aggregation printed `all gates passed` over
    it. The gate was honest; the roll-up was not, and it is the roll-up a
    reader believes.

    The refusing gates must also be NAMED. A bare count cannot answer the only
    question a reader has — was it the gate I cared about?
    """
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    _probe(root, "p_refuse", """
        import sys
        print("DIRTY_CHECKOUT: this is not a pass")
        sys.exit(2)
    """)
    out = _run_fixture_script(root, (
        f'run "a green gate" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run_tolerating_uncheckable "gates are host-independent" "$ROOT" '
        f'python3 "{root}/p_refuse.py"\n'))
    text = out.stdout + out.stderr
    assert "all gates passed" not in text, (
        "the roll-up still claims every gate passed while one REFUSED — "
        f"that is the false sentence #539 is about:\n{text}")
    # Scoped to the ROLL-UP LINE, not to the whole stream. `_dispatch` already
    # echoes a `── <label>` header for every gate, so asserting over all of
    # stdout is satisfied by that header and says nothing about whether the
    # summary names the refusal — a mutation replacing the name with "(some
    # gate)" walked straight through the unscoped version of this assertion.
    rollup = [ln for ln in out.stdout.splitlines()
              if ln.startswith("repo_hygiene_gates:")]
    assert len(rollup) == 1, f"expected exactly one roll-up line:\n{text}"
    assert "1 of 2 gate(s) passed" in rollup[0], rollup[0]
    assert "gates are host-independent" in rollup[0], (
        "the refusing gate is not NAMED in the roll-up; a bare count cannot "
        f"tell a reader whether the gate they care about ran:\n{rollup[0]}")
    assert "NOT a pass" in rollup[0], rollup[0]
    # rc stays 0 ON PURPOSE — see `gate_dispatch_finish`. A maintainer whose
    # tree is dirty by construction must not face a permanently red script,
    # because a permanently red gate is a skipped gate.
    assert out.returncode == 0, text


def test_the_unqualified_sentence_survives_when_nothing_refused(tmp_path):
    """The other half: the fix must not make the clean case read as degraded."""
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    out = _run_fixture_script(root, (
        f'run "one" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run "two" "$ROOT" python3 "{root}/p_ok.py"\n'))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all 2 gate(s) passed" in out.stdout, out.stdout
    assert "NOT CHECKED" not in out.stdout
