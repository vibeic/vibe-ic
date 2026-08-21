#!/usr/bin/env python3
"""A REAL protected-landing transition tuple, for a synthetic repository.

WHY THIS EXISTS
===============
`landing_merge_verdict.read_protected_transition_receipt` REFUSES when no
protected-landing-transition receipt is supplied, and that refusal is
UNMEASURABLE rather than red — a landing gate that cannot tell "measured and
clean" from "could not measure" is the exact defect this repository exists to
hunt. So the refusal is correct and stays; what was missing is the thing it
asks for.

Two callers need that thing and they need it in different forms:

  * `tools/test_gatekeeper_land_differential.py` drives the WHOLE driver over a
    synthetic repository, so it needs the repository itself to carry a valid
    manifest and the complete protected tuple. The receipt is then built by the
    REAL builder out of the REAL validator, exactly as a landing builds it.
    :func:`install` and :func:`write_manifest` do that.

  * `test_landing_gate_direct_push_tier.py` calls the verdict program directly
    with synthetic commit ids and no repository at all. Its subject is
    `decide()`, not the receipt builder, so the receipt is an INPUT there —
    :func:`receipt_for` writes one through the real parser's own canonical
    encoder, for the ids that test uses.

WHAT IS NOT DONE HERE, ON PURPOSE
=================================
Nothing weakens the manifest policy. The path/role set and the hermetic runner
profile are read VERBATIM from the shipped `tools/ci/
protected_landing_transition.json`, so `parse_manifest`'s exact five-file
runtime tuple and its required authority closure are satisfied by the real
policy rather than by a relaxed copy of it. Only the two atomic STATES are
recomputed, because they describe the bytes of THIS tree and could not
truthfully describe any other.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process node.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
MANIFEST_REL = "tools/ci/protected_landing_transition.json"
VALIDATOR_REL = "tools/ci/protected_landing_transition.py"

#: The authority files a synthetic tree must carry as the REAL programs rather
#: than as placeholders. `gatekeeper-land-differential.sh` EXECUTES the
#: validator out of the repository under test and `read_protected_transition_
#: receipt` loads it from beside the verdict, and the validator in turn imports
#: the worktree attester from beside itself. A placeholder for either would
#: make the receipt unbuildable rather than the tuple unmeasured.
REAL_FILES = (VALIDATOR_REL, "tools/ci/trusted_worktree_attest.py")

#: Ids for the two atomic states of the synthetic tuple. `parse_manifest`
#: refuses a manifest whose current and next ids are equal, and `_parse_receipt`
#: refuses a live state that is neither of them.
CURRENT_STATE_ID = "synthetic-live"
NEXT_STATE_ID = "synthetic-prepared"


def _shipped_manifest() -> dict:
    return json.loads((REPO / MANIFEST_REL).read_text(encoding="utf-8"))


def _placeholder(rel: str) -> bytes:
    """Bytes for a protected path this fixture has no real use for.

    The manifest describes exactly these bytes, so a placeholder is a truthful
    member of the tuple; what it must not be is something a reader could
    mistake for the shipped program.
    """
    if rel.endswith(".json"):
        return b'{"placeholder": "protected-tuple fixture, never executed"}\n'
    return (f"# placeholder for {rel} — protected-tuple fixture, "
            f"never executed\n").encode("utf-8")


#: Config that must be pinned OFF in a synthetic repository, because each of
#: these makes the WORKING TREE bytes differ from the BLOB bytes — and
#: `trusted_worktree_attest` compares exactly those two, on purpose. Its own
#: docstring names the reason: "A clean/smudge filter, sparse index, alternate
#: gitdir, or staged replacement must not be able to make later gates consume a
#: different population after raw worktree bytes were attested."
#:
#: MEASURED, and this is why the list is a list and not a comment: on a host
#: whose GLOBAL git config carries `core.autocrlf = true`, git checks `x\n` out
#: as `x\r\n`, the attester refuses "raw bytes differ from expected blob:
#: candidate_marker", no receipt can be built, and EVERY case in
#: `tools/test_gatekeeper_land_differential.py` that expects a clean run
#: refuses as PROTECTED LANDING SOURCE TRANSITION IS UNMEASURED. Eleven of its
#: twenty-five did exactly that on a maintainer's host while all twenty-five
#: passed on two others, and the only difference was one line of `~/.gitconfig`.
#:
#: The gate is right and does not move. What was wrong is that this fixture
#: built its repository with `git init` and then inherited whatever the host
#: said about byte transformation — the same class of defect this module
#: already documents for `$USER`: THE HARNESS'S OWN ENVIRONMENT MUST NOT DECIDE
#: THE VERDICT. These are set at the LOCAL level, which outranks `--global` and
#: `--system`, so a host may carry any of them and this tuple still attests.
BYTE_TRANSFORM_OFF = (
    ("core.autocrlf", "false"),
    ("core.eol", "lf"),
    ("core.safecrlf", "false"),
)


def scrubbed_env(env: dict | None = None) -> dict:
    """`env` without git's COMMAND-LINE-precedence config injection.

    `BYTE_TRANSFORM_OFF` is set at the repository's LOCAL level, which outranks
    `--global` and `--system` — so a host may carry any of those and this
    fixture still attests. `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_n`/
    `GIT_CONFIG_VALUE_n` are different: git gives them COMMAND-LINE precedence,
    which no config file can outrank. MEASURED — with
    `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.autocrlf GIT_CONFIG_VALUE_0=true`
    exported, `harden()` writes its local config and is then ignored, and the
    same twelve cases refuse.

    So they are REMOVED from the environment of the synthetic repository's git,
    and only there. The production driver deliberately does NOT do this: an
    operator's exported config is the operator's, and a landing whose bytes
    would be mangled by it must refuse — which it does, now under a heading
    that names the reason. What must not happen is the HARNESS's environment
    deciding the verdict of a tuple it built itself.
    """
    out = dict(os.environ if env is None else env)
    for name in list(out):
        if name == "GIT_CONFIG_COUNT" or name.startswith(
                ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            del out[name]
    return out


def harden(root: Path) -> None:
    """Make a synthetic repository's checkout byte-identical to its blobs.

    Call once, straight after `git init`, BEFORE anything is staged.
    """
    for key, value in BYTE_TRANSFORM_OFF:
        subprocess.run(["git", "-C", str(root), "config", key, value],
                       check=True, capture_output=True, env=scrubbed_env())
    # A GLOBAL `core.attributesFile` can switch a clean/smudge filter on for a
    # tree that carries no `.gitattributes` of its own, which is the same defect
    # wearing a different hat. Point the setting at an empty file this fixture
    # owns; it lives under `.git/`, so it is not part of the attested worktree.
    empty = root / ".git" / "fixture-empty-attributes"
    empty.write_text("", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "config",
                    "core.attributesFile", str(empty)],
                   check=True, capture_output=True, env=scrubbed_env())


def install(root: Path) -> list[str]:
    """Materialise every path the shipped manifest names, and return them.

    Files the caller has already written (the stubs the driver actually runs)
    are left alone: the manifest is computed FROM the tree, so the tuple
    describes whatever those stubs really are.
    """
    manifest = _shipped_manifest()
    paths = [row["path"] for row in manifest["paths"]]
    for rel in REAL_FILES:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dst)
    for rel in paths:
        dst = root / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(_placeholder(rel))
    return paths


def _staged_records(root: Path, paths: list[str]) -> list[dict]:
    """One `_observe_file`-shaped record per path, read from the INDEX.

    The mode and object id are git's own, and the bytes are the ones that
    object holds, so these records are what `_observe_files` will compute over
    the commit — not a re-derivation that could disagree with it.
    """
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z", "--", *paths],
        check=True, capture_output=True).stdout
    staged: dict[str, tuple[str, str]] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        mode, oid, _stage = meta.decode("utf-8").split()
        staged[name.decode("utf-8")] = (mode, oid)
    missing = [rel for rel in paths if rel not in staged]
    if missing:
        raise AssertionError(f"protected paths were not staged: {missing}")
    blobs = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(f"{staged[rel][1]}\n" for rel in paths).encode("ascii"),
        check=True, capture_output=True).stdout
    out, cursor = [], 0
    for rel in paths:
        mode, oid = staged[rel]
        header_end = blobs.index(b"\n", cursor)
        size = int(blobs[cursor:header_end].split()[2])
        body = blobs[header_end + 1:header_end + 1 + size]
        cursor = header_end + 1 + size + 1
        out.append({"path": rel, "mode": mode, "blob_oid": oid,
                    "sha256": hashlib.sha256(body).hexdigest(), "size": size})
    return sorted(out, key=lambda row: row["path"])


def write_manifest(root: Path) -> Path:
    """Write the synthetic tree's manifest. Call AFTER the paths are staged."""
    manifest = _shipped_manifest()
    paths = [row["path"] for row in manifest["paths"]]
    current = _staged_records(root, paths)

    # THE PREPARED STATE IS A REAL OBJECT, not a fabricated digest. A manifest
    # authorises a move to `next`; writing those bytes into the object database
    # means the authorised future tuple is one that exists, which is what the
    # shipped manifest also claims about its own.
    moved = current[0]["path"]
    prepared = (root / moved).read_bytes() + b"\n# prepared, not activated\n"
    oid = subprocess.run(
        ["git", "-C", str(root), "hash-object", "-w", "-t", "blob", "--stdin"],
        input=prepared, check=True, capture_output=True).stdout.decode().strip()
    next_files = [dict(row) for row in current]
    next_files[0] = {"path": moved, "mode": current[0]["mode"],
                     "blob_oid": oid,
                     "sha256": hashlib.sha256(prepared).hexdigest(),
                     "size": len(prepared)}

    manifest["current"] = {"id": CURRENT_STATE_ID, "files": current}
    manifest["next"] = {"id": NEXT_STATE_ID, "files": next_files}
    out = root / MANIFEST_REL
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    return out


