"""vibe-ic#1382 — the 63x8 census is re-derived at LAND, and that step may fail.

#1382 measured `63x8 census freshness` blocking eleven of thirteen finished
landing batches on 2026-08-13, with every reported figure off by exactly one —
one gate added by one PR in the batch, and the derived figures never re-derived.
It put two readings and asked the repo to choose a DERIVATION POINT:

    (a) derive at LAND — the batch builder re-derives before gating, exactly as
        it already does for `programs/INDEX.md`;
    (b) derive at PUSH — move the check into `pre-push`, and accept a conflict
        on every gate-adding PR because the figures live in shared files that
        carry tree-wide counters.

This file pins (a). It is not a test that the census is CORRECT — the generator
owns that, and `repo_hygiene_gates.sh` still runs its `--check` on the tree this
step produces. It is a test of the three properties that make deriving here
safe, each of which has a way of being quietly lost:

    1. the step RUNS, and every path it writes is DECLARED to the boundary;
    2. an undeclared write is still REFUSED — the #1029/#1089 rule does not get
       an exception for the new step;
    3. a census that CANNOT be re-derived does not refuse the landing, and says
       so out loud instead of passing silently. On a contended host the
       generator fails for reasons no re-derivation reaches (#1277), so a fatal
       step would refuse every landing — strictly worse than the blocker it is
       meant to remove.

Cheap on purpose, like `test_issue1382_census_repair_is_one_invocation.py`
beside it: the writers are injected, so nothing here runs the three-minute
census. The behavioural proof that `--written-json` names the files the real
generator wrote lives in the PR body.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
MOD = PROGRAMS / "gatekeeper_prepare_landing.py"
REPO = Path(__file__).resolve().parents[5]
GEN = REPO / "tools" / "gen_flow_matrix_census.py"

INDEX_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
PJSON_REL = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"
CENSUS_REL = ("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
              "flow_matrix/README.md")
# An ANCHORED-FIGURE file, named as one of the corpus files `--fix` rewrites.
# Deliberately NOT the other one: the census corpus is discovered by content
# ("a typed list is a promise that nobody will add a document"), and a file that
# names that token joins the corpus it is testing.
ANCHOR_REL = ("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
              "test_matrix_d2_falsifiable.py")
MUTATED_FIGURE_REL = (Path("vibe-ic-marketplace/plugins/vibe-ic/programs/tests")
                      / "flow_matrix" / ("flow" + "ref.py"))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load(MOD, "_gpl_1382_under_test")


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """A real git repo carrying the paths the census generator writes."""
    r = tmp_path / "repo"
    for rel in (INDEX_REL, PJSON_REL, CENSUS_REL, ANCHOR_REL,
                MUTATED_FIGURE_REL):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
    (r / PJSON_REL).write_text('{"version": "1.2.3"}\n', encoding="utf-8")
    (r / INDEX_REL).write_text("stale index\n", encoding="utf-8")
    (r / CENSUS_REL).write_text("stale census block\n", encoding="utf-8")
    (r / ANCHOR_REL).write_text("stated = 164\n", encoding="utf-8")
    (r / MUTATED_FIGURE_REL).write_text("original figure source\n",
                                        encoding="utf-8")
    (r / "untouched.py").write_text("# not preparation's business\n",
                                    encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base commit, deliberately untagged")
    return r


def _index_writer(repo_path: Path):
    (repo_path / INDEX_REL).write_text("regenerated\n", encoding="utf-8")
    return [INDEX_REL]


def _version_writer(repo_path: Path, plugin: Path, old):
    (repo_path / PJSON_REL).write_text('{"version": "1.2.4"}\n',
                                       encoding="utf-8")
    return [PJSON_REL]


def _census_writer_ok(repo_path: Path):
    """The generator's success shape: both halves rewritten, both declared."""
    (repo_path / CENSUS_REL).write_text("fresh census block\n", encoding="utf-8")
    (repo_path / ANCHOR_REL).write_text("stated = 165\n", encoding="utf-8")
    return [CENSUS_REL, ANCHOR_REL], None


