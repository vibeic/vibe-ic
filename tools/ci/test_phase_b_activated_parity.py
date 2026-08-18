"""Phase-B parity: the landing runtime IS the activated tuple, exactly.

This file replaces `test_phase_a_dormant_parity.py`, whose subject was the
Phase-A commit: "install transition evidence WITHOUT activating Phase B". Every
assertion in that file was a DORMANCY claim -- the five protected runtime paths
still equal base 116, the hygiene script still behaves exactly like base 116,
and Phase-B's routed producer and structural opt-in are not wired. ACTIVATE
falsifies all of them BY DESIGN, so keeping it would have pinned main to a
premise the tree had deliberately left behind: five tests that can only ever be
red, which is worse than no test, because a permanently-red guard trains the
reader to ignore the file.

The rigour is retained and inverted. This is still an object-database test, not
a restatement of production constants: the expected bytes are read from the
manifest that `protected_landing_transition.py` itself verifies at landing
time, and the historical half is read from the PREPARE commit's object
database.

Three invariants, which together say "the activation happened, completely, and
nothing else moved":

  1. The manifest is the one this transition was authorised for -- schema, kind,
     both state ids, and a 47-path protected set whose roles are known.
  2. The manifest's `current` tuple is still EXACTLY the commit it was PREPAREd
     against (Phase-A head, not base 116 -- Phase-A had already installed the
     authority files, so 28 of the 47 paths differ from 116 and 0 differ from
     the PREPARE commit). That is a fact about history and stays assertable
     forever; it is what makes the `next` tuple a *move* rather than a
     free-standing claim.
  3. The LIVE tree equals the manifest's `next` tuple for all 47 paths -- byte
     length, sha256 and git blob oid. Nine of those paths genuinely change
     between `current` and `next`; the other 38 must be untouched, and a
     mixture is exactly what the landing verifier refuses.

Post-activation the state machine settles by itself: ACTIVATE leaves the
manifest unchanged, so the next landing observes base_state_id ==
candidate_state_id == `semantic-landing-v1` and classifies as STEADY (see
`protected_landing_transition.py`, `_match_state` / operation selection).
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
# The commit the manifest was PREPAREd against (Phase-A head). Measured: the
# manifest's `current` tuple matches all 47 paths here and 28 of them differ
# from base 116, because Phase-A had already installed the authority files.
_PREPARE = "d78f84997aff"
_MANIFEST = "tools/ci/protected_landing_transition.json"
_DISPATCH = "tools/ci/_gate_dispatch.sh"
_HYGIENE = "tools/ci/repo_hygiene_gates.sh"

_CURRENT_ID = "legacy-landing-v1"
_NEXT_ID = "semantic-landing-v1"
_PROTECTED_PATHS = 47
_ROLES = frozenset({"authority", "runtime"})

# The nine paths whose bytes genuinely move. Named rather than counted, so that
# a manifest which quietly widened or narrowed the activation is caught here
# instead of silently redefining what "the activation" was.
_MOVED = frozenset({
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


def _git_bytes(*args: str, input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=_ROOT,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return proc.stdout


def _commit_present(rev: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{rev}^{{commit}}"],
        cwd=_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False)
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


def test_the_manifest_is_the_authorised_transition(manifest):
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

    # Both tuples must describe exactly the protected path set -- no side
    # entries, no omissions. An asymmetric tuple would let a path move without
    # either state naming it.
    for side in ("current", "next"):
        recorded = [row["path"] for row in manifest[side]["files"]]
        assert sorted(recorded) == sorted(paths), side


def test_the_current_tuple_is_exactly_the_prepare_commit(manifest):
    """History half. `next` is a MOVE only if `current` is where we moved from.

    The anchor is the PREPARE commit, NOT base 116. PREPARE requires
    `candidate_manifest["current"]["files"] == base_files` observed at the
    commit the manifest was authored against, and Phase-A had already added the
    27 authority files and rewritten `_gate_dispatch.sh` by then. Measured: 28
    of the 47 paths differ from base 116 and 0 differ from the PREPARE commit.
    """
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


def test_the_live_tree_is_exactly_the_activated_next_tuple(manifest):
    """The activation half: every protected path, byte-identical to `next`."""
    drift = []
    for row in manifest["next"]["files"]:
        path = row["path"]
        assert (_ROOT / path).is_file(), f"{path} is named by the manifest but absent"
        if _observed(path) != _recorded(row):
            drift.append(path)
    assert drift == [], (
        "the live protected tuple is not the activated state; these paths do "
        f"not match the manifest's `{_NEXT_ID}` tuple: {drift}")


def test_the_activation_moved_exactly_the_nine_runtime_paths(manifest):
    """A partial or widened activation is refused by the landing verifier.

    Pinning the set here catches a manifest edit that redefined the move, which
    the byte-equality test above would otherwise happily confirm against the
    edited manifest.
    """
    current = {row["path"]: _recorded(row) for row in manifest["current"]["files"]}
    nxt = {row["path"]: _recorded(row) for row in manifest["next"]["files"]}
    moved = {path for path in nxt if current[path] != nxt[path]}
    assert moved == _MOVED
    for path in nxt:
        if path not in _MOVED:
            assert _observed(path) == current[path], (
                f"{path} is outside the activation but its live bytes moved")


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
