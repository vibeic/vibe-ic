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
(`protected_landing_transition.py`, `_match_state` and `build_receipt`):

  * PREPARE lands a NEW manifest and is REFUSED if it moves protected bytes,
    so at a PREPARE commit the live tuple equals `current`.
  * ACTIVATE moves the protected bytes and leaves the manifest untouched, so
    afterwards the live tuple equals `next` and every later landing is STEADY.
  * `_match_state` accepts a tuple equal to `current` or equal to `next` and
    REFUSES anything else.  A per-file mixture is the refusal with teeth.

Both states are real states of main, measured in this history: at 15e4c463a6
("PREPARE: authorise the xdist per-worker progress protocol") the live tuple
equals `current` exactly; at 74ac9fa788, after 2b93d8723f ("ACTIVATE"), it
equals `next` exactly.  A test that demanded `next` specifically would be red
on main for the whole PREPARE..ACTIVATE window -- the identical failure mode,
rearmed.  So the assertion here is the exact XOR: the live tuple equals ONE
recorded state on EVERY protected path -- mode, git blob oid, sha256 and byte
length -- and the paths where `current` and `next` disagree are exactly the
paths the transition moves.  Nothing outside that set may differ, and the
moved paths may not straddle the two states.

The three invariants, as properties:

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
  3. The live tree is exactly one recorded state, per path, with no mixture.

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
import json
import re
import stat
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest


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
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py",
})

_UNVERIFIED = (
    "{what} is not in this checkout's object database (shallow clone or "
    "pruned history) — that half is UNVERIFIED here, which is not the same "
    "as verified"
)


#: Inner bound for the `git` plumbing calls below, in seconds.
#:
#: These are `git cat-file` / `git ls-tree` / `git rev-parse` reads of this
#: repository, MEASURED at under 0.01 s each in the pinned image (the whole file
#: runs in 1.30 s with the sibling preflight file). The 120 s literal they
#: carried was above the per-call ceiling `ci_harness_timeout_ceiling_check`
#: publishes, and a bound above that ceiling turns that gate red — which put a
#: smoke-floor test, and therefore every landing, in refusal.
_GIT_BOUND = 30


def _git(*args: str, input_bytes: bytes | None = None) -> tuple[int, bytes]:
    proc = subprocess.run(
        ["git", *args],
        cwd=_ROOT,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_GIT_BOUND,
        check=False,
    )
    return proc.returncode, proc.stdout


def _git_bytes(*args: str, input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=_ROOT,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_GIT_BOUND,
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


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((_ROOT / _MANIFEST).read_text(encoding="utf-8"))


def test_the_manifest_is_a_well_formed_authorised_transition(manifest):
    """Invariant 1. Whatever transition this is, it is completely described."""
    assert set(manifest) == _MANIFEST_KEYS, sorted(manifest)
    assert manifest["schema"] == 1
    assert manifest["kind"] == "vibeic.protected-landing-transition"
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

    assert manifest["current"]["files"] != manifest["next"]["files"], (
        "the `next` tuple does not differ from `current`: nothing is authorised")

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

    drift = sorted(path for path in paths if observed[path] != current[path])
    assert drift == [], (
        f"{author[:12]} authored this manifest over an existing one, which the "
        "landing verifier only accepts as a PREPARE, and a PREPARE may not "
        "move protected bytes; `current` must therefore be the tuple that "
        f"commit records, and these paths disagree: {drift}")

    parent_observed = _tree_tuple(f"{author}^", paths)
    assert sorted(parent_observed) == sorted(paths), (
        f"the PREPARE at {author[:12]} added protected paths, which it may not: "
        f"{sorted(set(paths) - set(parent_observed))}")
    parent_drift = sorted(
        path for path in paths if parent_observed[path] != current[path])
    assert parent_drift == [], (
        f"the PREPARE at {author[:12]} moved protected bytes together with the "
        f"manifest; these differ from `current` at its parent: {parent_drift}")


def test_the_live_tree_is_exactly_one_recorded_state_and_never_a_mixture(manifest):
    """Invariant 3. `_match_state`, restated on the live bytes.

    Equal to `current` means PREPAREd and not yet activated; equal to `next`
    means activated. Anything else -- one path drifted, one path left behind,
    an activation applied by hand to half the tuple -- is the mixture the
    landing verifier refuses, and it is refused here on every protected path by
    mode, git blob oid, sha256 and byte length.
    """
    paths = _paths(manifest)
    for path in paths:
        assert (_ROOT / path).is_file(), (
            f"{path} is named by the manifest but absent from the live tree")
    observed = {path: _observed(path) for path in paths}

    matched: list[str] = []
    drift: dict[str, list[str]] = {}
    for side in ("current", "next"):
        recorded = _state_map(manifest, side)
        differing = sorted(path for path in paths if observed[path] != recorded[path])
        drift[manifest[side]["id"]] = differing
        if not differing:
            matched.append(manifest[side]["id"])

    assert len(matched) == 1, (
        "the live protected tuple is not exactly one recorded state of "
        f"`{manifest['transition_id']}`; paths differing from each state: {drift}")


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
    assert moved, "the manifest authorises a transition that moves nothing"

    role_map = {row["path"]: frozenset(row["roles"]) for row in manifest["paths"]}
    for path in moved:
        assert role_map.get(path), f"{path} moves but carries no role"

    for path in paths:
        if path in set(moved):
            continue
        assert current[path] == nxt[path], path
        assert _observed(path) == current[path], (
            f"{path} is outside the authorised move but its live bytes differ "
            "from both recorded states")

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
