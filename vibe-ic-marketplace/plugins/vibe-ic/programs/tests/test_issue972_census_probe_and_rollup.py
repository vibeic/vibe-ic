#!/usr/bin/env python3
"""vibe-ic#972 — two defects the empty-tree probe was reporting as one.

RE-MEASURED on ``origin/main`` at ``6525cf05`` before anything was changed, and
the issue's headline symptom did NOT reproduce:

    gate_discloses_denominator_check --population ci   rc 0, PASS,
                                                       0 findings,
                                                       50 probed / 74 declared
    tools/gen_matrix_63x8_census.py --check
      launched with cwd inside an EMPTY git repository:
        [PASS] 63x8 census fresh: 504 cells over 8 dimensions; ...
        real 1m50.203s

1m50 is UNDER the probe's 120s bound, so nothing timed out and no
GATE_UNRUNNABLE was raised. The issue was written against a 2m07s measurement;
#978 (``38598e89``) has since changed the program and the number moved.

WHAT IS STILL TRUE, AND IS WHAT THESE TESTS PIN
===============================================
The two DEFECTS the issue names are both real, and neither one is a timing
fact:

(a) THE CENSUS ANSWERED FOR THE WRONG TREE. Look at what that measurement says:
    504 cells over 8 dimensions, from a directory holding one file. Every path
    in the program resolved off ``__file__``, the CI declaration handed it no
    subject at all, and so the answer did not depend on the input. The 110
    seconds were the symptom; a check that cannot be pointed anywhere is the
    defect, and it is the campaign's own subject. It also sat 8% under the
    bound, so any slower host does report it as unrunnable — the issue's
    measurement was not wrong, it was taken on a slower one.

(b) "UNRUNNABLE" WAS COUNTED AS "PASSED WITHOUT DISCLOSING". Both verdict lines
    in ``gate_discloses_denominator_check`` reported ``len(findings)`` under one
    sentence describing one kind, and named no gate. A run whose only finding is
    a GATE_UNRUNNABLE printed "1 gate(s) ... answer PASS over an empty tree
    without disclosing it" — a claim about an output that never existed.

Every fixture here is DISCOVERED: the census's command line is read out of the
tree that really launches it — the CI script through the repo's own parser and
expander, and the landing driver by DRIVING it with its launcher stubbed. A
hand-written copy of either would pass while the real wiring stayed broken.

WHERE THAT LAUNCH LIVES MOVED, and this module did not move with it.
``1e74ab469`` (owner decision, 2026-08-16) withdrew ``run "63x8 census
freshness"`` from ``tools/ci/repo_hygiene_gates.sh`` — the census is a question
about the campaign, not about whether a change breaks anything, and the two
tiers are now separate by construction. The check was not deleted; it is
started by ``gatekeeper_prepare_landing`` and re-checked in the suite. Both
tests below read that one deleted line and asserted there was exactly one of
it, so on ``origin/main`` they failed with ``found 0`` — reporting a wiring
defect that does not exist. The rule they enforce is a property of WHOEVER
STARTS THE CENSUS, so the population is discovered instead of named.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, NamedTuple

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import gate_discloses_denominator_check as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]
_CI_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_GEN = _REPO / "tools" / "gen_matrix_63x8_census.py"

#: The probe's own per-gate budget. The point of (a) is that the census gate no
#: longer needs a meaningful fraction of it; a bound generous enough to survive
#: a loaded host and still be decisive is one tenth of it.
_FAST_S = 12.0


def _gen_module():
    """The generator, imported rather than launched (the freshness test's
    posture — an import of a `__main__` script leaves no bytecode behind and
    costs no interpreter start)."""
    import importlib.util
    if not _GEN.is_file():
        pytest.skip(f"generator not present at {_GEN} (mirror tree)")
    spec = importlib.util.spec_from_file_location("_gen972", str(_GEN))
    mod = importlib.util.module_from_spec(spec)
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


class _Launch(NamedTuple):
    """One place this repository starts the census, and the argv it starts."""
    where: str
    argv: List[str]


def _ci_launches(subject: Path) -> List[_Launch]:
    """Census launches declared as `run` lines in the CI hygiene script.

    ZERO IS A FACT HERE, NOT A FAILURE. `1e74ab469` (owner decision,
    2026-08-16) deleted `run "63x8 census freshness" …` from that script and
    wrote the reason where the line used to be: the census asks whether the
    campaign's published figures are still true, landing asks whether a change
    breaks anything, and the two tiers are now separate by construction. The
    check was moved, not removed. This function keeps reading the script so
    that a census gate wired back in WRONG is still caught the moment it lands.
    """
    if not _CI_SCRIPT.is_file():
        return []
    return [_Launch(f"{_CI_SCRIPT.name}:{d.lineno} ({d.label})",
                    G._expand(d.cmd, _REPO, subject))
            for d in G.parse_declarations(_CI_SCRIPT) if _GEN.name in d.cmd]


class _Stop(Exception):
    """Raised inside the stub the moment the census argv has been seen."""


def _landing_launches(subject: Path) -> List[_Launch]:
    """The census launch inside the LANDING driver, DRIVEN rather than read.

    `gatekeeper_prepare_landing._default_census_writer` is where the census is
    started now. Its argv is captured by stubbing the launcher and driving the
    real function, so what is asserted is the command line that really runs —
    not one re-typed here, which is the copy that would stay green while the
    wiring rotted. Only the census's own launch is intercepted; the function's
    other subprocesses (it asks git what is dirty first) go through untouched,
    and the stub is torn down in a `finally` BEFORE this returns — a caller that
    inherited it would have its own `subprocess.run` of the census swallowed by
    the spy, which is what the first version of this did.
    """
    try:
        import gatekeeper_prepare_landing as L
    except Exception as exc:                        # pragma: no cover
        pytest.fail(f"the landing driver could not be imported, so this test "
                    f"measures nothing: {exc!r}")
    assert hasattr(L, "_default_census_writer"), (
        "gatekeeper_prepare_landing no longer exposes `_default_census_writer`;"
        " this module measures nothing until it is repointed — which is a "
        "failure, not a skip.")

    captured: List[List[str]] = []
    real = subprocess.Popen

    def spy(argv, *a, **kw):
        if any(_GEN.name in str(tok) for tok in argv):
            captured.append([str(tok) for tok in argv])
            raise _Stop
        return real(argv, *a, **kw)

    subprocess.run(["git", "init", "-q", str(subject)], check=True)
    subprocess.Popen = spy
    try:
        L._default_census_writer(subject)
    except _Stop:
        pass
    finally:
        subprocess.Popen = real
    return [_Launch("gatekeeper_prepare_landing._default_census_writer", a)
            for a in captured]


def _census_launches(subject: Path) -> List[_Launch]:
    """EVERY live launch of the census, with `subject` as the tree to census.

    WHY THIS IS NO LONGER A SINGLE `run` LINE. It used to be
    `_census_declaration()`, which asserted `len(hits) == 1` over the CI
    hygiene script. That line was deliberately removed (see `_ci_launches`), so
    both tests below went red claiming a wiring defect that does not exist —
    measured on `origin/main`: `expected exactly one declaration launching
    gen_matrix_63x8_census.py; found 0`. The census still runs, from a
    different place, and the property #972 is about is a property of WHOEVER
    STARTS IT rather than of one script.

    So the population is DISCOVERED across both languages this repo declares
    launches in, and an EMPTY population is a failure: a test that finds
    nothing to measure must not report that it measured.
    """
    if not _GEN.is_file():
        pytest.skip(f"generator not present at {_GEN} (mirror tree)")
    return _ci_launches(subject) + _landing_launches(subject)


# ── (a) the census answers for the tree it is pointed at ────────────────────

def test_the_ci_declaration_hands_the_census_gate_the_probed_tree(tmp_path):
    """The wiring half, asserted against every live launch of the census.

    The program can accept a root all day; if the line that runs it passes
    none, the census still answers about itself — the state measured at
    6525cf05, and still reachable: `gen_matrix_63x8_census.py --check` with no
    subject censuses ITS OWN checkout, which is the whole hazard.

    The argument must be an ARGUMENT, not merely a `$ROOT` somewhere in the
    line: the pre-fix CI declaration already contained one, inside the path to
    the program (`"$ROOT/tools/gen_matrix_63x8_census.py"`), and `_expand`
    rewrites THAT one to the real repository so the interpreter can find the
    file. Testing for `$ROOT` in the text passes on the broken wiring —
    measured, on the first version of this test, which is why the assertion is
    on the argv AFTER the program path and on the SCRATCH tree specifically.

    WHAT MOVED. The subject used to be the one `run` line in the CI hygiene
    script; that line was withdrawn from the landing path on purpose and the
    census is started by `gatekeeper_prepare_landing` now. The rule did not
    move with it, so it is asserted over the discovered population instead of
    over one named file — see `_census_launches`.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    launches = _census_launches(scratch)
    assert launches, (
        "nothing in this repository was found launching "
        f"{_GEN.name}. Either the census is started somewhere this test does "
        "not read — in which case it is unguarded — or it is started nowhere, "
        "and the freshness it exists to protect is nobody's job. Both are "
        "failures; neither is a skip.")
    for where, argv in launches:
        assert str(_GEN) in argv, (
            f"{where} cannot launch the census program at all: {argv}")
        after_program = argv[argv.index(str(_GEN)) + 1:]
        assert str(scratch) in after_program, (
            f"{where} passes the tree to census as no argument, so the program "
            f"resolves every path off __file__ and answers for its own "
            f"checkout whatever tree it is asked about (vibe-ic#972).\n"
            f"  argv: {argv}")


