"""A gate declared always-run-and-blocking cannot be red while a landing succeeds.

WHY THIS FILE EXISTS
====================
`prose_polarity_consulted_check` is declared in `tools/ci/repo_hygiene_gates.sh`
with no `gate_scope` and no `uncheckable_until` -- always-run, and blocking. It
went RED at v1.11.5 and stayed red through v1.11.18: MEASURED at every one of
the 36 commits in that window by running THAT revision's own checker against
THAT revision's own `programs/` tree, rc 1 at all 36. Fourteen version-bearing
landings went past it, and it collected two further findings on the way.

Every link of the chain that is supposed to make that impossible was, and is,
individually correct:

    a red always-run gate      -> `gate_dispatch_finish` exits non-zero
    that exit                  -> `repo_hygiene_gates.sh` exits non-zero
    that exit                  -> `gatekeeper-land.sh`'s `run` sets FAILED=1
    FAILED != 0                -> no `.git/gatekeeper-stamp`, and it is REMOVED
    no / stale stamp on main   -> `tools/git-hooks/pre-push` refuses the push

Nothing asserted the CHAIN. Every existing test asserts one link in isolation
(`test_gatekeeper_stamp_works_in_a_worktree`,
`test_issue636_prepush_gates_by_destination`,
`test_issue1254_a_gate_that_could_not_look_must_not_pass`), and a chain of five
sound links with nothing holding them together is exactly what fourteen landings
walked through.

WHAT IS RUN AND WHAT IS READ, AND WHY THE SPLIT
===============================================
The two ends are EXECUTED, against the real artefacts, in a throwaway fixture:

    `_gate_dispatch.sh`     sourced by a fixture gate script, the idiom
                            `test_corpus_write_guard.py` already uses, for the
                            reason that library's own header gives -- a fixture
                            copy of the dispatch code would drift from the code
                            CI runs.
    `tools/git-hooks/pre-push`
                            invoked with a fabricated stdin line, in a fixture
                            clone, with and without a stamp.

The middle link -- `run` setting `FAILED`, and `FAILED` gating the stamp -- is
inline shell inside `gatekeeper-land.sh`, which cannot be sourced (it does work
at top level) and cannot be edited: `tools/ci/protected_landing_transition.json`
pins its sha256 in both the `current` and `next` halves, together with
`repo_hygiene_gates.sh` and `_gate_dispatch.sh`. So that link is read from the
source -- and every read here carries a NEGATIVE CONTROL that mutates a COPY of
the file and asserts the same reader then refuses it. A reader that cannot fail
proves nothing, which is the whole subject of this file.

BOTH DIRECTIONS, EVERYWHERE
===========================
A test that only proves "red stops the landing" would pass just as well if the
dispatch refused everything. Each direction below is paired with its opposite:
green passes, a gate the set does NOT declare blocking does not stop anything, a
push that is not to `main` is not stamp-gated.
"""
from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_LAND = _REPO / "tools" / "gatekeeper-land.sh"
_HOOK = _REPO / "tools" / "git-hooks" / "pre-push"

#: Every fixture gate returns instantly. This only stops a hung one from taking
#: the pytest session down, and it must stay under the 60 s ceiling
#: `ci_harness_timeout_ceiling_check` enforces or the bound cannot fire as a TEST
#: failure -- pytest kills the session first, taking every other file with it.
_T = 55

#: The pre-push hook runs the whole cheap tier against the fixture repo. Slower
#: than a dispatch fixture and still far under the ceiling; measured at ~3 s on
#: this tree.
_HOOK_T = 55

