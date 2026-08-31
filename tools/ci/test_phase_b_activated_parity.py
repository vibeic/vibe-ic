"""Phase-B parity: the landing runtime is exactly ONE recorded state of the
transition the manifest currently authorises -- never a mixture.

Lineage, because this file has now had the same disease twice.

It replaced `test_phase_a_dormant_parity.py`, whose every assertion was a
DORMANCY claim that ACTIVATE falsified by design: "five tests that can only
ever be red, which is worse than no test, because a permanently-red guard
trains the reader to ignore the file."  Then it inherited the defect in a
slower form.  It pinned ONE historical transition by literal id
(`semantic-landing-v1`) and by the exact nine paths that transition moved, so
the first LATER protected transition to land made it red and kept it red.
Measured on clean origin/main 74ac9fa788, with no changes in the tree:

    test_the_manifest_is_the_authorised_transition
      AssertionError: assert 'xdist-per-worker-progress-v1' == 'semantic-landing-v1'
    test_the_activation_moved_exactly_the_nine_runtime_paths
      AssertionError: assert {3 paths} == frozenset({9 paths})

Since `tools/gatekeeper-land.sh` runs this corpus, a file pinned to a spent
transition blocks every landing including the one that would repair it.  The
subject is therefore widened from ONE transition to the PROPERTIES that hold
of whatever transition the manifest describes.  Everything asserted here is
still measured against the object database and the live bytes; nothing is a
restatement of a production constant, and nothing was dropped to go green.

The state machine, which is what makes "properties" the right altitude
(`protected_landing_transition.py`, `classify_move` and `build_receipt`):

  * PREPARE lands a NEW manifest and is REFUSED if it moves protected bytes,
    so at a PREPARE commit the live tuple equals `current`.
  * ACTIVATE moves the protected bytes and leaves the manifest untouched, so
    afterwards the live tuple equals `next`.  This repository SQUASH-merges,
    so a PREPARE+ACTIVATE branch lands as ONE commit that carries the manifest
    and records `next`; that shape is a first-class recorded state here, not a
    mixture.
  * `classify_move` compares the candidate against the BASE's OBSERVED tuple
    and accepts STEADY (nothing protected moved) or ACTIVATE (exactly the
    authorised paths, to exactly the authorised bytes).  Anything else is
    REFUSED, and the refusal NAMES the paths.  That is the refusal with teeth.

WHY THE REFERENCE POINT IS THE BASE AND NOT A PHOTOGRAPH.  This file used to
ask whether the LIVE tuple was byte-identical to one of the two tuples the
manifest records for all 52 protected paths.  That question has a stale answer
by construction: the recorded tuples photograph every protected path at ONE
commit, so any later landing that moves any protected path -- including one no
transition ever named -- falsifies BOTH of them and reddens this file until a
human re-renders the register.  It happened again fourteen landings after the
register's path set was made self-deriving:

    v1.13.8   tools/gatekeeper-land.sh                   (durable JUnit)
    v1.13.16  tools/ci/repo_hygiene_gates.sh             (wiring a gate)
              ci_harness_timeout_ceiling_check.py

three legitimate changes, all staying, none of them a defect, and between them
enough drift to put three of this file's seven cases red on trunk -- which
blocks every landing, including the one that would repair it.  A re-author
somebody has to remember to run is the same defect wearing a smaller hat.  So
the byte-state half stops being a photograph: the state a path moved FROM is
now OBSERVED at the base, the manifest records only the move it authorises,
and nothing in the register goes stale when an unrelated protected file
legitimately changes.  What the manifest still has to record -- the exact
future bytes of the paths a transition authorises -- is the half that cannot
be observed, because at PREPARE time those bytes do not exist yet.

Both states are real states of main, measured in this history: at 15e4c463a6
("PREPARE: authorise the xdist per-worker progress protocol") the live tuple
equals `current` exactly; at 74ac9fa788, after 2b93d8723f ("ACTIVATE"), it
equals `next` exactly.  A test that demanded `next` specifically would be red
on main for the whole PREPARE..ACTIVATE window -- the identical failure mode,
rearmed.  So the assertion on the AUTHORISED paths is still the exact XOR --
mode, git blob oid, sha256 and byte length -- and they may not straddle the
two states.  The paths the transition does NOT move are held to the two
questions that have non-stale answers: their live bytes are the bytes this
commit records (nothing was edited into the tree behind git's back), and the
candidate does not move them at all relative to its base.

The four invariants, as properties:

  1. The manifest is well formed and internally consistent: the exact schema
     the verifier parses, canonical distinct state ids, a sorted unique
     protected set that never includes the manifest itself, a role on every
     path, both tuples covering exactly that set in the same order, a hermetic
     runner profile pinned to an immutable image digest, and a `next` that
     actually differs from `current`.
  2. `current` is a real recorded state, not a free-standing claim: it is the
     tuple that the commit which AUTHORED this manifest version records in the
     object database (and its parent too, since PREPARE may not move bytes).
     The anchor commit is DISCOVERED by matching the live manifest bytes
     against the manifest's own history, not pinned as a literal sha.
  3. The live tree is exactly one recorded state of the AUTHORISED move, per
     path, with no mixture -- and on every protected path, authorised or not,
     the live bytes are the bytes this commit records.
  4. Against the BASE this tree lands on, the only protected paths that move
     are the ones the manifest authorises, and they move to exactly the bytes
     it records.  This is `classify_move`, run on the live tree; it is the
     clause that refuses an undeclared change to a protected file, and it
     names the file.

`transition_id == next.id` is deliberately NOT asserted: measured across all
four manifest versions in this history, it held only for `semantic-landing-v1`
(the later three use `<transition_id>-next`, or an unrelated id).  What the
verifier actually requires -- both ids canonical, and `current.id != next.id`
-- is asserted instead.

The historical claim about `semantic-landing-v1` is a fact about history and
stays assertable forever, so it keeps its own test, read out of the object
database.  On a shallow clone or pruned history it SKIPS with a message that
says UNVERIFIED, which is not the same as verified.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

import sys
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402


_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = "tools/ci/protected_landing_transition.json"
_DISPATCH = "tools/ci/_gate_dispatch.sh"
_HYGIENE = "tools/ci/repo_hygiene_gates.sh"

_ROLES = frozenset({"authority", "runtime"})
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_IMAGE_RE = re.compile(r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}\Z")
_FILE_KEYS = frozenset({"path", "mode", "blob_oid", "sha256", "size"})
_MANIFEST_KEYS = frozenset({
    "schema", "kind", "transition_id", "manifest_path", "runner", "paths",
    "current", "next"})

# The two register kinds, as LITERALS. Reading them off the verifier would make
# every assertion below a comparison of a constant with itself; this file is the
# independent witness and states its own expectation.
_TRANSITION_KIND = "vibeic.protected-landing-transition"
_REOBSERVATION_KIND = "vibeic.protected-landing-reobservation"

# Not a count and not a whole tuple: the entry points that decide a landing.
# If one of these stopped being protected, an unmeasured edit to it could ride
# in with any candidate, and every other assertion in this file would still
# pass. The landing verifier enforces the same closure from the other side;
# this is the independent witness.
_MUST_STAY_PROTECTED = frozenset({
    "tools/ci/_gate_dispatch.sh",
    "tools/ci/protected_landing_transition.py",
    "tools/ci/repo_hygiene_gates.sh",
    "tools/gatekeeper-land.sh",
    "tools/gatekeeper-verify-merge.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py",
})

# History, not policy: what the manifest recorded when the semantic landing
# runtime was activated. This is asserted against the object database, never
# against the live manifest.
_HISTORIC_TRANSITION = "semantic-landing-v1"
_HISTORIC_CURRENT = "legacy-landing-v1"
_HISTORIC_PROTECTED = 47
_HISTORIC_MOVED = frozenset({
    "tools/ci/repo_hygiene_gates.sh",
    "tools/gatekeeper-land.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_pytest_progress_plugin.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/ci_harness_timeout_ceiling_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/pytest_per_file_junit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py",
})

_UNVERIFIED = (
    "{what} is not in this checkout's object database (shallow clone or "
    "pruned history) — that half is UNVERIFIED here, which is not the same "
    "as verified"
)


def _git(*args: str, input_bytes: bytes | None = None) -> tuple[int, bytes]:
    proc = _pr.run(
        ["git", *args],
        cwd=_ROOT,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        check=False,
    )
    return proc.returncode, proc.stdout


def _git_bytes(*args: str, input_bytes: bytes | None = None) -> bytes:
    proc = _pr.run(
        ["git", *args],
        cwd=_ROOT,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return proc.stdout


@lru_cache(maxsize=1)
def _history_readable() -> bool:
    """`git hash-object --stdin` works anywhere; commit history does not."""
    return _git("rev-parse", "--git-dir")[0] == 0


@lru_cache(maxsize=1)
def _shallow() -> bool:
    code, out = _git("rev-parse", "--is-shallow-repository")
    return code != 0 or out.strip() == b"true"


@lru_cache(maxsize=1)
def _manifest_history() -> tuple[str, ...]:
    """Commits that touched the manifest, newest first."""
    if not _history_readable():
        return ()
    code, out = _git("log", "--format=%H", "--", _MANIFEST)
    if code != 0:
        return ()
    return tuple(out.decode("ascii").split())


def _manifest_at(rev: str) -> dict | None:
    code, raw = _git("show", f"{rev}:{_MANIFEST}")
    if code != 0:
        return None
    return json.loads(raw)


@lru_cache(maxsize=1)
def _authoring_commit() -> str | None:
    """The newest commit whose manifest blob IS the live manifest, byte for byte."""
    live = (_ROOT / _MANIFEST).read_bytes()
    for rev in _manifest_history():
        code, raw = _git("show", f"{rev}:{_MANIFEST}")
        if code == 0 and raw == live:
            return rev
    return None


def _blob_oid(raw: bytes) -> str:
    return _git_bytes("hash-object", "--stdin", input_bytes=raw).decode().strip()


def _observed(path: str) -> tuple[str, str, str, int]:
    """The live tuple for one path, in the manifest's own shape."""
    live = _ROOT / path
    info = live.lstat()
    assert stat.S_ISREG(info.st_mode) and not live.is_symlink(), (
        f"{path} is not a regular file")
    raw = live.read_bytes()
    mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
    return (mode, _blob_oid(raw), hashlib.sha256(raw).hexdigest(), len(raw))


