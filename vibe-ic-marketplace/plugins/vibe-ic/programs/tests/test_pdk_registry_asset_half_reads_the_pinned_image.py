#!/usr/bin/env python3
"""The asset half must read the image the repo PINS, not whatever container
happens to carry the right NAME.

WHY
---
`pdk_registry_selectable_check` answers "does the image ship every asset the
registry declares". It reached that image through `--container`, and believed
any live container with that name. A container keeps the image it was CREATED
from for its whole life — pulling a newer tag does not touch it — so the
gate's verdict was a function of unpinned host state.

MEASURED, one host, one pristine tree, `git status --porcelain` empty, same
commit, same registry, only the container's image differing:

    container on the pinned image   -> rc=0, 33/33 declared paths resolve
    container on the upstream base  -> rc=1, 10 findings, every nangate45 and
                                       every asap7 asset "resolves to nothing"

The upstream base image genuinely ships neither PDK; the pinned image ships
both, all five declared nangate45 paths present. So the second run's findings
were a true statement about that container and a FALSE statement about
`pdk_registry.json` — indistinguishable, in the output, from a real registry
defect. The mirror case is the one that actually ships damage: a container
NEWER than the pin reports clean for a pin that cannot provide the assets.

HOW THESE TESTS BITE
--------------------
They put a stub `docker` on PATH and drive `_resolve_target`, which both the
old and the new program call. Nothing here depends on a symbol the fix
introduced, so every assertion below is a statement about BEHAVIOUR: against
the unfixed program the stub reports a container on a foreign image and the
program returns that container anyway. No daemon, no image, no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import pdk_registry_selectable_check as C  # noqa: E402

PINNED = "ghcr.io/vibeic/vibeic-eda:9.9.9"
PINNED_ID = "sha256:" + "a" * 64
FOREIGN_REF = "hpretl/iic-osic-tools:latest"
FOREIGN_ID = "sha256:" + "b" * 64

# A stub `docker` that answers the three questions either version of the
# program can ask, and logs every invocation so a test can count them.
_STUB = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ.get("PDKREG_STUB_LOG")
if log:
    open(log, "a").write("\t".join(a) + "\n")
ref = os.environ.get("PDKREG_STUB_CONTAINER_REF", "")
cid = os.environ.get("PDKREG_STUB_CONTAINER_ID", "")
known = dict(p.split("=", 1)
             for p in os.environ.get("PDKREG_STUB_IMAGES", "").split(",") if p)
if a[:1] == ["exec"]:
    sys.exit(0 if ref else 1)
if a[:2] == ["image", "inspect"]:
    want = a[-1]
    if want in known:
        if "--format" in a:
            sys.stdout.write(known[want] + "\n")
        else:
            sys.stdout.write("[{}]\n")
        sys.exit(0)
    sys.exit(1)
if a[:1] == ["inspect"]:
    if not ref:
        sys.stderr.write("No such object\n")
        sys.exit(1)
    if "{{json .Mounts}}" in a:
        dests = json.loads(os.environ.get("PDKREG_STUB_CONTAINER_MOUNTS", "[]"))
        sys.stdout.write(json.dumps([{"Destination": d} for d in dests]) + "\n")
        sys.exit(0)
    sys.stdout.write("/%s\t%s\t%s\ttrue\t2026-01-01\n" % (a[-1], ref, cid))
    sys.exit(0)
sys.exit(1)
'''


@pytest.fixture()
def docker_stub(tmp_path, monkeypatch):
    """Install the stub and return a configure(...) callable."""
    d = tmp_path / "bin"
    d.mkdir()
    exe = d / "docker"
    exe.write_text(_STUB)
    exe.chmod(0o755)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("PDKREG_STUB_LOG", str(log))
    monkeypatch.setattr(C, "_image_tag", lambda: PINNED)

    def configure(container_ref, container_id, images, mounts=()):
        monkeypatch.setenv("PDKREG_STUB_CONTAINER_REF", container_ref or "")
        monkeypatch.setenv("PDKREG_STUB_CONTAINER_ID", container_id or "")
        monkeypatch.setenv("PDKREG_STUB_IMAGES",
                           ",".join(f"{k}={v}" for k, v in images.items()))
        monkeypatch.setenv("PDKREG_STUB_CONTAINER_MOUNTS", json.dumps(mounts))
        # The fix memoises the decision; clearing keeps tests independent.
        # getattr-guarded so this file RUNS against the unfixed program and
        # fails on its ASSERTIONS rather than on a missing symbol.
        getattr(C, "_TARGET_MEMO", {}).clear()
        if log.exists():
            log.unlink()
        return log

    return configure


def test_a_container_on_a_foreign_image_is_not_used(docker_stub):
    """THE FIX. The name matched; the image did not. Believing it is what
    turned a fact about `hpretl/iic-osic-tools` into ten findings against
    `pdk_registry.json`."""
    docker_stub(FOREIGN_REF, FOREIGN_ID,
                {PINNED: PINNED_ID, FOREIGN_REF: FOREIGN_ID})
    assert C._resolve_target("vibeic-eda") == ("run", PINNED), (
        "a container that is NOT running the pinned image must not be the "
        "source of truth for what the pinned image ships")


def test_a_container_on_the_pinned_image_is_still_the_fast_path(docker_stub):
    """The paired direction. The fix must not throw the shortcut away — a
    matching container is 33 `docker exec` instead of 33 `docker run`."""
    docker_stub(PINNED, PINNED_ID, {PINNED: PINNED_ID})
    assert C._resolve_target("vibeic-eda") == ("exec", "vibeic-eda")


def test_a_container_matched_by_id_when_the_tag_was_retagged(docker_stub):
    """Same image, different ref string: a digest pull or a local retag.
    Content-addressed identity is the truth, so this must be ACCEPTED —
    rejecting it would push every such host onto the slow path for nothing."""
    docker_stub("some-local-retag:dev", PINNED_ID,
                {PINNED: PINNED_ID, "some-local-retag:dev": PINNED_ID})
    assert C._resolve_target("vibeic-eda") == ("exec", "vibeic-eda")


def test_a_matching_container_with_a_pdk_mount_is_not_authoritative(
        docker_stub):
    """Image identity does not undo Docker's mount overlay. A matching image
    whose Nangate tree is replaced by host staging bytes must fall back to the
    pinned image rather than turn those host bytes into a registry verdict."""
    docker_stub(PINNED, PINNED_ID, {PINNED: PINNED_ID},
                mounts=["/foss/pdks/nangate45"])
    assert C._resolve_target("vibeic-eda") == ("run", PINNED)
    _target, why = C._target_and_why("vibeic-eda")
    rejected = why.get("container_rejected") or {}
    assert rejected.get("masking_mounts") == ["/foss/pdks/nangate45"]


def test_no_container_at_all_still_reads_the_pinned_image(docker_stub):
    """#408 finding 1 must stay fixed: a missing container is not a reason to
    stop looking, because the pinned image answers the same question."""
    docker_stub(None, None, {PINNED: PINNED_ID})
    assert C._resolve_target("vibeic-eda") == ("run", PINNED)


def test_a_foreign_container_and_no_pinned_image_is_not_a_source(docker_stub):
    """The honesty case. With no pinned image to look inside, the answer is
    "I could not look" — never findings mined out of the wrong image."""
    docker_stub(FOREIGN_REF, FOREIGN_ID, {FOREIGN_REF: FOREIGN_ID})
    assert C._resolve_target("vibeic-eda") is None


def test_the_report_says_what_it_looked_inside(docker_stub, monkeypatch):
    """A finding is only a claim about the registry when the thing inspected
    IS the pinned image. `--json` must carry which one it was, so no reader
    has to assume — and so a rejected container is visible, not silent."""
    docker_stub(FOREIGN_REF, FOREIGN_ID,
                {PINNED: PINNED_ID, FOREIGN_REF: FOREIGN_ID})
    monkeypatch.setattr(C, "_container_alive", lambda n: True)
    monkeypatch.setattr(C, "_resolves", lambda c, p: True)
    monkeypatch.setattr(C, "shipped_trees", lambda c: {})
    monkeypatch.setattr(C, "_resolved", lambda c, p: p)
    rep = C.audit(_PROGRAMS / "pdk_registry.json", "vibeic-eda")
    assert rep.get("pinned_image") == PINNED, (
        "the report does not record which image the asset half read")
    rej = rep.get("container_rejected")
    assert rej and rej.get("image_ref") == FOREIGN_REF, (
        "a container skipped for running the wrong image must be reported, "
        "not dropped silently")


def test_resolution_does_not_re_probe_docker_for_every_asset(docker_stub):
    """It used to be recomputed inside every `_resolves` call — 33 probes for
    33 declared paths. With an image check added that cost triples, so the
    decision is made once. Property: the docker-call count must not grow with
    the number of lookups."""
    log = docker_stub(PINNED, PINNED_ID, {PINNED: PINNED_ID})
    for _ in range(2):
        C._resolve_target("vibeic-eda")
    few = len(log.read_text().splitlines()) if log.exists() else 0

    log = docker_stub(PINNED, PINNED_ID, {PINNED: PINNED_ID})
    for _ in range(8):
        C._resolve_target("vibeic-eda")
    many = len(log.read_text().splitlines()) if log.exists() else 0

    assert few == many, (
        f"docker invocations grew {few} -> {many} with the number of "
        f"lookups; the resolution must be decided once")


def test_the_program_still_runs_end_to_end():
    """Import-level guard: the fix added a sibling import, so prove the file
    is still executable exactly as the gate invokes it."""
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "pdk_registry_selectable_check.py"),
         "--help"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