def _run(repo_path, **kw):
    kw.setdefault("do_commit", False)
    kw.setdefault("index_writer", _index_writer)
    kw.setdefault("version_writer", _version_writer)
    kw.setdefault("census_writer", _census_writer_ok)
    kw.setdefault("plugin_root",
                  repo_path / "vibe-ic-marketplace/plugins/vibe-ic")
    return G.prepare(repo_path, **kw)


# ---------------------------------------------------------------------------
# 1. THE DERIVATION HAPPENS HERE — reading (a), as executable behaviour
# ---------------------------------------------------------------------------
def test_preparation_re_derives_the_census_and_declares_what_it_wrote(repo):
    """Without this, #1382's contract is a comment rather than a step."""
    rc, notes, declared = _run(repo)
    assert rc == G.RC_OK, notes
    assert CENSUS_REL in declared, declared
    assert ANCHOR_REL in declared, declared
    assert (repo / ANCHOR_REL).read_text(encoding="utf-8") == "stated = 165\n"
    assert any("census re-derived" in n for n in notes), notes


def test_the_real_default_writer_is_wired_in_and_is_the_census_generator():
    """A test that only ever sees an injected writer cannot notice that the
    default was unplugged, which is how a fix stops reaching the code that runs.
    """
    assert G.GEN_CENSUS.name == "gen_flow_matrix_census.py", G.GEN_CENSUS

    # ASSERTED BY BEHAVIOUR, NOT BY SPELLING.
    #
    # This was `assert "census_writer or _default_census_writer" in src`. That
    # pinned one EXPRESSION, and v1.10.48 replaced it with an if/elif/else so a
    # census timeout could be passed to the default writer only — behaviour
    # identical, spelling different, test red. A source-text assertion cannot tell
    # a refactor from an unplugging, which is the one thing it exists to tell.
    #
    # So: call prepare() with NO census_writer and prove the real default ran, by
    # observing the only thing the real one does that no stand-in would — it
    # launches GEN_CENSUS as a subprocess.
    # Record EVERY launch, not just the first: the writer legitimately shells out
    # to `git` before the census (it snapshots what was already dirty), so a spy
    # that captures one Popen captures the wrong one.
    launches = []
    real_popen = G.subprocess.Popen

    def spy(cmd, *a, **kw):
        launches.append(list(cmd))
        if any(str(G.GEN_CENSUS) in str(x) for x in cmd):
            # It reached the census. That is the whole question — do not actually
            # run it; this test must not cost the census's own two-to-four minutes.
            raise RuntimeError("census reached")
        return real_popen(cmd, *a, **kw)

    G.subprocess.Popen = spy
    try:
        G._default_census_writer(G.REPO)
    except Exception:
        pass
    finally:
        G.subprocess.Popen = real_popen

    assert launches, (
        "the default census writer launched no subprocess at all, so a landing "
        "prepared by the shell script re-derives nothing")
    assert any(any(str(G.GEN_CENSUS) in str(x) for x in argv) for argv in launches), (
        f"the default writer ran {len(launches)} subprocess(es) and none of them "
        f"was the census generator: {launches}")