def _recorded(row: dict) -> tuple[str, str, str, int]:
    return (row["mode"], row["blob_oid"], row["sha256"], row["size"])


def _tree_tuple(rev: str, paths: list[str]) -> dict[str, tuple[str, str, str, int]]:
    """The same tuple, read out of a commit's tree instead of the worktree."""
    out: dict[str, tuple[str, str, str, int]] = {}
    for entry in _git_bytes("ls-tree", "-z", rev, "--", *paths).split(b"\0"):
        if not entry:
            continue
        head, recorded_path = entry.split(b"\t", 1)
        mode, object_type, oid = head.decode("ascii").split()
        assert object_type == "blob", f"{recorded_path!r} at {rev[:12]} is a {object_type}"
        raw = _git_bytes("cat-file", "blob", oid)
        out[recorded_path.decode("utf-8")] = (
            mode, oid, hashlib.sha256(raw).hexdigest(), len(raw))
    return out


def _paths(manifest: dict) -> list[str]:
    return [row["path"] for row in manifest["paths"]]


def _state_map(manifest: dict, side: str) -> dict[str, tuple[str, str, str, int]]:
    return {row["path"]: _recorded(row) for row in manifest[side]["files"]}


def _moved(manifest: dict) -> set[str]:
    current = _state_map(manifest, "current")
    nxt = _state_map(manifest, "next")
    return {path for path in nxt if current[path] != nxt[path]}