# ------------------------------------------------------------ the unit-test form

def _validator():
    """The shipped validator, imported by path rather than by name."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_fixture_protected_landing_transition", REPO / VALIDATOR_REL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt_for(path: Path, *, base_commit: str, base_tree: str,
                candidate_commit: str, candidate_tree: str,
                operation: str = "STEADY") -> Path:
    """Write a STEADY receipt binding four synthetic ids, and return its path.

    The payload is encoded and digested by the SHIPPED module's own
    `canonical_bytes`, so what this writes is a receipt the real
    `strict_load_receipt` accepts — and, when a caller perturbs any of the four
    ids, one it correctly refuses.
    """
    module = _validator()
    manifest = _shipped_manifest()
    oid_len = len(base_commit)

    def _identity(rel: str) -> dict:
        # One DISTINCT identity per protected path. A tuple whose members were
        # all the same digest would let a receipt that mixed two paths up still
        # parse, and this fixture is also the negative control for that.
        digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()
        return {"path": rel, "mode": "100644", "blob_oid": digest[:oid_len],
                "sha256": digest, "size": len(rel)}

    files = [{**_identity(row["path"]), "roles": list(row["roles"])}
             for row in manifest["paths"]]
    manifest_file = _identity(MANIFEST_REL)
    payload = {
        "operation": operation,
        "base_commit": base_commit, "base_tree": base_tree,
        "candidate_commit": candidate_commit, "candidate_tree": candidate_tree,
        "base_manifest": manifest_file, "candidate_manifest": manifest_file,
        "runner": manifest["runner"],
        "base_transition_id": manifest["transition_id"],
        "candidate_transition_id": manifest["transition_id"],
        "base_current_state_id": CURRENT_STATE_ID,
        "base_next_state_id": NEXT_STATE_ID,
        "base_state_id": CURRENT_STATE_ID,
        "candidate_state_id": CURRENT_STATE_ID,
        "base_files": files, "candidate_files": [dict(row) for row in files],
        "worktrees": [
            {"role": "candidate-gates", "commit": candidate_commit,
             "tree": candidate_tree, "complete": True},
            {"role": "candidate-tests", "commit": candidate_commit,
             "tree": candidate_tree, "complete": True},
        ],
    }
    receipt = {"schema": 1, "kind": module.RECEIPT_KIND, "complete": True,
               "payload": payload,
               "payload_sha256": hashlib.sha256(
                   module.canonical_bytes(payload)).hexdigest()}
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path