_ZERO = "0" * 40


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _repo(tmp_path: Path, name: str = "repo") -> Path:
    r = tmp_path / name
    r.mkdir(parents=True)
    (r / "f.txt").write_text("x\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def _gate(root: Path, name: str, rc: int, line: str) -> Path:
    """A fixture gate program with a chosen exit code."""
    p = root / f"{name}.py"
    p.write_text(f"print({line!r})\nraise SystemExit({rc})\n"
                 if rc else f"print({line!r})\n")
    return p


def _dispatch(root: Path, gate_lines: str, *, changed: Path | None = None):
    """Drive the REAL `_gate_dispatch.sh` over `gate_lines`."""
    s = root / "gates.sh"
    s.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + gate_lines + "\ngate_dispatch_finish\n")
    env = None
    if changed is not None:
        import os
        env = dict(os.environ, GATEKEEPER_CHANGED_PATHS=str(changed))
    return subprocess.run(["bash", str(s)], cwd=str(root), env=env,
                          capture_output=True, text=True, timeout=_T)


# --------------------------------------------------------------------------- #
# LINK 1 -- a red gate the set declares BLOCKING makes the dispatch exit non-zero
# --------------------------------------------------------------------------- #
def test_link1_a_declared_blocking_red_gate_fails_the_dispatch(tmp_path):
    r = _repo(tmp_path)
    _gate(r, "red", 1, "FAIL: the fixture gate found something")
    out = _dispatch(r, f'run "a red gate" "$ROOT" python3 "{r}/red.py"\n')
    assert out.returncode != 0, (
        "a RED gate with no gate_scope and no uncheckable_until -- the exact "
        "declaration `prose extractors read polarity` carries -- did not fail "
        "the dispatch:\n" + out.stdout + out.stderr)


def test_link1_REVERSE_a_green_gate_does_not(tmp_path):
    """NEGATIVE CONTROL. A dispatch that refused everything would satisfy the
    test above and enforce nothing."""
    r = _repo(tmp_path)
    _gate(r, "green", 0, "PASS (1 item examined)")
    out = _dispatch(r, f'run "a green gate" "$ROOT" python3 "{r}/green.py"\n')
    assert out.returncode == 0, out.stdout + out.stderr


def test_link1_a_gate_NOT_declared_blocking_does_not_stop_the_landing(tmp_path):
    """THE OTHER DIRECTION THE BRIEF ASKS FOR.

    "Blocking" is the DEFAULT here, not a marker: a gate stops being blocking
    only by being declared `uncheckable_until` and returning rc 2 -- "I could
    not look" -- which is tolerated alongside a gate that did reach a verdict.
    """
    r = _repo(tmp_path)
    _gate(r, "green", 0, "PASS (1 item examined)")
    _gate(r, "blind", 2, "NOT CHECKED: the fixture gate could not look")
    out = _dispatch(r, textwrap.dedent(f"""\
        run "a green gate" "$ROOT" python3 "{r}/green.py"
        uncheckable_until 2099-01-01 "the fixture prerequisite is deliberately absent"
        run_tolerating_uncheckable "a tolerated gate" "$ROOT" python3 "{r}/blind.py"
        """))
    assert out.returncode == 0, (
        "an rc-2 gate under an unexpired exemption, alongside a gate that DID "
        "reach a verdict, must not fail the set:\n" + out.stdout + out.stderr)


def test_link1_tolerance_is_for_rc2_ONLY_not_for_a_finding(tmp_path):
    """The exemption says "this gate may be unable to LOOK". It must not absorb
    a gate that looked and found something."""
    r = _repo(tmp_path)
    _gate(r, "red", 1, "FAIL: the fixture gate found something")
    out = _dispatch(r, textwrap.dedent(f"""\
        uncheckable_until 2099-01-01 "the fixture prerequisite is deliberately absent"
        run_tolerating_uncheckable "a tolerated gate" "$ROOT" python3 "{r}/red.py"
        """))
    assert out.returncode != 0, (
        "an exemption absorbed a real finding (rc 1), not just an "
        "I-could-not-look (rc 2):\n" + out.stdout + out.stderr)


