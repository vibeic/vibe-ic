#!/usr/bin/env python3
"""Regression: `restart-eda.sh` must default to an IMMUTABLE image reference,
never a floating `latest` — a stale local `latest` would silently recreate the
MCP-EDA container on an outdated toolchain (the same drift class fixed for
`fault_atpg_run.py` in v1.3.80). Measured on 8HD-9 2026-08-21, that risk is not
hypothetical: the local `latest` tag carried RepoDigest `sha256:549357686ed1…`
while the registry's `latest` was `sha256:f34af8763eb0…` — the same name, two
different images, in the same minute.

WHAT CHANGED. The default used to be `$(cat tools/vibeic-eda/VERSION)` —
vibeic-eda's version number stored in the vibe-ic repo, which meant a PR here for
every image release. That file is gone. The default is now a DIGEST, and the
script SHELLS OUT to `programs/_eda_image.py --judged` for it rather than growing
a second copy of "which image" in bash: two implementations of one rule is the
drift these tests exist to catch, one level up.

`RESTART_EDA_PRINT_IMAGE=1` prints the resolved ref and exits before any docker
interaction, so the argument-handling tests need no docker daemon. The default
path DOES need one — it asks this host what it has — and it says so rather than
passing when it could not look.
"""
import os
import re
import shutil
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


def _find(rel):
    for up in Path(__file__).resolve().parents:
        c = up / rel
        if c.is_file():
            return c
    return None


SCRIPT = _find(Path("tools") / "vibeic-eda" / "restart-eda.sh")
RESOLVER = _find(Path("vibe-ic-marketplace") / "plugins" / "vibe-ic" /
                 "programs" / "_eda_image.py")
_skip = pytest.mark.skipif(SCRIPT is None,
                           reason="tools/vibeic-eda/restart-eda.sh not present")

#: The script needs `python3` on PATH to reach the resolver, so the environment
#: is not the bare `/usr/bin:/bin` this file used to hand it.
_ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "RESTART_EDA_PRINT_IMAGE": "1"}
_DIGEST_REF = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")


def _resolve(*args, expect_ok=True):
    r = _pr.run(["bash", str(SCRIPT), *args],
                       capture_output=True, text=True, env=_ENV)
    if expect_ok:
        assert r.returncode == 0, r.stderr
    return r


@_skip
def test_the_script_reads_no_version_out_of_this_repo():
    """The rule, asserted on the SOURCE. A default that re-learns a version from
    a file here brings back the PR-per-release coupling, and it would look like a
    one-line convenience in review."""
    src = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "VERSION" not in code, (
        "restart-eda.sh reads a version out of the source tree again")
    assert "_eda_image.py" in code and "--judged" in code, (
        "restart-eda.sh should ask the one resolver rather than deciding itself")


@_skip
@pytest.mark.skipif(
    RESOLVER is None or shutil.which("docker") is None,
    reason="NOT_VERIFIED: the default asks this host which image it holds and "
           "needs docker — remedy: install docker, or "
           "docker pull ghcr.io/vibeic/vibeic-eda:latest")
def test_the_default_is_a_digest_or_an_honest_refusal():
    """Two acceptable answers and one forbidden one.

    A host holding a vibeic-eda image gets that image BY DIGEST. A host holding
    none gets a non-zero exit naming the problem. What it must never do is fall
    back to a floating tag, which is the whole point of the file."""
    r = _resolve(expect_ok=False)
    got = r.stdout.strip()
    if r.returncode == 0:
        assert _DIGEST_REF.match(got), got
    else:
        assert "pass a tag explicitly" in (r.stderr or ""), r.stderr
        assert not got, got
    assert ":latest" not in got


@_skip
def test_bare_tag_prepends_repo():
    assert _resolve("0.1.99").stdout.strip() == "vibeic/vibeic-eda:0.1.99"


@_skip
def test_full_ref_honored_as_is():
    ref = "example.com/some/image:1.2.3"
    assert _resolve(ref).stdout.strip() == ref


@_skip
def test_explicit_latest_still_honored_as_opt_in():
    assert _resolve("latest").stdout.strip() == "vibeic/vibeic-eda:latest"


@_skip
def test_no_floating_default_in_source():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "${1:-latest}" not in src, (
        "restart-eda.sh must not default to a floating :latest tag")
