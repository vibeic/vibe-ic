#!/usr/bin/env python3
"""eda_doctor must name the IMAGE the container actually runs.

A container's image is fixed when it is CREATED. `docker pull` moves a TAG and
leaves an existing container on the old bytes, so an operator who pulls and then
runs executes every tool, PDK and sign-off number from the OLDER image.

`container_image_provenance.py` names this exact failure — "Stale-container
substitution (silent)" — and RECORDS the identity on every run, but it only
ENFORCES under `--require-image`, which nothing in the flow passes. A fact that
nobody compares does not make the substitution visible.

And `eda_doctor`, which `skills/loop2converge/SKILL.md` §1.0 tells operators to
read the toolchain back from — in the same table that catches the MCP-binding
version of this mistake — answered "container reachable" and named no image.

MEASURED 2026-08-30 on 8hd-3 after following §1.0 literally:

    container `vibeic-eda`  sha256:ddbf1e71… 2026-08-28  openroad 26Q3-1867-gfbdee51542
    :latest, same host      sha256:de6b0e0f… 2026-08-29  openroad 26Q3-1884-g80f878d28a

`eda_doctor` reported "12/12 checks passed". The gap was load-bearing: on 1867
`repair_timing -setup` died of SIGSEGV in `postroute_drv_repair` and the run
halted; on 1884 the same design cleared that stage in four repair+reroute
iterations. A tool bug was filed against a build already superseded on the very
machine that filed it.

The helper is EXECUTED here, not grepped for: these tests stub the docker calls
and run `_containerImageIdentity` under node, so they assert what it DOES. The
registration test is the only static one, because the wiring is a shape.
"""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
INDEX_JS = HERE.parent / "src" / "index.js"

sys.path.insert(0, str(HERE.parents[1] / "programs"))
import _watchdog                                              # noqa: E402

_STALL_GRACE_S = 60

RUNNING_ID = "sha256:" + "a" * 64
NEWER_ID = "b" * 12
RUNNING_REF = "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 64


def _helper_source() -> str:
    """The shipped helper itself. A copy in this file would pass while the
    server did something else, which is the failure this test exists to catch."""
    src = INDEX_JS.read_text(encoding="utf-8")
    start = src.index("const _EDA_IMAGE_REPO =")
    end = src.index("// ─── Tool: eda_doctor", start)
    body = src[start:end]
    assert "_containerImageIdentity" in body, body[:200]
    return body