@lru_cache(maxsize=1)
def _verifier():
    """The landing verifier itself, loaded by exact path.

    NO SECOND DEFINITION.  The question "does this tree move a protected path
    the base did not authorise" is answered here by running the SAME function
    the landing runs (`classify_move`), not by a restatement of it that can
    drift from it.  Loaded by path rather than by name so a same-named module
    on `sys.path` cannot answer for it.
    """
    target = _ROOT / "tools" / "ci" / "protected_landing_transition.py"
    spec = importlib.util.spec_from_file_location(
        "_parity_protected_landing_transition", target)
    assert spec is not None and spec.loader is not None, target
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(path: str, observed: tuple[str, str, str, int]) -> dict:
    """One tuple in the manifest's own row shape, for `classify_move`."""
    mode, blob_oid, sha256, size = observed
    return {"path": path, "mode": mode, "blob_oid": blob_oid,
            "sha256": sha256, "size": size}


def _rows(observed: dict[str, tuple[str, str, str, int]]) -> list[dict]:
    return [_row(path, value) for path, value in sorted(observed.items())]


@lru_cache(maxsize=1)
def _base_commit() -> str | None:
    """The commit this tree lands ON TOP OF, or None if it cannot be named.

    `tools/gatekeeper-land.sh` line 68 spells the base as
    `${GATEKEEPER_BASE:-origin/main}`, so that is asked FIRST and by the same
    name; the merge-base with it is the commit the candidate forked from.  On
    trunk itself the merge-base is HEAD, which makes the comparison STEADY --
    correct, and the reason this file stops going red behind an ordinary
    landing.
    """
    if not _history_readable():
        return None
    for ref in (os.environ.get("GATEKEEPER_BASE") or "", "origin/main", "main"):
        if not ref:
            continue
        if _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")[0] != 0:
            continue
        code, out = _git("merge-base", "HEAD", ref)
        if code == 0 and out.strip():
            return out.decode("ascii").strip()
    return None


@lru_cache(maxsize=1)
def _predecessor_of_the_anchor() -> str | None:
    """The commit whose tree `current` must record: the state moved FROM.

    On trunk, where the transition has already landed as ONE squashed commit,
    that is the anchor's first parent.  On the BRANCH that authors it, the
    anchor is a branch commit and its parent is whatever the author happened
    to commit before it -- an intermediate state that records neither tuple and
    that a squash-merge will erase.  There the state moved FROM is the BASE the
    branch forked at, which is exactly the commit
    `protected_landing_manifest_author.py --commit` observes.

    Which of the two is decided by measurement, not by a flag: an anchor the
    base can reach has landed; one it cannot is still on a branch.
    """
    author = _authoring_commit()
    if author is None:
        return None
    base = _base_commit()
    if base is not None and _git(
            "merge-base", "--is-ancestor", author, base)[0] != 0:
        return base
    if _git("rev-parse", "--verify", "--quiet", f"{author}^{{commit}}")[0] != 0:
        return None
    return f"{author}^"


@lru_cache(maxsize=1)
def _head_tuple() -> dict[str, tuple[str, str, str, int]] | None:
    """What HEAD's tree records for the protected paths."""
    if not _history_readable():
        return None
    manifest = json.loads((_ROOT / _MANIFEST).read_text(encoding="utf-8"))
    if _git("rev-parse", "--verify", "--quiet", "HEAD^{commit}")[0] != 0:
        return None
    return _tree_tuple("HEAD", _paths(manifest))


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((_ROOT / _MANIFEST).read_text(encoding="utf-8"))