def test_link1_an_expired_exemption_is_not_a_pass(tmp_path):
    r = _repo(tmp_path)
    _gate(r, "blind", 2, "NOT CHECKED: the fixture gate could not look")
    out = _dispatch(r, textwrap.dedent(f"""\
        uncheckable_until 2000-01-01 "the fixture prerequisite is deliberately absent"
        run_tolerating_uncheckable "a tolerated gate" "$ROOT" python3 "{r}/blind.py"
        """))
    assert out.returncode != 0, (
        "an exemption past its review date still tolerated the gate -- an "
        "immortal exemption is a skip button with a date printed on it:\n"
        + out.stdout + out.stderr)


@pytest.mark.parametrize("changed,expect_fail", [
    ("docs/readme.md", False),   # scope not touched -> SKIP
    ("tools/ci/x.sh", True),     # scope touched     -> runs, and it is red
])
def test_link1_a_scope_is_the_only_way_a_red_gate_is_skipped(
        tmp_path, changed, expect_fail):
    """Both halves of the one narrowing that exists, because it is the only
    mechanism by which a red gate can legitimately not stop a landing -- and
    therefore the one a future author could reach for to quiet this gate."""
    r = _repo(tmp_path)
    _gate(r, "red", 1, "FAIL: the fixture gate found something")
    ch = r / "changed.txt"
    ch.write_text(changed + "\n")
    out = _dispatch(r, textwrap.dedent(f"""\
        gate_scope tools/
        run "a scoped red gate" "$ROOT" python3 "{r}/red.py"
        """), changed=ch)
    assert (out.returncode != 0) is expect_fail, out.stdout + out.stderr


def test_link1_an_unknown_change_set_runs_the_scoped_gate_anyway(tmp_path):
    """"I could not find out what changed" must never render as "nothing
    relevant changed"."""
    r = _repo(tmp_path)
    _gate(r, "red", 1, "FAIL: the fixture gate found something")
    out = _dispatch(r, textwrap.dedent(f"""\
        gate_scope tools/
        run "a scoped red gate" "$ROOT" python3 "{r}/red.py"
        """))                       # GATEKEEPER_CHANGED_PATHS deliberately unset
    assert out.returncode != 0, out.stdout + out.stderr


# --------------------------------------------------------------------------- #
# LINK 2 -- the polarity gate is declared the always-run-and-blocking way
# --------------------------------------------------------------------------- #
_POLARITY_LABEL = "prose extractors read polarity"

#: The declarators that make the NEXT gate something other than
#: always-run-and-blocking. Both attach to the gate that FOLLOWS them.
_WEAKENERS = ("gate_scope", "uncheckable_until")


def _hygiene_lines() -> list[str]:
    return _HYGIENE.read_text(errors="replace").splitlines()


def _gate_invocations(lines: list[str]) -> list[tuple[int, str, str]]:
    """`(index, runner, label)` for every gate declared in the set."""
    rx = re.compile(r'^\s*(run|run_tolerating_uncheckable|report)\s+"([^"]+)"')
    out = []
    for i, line in enumerate(lines):
        m = rx.match(line)
        if m:
            out.append((i, m.group(1), m.group(2)))
    return out


def _preceding_declarator(lines: list[str], idx: int) -> str | None:
    """The weakening declarator attached to the gate at `idx`, if any.

    Attachment is by ADJACENCY in this library: a declarator sets a pending slot
    that the next gate consumes, and `gate_dispatch_finish` raises a wiring
    error for one that attaches to nothing. Comment and blank lines between them
    are ordinary.
    """
    for j in range(idx - 1, -1, -1):
        s = lines[j].strip()
        if not s or s.startswith("#"):
            continue
        for w in _WEAKENERS:
            if s.startswith(w + " "):
                return w
        return None
    return None


def test_link2_the_set_declares_gates_at_all():
    """FLOOR, asserted before anything is concluded from the parse. A regex that
    matched nothing would make every assertion below vacuously true, which is
    the shape this whole file is about."""
    gates = _gate_invocations(_hygiene_lines())
    assert len(gates) > 30, (
        f"only {len(gates)} gate invocation(s) parsed out of {_HYGIENE} -- the "
        "reader is broken, and a broken reader concludes nothing")