def _retargeted(argv: List[str], tmp_path: Path) -> List[str]:
    """`argv` with its `--written-json` scratch file moved into `tmp_path`.

    The landing driver opens that path inside a `TemporaryDirectory` it deletes
    on the way out, so the captured argv names a file whose directory is gone
    by the time this test runs the command. MEASURED: the census writes that
    declaration from a `finally`, so an unwritable path turns the rc 2 refusal
    below into rc 1 — a real refusal reported as a crash. Only the destination
    moves; every other token is the driver's own.
    """
    out = list(argv)
    for i, tok in enumerate(out[:-1]):
        if tok == "--written-json":
            out[i + 1] = str(tmp_path / "written.json")
    return out


def test_an_empty_tree_is_refused_as_a_zero_denominator_and_refused_fast(
        tmp_path):
    """The defect and its consequence, in one run of the REAL command line.

    Both halves are asserted because either alone is satisfiable the wrong way:
    a gate that refuses slowly still burns its caller's budget, and a gate that
    exits quickly with rc 0 is the silent pass the whole campaign is about.

    The command line is the one the live driver builds (see `_census_launches`)
    rather than one written here, for the reason the module docstring gives: a
    hand-written copy passes while the real wiring stays broken.
    """
    scratch = tmp_path / "empty"
    scratch.mkdir()
    launches = _census_launches(scratch)
    assert launches, (
        f"no live launch of {_GEN.name} was found, so this drove nothing")

    for where, raw_argv in launches:
        argv = _retargeted(raw_argv, tmp_path)
        t0 = time.monotonic()
        r = subprocess.run(argv, cwd=str(scratch), capture_output=True,
                           text=True, timeout=60)
        elapsed = time.monotonic() - t0
        out = (r.stdout or "") + (r.stderr or "")
        _assert_refuses_an_empty_tree(where, argv, r.returncode, out, elapsed)