def test_the_manifest_is_a_well_formed_authorised_transition(manifest):
    """Invariant 1. Whatever transition this is, it is completely described."""
    assert set(manifest) == _MANIFEST_KEYS, sorted(manifest)
    assert manifest["schema"] == 1
    assert manifest["kind"] in {_TRANSITION_KIND, _REOBSERVATION_KIND}, (
        "manifest.kind is not a protected-landing register kind: "
        f"{manifest['kind']!r}")
    assert manifest["manifest_path"] == _MANIFEST

    for what, value in (
        ("transition_id", manifest["transition_id"]),
        ("current.id", manifest["current"]["id"]),
        ("next.id", manifest["next"]["id"]),
    ):
        assert isinstance(value, str) and _ID_RE.fullmatch(value), f"{what}: {value!r}"
    assert manifest["current"]["id"] != manifest["next"]["id"], (
        "a transition whose two states share an id names no move at all")

    paths = _paths(manifest)
    assert paths, "the protected set is empty"
    assert paths == sorted(paths), "manifest.paths is not sorted"
    assert len(paths) == len(set(paths)), "a protected path is listed twice"
    assert _MANIFEST not in paths, "the manifest cannot recursively include itself"
    for row in manifest["paths"]:
        assert set(row) == {"path", "roles"}, row
        assert row["roles"], f"{row['path']} carries no role"
        assert set(row["roles"]) <= _ROLES, row
        assert row["roles"] == sorted(set(row["roles"])), row
    roles = {role for row in manifest["paths"] for role in row["roles"]}
    assert roles == _ROLES, (
        f"the protected set uses only {sorted(roles)}; both an executing "
        "runtime and the authority that measures it must be covered")

    missing = sorted(_MUST_STAY_PROTECTED - set(paths))
    assert missing == [], (
        f"these decide a landing and stopped being protected: {missing}")

    # Both tuples must describe exactly the protected path set, in the same
    # order the verifier compares them in -- no side entries, no omissions. An
    # asymmetric tuple would let a path move without either state naming it.
    for side in ("current", "next"):
        state = manifest[side]
        assert set(state) == {"id", "files"}, sorted(state)
        recorded = [row["path"] for row in state["files"]]
        assert recorded == paths, side
        for row in state["files"]:
            assert set(row) == _FILE_KEYS, row
            assert row["mode"] in {"100644", "100755"}, row
            assert _OID_RE.fullmatch(row["blob_oid"]), row
            assert _SHA256_RE.fullmatch(row["sha256"]), row
            assert type(row["size"]) is int and row["size"] >= 0, row

    # THE TWO KINDS CARRY OPPOSITE RULES AND BOTH ARE ASSERTED, so neither can
    # wear the other's shape. A register that calls itself a transition and
    # moves nothing is the historical malformation and stays refused on the
    # identical predicate; a register that calls itself a re-observation and
    # moves something is the NEW way to lie, and is refused here.
    if manifest["kind"] == _REOBSERVATION_KIND:
        smuggled = sorted(
            row["path"] for row, was in zip(manifest["next"]["files"],
                                            manifest["current"]["files"])
            if row != was)
        assert smuggled == [], (
            "this register declares itself a RE-OBSERVATION, which authorises "
            "nothing, and its `next` moves: " + ", ".join(smuggled))
    else:
        assert manifest["current"]["files"] != manifest["next"]["files"], (
            "the `next` tuple does not differ from `current`: nothing is "
            "authorised")

    runner = manifest["runner"]
    assert runner["schema"] == 1
    assert runner["engine"] == "docker"
    assert _IMAGE_RE.fullmatch(runner["image"]), (
        f"the runner image is not an immutable digest reference: {runner['image']!r}")
    assert runner["network"] == "none"
    assert runner["read_only"] is True
    assert runner["pull"] == "never"
    assert runner["cap_drop"] == ["ALL"]
    assert runner["security_opt"] == ["no-new-privileges:true"]
    assert re.fullmatch(r"[1-9][0-9]*:[0-9]+", runner["user"]), (
        f"the hermetic runner would run as uid 0: {runner['user']!r}")


def test_the_current_tuple_is_the_tuple_recorded_where_the_manifest_was_authored(
        manifest):
    """Invariant 2. `next` is a MOVE only if `current` is where we moved from.

    The anchor is discovered, not pinned: the newest commit whose manifest blob
    is byte-identical to the live one is the commit that authored this
    transition. If a predecessor manifest existed at that commit's first
    parent, the commit is a PREPARE, and PREPARE is refused when it moves
    protected bytes ("PREPARE changed live protected bytes with the manifest"),
    so `current` MUST be the tuple both that commit and its parent record.
    Measured across every manifest version in this history: 15e4c463a6,
    73a7db727c and 46964e1fb8 all satisfy it on both commits. The one
    exception is the bootstrap commit 7c376e3481, which introduced the manifest
    and activated it at once; there `current` predates the scheme and the
    commit records `next`, so that shape is asserted as the exact XOR instead.
    """
    if not _manifest_history():
        pytest.skip(_UNVERIFIED.format(what="the manifest's commit history"))
    author = _authoring_commit()
    if author is None:
        if _shallow():
            pytest.skip(_UNVERIFIED.format(
                what="the commit that authored the live manifest"))
        pytest.fail(
            "no commit in this checkout's history of the manifest carries the "
            "live manifest bytes, so its `current` tuple is an unrecorded "
            "claim rather than a state this repository ever had")

    paths = _paths(manifest)
    current = _state_map(manifest, "current")
    observed = _tree_tuple(author, paths)
    assert sorted(observed) == sorted(paths), (
        f"paths named by the manifest are absent at {author[:12]}: "
        f"{sorted(set(paths) - set(observed))}")

    predecessor = _git("cat-file", "-e", f"{author}^:{_MANIFEST}")[0] == 0
    if not predecessor:
        nxt = _state_map(manifest, "next")
        assert observed in (current, nxt), (
            f"{author[:12]} introduced the manifest, so it must record one of "
            "its two states exactly; it records a mixture")
        return

    predecessor = _predecessor_of_the_anchor()
    if predecessor is None:
        pytest.fail(
            f"{author[:12]} carries the live manifest but the state it moved "
            "FROM is not in this checkout, so `current` cannot be checked "
            "against anything")
    _assert_authoring_shape(
        author, paths, observed, _tree_tuple(predecessor, paths),
        current, _state_map(manifest, "next"))