def test_link2_the_polarity_gate_is_always_run_and_blocking():
    lines = _hygiene_lines()
    hits = [(i, runner) for i, runner, label in _gate_invocations(lines)
            if label == _POLARITY_LABEL]
    assert len(hits) == 1, (
        f"expected exactly one {_POLARITY_LABEL!r} declaration, found "
        f"{len(hits)}")
    idx, runner = hits[0]
    assert runner == "run", (
        f"{_POLARITY_LABEL!r} is declared with {runner!r}. `report` records "
        "without failing and `run_tolerating_uncheckable` forgives rc 2; this "
        "gate BLOCKS (rc=1 on a NEW polarity-blind extractor) and must be "
        "declared with the runner that makes that fatal.")
    weakener = _preceding_declarator(lines, idx)
    assert weakener is None, (
        f"{_POLARITY_LABEL!r} now carries a {weakener!r} declaration. It was "
        "always-run when it went red at v1.11.5 and stayed red for fourteen "
        "landings; narrowing it now would make the next such window invisible "
        "rather than merely unenforced.")


def test_link2_REVERSE_the_reader_can_see_a_weakened_gate():
    """NEGATIVE CONTROL for the reader above. The set really does contain gates
    declared the tolerant way, so `_preceding_declarator` returning None for the
    polarity gate is a measurement and not a parser that always says None."""
    lines = _hygiene_lines()
    tolerant = [label for i, runner, label in _gate_invocations(lines)
                if runner == "run_tolerating_uncheckable"]
    assert tolerant, (
        "no gate in the set is declared `run_tolerating_uncheckable`, so the "
        "runner assertion above cannot distinguish anything")
    weakened = [label for i, runner, label in _gate_invocations(lines)
                if _preceding_declarator(lines, i) is not None]
    assert weakened, (
        "`_preceding_declarator` found no weakened gate anywhere in the set. "
        "Either the set has stopped using exemptions -- in which case this "
        "control must be retired deliberately -- or the reader is blind, and a "
        "blind reader would clear the polarity gate no matter how it is "
        "declared.")


def _polarity_index(lines: list[str]) -> int:
    return next(i for i, runner, label in _gate_invocations(lines)
                if label == _POLARITY_LABEL)


def test_link2_REVERSE_the_reader_sees_a_polarity_gate_given_a_scope():
    """MUTATION CONTROL, on a COPY of the lines -- the file is never edited.

    `gate_scope` is the ONE mechanism by which a red gate legitimately does not
    stop a landing (link 1 measures both halves of it), so it is also the one an
    author could reach for to quiet a gate that has gone red and stayed red. The
    reader has to see it.
    """
    lines = _hygiene_lines()
    i = _polarity_index(lines)
    mutated = lines[:i] + ["gate_scope vibe-ic-marketplace/"] + lines[i:]
    assert _preceding_declarator(mutated, i + 1) == "gate_scope", (
        "a `gate_scope` inserted directly above the polarity gate was not seen "
        "-- the always-run assertion above cannot fail, so it proves nothing")


def test_link2_REVERSE_the_reader_sees_a_polarity_gate_given_an_exemption():
    lines = _hygiene_lines()
    i = _polarity_index(lines)
    mutated = (lines[:i]
               + ['uncheckable_until 2099-01-01 "a fabricated exemption"']
               + lines[i:])
    assert _preceding_declarator(mutated, i + 1) == "uncheckable_until", (
        "an `uncheckable_until` inserted directly above the polarity gate was "
        "not seen")


def test_link2_REVERSE_the_reader_sees_a_polarity_gate_made_tolerant():
    lines = _hygiene_lines()
    i = _polarity_index(lines)
    mutated = list(lines)
    mutated[i] = mutated[i].replace("run ", "run_tolerating_uncheckable ", 1)
    hits = [runner for j, runner, label in _gate_invocations(mutated)
            if label == _POLARITY_LABEL]
    assert hits == ["run_tolerating_uncheckable"], (
        f"switching the polarity gate to the tolerant runner was not seen "
        f"(reader says {hits}) -- the runner assertion above cannot fail")