def _assert_refuses_an_empty_tree(where, argv, rc, out, elapsed):
    assert rc == 2, (
        f"{where}: a tree with no matrix suite must REFUSE (rc 2), not answer. "
        f"rc={rc}\n  argv: {argv}\n{out}")
    assert "ZERO_DENOMINATOR" in out, (
        f"{where}: the refusal does not name its own state:\n{out}")
    assert G.discloses(out), (
        f"{where}: the refusal does not disclose what it examined, which is "
        f"the rule the denominator probe enforces on everybody else:\n{out}")
    # Match the SHAPE of the claim, not the digits of one recorded instance.
    #
    # This was `assert "504" not in out`, and `out` embeds absolute paths: the
    # refusal ends with "or omit the argument to census <this script's own
    # root>". So the assertion fired on any checkout whose PATH contains those
    # three digits, with nothing wrong with the gate at all. Measured on
    # 3d13e2c59, same commit, same basetemp, only the checkout path differing:
    #
    #     /tmp/.../5bd54937-551b-4504-8f2a-.../m2   1 failed   <- "4504"
    #     /tmp/claude-1000/mainclean                1 passed
    #
    # A per-agent scratch path decided the verdict, which is how this sat in a
    # red list attributed to main. The defect being guarded is REPORTING A
    # NON-ZERO CELL COUNT over an empty tree, so ask exactly that: every cell
    # count the output states must be zero. "0 of 0 cells" still passes,
    # "504 cells over 8 dimensions" still fails, and no path can reach it.
    counts = [int(n) for n in re.findall(r"(\d+)\s+cells\b", out)]
    assert counts and not any(counts), (
        f"{where}: the gate reported the real suite's cell count over an EMPTY tree — "
        f"this is the defect verbatim (measured 6525cf05: '504 cells over 8 "
        f"dimensions' in 1m50.203s over a directory holding one file). "
        f"cell counts stated: {counts}\n{out}")
    assert elapsed < _FAST_S, (
        f"{where}: refusing an empty tree took {elapsed:.1f}s (bound "
        f"{_FAST_S}s). The "
        f"110s measured at 6525cf05 were spent AFTER everything needed to "
        f"refuse was already known, and they sat 8% under the probe's 120s "
        f"budget.")