def _assert_authoring_shape(author, paths, observed, parent_observed,
                            current, nxt) -> None:
    """The two recorded shapes, and the refusal of everything else.

    Its own function so a FORGED tuple can be pushed through exactly the code
    the live manifest goes through: a refusal only ever exercised by the one
    input that passes is a refusal nobody has checked.
    `test_a_tuple_no_commit_records_is_still_refused` is that exercise.

    THE PARENT IS THE ANCHOR OF `current`, IN BOTH SHAPES, AND IT IS NOT
    RELAXED.  Whatever the authoring commit did, the state it moved FROM has
    to be one this repository actually held, on the commit immediately before
    it.  This is the clause that makes `current` a record instead of a claim.

    THE AUTHORING COMMIT IS THEN EITHER SHAPE, AND EXACTLY ONE OF THEM.  A
    PREPARE records `current` -- it declares the move without making it.  A
    SQUASHED PREPARE+ACTIVATE records `next` -- it declares the move and makes
    it in one commit, which is what a squash-merge of a two-commit branch
    produces and is how this repository lands.  MEASURED at v1.13.21, anchor
    66fa718ae3 (`git rev-list --parents -n 1` returns ONE parent, so a squash,
    not a merge): the anchor differs from `next` on 0 of 52 paths and its
    parent differs from `current` on 0 of 52.  Both endpoints are recorded, on
    adjacent commits.  The check refused it anyway, because it assumed an
    authoring commit with a predecessor manifest could only ever be a PREPARE
    -- so a correctly recorded ACTIVATE read as an unrecorded claim.  The
    diagnosis and the shape of this limb are vibe-ic#1862's; it is carried
    here because this file is rewritten around it and the two cannot land
    side by side.
    """
    assert sorted(parent_observed) == sorted(paths), (
        f"the transition at {author[:12]} added protected paths, which it may "
        f"not: {sorted(set(paths) - set(parent_observed))}")
    parent_drift = sorted(
        path for path in paths if parent_observed[path] != current[path])
    assert parent_drift == [], (
        f"the transition at {author[:12]} does not move FROM `current`; these "
        f"differ at its parent: {parent_drift}")

    if observed == current:
        return                                            # PREPARE
    activate_drift = sorted(path for path in paths if observed[path] != nxt[path])
    assert activate_drift == [], (
        f"{author[:12]} carries the manifest but records NEITHER state: it is "
        "not `current` (a PREPARE) and it is not `next` (a squashed "
        f"PREPARE+ACTIVATE). These paths differ from `next`: {activate_drift}")


def test_the_live_tree_is_exactly_one_recorded_state_and_never_a_mixture(manifest):
    """Invariant 3. The authorised move, restated on the live bytes.

    On the paths the transition AUTHORISES, equal to `current` means PREPAREd
    and not yet activated; equal to `next` means activated.  Anything else --
    one path left behind, an activation applied by hand to half the tuple --
    is the mixture the landing verifier refuses, and it is refused here by
    mode, git blob oid, sha256 and byte length.

    On EVERY protected path, authorised or not, the live bytes must be the
    bytes THIS COMMIT records.  That is the half of the old whole-tuple
    comparison which has a non-stale answer, and it is the one with the teeth
    at run time: the register exists so that the runtime deciding a landing is
    the runtime somebody measured, and a file edited into the checkout behind
    git's back is exactly the substitution it has to refuse.  The other half --
    "has any protected path moved since the last transition" -- is answered
    against the BASE by `test_the_live_tree_moves_no_protected_path_the_base_
    did_not_authorise`, because a photograph of one commit answers it stale.
    """
    paths = _paths(manifest)
    for path in paths:
        assert (_ROOT / path).is_file(), (
            f"{path} is named by the manifest but absent from the live tree")
    observed = {path: _observed(path) for path in paths}

    head = _head_tuple()
    if head is not None:
        unlanded = sorted(path for path in paths if observed[path] != head[path])
        assert unlanded == [], (
            "these protected paths do not hold the bytes this commit records, "
            "so the runtime in this tree is not the runtime any commit "
            f"measured: {unlanded}")

    moved = sorted(_moved(manifest))
    matched: list[str] = []
    drift: dict[str, list[str]] = {}
    for side in ("current", "next"):
        recorded = _state_map(manifest, side)
        differing = sorted(path for path in moved if observed[path] != recorded[path])
        drift[manifest[side]["id"]] = differing
        if not differing:
            matched.append(manifest[side]["id"])

    assert len(matched) == 1, (
        "the authorised paths of `" + str(manifest["transition_id"]) + "` are "
        "not exactly one recorded state; paths differing from each state: "
        f"{drift}")