def test_link2_the_set_ends_in_the_finish_that_carries_the_verdict():
    """`gate_dispatch_finish` is what turns a recorded FAIL into the script's
    exit code. A set that ended without it would print its findings and exit 0.
    """
    tail = [s.strip() for s in _hygiene_lines() if s.strip()][-1]
    assert tail == "gate_dispatch_finish", (
        f"{_HYGIENE.name} no longer ends in `gate_dispatch_finish` (last "
        f"statement: {tail!r}) -- its exit code may no longer carry the set's "
        "verdict")


# --------------------------------------------------------------------------- #
# LINK 3 -- the lander makes the hygiene exit fatal, and gates the stamp on it
# --------------------------------------------------------------------------- #
#: `tools/gatekeeper-land.sh` is sha256-pinned in
#: `tools/ci/protected_landing_transition.json` (role `runtime`, in BOTH the
#: `current` and `next` halves) alongside `repo_hygiene_gates.sh` and
#: `_gate_dispatch.sh` (role `authority`). It therefore cannot be refactored
#: into something sourceable without re-authoring that manifest, and these three
#: links are read rather than executed. Every one of them is paired with a
#: mutation control below, so the reader is proved able to fail.
_STAMP_EXPR = 'git rev-parse HEAD > "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"'
_STAMP_RM = 'rm -f "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"'


def _land_text() -> str:
    return _LAND.read_text(errors="replace")


def _hygiene_is_run_through(text: str) -> bool:
    """Is the hygiene script invoked by `run` -- the wrapper that sets FAILED?

    `report` and the bare command would both execute it and both discard the
    verdict, which is disease (b): the gate runs, its rc is collected, and
    nothing is fatal.
    """
    return bool(re.search(
        r'^\s*run\s+"full:repo-hygiene"[^\n]*(?:\\\n[^\n]*)*'
        r'repo_hygiene_gates\.sh',
        text, re.M))


def _run_sets_failed(text: str) -> bool:
    """Does `run()` set FAILED on a non-zero rc?"""
    m = re.search(r'^run\(\)\s*\{(.*?)^\}', text, re.M | re.S)
    return bool(m) and "FAILED=1" in m.group(1)


def _stamp_is_gated_on_failed(text: str) -> bool:
    """Is the stamp written ONLY under `FAILED -eq 0`, and removed otherwise?"""
    if text.count(_STAMP_EXPR) != 1:
        return False
    i = text.index(_STAMP_EXPR)
    head = text[:i]
    guard = head.rfind('[ "$FAILED" -eq 0 ]')
    return guard != -1 and text.count(_STAMP_RM, guard) >= 1


def _exits_failed(text: str) -> bool:
    return bool(re.search(r'^exit\s+"\$FAILED"\s*$', text, re.M))


_LAND_READERS = {
    "the hygiene script is invoked through `run`": _hygiene_is_run_through,
    "`run` sets FAILED on a non-zero rc": _run_sets_failed,
    "the stamp is written only under FAILED == 0": _stamp_is_gated_on_failed,
    "the script exits FAILED": _exits_failed,
}


@pytest.mark.parametrize("claim", sorted(_LAND_READERS))
def test_link3_the_lander_still_makes_a_red_hygiene_set_fatal(claim):
    assert _LAND_READERS[claim](_land_text()), (
        f"{_LAND.name}: {claim} -- no longer true. With this link broken, a "
        "red always-run gate and a successful landing can coexist, which is "
        "the state fourteen landings were made in.")


