"""A protected runtime path must be RENAMEABLE, in-band, exactly once.

WHY THIS FILE EXISTS.  Before `manifest.moves`, the protected register could
evolve BYTES at frozen PATHS and nothing else: `build_receipt` observed the
CANDIDATE at the BASE's path list, so a candidate that renamed a protected file
refused with "protected path is absent" before a single test ran.  Adding,
removing or renaming a protected runtime path was inexpressible, and the only
live precedent for doing it -- `c51f830824`, which grew `RUNTIME_PATHS` from
nine entries to eleven -- says in its own last line that it "Landed with
--no-verify".

Every test here is written so that it CANNOT PASS against the pre-move code.
`test_the_rename_is_refused_when_the_base_authorises_no_move` is the negative
control: it pins the OLD behaviour, so the suite proves the new limb is reached
because the manifest declares the move and not for some unrelated reason.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_T = importlib.util.spec_from_file_location(
    "test_protected_landing_transition",
    _HERE / "test_protected_landing_transition.py")
assert _T and _T.loader
T = importlib.util.module_from_spec(_T)
_T.loader.exec_module(T)

#: THE SAME MODULE OBJECT THE FIXTURES RAISE FROM, not a second load of the
#: same file.  `importlib` gives a fresh module each time, so a private copy
#: would define a DIFFERENT `Refusal` class and every `pytest.raises` here
#: would miss the exception it was written to catch -- a test that cannot fail
#: for the reason it claims.  Measured: with a private copy, five of these
#: reported FAILED while the correct refusal was visible in the traceback.
P = T.P

#: The path this suite renames.  It is DERIVED from `RUNTIME_PATHS`, never
#: typed: a test that hard-codes the name of the file it renames goes stale the
#: first time that file is renamed, which is the exact disease this whole change
#: treats.  `runtime` is the role worth testing because its set is compared for
#: EXACT equality; an authority-only path is compared as a subset and would
#: prove less.
FROM_PATH = sorted(P.RUNTIME_PATHS)[-1]
TO_PATH = FROM_PATH.rsplit("/", 1)[0] + "/zz_renamed_by_this_test.py"
assert TO_PATH not in P.RUNTIME_PATHS | P.REQUIRED_AUTHORITY_PATHS


def _moved_manifest(repo: Path, base_manifest: dict) -> dict:
    """BASE's manifest, re-issued to AUTHORISE the rename.

    `current` still photographs the live tuple at the OLD paths.  `next`
    photographs the SAME BYTES at the NEW paths -- a rename moves a file, it
    does not rewrite one -- so the only difference between the two states is
    where the bytes live.  That is what makes the move checkable.
    """
    manifest = P.strict_loads(P.canonical_bytes(base_manifest),
                              what="base manifest")
    manifest["transition_id"] = "rename-flow-matrix-v1"
    manifest["moves"] = [{"from": FROM_PATH, "to": TO_PATH}]
    manifest["current"] = {"id": "before-the-rename",
                           "files": list(base_manifest["current"]["files"])}
    renamed = []
    for row in base_manifest["current"]["files"]:
        row = dict(row)
        if row["path"] == FROM_PATH:
            row["path"] = TO_PATH
        renamed.append(row)
    manifest["next"] = {"id": "after-the-rename",
                        "files": sorted(renamed, key=lambda r: r["path"])}
    return manifest


def _perform(repo: Path, authorising: dict, *, close: bool = True) -> str:
    """Do what the RENAME landing does: move the file, close the transition.

    The move happens FIRST, because the closing register photographs the tuple
    the candidate actually holds -- and a register written before the move
    would be describing a tree that does not exist yet.
    """
    T._git(repo, "mv", FROM_PATH, TO_PATH)
    if close:
        register = _closed_register(repo, authorising)
    else:
        register = P.strict_loads(P.canonical_bytes(authorising), what="m")
        register["transition_id"] = "rename-flow-matrix-v1-open"
    T._write(repo, P.MANIFEST_PATH, P.canonical_bytes(register))
    return T._commit(repo, "rename candidate")


def _closed_register(repo: Path, authorising: dict) -> dict:
    """The register the candidate must ship: moved paths, no pending move."""
    manifest = P.strict_loads(P.canonical_bytes(authorising),
                              what="candidate manifest")
    manifest["transition_id"] = "rename-flow-matrix-v1-closed"
    manifest["moves"] = []
    manifest["paths"] = sorted(
        [{"path": (TO_PATH if row["path"] == FROM_PATH else row["path"]),
          "roles": list(row["roles"])} for row in authorising["paths"]],
        key=lambda r: r["path"])
    manifest["current"] = {"id": "after-the-rename",
                           "files": list(authorising["next"]["files"])}
    # A register must always declare a REAL pending transition -- `next` may
    # not equal `current` -- so the closing register opens the next one rather
    # than photographing the same tuple twice.
    manifest["next"] = {
        "id": "after-the-rename-next",
        "files": [T._record(repo, row["path"], b"future:" + row["path"].encode())
                  for row in authorising["next"]["files"]]}
    return manifest


def _base_with_authorised_move(tmp_path: Path):
    repo, _base, manifest = T._repo(tmp_path)
    authorising = _moved_manifest(repo, manifest)
    T._write(repo, P.MANIFEST_PATH, P.canonical_bytes(authorising))
    base = T._commit(repo, "base authorises the rename")
    return repo, base, authorising


# --------------------------------------------------------------------------
# THE NEGATIVE CONTROL.  This is the behaviour BEFORE moves existed, and it
# must survive unchanged: with no authorised move, a rename is still refused.
# --------------------------------------------------------------------------
def test_the_rename_is_refused_when_the_base_authorises_no_move(tmp_path):
    repo, base, _manifest = T._repo(tmp_path)
    T._git(repo, "mv", FROM_PATH, TO_PATH)
    candidate = T._commit(repo, "rename with no authorisation")
    with pytest.raises(P.Refusal) as excinfo:
        T._receipt(repo, base, candidate, tmp_path)
    assert "protected path is absent" in str(excinfo.value)
    assert FROM_PATH in str(excinfo.value)


def test_apply_moves_with_no_moves_is_the_identity():
    """The empty case must be bit-identical, or the new limb is reachable from
    a landing that declares nothing -- which is how a safety gate acquires a
    hole nobody is looking at."""
    names = sorted(P.REQUIRED_AUTHORITY_PATHS | P.RUNTIME_PATHS)
    assert P.apply_moves(names, []) == names


def test_a_manifest_without_the_moves_key_still_parses(tmp_path):
    """BASE authority is read from whatever commit is the base -- including one
    written before `moves` existed.  Absent is not malformed."""
    repo, _base, manifest = T._repo(tmp_path)
    assert "moves" not in manifest
    parsed = P.parse_manifest(
        P.strict_loads(P.canonical_bytes(manifest), what="m"), 40)
    assert parsed["moves"] == []


# --------------------------------------------------------------------------
# THE POSITIVE CASE.
# --------------------------------------------------------------------------
def test_a_base_authorised_rename_is_classified_RENAME(tmp_path):
    repo, base, authorising = _base_with_authorised_move(tmp_path)
    candidate = _perform(repo, authorising)
    receipt = T._receipt(repo, base, candidate, tmp_path)
    payload = receipt["payload"]
    assert payload["operation"] == "RENAME"
    assert payload["moves"] == [{"from": FROM_PATH, "to": TO_PATH}]
    observed = [row["path"] for row in payload["candidate_files"]]
    assert TO_PATH in observed and FROM_PATH not in observed
    # The receipt must survive its own parser, or nothing downstream can read it.
    P._parse_receipt(P.strict_loads(P.canonical_bytes(receipt), what="r"), 40)


def test_the_renamed_row_keeps_the_roles_of_the_path_it_came_from(tmp_path):
    """A rename must not launder a runtime file into an authority one."""
    repo, base, authorising = _base_with_authorised_move(tmp_path)
    candidate = _perform(repo, authorising)
    receipt = T._receipt(repo, base, candidate, tmp_path)
    was = next(row["roles"] for row in receipt["payload"]["base_files"]
               if row["path"] == FROM_PATH)
    now = next(row["roles"] for row in receipt["payload"]["candidate_files"]
               if row["path"] == TO_PATH)
    assert now == was


# --------------------------------------------------------------------------
# FALSIFICATION.  Each of these is a way the move could be abused; each must
# refuse, and the refusal must NAME what is wrong.
# --------------------------------------------------------------------------
def test_a_move_onto_an_already_protected_path_is_refused(tmp_path):
    """Renaming A onto B where B is protected merges two register rows into
    one and silently drops a file -- a deletion wearing a rename's clothes."""
    repo, _base, manifest = T._repo(tmp_path)
    other = sorted(P.RUNTIME_PATHS - {FROM_PATH})[0]
    bad = _moved_manifest(repo, manifest)
    bad["moves"] = [{"from": FROM_PATH, "to": other}]
    with pytest.raises(P.Refusal) as excinfo:
        P.parse_manifest(P.strict_loads(P.canonical_bytes(bad), what="m"), 40)
    assert "already-protected path" in str(excinfo.value)


