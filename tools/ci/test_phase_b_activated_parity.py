"""The landing runtime is one of its manifest's TWO authorised states, exactly.

HISTORY OF THIS FILE, because it has been rewritten twice and both rewrites were
the design working rather than churn. `test_phase_a_dormant_parity.py` asserted
Phase-A DORMANCY; ACTIVATE falsified every one of its claims by design, so it was
replaced by a file asserting the activated tuple. That file in turn pinned ONE
moment — `live == next` — and the next repair to a protected runtime path
falsified it the same way. A guard that can only be true between two landings
trains the reader to ignore it, which is worse than no guard.

So this file asserts the INVARIANT instead of the moment, and the invariant is
the manifest's own: `protected_landing_transition._match_state` accepts a
protected tuple that equals `current` OR `next` and refuses everything else,
because those are the only two states a landing may observe. PREPARE moves the
manifest and no bytes; ACTIVATE moves the bytes and no manifest. Both are
legitimate tips and this file is true at both.

What keeps that from being a weaker claim is the BICONDITIONAL below: the state
the tuple is in must agree with what the runtime actually does. A tree at `next`
must carry the repair `next` was authorised for; a tree at `current` must not. A
half-activation — some protected paths moved, or the bytes moved without the
behaviour — satisfies neither side and is exactly what the landing verifier
refuses.

Four invariants, which together say "the runtime is at an authorised state,
completely, and nothing else moved":

  1. The manifest is a well-formed transition — schema, kind, both state ids, and
     a 47-path protected set whose roles are known. Its `paths` set is IMMUTABLE
     under this protocol (PREPARE refuses a path-set change and ACTIVATE refuses
     any manifest change at all), so the count is pinned rather than counted.
  2. `current` is EXACTLY the live tuple at the commit the transition was
     PREPAREd against. That is a fact about history and stays assertable forever;
     it is what makes `next` a *move* rather than a free-standing claim.
  3. The live tree equals `current` or `next` for all 47 paths — byte length,
     sha256 and git blob oid — and the paths that differ between the two tuples
     are exactly the declared move.
  4. The behaviour agrees with the state (the biconditional).
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = "tools/ci/protected_landing_transition.json"
_DISPATCH = "tools/ci/_gate_dispatch.sh"
_HYGIENE = "tools/ci/repo_hygiene_gates.sh"
_LAND = "tools/gatekeeper-land.sh"

# The commit `semantic-landing-v2` was PREPAREd against: the activated
# `semantic-landing-v1` tip. Measured: the manifest's `current` tuple matches all
# 47 paths here.
_PREPARE = "7c376e348"
_CURRENT_ID = "semantic-landing-v1"
_NEXT_ID = "semantic-landing-v2"
_PROTECTED_PATHS = 47
_ROLES = frozenset({"authority", "runtime"})

# The paths whose bytes this transition moves. NAMED rather than counted, so a
# manifest edit that quietly widened or narrowed the move is caught here instead
# of being confirmed by the byte-equality test against the edited manifest.
_MOVED = frozenset({
    "tools/gatekeeper-land.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/ci_harness_timeout_ceiling_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py",
})

# WHAT `semantic-landing-v2` IS FOR, in one readable token per claim. v1 routed
# all three landing arms through the isolated trusted entry, and `-I` suppresses
# the USER site directory: on a host whose test runner lives only there the child
# died before one lifecycle event and EVERY selected file in EVERY arm reported
# NORECORD, with no junit test case anywhere. Measured on the landing host at
# 7c376e348, the repo-tools arm alone: asked 40, recorded 0, NORECORD 40.
_PREFLIGHT_PROGRAM = "landing_pytest_runtime_preflight.py"
_HOST_LANE_ENV = "VIBEIC_TRUSTED_PYTEST_SITE"


def _git_bytes(*args: str, input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(
        ["git", *args], cwd=_ROOT, input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return proc.stdout


def _commit_present(rev: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=_ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return proc.returncode == 0


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


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((_ROOT / _MANIFEST).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live_state(manifest) -> str:
    """Which authorised state the tree is at — the verifier's own rule.

    `_match_state` refuses a tuple matching neither, so a test that could not
    decide would be describing a tree the landing verifier already rejects.
    """
    live = {row["path"]: _observed(row["path"])
            for row in manifest["next"]["files"]}
    for side in ("current", "next"):
        recorded = {row["path"]: _recorded(row) for row in manifest[side]["files"]}
        if live == recorded:
            return manifest[side]["id"]
    drift = sorted(path for path, value in live.items()
                   if value != {row["path"]: _recorded(row)
                                for row in manifest["next"]["files"]}[path])
    pytest.fail(
        "the live protected tuple matches NEITHER authorised atomic state, "
        "which is what protected_landing_transition._match_state refuses. "
        f"Paths differing from `{_NEXT_ID}`: {drift}")


def test_the_manifest_is_a_wellformed_authorised_transition(manifest):
    assert manifest["schema"] == 1
    assert manifest["kind"] == "vibeic.protected-landing-transition"
    assert manifest["manifest_path"] == _MANIFEST
    assert manifest["transition_id"] == _NEXT_ID
    assert manifest["current"]["id"] == _CURRENT_ID
    assert manifest["next"]["id"] == _NEXT_ID

    paths = [row["path"] for row in manifest["paths"]]
    assert len(paths) == _PROTECTED_PATHS
    assert len(set(paths)) == _PROTECTED_PATHS, "a protected path is listed twice"
    for row in manifest["paths"]:
        assert row["roles"], f"{row['path']} carries no role"
        assert set(row["roles"]) <= _ROLES, row

    # Both tuples must describe exactly the protected path set — no side entries,
    # no omissions. An asymmetric tuple would let a path move without either
    # state naming it.
    for side in ("current", "next"):
        recorded = [row["path"] for row in manifest[side]["files"]]
        assert sorted(recorded) == sorted(paths), side


def test_the_current_tuple_is_exactly_the_prepare_commit(manifest):
    """History half. `next` is a MOVE only if `current` is where we moved from."""
    if not _commit_present(_PREPARE):
        pytest.skip(
            f"the PREPARE commit {_PREPARE[:12]} is not in this checkout's "
            "object database (shallow clone or pruned history) — the historical "
            "half is UNVERIFIED here, which is not the same as verified")
    for row in manifest["current"]["files"]:
        path = row["path"]
        tree = _git_bytes("ls-tree", "-z", _PREPARE, "--", path)
        assert tree, f"{path} does not exist at PREPARE {_PREPARE[:12]}"
        head, recorded_path = tree.rstrip(b"\0").split(b"\t", 1)
        mode, object_type, blob = head.decode("ascii").split()
        assert recorded_path.decode("utf-8") == path
        assert object_type == "blob"
        raw = _git_bytes("cat-file", "blob", blob)
        assert (mode, blob, hashlib.sha256(raw).hexdigest(), len(raw)) == \
            _recorded(row), path


def test_the_transition_moves_exactly_the_declared_runtime_paths(manifest):
    """A partial or widened move is refused by the landing verifier.

    Pinning the set here catches a manifest edit that redefined the move, which
    the state test above would otherwise happily confirm against the edited
    manifest.
    """
    current = {row["path"]: _recorded(row) for row in manifest["current"]["files"]}
    nxt = {row["path"]: _recorded(row) for row in manifest["next"]["files"]}
    moved = {path for path in nxt if current[path] != nxt[path]}
    assert moved == _MOVED


def test_the_live_tree_is_one_of_the_two_authorised_states(manifest, live_state):
    """`live_state` fails if it is neither; this pins what "neither" would mean."""
    assert live_state in {_CURRENT_ID, _NEXT_ID}
    # Whatever state the tree is at, the 44 paths OUTSIDE the move are identical
    # in both tuples, so they are asserted unconditionally. A mixture is exactly
    # what the landing verifier refuses.
    current = {row["path"]: _recorded(row) for row in manifest["current"]["files"]}
    for path, recorded in current.items():
        if path not in _MOVED:
            assert _observed(path) == recorded, (
                f"{path} is outside the declared move but its live bytes moved")


def test_the_runtime_behaviour_agrees_with_the_state_it_is_in(live_state):
    """THE BICONDITIONAL. Bytes and behaviour must move together or not at all.

    `semantic-landing-v2` exists to make the landing REFUSE ONCE, attributably,
    on a host where the isolated trusted entry cannot import the test runner —
    instead of reporting NORECORD for every file in all three arms. So a tree at
    `next` must carry that refusal and the host lane it names, and a tree at
    `current` must carry neither. Asserting only one direction would let a
    reverted runtime sit under an activated manifest and still read as green.
    """
    land = (_ROOT / _LAND).read_text(encoding="utf-8")
    entry = (_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
             "programs" / "trusted_pytest_entry.py").read_text(encoding="utf-8")
    activated = live_state == _NEXT_ID

    assert (_PREFLIGHT_PROGRAM in land) is activated, (
        f"state is {live_state} but the landing "
        f"{'does not run' if activated else 'runs'} the runtime preflight")
    assert (_HOST_LANE_ENV in entry) is activated, (
        f"state is {live_state} but the trusted entry "
        f"{'has no' if activated else 'has a'} host lane")
    if activated:
        # The preflight must be able to STOP the tier, not merely run in it.
        guard = re.search(
            r'^if ! python3 "\$PROGRAMS/' + re.escape(_PREFLIGHT_PROGRAM)
            + r'"; then\n(?:.*\n)*?^fi$', land, re.MULTILINE)
        assert guard, "the runtime preflight is not a fatal top-level guard"
        assert "exit 2" in guard.group(0), (
            "the runtime preflight guard does not refuse the landing")


def test_phase_b_routed_producer_and_structural_opt_in_are_active():
    """Carried forward unchanged from the v1 activation: these became present at
    ACTIVATE and no later transition may quietly undo them."""
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


def test_the_landing_runtime_has_no_wall_clock_pytest_timeout():
    """The point of the v1 transition, still asserted on the artefact.

    `-p pytest_timeout --timeout=...` kills the session and loses its JUnit, so a
    hang becomes an unattributable red. Semantic progress replaces it; if the
    timeout idiom came back the transition would have been undone in place.
    """
    land = (_ROOT / _LAND).read_text(encoding="utf-8")
    body = re.search(
        r"^run_repo_tools_pytest\(\) \{.*?^\}", land, re.MULTILINE | re.DOTALL)
    assert body, "run_repo_tools_pytest is gone from gatekeeper-land.sh"
    fn = body.group(0)
    assert "-p pytest_timeout" not in fn
    assert "--timeout" not in fn
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in fn
    assert "trusted_pytest_entry.py" in fn