#: Each mutation breaks exactly one link, so the reader that must go red is
#: named. A control that broke two would not prove which reader saw it.
_LAND_MUTATIONS = {
    "the hygiene script is invoked through `run`": (
        'run "full:repo-hygiene" "repo hygiene gates"',
        'report "full:repo-hygiene" "repo hygiene gates"'),
    "`run` sets FAILED on a non-zero rc": (
        "    FAILED=1\n    state=FAIL", "    state=FAIL"),
    "the stamp is written only under FAILED == 0": (
        _STAMP_EXPR, "true  # stamp write removed by the mutation control"),
    # NEWLINE-ANCHORED. `gatekeeper-land.sh` carries TWO `exit "$FAILED"`: the
    # indented one in the `--cheap-only` early return (which writes no stamp and
    # is not this link) and the unindented final one. Mutating the first left
    # the reader green -- MEASURED, this control failed on its first cut, which
    # is the control working on itself.
    "the script exits FAILED": (
        '\nexit "$FAILED"', "\nexit 0"),
}


@pytest.mark.parametrize("claim", sorted(_LAND_MUTATIONS))
def test_link3_REVERSE_each_reader_refuses_a_broken_lander(claim, tmp_path):
    """MUTATION CONTROL, on a COPY -- `gatekeeper-land.sh` is never edited.

    A reader that cannot fail is not a reader. Each mutation below is the
    smallest edit that actually breaks the property, applied to a copy of the
    real file, and the matching reader must refuse it.
    """
    old, new = _LAND_MUTATIONS[claim]
    text = _land_text()
    assert old in text, (
        f"the mutation control for {claim!r} no longer matches the file -- it "
        "would silently mutate nothing and 'pass'")
    broken = text.replace(old, new, 1)
    assert broken != text
    assert not _LAND_READERS[claim](broken), (
        f"the reader for {claim!r} accepted a lander with that property "
        "removed, so its green above means nothing")


def test_link3_REVERSE_the_readers_are_independent(tmp_path):
    """Each mutation must leave the OTHER three readers green, or a single
    broken link would light up every claim and none of them would locate it."""
    for claim, (old, new) in _LAND_MUTATIONS.items():
        broken = _land_text().replace(old, new, 1)
        for other in _LAND_READERS:
            if other == claim:
                continue
            assert _LAND_READERS[other](broken), (
                f"mutating {claim!r} also broke the reader for {other!r}; the "
                "controls do not isolate their links")


# --------------------------------------------------------------------------- #
# LINK 4 -- the hook refuses a main push whose commit has no passing stamp
# --------------------------------------------------------------------------- #
_NO_STAMP = "the full suites have not been run for this commit"
_STALE_STAMP = "the gatekeeper stamp is for a different commit"