def test_the_default_subject_is_still_this_checkout(tmp_path):
    """No argument keeps the previous behaviour verbatim — the freshness test,
    the host-independence probe and a human all rely on it. A fix that made the
    subject follow the CWD would break every one of them from a different
    directory, so the default is pinned rather than left to be discovered by
    whoever runs pytest from somewhere else."""
    gen = _gen_module()
    state, counts = gen.classify_subject(gen.REPO_ROOT)
    assert state == gen.SUBJECT_OWN, (
        f"this checkout does not classify as its own subject: {state} "
        f"{counts}")
    assert (counts["census_inputs_present"]
            == counts["census_inputs_required"]), counts


def test_a_different_checkout_is_refused_rather_than_answered_about(tmp_path):
    """The third state, and the reason it is not folded into the second.

    The census imports the dimension modules through `sys.path` anchored on
    `__file__`. A tree that HAS a suite is therefore still one this program
    cannot count — and the honest answer is to say so, not to print its own
    numbers under a heading naming somebody else's tree. That substitution is
    what the measured run did.
    """
    gen = _gen_module()
    other = tmp_path / "other-checkout"
    for rel in gen.CENSUS_INPUTS_REL:
        p = other / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture\n", encoding="utf-8")
    readme = other / gen.README_REL
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(f"{gen.BEGIN}\nx\n{gen.END}\n", encoding="utf-8")

    state, counts = gen.classify_subject(other.resolve())
    assert state == gen.SUBJECT_CROSS_TREE, (
        f"a populated OTHER checkout classified as {state}: {counts}")
    lines = "\n".join(gen.subject_refusal_lines(state, other.resolve(), counts))
    assert str(gen.REPO_ROOT) in lines and str(other.resolve()) in lines, (
        f"the refusal must name BOTH trees, or a reader cannot tell which one "
        f"the numbers would have described:\n{lines}")