def _run(responses: dict) -> dict:
    """`responses` maps a marker present in the argv to {status, stdout}.

    Dispatching on argv rather than call order is deliberate: an order-indexed
    stub silently keeps passing if the helper is refactored to ask in a
    different sequence, which is the kind of test that measures nothing.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available; the helper under test is JavaScript")
    script = textwrap.dedent(f"""
        const CONTAINER = "vibeic-eda";
        const RESPONSES = {json.dumps(responses)};
        const _spawnSync = (cmd, args) => {{
          const key = Object.keys(RESPONSES).find(k => args.join(" ").includes(k));
          return key ? RESPONSES[key] : {{ status: 1, stdout: "" }};
        }};
        {_helper_source()}
        console.log(JSON.stringify(_containerImageIdentity()));
    """)
    argv = [node, "-e", script]
    res = _watchdog.run_host_supervised(argv, stall_grace_s=_STALL_GRACE_S)
    assert res.outcome not in ("stalled", "ceiling"), (
        f"the node child made NO forward progress for {_STALL_GRACE_S}s\n"
        f"{res.out}{res.err}")
    run = _watchdog.completed_process(argv, res)
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def _responses(*, running_created, newest_created, label="0.3.36",
               newest_tag="ghcr.io/vibeic/vibeic-eda:latest"):
    rows = []
    if newest_created is not None:
        rows.append(f"{NEWER_ID}\t{newest_created}\t{newest_tag}")
    return {
        "inspect vibeic-eda --format": {
            "status": 0, "stdout": f"{RUNNING_ID}\t{RUNNING_REF}\n"},
        "image inspect": {
            "status": 0, "stdout": f"{running_created}\t{label}\n"},
        "image ls": {"status": 0, "stdout": "\n".join(rows) + "\n"},
    }


# ── the case this exists for ───────────────────────────────────────────────

def test_a_container_older_than_a_local_image_is_reported_stale():
    out = _run(_responses(running_created="2026-08-28T09:22:50.0Z",
                          newest_created="2026-08-29 19:42:34 +0800 CST"))
    assert out["ok"] is False
    assert "STALE CONTAINER" in out["detail"]


def test_the_message_carries_both_identities_and_the_fix():
    """An operator who cannot see WHICH two images differ cannot act, and one
    who is not told a recreate drops the mounts and the ceiling loses both."""
    d = _run(_responses(running_created="2026-08-28T09:22:50.0Z",
                        newest_created="2026-08-29 19:42:34 +0800 CST"))["detail"]
    assert "a" * 12 in d and NEWER_ID in d
    assert "docker rm -f" in d and "--memory-swap" in d and "mounts" in d
    assert "fixed when it is CREATED" in d, (
        "the message must say WHY a pull did not move the container")


def test_the_version_label_is_read_back():
    """§1.0 asks for the digest AND the label; the label is what a human says."""
    d = _run(_responses(running_created="2026-08-28T09:22:50.0Z",
                        newest_created="2026-08-29 19:42:34 +0800 CST",
                        label="0.3.36"))["detail"]
    assert "0.3.36" in d


# ── the controls: green in both directions ─────────────────────────────────

def test_control_a_container_on_the_newest_local_image_passes():
    """THE CONTROL. Without it the check is satisfied by code that calls every
    container stale."""
    out = _run(_responses(running_created="2026-08-29T11:42:34.0Z",
                          newest_created="2026-08-28 17:22:50 +0800 CST"))
    assert out["ok"] is True
    assert "STALE" not in out["detail"]
    assert "newest local image" in out["detail"]


def test_control_the_running_image_is_not_compared_against_itself():
    """The running image is usually still tagged. Counting it as 'newer than
    itself' would report every container stale — the same everything-matches
    defect `_commercial_pdk` refuses an empty alternation for."""
    r = _responses(running_created="2026-08-29T11:42:34.0Z", newest_created=None)
    r["image ls"] = {"status": 0,
                     "stdout": f"{'a' * 12}\t2026-08-29 19:42:34 +0800 CST\t"
                               f"ghcr.io/vibeic/vibeic-eda:latest\n"}
    out = _run(r)
    assert out["ok"] is True, out["detail"]


def test_control_no_other_local_image_still_passes():
    out = _run(_responses(running_created="2026-08-29T11:42:34.0Z",
                          newest_created=None))
    assert out["ok"] is True


# ── cannot-look is never a clean bill ──────────────────────────────────────

def test_an_unreadable_container_is_not_reported_as_current():
    out = _run({})
    assert out["ok"] is False
    assert "UNIDENTIFIED" in out["detail"]


def test_an_undateable_image_says_it_was_not_compared():
    """NOT-KNOWN IS NOT CURRENT. An unparseable creation time must not silently
    sort as newest and print a clean bill."""
    out = _run(_responses(running_created="not-a-date",
                          newest_created="2026-08-29 19:42:34 +0800 CST"))
    assert "NOT compared" in out["detail"]


def test_an_unlistable_image_set_says_so_rather_than_claiming_current():
    r = _responses(running_created="2026-08-29T11:42:34.0Z", newest_created=None)
    r["image ls"] = {"status": 1, "stdout": ""}
    assert "could not list" in _run(r)["detail"]


# ── registration shape ─────────────────────────────────────────────────────

def test_the_check_is_soft_and_wired_after_the_docker_probe():
    """SOFT deliberately, like the memory ceiling beside it: an older image runs
    every flow correctly and may be pinned on purpose. `if (!ok && !soft) allOk
    = false;` is what makes `soft` mean that."""
    src = INDEX_JS.read_text(encoding="utf-8")
    i = src.index('check: "eda_image_identity"')
    block = src[i - 400:i + 400]
    assert "_containerImageIdentity()" in block
    assert "soft: img.ok ? undefined : true" in block
    assert src.index('check: "docker_reachable"') < i, (
        "the identity check must run after docker is known reachable")