@pytest.fixture(scope="module")
def hook_repo():
    """ONE throwaway clone of THIS repo, shared by the four hook tests.

    A real tree, because the hook resolves `REPO_ROOT` from cwd and runs the
    whole cheap tier out of it; a stub repo would exit early at the "NDA message
    guard not found" warning and prove nothing about the stamp.

    `--no-hardlinks`: a clone that borrows objects is refused by the runtime
    preflight, and a fixture must never be able to write into the real object
    store. NOT shallow -- `HEAD~1` has to resolve.

    `tempfile.mkdtemp`, not `tmp_path`: pytest's tmp dir carries a NEWLINE in
    the paths this repo's own container produces, and a newline in a path breaks
    every `git -C` below in a way that reads as a git failure.
    """
    import shutil
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="j4r3_hook_"))
    dst = base / "clone"
    subprocess.run(["git", "clone", "--no-hardlinks", "-q", str(_REPO),
                    str(dst)], check=True, timeout=_HOOK_T)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(dst), "config", k, v], check=True)
    try:
        yield dst
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _stamp_path(repo: Path) -> Path:
    out = subprocess.run(["git", "-C", str(repo), "rev-parse",
                          "--absolute-git-dir"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip()) / "gatekeeper-stamp"


def _push(repo: Path, remote_ref: str, *, stamp: str | None):
    """Drive the REAL hook with the stdin line git would give it.

    `remote_sha` is `HEAD~1` and NOT the all-zero sha. With zeros the hook takes
    its new-branch path, `RANGE` becomes `<sha> --not --remotes`, and in a fresh
    clone every commit is already on a remote -- so the range is EMPTY, the loop
    `continue`s, `PUSH_RANGE` is never set, and the stamp block (guarded on it)
    never runs. The hook returns 0 in silence. MEASURED: the first cut of these
    four tests used zeros and all of them read rc 0 as "not refused". A fixture
    that never reaches the code under test proves nothing about it.
    """
    def _rev(spec):
        return subprocess.run(["git", "-C", str(repo), "rev-parse", spec],
                              capture_output=True, text=True, check=True
                              ).stdout.strip()
    head, base = _rev("HEAD"), _rev("HEAD~1")
    sp = _stamp_path(repo)
    if stamp is None:
        sp.unlink(missing_ok=True)
    else:
        sp.write_text(head if stamp == "HEAD" else stamp)
    stdin = f"refs/heads/x {head} {remote_ref} {base}\n"
    out = subprocess.run(["bash", str(_HOOK), "origin", "https://example.invalid"],
                         cwd=str(repo), input=stdin, capture_output=True,
                         text=True, timeout=_HOOK_T)
    return out, head


def _reached_the_stamp_block(out) -> bool:
    """Did the hook get as far as the stamp gate at all?

    The FLOOR for every assertion below. A hook that returned early -- an empty
    range, a missing checker -- would satisfy "the stamp message is absent"
    while never having looked, and that is the vacuous pass this file exists to
    refuse. The cheap tier prints one line per gate it ran, so its output is the
    evidence that the loop did not `continue`.
    """
    return bool((out.stdout + out.stderr).strip())


def test_link4_a_main_push_with_no_stamp_is_refused(hook_repo):
    out, _ = _push(hook_repo, "refs/heads/main", stamp=None)
    text = out.stdout + out.stderr
    assert _reached_the_stamp_block(out), (
        "the hook produced no output at all -- it returned before reaching the "
        "stamp gate, so this test measured nothing")
    assert out.returncode != 0 and _NO_STAMP in text, (
        "a push to main with no gatekeeper stamp was not refused:\n" + text)


def test_link4_a_main_push_with_a_stale_stamp_is_refused(hook_repo):
    out, _ = _push(hook_repo, "refs/heads/main", stamp=_ZERO)
    text = out.stdout + out.stderr
    assert _reached_the_stamp_block(out), "the hook measured nothing"
    assert out.returncode != 0 and _STALE_STAMP in text, (
        "a push to main carrying another commit's stamp was not refused:\n"
        + text)


def test_link4_REVERSE_a_matching_stamp_clears_the_stamp_gate(hook_repo):
    """NEGATIVE CONTROL. A hook that refused every push would satisfy both
    tests above while enforcing nothing about the stamp."""
    out, _ = _push(hook_repo, "refs/heads/main", stamp="HEAD")
    text = out.stdout + out.stderr
    assert _reached_the_stamp_block(out), "the hook measured nothing"
    assert _NO_STAMP not in text and _STALE_STAMP not in text, (
        "the stamp gate fired on a commit whose stamp matches:\n" + text)


def test_link4_REVERSE_an_off_main_push_is_not_stamp_gated(hook_repo):
    """The stamp is written by the LANDING tool, so demanding it from a
    contributor pushing a feature branch would be a gate the documented flow
    cannot pass (vibe-ic#636). Pinned so the main-only narrowing is deliberate
    rather than inherited."""
    out, _ = _push(hook_repo, "refs/heads/feature/z", stamp=None)
    text = out.stdout + out.stderr
    assert _reached_the_stamp_block(out), "the hook measured nothing"
    assert _NO_STAMP not in text and _STALE_STAMP not in text, (
        "an off-main push was refused for a missing landing stamp:\n" + text)