# ── (b) the roll-up names the kind and the gate ─────────────────────────────

def test_an_unrunnable_gate_is_not_reported_as_a_silent_pass():
    """The exact sentence measured in the issue, refused.

    A GATE_UNRUNNABLE means the gate never produced an output; "answered PASS
    without disclosing it" is a claim ABOUT an output. Reporting the first as
    the second is not a wording problem — the remedies differ, and a reader
    acting on the printed one fixes the wrong thing.
    """
    lines = G.summarise_findings([
        {"gate": "63x8 census freshness", "kind": "GATE_UNRUNNABLE",
         "detail": "timed out"}])
    blob = "\n".join(lines)
    assert "GATE_UNRUNNABLE" in blob, blob
    assert "could not be driven" in blob, blob
    assert "without disclosing" not in blob, (
        f"an unrunnable gate is still being reported as a silent pass:\n{blob}")
    assert "63x8 census freshness" in blob, (
        f"the roll-up does not NAME the gate it is counting:\n{blob}")


def test_each_kind_gets_its_own_line_and_its_own_gates():
    """Mixed findings must not be collapsed onto whichever sentence is first."""
    lines = G.summarise_findings([
        {"gate": "alpha", "kind": "GATE_UNRUNNABLE", "detail": "x"},
        {"gate": "beta", "kind": "PASS_WITHOUT_DENOMINATOR", "detail": "y"},
        {"gate": "gamma", "kind": "PASS_WITHOUT_DENOMINATOR", "detail": "z"},
    ])
    assert len(lines) == 2, lines
    unrun = [ln for ln in lines if "GATE_UNRUNNABLE" in ln]
    silent = [ln for ln in lines if "PASS_WITHOUT_DENOMINATOR" in ln]
    assert len(unrun) == 1 and "alpha" in unrun[0] and "beta" not in unrun[0]
    assert len(silent) == 1 and "beta" in silent[0] and "gamma" in silent[0]
    assert "1 GATE_UNRUNNABLE" in unrun[0], unrun[0]
    assert "2 PASS_WITHOUT_DENOMINATOR" in silent[0], silent[0]


def test_an_unknown_kind_is_reported_under_its_own_name_not_absorbed():
    """DISCOVER, DO NOT ENUMERATE. `_KIND_HEADLINE` is a phrasing table, not the
    population: a kind added to either audit must arrive in this roll-up
    already reported, because a kind that falls through to somebody else's
    sentence is the defect being fixed, one release later."""
    lines = G.summarise_findings([
        {"gate": "delta", "kind": "A_KIND_NOBODY_HAS_WRITTEN_YET"}])
    assert len(lines) == 1
    assert "A_KIND_NOBODY_HAS_WRITTEN_YET" in lines[0], lines[0]
    assert "delta" in lines[0], lines[0]
    assert "without disclosing" not in lines[0], lines[0]


def test_neither_verdict_line_still_renames_what_it_counts():
    """The two call sites, pinned at the source.

    `summarise_findings` being correct buys nothing if a verdict line goes on
    printing the old sentence beside it. Both used to read
    "N gate(s) ... answer PASS over an empty tree without disclosing it" over a
    findings list that can hold four other kinds.
    """
    src = Path(G.__file__).read_text(encoding="utf-8")
    body = src.split("def summarise_findings", 1)[1]
    body = body.split("_KIND_HEADLINE = {", 1)[0]
    for banned in ("answer PASS over an empty tree without disclosing it",
                   "disclosure finding(s) over"):
        assert banned not in body, (
            f"a verdict line still describes every finding as {banned!r}; "
            f"GATE_UNRUNNABLE and STALE_INVENTORY_ENTRY are not that.")