def test_every_protected_path_holds_bytes_the_register_records(manifest):
    """Invariant 3b. THE SAME QUESTION, ASKED OF ALL 52 PATHS AND NOT 1.

    A TRACKER THAT ONLY WATCHES ENTRIES THAT DIFFER CANNOT SEE AN ENTRY THAT
    WAS CHANGED IN PLACE. Invariant 3 above asks whether the live bytes are one
    recorded state, but it asks it of `_moved(manifest)` -- the paths the
    transition AUTHORISES, which is normally one path and is sometimes none.
    For the other fifty-one, `current == next`, so they are outside `_moved`
    and that assertion never looks at them. Nothing else looks either:

      * Invariant 3's own `unlanded` clause compares the live bytes to what
        HEAD'S TREE records, which catches a file edited into the checkout
        behind git's back. Once the edit is COMMITTED, live and HEAD agree and
        it is silent -- which is exactly the state a landing leaves.
      * Invariant 4 compares the BASE this tree lands on against the live tree.
        Its docstring says so plainly: "On trunk the merge-base with
        `origin/main` is HEAD, so this is STEADY and green -- which is the
        point; an ordinary landing leaves no residue." That is the right
        behaviour for a candidate branch and it is total blindness on trunk,
        which is where this repository lands: all four commits below are
        single-parent pushes onto main, so `classify_move` compared a tree with
        itself and could only answer STEADY.

    So once a change is ON main, no clause compared the register's recorded
    bytes against the bytes main actually ships -- for fifty-one of the
    fifty-two paths. MEASURED on ead8dddfcb (v1.13.98), five protected paths
    hold bytes matching NEITHER recorded state, and only the one inside
    `_moved` is visible to invariant 3:

      VISIBLE    tools/ci/protected_landing_transition.py       (in `_moved`)
      INVISIBLE  tools/ci/repo_hygiene_gates.sh                 d155935a7d +3
      INVISIBLE  tools/gatekeeper-verify-merge.sh               19560655df
      INVISIBLE  …/programs/drc_vacuous_pass_check.py           70afd8a696
      INVISIBLE  …/programs/repo_hygiene_parallel.py            a4604d3fa3

    WHY THAT IS NOT COSMETIC. The register exists so that "the runtime deciding
    a landing is the runtime somebody measured" -- invariant 3's own words. A
    protected path whose shipped bytes appear in neither recorded state is a
    runtime nobody measured under the register, vouched for by a register that
    still names the bytes it replaced. The four above include the hygiene gate
    runner and the merge verifier: the register was describing a landing tier
    that has not existed since v1.13.43.

    THIS IS A WEAKER PREDICATE THAN INVARIANT 3, DELIBERATELY, AND IT REPLACES
    NOTHING. For an authorised path, "matches current or next" is implied by
    "matches exactly one of them", so this adds nothing there and invariant 3
    keeps its stronger claim and its own failure text. What this adds is the
    fifty-one paths nobody was asking about.

    HOW TO CLEAR IT: re-author the manifest at the current base with
    `protected_landing_manifest_author.py --commit <base>`, which re-derives
    `current` from the tree that actually exists. Do NOT hand-edit a row --
    `test_the_current_tuple_is_the_tuple_recorded_where_the_manifest_was_authored`
    refuses a `current` the authoring commit and its parent do not both record.

    THAT COMMAND NEEDS A MOVE, AND THE DRIFT MAY NOT COME WITH ONE. Measured on
    `ac3232ddeb` (v1.14.4), the tree this clause first went red on: the last
    transition was fully activated, nothing protected was pending, and the
    author program refused -- "a manifest with no move is refused by
    parse_manifest". `--no-move` renders the register as a RE-OBSERVATION
    instead: it records the tree as it stands and authorises nothing, which is
    the strictest state `classify_move` has. That is the only way to clear this
    clause when no protected path is pending::

        python3 tools/ci/protected_landing_manifest_author.py --repo . \
            --commit <base> --transition-id <id> --current-id <id-naming-mover> \
            --next-id <id>-next --no-move \
            --out tools/ci/protected_landing_transition.json

    The ids are the audit trail: name the landing that moved the path. A
    register that records "whatever is there" without saying who put it there
    is a rubber stamp, not a record.
    """
    paths = _paths(manifest)
    observed = {path: _observed(path) for path in paths}
    current = _state_map(manifest, "current")
    nxt = _state_map(manifest, "next")

    stale = sorted(path for path in paths
                   if observed[path] != current[path]
                   and observed[path] != nxt[path])
    detail = "\n".join(
        f"    {path}\n"
        f"      current {current[path][2][:12]}  next {nxt[path][2][:12]}  "
        f"LIVE {observed[path][2][:12]}"
        f"{'  (inside the authorised move)' if path in _moved(manifest) else ''}"
        for path in stale)
    assert stale == [], (
        f"{len(stale)} of {len(paths)} protected path(s) ship bytes that "
        f"appear in NEITHER recorded state of "
        f"`{manifest['transition_id']}`, so the register vouches for a runtime "
        f"this tree does not contain:\n{detail}\n"
        f"    Re-author the manifest at this base with "
        f"protected_landing_manifest_author.py --commit <base>.")


def test_the_live_tree_moves_no_protected_path_the_base_did_not_authorise(
        manifest):
    """Invariant 4, and the clause with the teeth: `classify_move` on this tree.

    The undeclared-change refusal used to be spelled here as "the live bytes
    differ from both recorded states", which reads the answer off a photograph
    of one commit and therefore goes stale on every unrelated protected-file
    landing.  The same question against the BASE this tree lands on does not:
    the base is OBSERVED, so the only thing the manifest still has to record
    is the move it authorises.

    On trunk the merge-base with `origin/main` is HEAD, so this is STEADY and
    green -- which is the point; an ordinary landing leaves no residue.  On a
    branch it is the fork point, so a protected path this branch moves without
    a transition naming it is REFUSED here, by name, before it can land.

    `classify_move` is imported from the verifier rather than restated, so
    there is one definition of what an authorised move is.
    """
    base = _base_commit()
    if base is None:
        pytest.skip(_UNVERIFIED.format(
            what="the base commit this tree lands on ($GATEKEEPER_BASE, "
                 "origin/main or main)"))
    paths = _paths(manifest)
    verifier = _verifier()
    base_rows = _rows(_tree_tuple(base, paths))
    live_rows = _rows({path: _observed(path) for path in paths})
    operation, base_state_id, candidate_state_id = verifier.classify_move(
        base_rows, live_rows, manifest)
    assert operation in {"STEADY", "ACTIVATE"}, operation
    assert base_state_id in {manifest["current"]["id"], manifest["next"]["id"]}
    assert candidate_state_id in {
        manifest["current"]["id"], manifest["next"]["id"]}