def test_a_move_of_a_path_the_register_does_not_protect_is_refused(tmp_path):
    repo, _base, manifest = T._repo(tmp_path)
    bad = _moved_manifest(repo, manifest)
    bad["moves"] = [{"from": "tools/ci/not_protected_at_all.py", "to": TO_PATH}]
    with pytest.raises(P.Refusal) as excinfo:
        P.parse_manifest(P.strict_loads(P.canonical_bytes(bad), what="m"), 40)
    assert "does not protect" in str(excinfo.value)


def test_two_moves_onto_one_destination_are_refused(tmp_path):
    repo, _base, manifest = T._repo(tmp_path)
    a, b = sorted(P.RUNTIME_PATHS)[:2]
    bad = _moved_manifest(repo, manifest)
    bad["moves"] = sorted([{"from": a, "to": TO_PATH},
                           {"from": b, "to": TO_PATH}],
                          key=lambda r: r["from"])
    with pytest.raises(P.Refusal) as excinfo:
        P.parse_manifest(P.strict_loads(P.canonical_bytes(bad), what="m"), 40)
    assert "one destination" in str(excinfo.value)


def test_next_must_cover_the_moved_path_set_not_the_old_one(tmp_path):
    """A manifest that declares a move but photographs `next` at the OLD paths
    is describing two different transitions at once."""
    repo, _base, manifest = T._repo(tmp_path)
    bad = _moved_manifest(repo, manifest)
    bad["next"] = {"id": "after-the-rename",
                   "files": list(manifest["current"]["files"])}
    with pytest.raises(P.Refusal) as excinfo:
        P.parse_manifest(P.strict_loads(P.canonical_bytes(bad), what="m"), 40)
    assert "after the" in str(excinfo.value)