def test_the_default_writer_asks_the_generator_to_DECLARE_its_writes():
    """`--written-json` is the boundary's only honest source for this step.

    Reconstructing it from `git status` would forgive any concurrent edit; a
    typed allow-list would rot the moment the corpus gained a file, in the
    forgiving direction.
    """
    src = MOD.read_text(encoding="utf-8")
    assert "--written-json" in src, (
        "the census writer no longer asks the generator what it wrote")
    assert "--fix" in src, (
        "the census writer must run the COMPLETE repair; `--fix-figures` alone "
        "leaves the census block stale and the gate still red (#1382)")

    flags = {
        a.value
        for node in ast.walk(ast.parse(GEN.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "add_argument"
        for a in node.args
        if isinstance(a, ast.Constant) and isinstance(a.value, str)
    }
    assert "--written-json" in flags, (
        f"the generator does not offer --written-json, so the flag the "
        f"preparation passes is silently ignored. flags: {sorted(flags)}")


# ---------------------------------------------------------------------------
# 2. THE BOUNDARY GETS NO EXCEPTION FOR THE NEW STEP
# ---------------------------------------------------------------------------
def test_a_census_write_OUTSIDE_the_declared_set_is_REFUSED(repo):
    """#1029/#1089, applied to the step that was just added.

    The census generator reaches further than any other writer here — a whole
    corpus discovered by content — so it is the writer most able to leave a path
    nobody authorised.
    """
    def scribbles(repo_path: Path):
        (repo_path / "untouched.py").write_text("# EDITED\n", encoding="utf-8")
        (repo_path / CENSUS_REL).write_text("fresh\n", encoding="utf-8")
        return [CENSUS_REL], None          # declares ONLY the census block

    rc, notes, _ = _run(repo, census_writer=scribbles)
    assert rc == G.RC_REFUSED, notes
    assert any("OUTSIDE the set its writers declared" in n for n in notes), notes
    assert any("untouched.py" in n for n in notes), notes


def test_the_same_census_write_INSIDE_the_declared_set_is_allowed(repo):
    """The paired direction: identical edit, identical file — only the
    DECLARATION differs, and only that decides."""
    def declares_it(repo_path: Path):
        (repo_path / "untouched.py").write_text("# EDITED\n", encoding="utf-8")
        (repo_path / CENSUS_REL).write_text("fresh\n", encoding="utf-8")
        return [CENSUS_REL, "untouched.py"], None

    rc, notes, declared = _run(repo, census_writer=declares_it)
    assert rc == G.RC_OK, notes
    assert "untouched.py" in declared, declared


# ---------------------------------------------------------------------------
# 3. A CENSUS THAT CANNOT BE RE-DERIVED IS NOT A REFUSAL — AND NOT A SILENCE
# ---------------------------------------------------------------------------
def test_a_census_that_cannot_run_does_NOT_refuse_the_landing(repo):
    """The asymmetry with the index/version steps, as behaviour.

    On a contended host the generator fails for a reason no re-derivation
    reaches (#1277). If that refused the landing, every batch would be turned
    away by the step meant to unblock them.
    """
    rc, notes, _ = _run(
        repo,
        census_writer=lambda p: ([], "rc=1: the outcome run for "
                                     "test_matrix_d6_skip_discipline.py did "
                                     "not finish within 60s"))
    assert rc == G.RC_OK, notes


def test_a_census_that_cannot_run_SAYS_SO_and_never_reads_as_re_derived(repo):
    """An empty result is not a zero. `NOT RE-DERIVED` must be in the notes and
    `re-derived` must not, or the operator reads a failure as a repair."""
    rc, notes, _ = _run(
        repo, census_writer=lambda p: ([], "rc=1: could not drive the census"))
    assert rc == G.RC_OK, notes
    said = [n for n in notes if "NOT RE-DERIVED" in n]
    assert said, notes
    assert "could not drive the census" in said[0], said
    assert not any(n.startswith("63x8 census re-derived") for n in notes), notes


def test_a_PARTIAL_repair_declares_what_it_wrote_AND_still_reports_failure(repo):
    """`--fix` writes the anchors first and only then drives the census, so
    "wrote two files, then failed" is the NORMAL failure. Both facts must
    survive: the writes have to be attributable or the boundary refuses a
    landing over the step's own output, and the failure has to be visible or the
    operator reads a half-repair as a repair."""
    def partial(repo_path: Path):
        (repo_path / ANCHOR_REL).write_text("stated = 165\n", encoding="utf-8")
        return [ANCHOR_REL], "rc=1: README census block is stale"

    rc, notes, declared = _run(repo, census_writer=partial)
    assert rc == G.RC_OK, notes
    assert ANCHOR_REL in declared, declared
    assert any("NOT RE-DERIVED" in n and "1 file(s) written" in n
               for n in notes), notes


def test_an_EXCEPTION_in_the_census_writer_is_not_more_fatal_than_a_failure(repo):
    """A best-effort step that crashes must not out-rank the failure mode it is
    best-effort about, or the asymmetry above holds only for the errors somebody
    remembered to return."""
    def explodes(repo_path: Path):
        raise RuntimeError("generator vanished")

    rc, notes, _ = _run(repo, census_writer=explodes)
    assert rc == G.RC_OK, notes
    assert any("NOT RE-DERIVED" in n and "generator vanished" in n
               for n in notes), notes


# ---------------------------------------------------------------------------
# 4. THE READING THAT WAS *NOT* ADOPTED — pinned so a later change is deliberate
# ---------------------------------------------------------------------------
def test_the_expensive_check_is_not_moved_into_the_push_hook(repo):
    """Reading (b) was refused on measurement, not on taste: the anchored
    figures live in shared files carrying tree-wide counters, so per-PR
    re-derivation converts every gate-adding PR into a conflict with every
    other one — the pathology `programs/INDEX.md` already has and that
    `tools/resolve_generated_conflicts.sh` exists to clean up after.

    This does not forbid (b) forever. It makes adopting it a decision somebody
    takes with this test in front of them, rather than a line added to a hook.
    """
    hook = REPO / "tools" / "git-hooks" / "pre-push"
    if not hook.is_file():
        pytest.skip(f"no pre-push hook at {hook} — nothing to assert about")
    text = hook.read_text(encoding="utf-8")
    assert "gen_flow_matrix_census" not in text, (
        "the census check has been added to pre-push. Reading (b) of #1382 "
        "costs a guaranteed conflict on every gate-adding PR; if that is now "
        "the intended contract, change this test and say why in the PR.")


def test_the_written_json_declaration_survives_a_failing_run():
    """The generator must emit `--written-json` from a `finally`.

    On the success path a declaration is easy. The case that matters is the one
    that actually happens: anchors written, census blown, non-zero exit — and
    those writes still have to reach the boundary. A declaration emitted only
    after the census would leave exactly them unattributable.
    """
    tree = ast.parse(GEN.read_text(encoding="utf-8"))
    main = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main is not None, "gen_flow_matrix_census.py has no main()"
    finallys = [n for n in ast.walk(main)
                if isinstance(n, ast.Try) and n.finalbody]
    assert finallys, (
        "main() has no try/finally, so --written-json cannot be emitted on the "
        "failing path — which is the path that needs it")
    dumped = any("written_json" in ast.dump(stmt)
                 for t in finallys for stmt in t.finalbody)
    assert dumped, (
        "no finally block writes --written-json; a partial repair would leave "
        "its writes undeclared and the landing would be REFUSED over the "
        "preparation's own output")


def test_the_bound_on_the_census_subprocess_can_actually_fire(repo, monkeypatch):
    """An unbounded subprocess inside the landing path hangs the gate instead of
    reporting that it could not re-derive. The number is not the harness's
    `180 // 3` — nothing bounds this program with pytest — but it must exist and
    it must be finite."""
    assert isinstance(G.CENSUS_TIMEOUT_S, int), G.CENSUS_TIMEOUT_S
    assert 0 < G.CENSUS_TIMEOUT_S <= 3600, (
        f"CENSUS_TIMEOUT_S={G.CENSUS_TIMEOUT_S} — a bound longer than the whole "
        f"landing gate is a bound that cannot fire")
    src = MOD.read_text(encoding="utf-8")

    # ASSERTED BY BEHAVIOUR, NOT BY SPELLING.
    #
    # This was `assert "timeout=CENSUS_TIMEOUT_S" in src`. v1.10.48 renamed the
    # argument to `timeout_s` (defaulting to CENSUS_TIMEOUT_S) so the bound could
    # differ between the two callers, whose wall clocks are an order of magnitude
    # apart. The constant still reaches the subprocess; only its spelling at the
    # call site changed, and the old assertion could not tell those apart.
    #
    # The property is "a bound reaches the subprocess AND CAN FIRE", so fire it:
    # a 1-second bound must return promptly with a named reason and zero declared
    # paths, rather than hanging or claiming a re-derivation it did not do. The
    # write-capable probe operates on this test's temporary subject, never REPO.
    slow = repo / "_slow_census.py"
    slow.write_text(
        "import pathlib, sys, time\n"
        f"pathlib.Path(sys.argv[1]).joinpath({str(MUTATED_FIGURE_REL)!r})"
        ".write_text('changed by census\\n')\n"
        "time.sleep(30)\n",
        encoding="utf-8")
    monkeypatch.setattr(G, "GEN_CENSUS", slow)

    import time as _t
    t0 = _t.time()
    wrote, why = G._default_census_writer(repo, 1.0)
    dt = _t.time() - t0
    assert dt < 60, (
        f"a 1s bound took {dt:.0f}s to return — the bound is declared and not "
        f"actually applied to the subprocess")
    assert why and "did not finish" in why, (
        f"the bound fired but said nothing usable: {why!r}. A refusal that cannot "
        f"name itself sends the next reader to the wrong place")
    assert wrote == [], (
        f"the bound fired and the writer still declared {wrote} — a killed child's "
        f"`finally` never runs, so anything declared here is a claim about work "
        f"that was not finished")
    assert (repo / MUTATED_FIGURE_REL).read_text(
        encoding="utf-8") == "original figure source\n"

    assert "subprocess.TimeoutExpired" in src, (
        "a bound with no handler takes the preparation down instead of "
        "reporting NOT RE-DERIVED")


def test_the_bound_probe_never_points_a_writer_at_the_shipped_tree(
        repo, monkeypatch):
    """A pytest session may read the shipped census corpus, never rewrite it."""
    shipped_figure = REPO / MUTATED_FIGURE_REL
    before = shipped_figure.read_bytes()
    observed = []

    def observe_subject(repo_path: Path, timeout_s: float):
        observed.append(Path(repo_path).resolve())
        return [], f"the generator did not finish within {timeout_s}s"

    monkeypatch.setattr(G, "_default_census_writer", observe_subject)
    test_the_bound_on_the_census_subprocess_can_actually_fire(repo, monkeypatch)

    assert observed, "the timeout probe never reached the census writer"
    assert observed[0] != G.REPO.resolve(), (
        f"the timeout probe pointed a writer at the shipped tree: {observed[0]}. "
        "A pytest session may read that tree but must use a temporary subject "
        "for every write-capable probe")
    assert shipped_figure.read_bytes() == before, (
        "the timeout probe changed the shipped figure source during this pytest "
        "session")


def test_a_blown_bound_is_reported_as_the_bound_and_not_as_a_finding(repo):
    """A timeout is neither a pass nor a failure of the tree. It must name the
    bound, so nobody reads it as a defect in the batch."""
    def times_out(repo_path: Path):
        return [], f"the generator did not finish within {G.CENSUS_TIMEOUT_S}s"

    rc, notes, _ = _run(repo, census_writer=times_out)
    assert rc == G.RC_OK, notes
    assert any(f"did not finish within {G.CENSUS_TIMEOUT_S}s" in n
               for n in notes), notes


def test_the_declaration_reader_never_invents_a_path(tmp_path):
    """`_read_written` is fed a file the generator may never have written. It
    must return an EMPTY declaration rather than guessing — an invented path is
    a path the boundary would then forgive."""
    missing = tmp_path / "nope.json"
    assert G._read_written(missing) == []

    junk = tmp_path / "junk.json"
    junk.write_text("not json at all", encoding="utf-8")
    assert G._read_written(junk) == []

    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert G._read_written(wrong) == []

    good = tmp_path / "good.json"
    good.write_text(json.dumps([CENSUS_REL]), encoding="utf-8")
    assert G._read_written(good) == [CENSUS_REL]