def test_the_move_is_exactly_the_paths_the_two_states_disagree_on(manifest):
    """A partial or widened activation is refused by the landing verifier.

    The moved set is read off the manifest rather than pinned, because the set
    is a property of whichever transition is authorised; what is pinned is that
    NOTHING ELSE may differ and that the moved paths may not straddle the two
    states. That catches the half-applied activation, and it catches a live
    edit to a protected file that the transition never authorised -- including
    an edit to a file the manifest quietly widened the move to cover.
    """
    paths = _paths(manifest)
    current = _state_map(manifest, "current")
    nxt = _state_map(manifest, "next")
    moved = sorted(_moved(manifest))
    if manifest["kind"] == _REOBSERVATION_KIND:
        assert moved == [], (
            "a re-observation authorises nothing, so nothing may differ "
            f"between its two states: {moved}")
    else:
        assert moved, "the manifest authorises a transition that moves nothing"

    role_map = {row["path"]: frozenset(row["roles"]) for row in manifest["paths"]}
    for path in moved:
        assert role_map.get(path), f"{path} moves but carries no role"

    head = _head_tuple()
    for path in paths:
        if path in set(moved):
            continue
        assert current[path] == nxt[path], path
        if head is not None:
            assert _observed(path) == head[path], (
                f"{path} is outside the authorised move and its live bytes are "
                "not the bytes this commit records")

    if not moved:
        # A re-observation: every path went through the loop above, and there
        # is no move to straddle. Not a skip -- the clause that matters here
        # (live == what this commit records, on all 52) has already run.
        return
    sides = set()
    for path in moved:
        live = _observed(path)
        if live == current[path]:
            sides.add(manifest["current"]["id"])
        elif live == nxt[path]:
            sides.add(manifest["next"]["id"])
        else:
            sides.add(f"neither ({path})")
    assert len(sides) == 1, (
        "the moved paths straddle the transition -- a partial activation: "
        f"{sorted(sides)}")


def test_the_semantic_landing_activation_is_still_what_history_records():
    """The historical half, and a fact about history stays assertable forever.

    `semantic-landing-v1` moved nine paths out of a 47-path protected set, from
    `legacy-landing-v1`. That is read from the manifest version the object
    database holds, discovered by transition id rather than by a pinned sha, so
    a later transition cannot make it red and a rewritten sha cannot make it
    vacuous. Every recorded version carrying that id must agree.
    """
    if not _manifest_history():
        pytest.skip(_UNVERIFIED.format(what="the manifest's commit history"))
    versions = []
    for rev in _manifest_history():
        doc = _manifest_at(rev)
        if doc is not None and doc.get("transition_id") == _HISTORIC_TRANSITION:
            versions.append((rev, doc))
    if not versions:
        pytest.skip(_UNVERIFIED.format(
            what=f"the `{_HISTORIC_TRANSITION}` manifest version"))

    for rev, doc in versions:
        assert doc["current"]["id"] == _HISTORIC_CURRENT, rev
        assert doc["next"]["id"] == _HISTORIC_TRANSITION, rev
        assert len(doc["paths"]) == _HISTORIC_PROTECTED, rev
        current = {row["path"]: _recorded(row) for row in doc["current"]["files"]}
        nxt = {row["path"]: _recorded(row) for row in doc["next"]["files"]}
        assert {path for path in nxt if current[path] != nxt[path]} == \
            _HISTORIC_MOVED, rev


def test_phase_b_routed_producer_and_structural_opt_in_are_active():
    """The inversion of the Phase-A dormancy claim.

    While Phase-A was dormant these three had to be ABSENT from the hygiene
    script; activation is precisely the moment they become present, and the
    legacy in-repo `git ls-files` producer callsite is retired.
    """
    hygiene = (_ROOT / _HYGIENE).read_text(encoding="utf-8")
    dispatch = (_ROOT / _DISPATCH).read_text(encoding="utf-8")

    assert "routed_def_corpus.py" in hygiene, (
        "the routed-DEF corpus producer is not wired into the hygiene script")
    assert "GATE_DISPATCH_ATTEST_POPULATION" in dispatch
    assert "GATE_DISPATCH_ATTEST_POPULATION" in hygiene, (
        "the structural population attestation is not opted into")

    legacy_callsite = re.compile(
        r'gate_dispatch_over "published cells carrying a routed DEF"\s*\\\s*'
        r"_per_published_cell_gates\s*\\\s*"
        r"git -C \"\$ROOT\" ls-files --\s*\\\s*"
        r"'benchmark-data/ic/\*/\*/phase3/stage3/pnr/routed\.def'",
        re.MULTILINE,
    )
    assert not legacy_callsite.search(hygiene), (
        "the legacy in-repo git-ls-files producer callsite survived activation")


def test_the_activated_runtime_no_longer_uses_a_wall_clock_pytest_timeout():
    """The point of the transition, asserted on the artefact rather than trusted.

    `-p pytest_timeout --timeout=...` kills the session and loses its JUnit, so
    a hang becomes an unattributable red. Semantic progress replaces it; if the
    timeout idiom came back the transition would have been undone in place.
    """
    land = (_ROOT / "tools" / "gatekeeper-land.sh").read_text(encoding="utf-8")
    body = re.search(
        r"^run_repo_tools_pytest\(\) \{.*?^\}", land, re.MULTILINE | re.DOTALL)
    assert body, "run_repo_tools_pytest is gone from gatekeeper-land.sh"
    fn = body.group(0)
    assert "-p pytest_timeout" not in fn
    assert "--timeout" not in fn
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in fn
    assert "trusted_pytest_entry.py" in fn


# --------------------------------------------------------------------------
# THE PAIRED REFUSALS.
#
# Every clause above is satisfied by the tree it runs in, so on its own each
# one is a check nobody has seen say no. These push CONSTRUCTED inputs through
# the SAME code -- `_assert_authoring_shape` and the verifier's own
# `classify_move` -- and require the refusal, and require it to NAME the file.
# A register that stops refusing is not a register, and it is worse than a
# stale one, because the staleness was at least visible.
# --------------------------------------------------------------------------

def _forge(row: dict) -> dict:
    """The same path, in a state no commit records."""
    return {**row,
            "blob_oid": "0" * len(row["blob_oid"]),
            "sha256": "f" * len(row["sha256"]),
            "size": row["size"] + 1}


def _live_rows(manifest: dict) -> list[dict]:
    return _rows({path: _observed(path) for path in _paths(manifest)})


