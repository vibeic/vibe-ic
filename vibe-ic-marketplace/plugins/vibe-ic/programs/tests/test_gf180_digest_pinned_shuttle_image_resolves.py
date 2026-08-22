"""A DIGEST-pinned shuttle precheck image must resolve, or the gate reports
"the counterparty was never asked" about an image that is sitting on the host.

WHAT THIS DISCRIMINATES
-----------------------
`tapeout_readiness_check.default_image_resolver` probes with
`docker images -q <ref>`. That command answers for a NAME:TAG reference and
returns EMPTY for a `repo@sha256:…` reference — measured on Docker 29.7.1:

    $ docker images -q ghcr.io/wafer-space/gf180mcu-precheck:latest
    f6c0cb88efce
    $ docker images -q ghcr.io/wafer-space/gf180mcu-precheck@sha256:f6c0cb88efce…
                              <- empty, exit 0
    $ docker image inspect ghcr.io/wafer-space/gf180mcu-precheck@sha256:f6c0cb88efce…
    sha256:f6c0cb88efce…      <- the image IS present

So the MORE precise way to pin the counterparty's tool — by content digest,
which is the only form that cannot silently drift to a different image — was
the one form the gate could not see. The consequence is not a wrong pass; it is
a `NOT_DETERMINED` whose stated reason ("the shuttle precheck image … is not
available … The counterparty was never asked") is FALSE, which is the same class
of defect this whole module exists to prevent: a report that says something
different from what is true about the run.

The two directions are both asserted, because a fix that made every reference
resolve would be far worse than the bug:

  * a digest ref for an image that IS present  -> resolves;
  * a digest ref for an image that is ABSENT   -> still None (and therefore
    still NOT_DETERMINED, never a pass).

The fake docker below reproduces the real binary's split behaviour exactly: it
answers `images -q` only for tag refs, and answers `image inspect` for whatever
it holds. Nothing here depends on a real Docker daemon.
"""
import importlib
import os
import stat
from pathlib import Path

trc = importlib.import_module("tapeout_readiness_check")

_PRESENT_TAG = "gf180mcu-precheck-pin:f6c0cb88"
_PRESENT_DIGEST = ("ghcr.io/wafer-space/gf180mcu-precheck@sha256:"
                   "f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f")
_ABSENT_DIGEST = ("ghcr.io/wafer-space/gf180mcu-precheck@sha256:"
                  "0000000000000000000000000000000000000000000000000000000000000000")
_IMAGE_ID = "f6c0cb88efce"


def _fake_docker(tmp_path):
    """A docker(1) that behaves the way the real one measurably does."""
    p = tmp_path / "fake-docker"
    p.write_text(f'''#!/usr/bin/env python3
import sys
argv = sys.argv[1:]
PRESENT = {{{_PRESENT_TAG!r}, {_PRESENT_DIGEST!r}}}
if argv[:2] == ["images", "-q"]:
    ref = argv[2]
    # the real binary matches `images -q` on NAME[:TAG] only; a digest
    # reference prints nothing and still exits 0
    if "@sha256:" not in ref and ref in PRESENT:
        print({_IMAGE_ID!r})
    sys.exit(0)
if argv[:2] == ["image", "inspect"]:
    ref = argv[-1]
    if ref in PRESENT:
        print("sha256:" + {_IMAGE_ID!r})
        sys.exit(0)
    print("Error: No such image: " + ref, file=sys.stderr)
    sys.exit(1)
if argv[:1] == ["pull"]:
    sys.exit(1)          # no network in a test
sys.exit(2)
''')
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


def test_a_digest_pinned_image_that_is_present_resolves(tmp_path):
    docker = _fake_docker(tmp_path)

    # control arm: the TAG form has always worked, and must keep working.
    assert trc.default_image_resolver(_PRESENT_TAG, False, docker_bin=docker) == _PRESENT_TAG, (
        "the tag form regressed — this arm is the control, not the fix")

    # the defect: same image, pinned the precise way, must resolve too.
    assert trc.default_image_resolver(_PRESENT_DIGEST, False, docker_bin=docker) == _PRESENT_DIGEST, (
        "a digest-pinned image that IS on the host resolved to None, so the gate "
        "reports 'the counterparty was never asked' about a tool it could have run")


def test_a_digest_pinned_image_that_is_absent_still_does_not_resolve(tmp_path):
    """The safety direction. Absent evidence must never become present."""
    docker = _fake_docker(tmp_path)
    assert trc.default_image_resolver(_ABSENT_DIGEST, False, docker_bin=docker) is None, (
        "an image that is NOT on the host resolved — that would turn a shuttle "
        "that was never asked into one that answered")


def test_a_missing_docker_binary_is_still_unresolvable(tmp_path):
    """No docker at all stays None, whatever the reference form."""
    assert trc.default_image_resolver(
        _PRESENT_DIGEST, False,
        docker_bin=str(tmp_path / "definitely-not-a-program")) is None