def test_a_rename_that_leaves_the_transition_open_is_refused(tmp_path):
    """The candidate must re-photograph the register in the SAME landing.  If
    it does not, the next base holds files its own register cannot name, and
    `build_receipt` observes the BASE first -- so EVERY later landing refuses
    on the base, which no candidate can route around."""
    repo, base, authorising = _base_with_authorised_move(tmp_path)
    candidate = _perform(repo, authorising, close=False)
    with pytest.raises(P.Refusal) as excinfo:
        T._receipt(repo, base, candidate, tmp_path)
    assert ("still declares a pending move" in str(excinfo.value)
            or "does not protect exactly the moved path set" in str(excinfo.value))


def test_a_rename_that_also_rewrites_the_bytes_is_refused(tmp_path):
    """A move moves a file.  Bytes that are not the ones `next` records are a
    smuggled edit riding on an authorised rename."""
    repo, base, authorising = _base_with_authorised_move(tmp_path)
    T._git(repo, "mv", FROM_PATH, TO_PATH)
    register = _closed_register(repo, authorising)
    (repo / TO_PATH).write_bytes(b"old:" + FROM_PATH.encode() + b"\nSMUGGLED\n")
    T._write(repo, P.MANIFEST_PATH, P.canonical_bytes(register))
    candidate = T._commit(repo, "rename plus a smuggled edit")
    with pytest.raises(P.Refusal) as excinfo:
        T._receipt(repo, base, candidate, tmp_path)
    assert "bytes other than the ones" in str(excinfo.value)