def test_a_tuple_no_commit_records_is_still_refused(manifest):
    """Accepting the squashed shape must not accept a tuple nobody recorded.

    Runs the LIVE anchor and the LIVE parent through `_assert_authoring_shape`
    with one path of `current` -- and then of `next` -- forged into a state no
    commit holds. If this ever passes, invariant 2 has stopped checking and
    every clause in it is decoration.
    """
    if not _manifest_history():
        pytest.skip(_UNVERIFIED.format(what="the manifest's commit history"))
    author = _authoring_commit()
    if author is None:
        pytest.skip(_UNVERIFIED.format(what="the authoring commit"))
    paths = _paths(manifest)
    predecessor = _predecessor_of_the_anchor()
    if predecessor is None:
        pytest.skip(_UNVERIFIED.format(what="the state the anchor moved FROM"))
    observed = _tree_tuple(author, paths)
    parent_observed = _tree_tuple(predecessor, paths)
    current = _state_map(manifest, "current")
    nxt = _state_map(manifest, "next")

    # THE CONTROL. The live tuple is accepted, or the negatives below prove
    # nothing -- a refusal that fires on everything is not discriminating.
    _assert_authoring_shape(author, paths, observed, parent_observed,
                            current, nxt)

    for victim in (sorted(current)[0], sorted(current)[-1]):
        forged = dict(current)
        mode, oid, sha256, size = forged[victim]
        forged[victim] = (mode, "0" * len(oid), "f" * len(sha256), size + 1)
        with pytest.raises(AssertionError) as caught:
            _assert_authoring_shape(author, paths, observed, parent_observed,
                                    forged, nxt)
        assert victim in str(caught.value), (victim, str(caught.value)[:400])

    if observed != current:                      # the squashed ACTIVATE limb
        victim = sorted(nxt)[0]
        forged_next = dict(nxt)
        mode, oid, sha256, size = forged_next[victim]
        forged_next[victim] = (mode, "0" * len(oid), "f" * len(sha256), size + 1)
        with pytest.raises(AssertionError) as caught:
            _assert_authoring_shape(author, paths, observed, parent_observed,
                                    current, forged_next)
        assert victim in str(caught.value), str(caught.value)[:400]


def test_a_protected_path_the_manifest_authorises_no_move_of_is_refused(
        manifest):
    """The undeclared change, CONSTRUCTED -- one per role, named in the refusal.

    This is the case the whole register exists for and the one an "accept any
    tree" repair would silently lose: a protected file changed by a candidate
    that no transition names. The base here is the live tree, so the control
    is STEADY and the only difference between the arms is the one mutated row.
    """
    verifier = _verifier()
    live = _live_rows(manifest)
    moved = _moved(manifest)
    roles = {row["path"]: frozenset(row["roles"]) for row in manifest["paths"]}

    # THE CONTROL, in both arms: an untouched tree is STEADY, not a refusal.
    operation, _base_id, _cand_id = verifier.classify_move(live, live, manifest)
    assert operation == "STEADY", operation

    victims = []
    for role in sorted(_ROLES):
        for row in live:
            if row["path"] not in moved and role in roles[row["path"]]:
                victims.append(row["path"])
                break
    assert len(victims) == len(_ROLES), (
        f"no unauthorised path to mutate for every role: {victims}")

    for victim in victims:
        candidate = [_forge(row) if row["path"] == victim else row
                     for row in live]
        with pytest.raises(verifier.Refusal) as caught:
            verifier.classify_move(live, candidate, manifest)
        assert victim in str(caught.value), str(caught.value)[:400]
        assert "authorises no move" in str(caught.value), str(caught.value)[:400]


def test_an_activation_to_bytes_next_does_not_record_is_refused(manifest):
    """The authorised path, moved to the wrong bytes, and moved back.

    `classify_move` accepts an ACTIVATE only when the candidate installs
    EXACTLY the bytes `next` records, and only while the base still stands at
    `current`. Both refusals are constructed here, against a base built to
    stand at `current` on the authorised paths -- so the ACTIVATE control
    below is a real acceptance and not a vacuous one.
    """
    verifier = _verifier()
    live = _live_rows(manifest)
    current = {row["path"]: row for row in manifest["current"]["files"]}
    nxt = {row["path"]: row for row in manifest["next"]["files"]}
    moved = sorted(_moved(manifest))
    if not moved:
        pytest.skip(
            "this register is a RE-OBSERVATION and authorises no move, so "
            "there is no ACTIVATE to construct -- that half is UNVERIFIED "
            "here, which is not the same as verified")

    prepared = [dict(current[row["path"]]) if row["path"] in set(moved) else row
                for row in live]

    # THE CONTROL: from `current`, installing exactly `next` IS an ACTIVATE.
    activated = [dict(nxt[row["path"]]) if row["path"] in set(moved) else row
                 for row in live]
    operation, base_id, cand_id = verifier.classify_move(
        prepared, activated, manifest)
    assert operation == "ACTIVATE", operation
    assert base_id == manifest["current"]["id"]
    assert cand_id == manifest["next"]["id"]

    # Bytes `next` does not record, on an authorised path.
    for victim in moved:
        wrong = [_forge(row) if row["path"] == victim else row
                 for row in prepared]
        with pytest.raises(verifier.Refusal) as caught:
            verifier.classify_move(prepared, wrong, manifest)
        assert victim in str(caught.value), str(caught.value)[:400]
        assert "neither authorised atomic state" in str(caught.value)

    # And a spent transition may not be re-run: from `next`, back to `current`.
    for victim in moved:
        rolled = [dict(current[row["path"]]) if row["path"] == victim else row
                  for row in activated]
        with pytest.raises(verifier.Refusal) as caught:
            verifier.classify_move(activated, rolled, manifest)
        assert victim in str(caught.value), str(caught.value)[:400]
        assert "rollback or unprepared move" in str(caught.value)
