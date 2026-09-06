#!/usr/bin/env python3
"""vibe-ic#927 — a BLOCKING gate must not compute its verdict from a mutable
third-party registry pointer.

THE DEFECT, as originally measured. `sync_image_version.py --check
--require-remote` ran in the landing gate and compared this repo's anchor against
two things the `vibeic/vibeic-eda` org re-points on its own cadence: the floating
`:latest` tag, and "the newest published semver tag". The anchor moved
0.2.75 -> 0.2.81 -> 0.2.82 -> 0.2.83 inside about twelve hours, once per fork
release. A verdict built that way has three defects at once:

    * it goes red for a reason nobody in this repo caused;
    * it goes green again when the third party ships nothing;
    * it cannot distinguish "we are behind" from "the registry moved under us" —
      different facts, with different owners.

WHY THIS FILE IS NOT THE SAME FILE. The mechanism #927 was written against —
`tools/vibeic-eda/VERSION` plus `sync_image_version.py` — has been DELETED,
because storing vibeic-eda's version number in this repo made every image release
need a PR here. The PROPERTY survives its mechanism, and this file is that
property re-pinned against `_eda_image.judged_image()`, which is what the blocking
gates ask now.

The anchor made a verdict independent of the registry by freezing a VERSION. The
resolver does it by preferring the image ALREADY ON THIS HOST and pinning it to a
DIGEST — and a digest is not a pointer anyone can re-point, while a local image
cannot move under a CI run that is already in progress. Reaching the registry is
still possible and is now OPT-IN, which is what these tests hold.

THE THREE REGISTRY CONDITIONS a correct implementation cannot tell apart, and
whose verdict must be identical:

    registry reachable and agreeing         the ordinary case
    registry SEVERED (docker/DNS raises)    "the network is gone"
    registry claiming different bytes       "the fork published while we ran"

A test that only checked the happy path would pass against a registry-reading
implementation too, so it would prove nothing.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _eda_image as M
import _eda_pin as _pin  # noqa: E402

#: Every program whose rc 1 can stop a landing while being a statement about the
#: IMAGE's contents. Each is wired in `tools/ci/repo_hygiene_gates.sh`.
_BLOCKING_IMAGE_GATES = (
    "sta_engine_parity_check.py",
    "pdk_registry_selectable_check.py",
    "pdk_via_patch_meets_layer_min_width_check.py",
)


def _local_only(monkeypatch, *, digest=None):
    """A host that HAS the pinned image, with the registry made fatal to touch.

    THE STUB MOVED WITH THE MECHANISM, AND #927'S PROPERTY DID NOT MOVE. This
    used to stub the local-TAG ladder, because that was how a blocking verdict
    reached an image. It resolves the PIN now — measured 2026-09-07 on 8hd-3,
    the tag ladder returned 0.3.16 on a host whose operator had pinned 0.3.47 —
    and the property being asserted is if anything better served: a fixed digest
    cannot be re-pointed by a publish AT ALL, whereas the newest local tag moved
    the moment anything on the host pulled a newer one.
    """
    digest = _pin.IMAGE_DIGEST if digest is None else digest
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: ["0.3.13"])
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (_pin.image_reference(env), ""))
    monkeypatch.setattr(M, "image_version",
                        lambda ref: ("0.3.47", "local-label", ""))
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: pytest.fail(
        "the blocking resolution asked the registry"))


# ── the three registry conditions ───────────────────────────────────────────

def test_the_verdict_is_identical_with_and_without_a_registry(monkeypatch):
    _local_only(monkeypatch)
    assert M.judged_image(env={}).digest == _pin.IMAGE_DIGEST


def test_a_registry_that_published_while_we_ran_changes_nothing(monkeypatch):
    """The failure that made #927: the fork publishes mid-run and a verdict here
    moves. `registry_digest` is not merely unused — touching it FAILS the test,
    so a future edit that "just checks whether we are behind" cannot slip in."""
    _local_only(monkeypatch)
    monkeypatch.setenv("SOMETHING_UNRELATED", "1")
    assert M.judged_image(env={}).source == "pinned"


def test_a_severed_registry_is_not_a_different_verdict(monkeypatch):
    """"The network is gone" must not be reported as a fact about the image."""
    def _boom(*a, **k):
        raise OSError("DNS is gone")
    _local_only(monkeypatch)
    monkeypatch.setattr(M, "registry_version_label", _boom)
    j = M.judged_image(env={})
    assert j.digest == _pin.IMAGE_DIGEST and j.version == "0.3.47"


def test_reaching_the_registry_is_OPT_IN_and_nothing_else_opts_in(monkeypatch):
    """The one door, and it is the caller's to open. `--allow-pull` exists
    because `docker run` on a reference this host does not hold FETCHES it, and
    the operator — not a gate — decides whether to spend that."""
    monkeypatch.setattr(_pin, "pinned_image_present",
                        lambda env=None: (None, "IMAGE_NOT_PRESENT: x"))
    monkeypatch.setattr(M, "image_digest",
                        lambda ref, **k: (_pin.IMAGE_DIGEST, "registry-manifest", ""))
    monkeypatch.setattr(M, "image_version", lambda ref: ("0.3.47", "registry-label", ""))
    assert M.judged_image(env={}).ref is None
    assert M.judged_image(env={}, allow_pull=True).source == "registry"


# ── the gates themselves ────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", _BLOCKING_IMAGE_GATES)
def test_a_blocking_gate_never_defaults_to_a_floating_reference(rel):
    """Written against SOURCE because the failure is a default nobody reads: a
    `or f"{REPO}:latest"` at the end of a resolution chain looks harmless and
    hands a landing verdict to another org's next push."""
    src = (_PROGRAMS / rel).read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', "",
                  "\n".join(l for l in src.splitlines()
                            if not l.lstrip().startswith("#")))
    assert not re.search(r"vibeic-eda:latest|:\s*latest['\"]", code), rel
    assert "judged_image" in code, (
        f"{rel} blocks on what it finds inside an image, so it must resolve that "
        f"image through _eda_image.judged_image()")


def _starts_a_container(rel: str) -> bool:
    """Does this gate launch a container of its own?"""
    src = (_PROGRAMS / rel).read_text(encoding="utf-8")
    return "docker\", \"run\"" in src or '"run",' in src


#: THE APPLICABLE SUBSET, DERIVED — NOT A SKIP INSIDE THE TEST.
#:
#: This used to be `pytest.skip(f"{rel} starts no container of its own")` in the
#: body, and it was the wrong construct twice over. It is not a verification that
#: could not happen: the clause below is VACUOUS for a gate that starts no
#: container, which is an applicability question about the SUBJECT, decided from
#: the repository, with no dependence on the host at all. And spelled as a skip
#: whose reason contains the word "container" it was read by
#: `test_not_verified_tier::test_no_new_undeclared_infrastructure_skip_appears`
#: as a NEW undeclared infrastructure-absent skip — a claim that this host could
#: not verify something. It never made that claim.
#:
#: Declaring it NOT_VERIFIED to satisfy that guard would have been a lie in the
#: other direction, so the skip is gone instead: the applicable set is derived
#: once, here, and pinned non-empty below so an empty subset FAILS rather than
#: quietly asserting nothing.
_CONTAINER_STARTING_GATES = tuple(
    rel for rel in _BLOCKING_IMAGE_GATES if _starts_a_container(rel))


def test_at_least_one_blocking_gate_starts_a_container():
    """The premise of the parametrisation below. If no gate matches, that test
    runs zero cases and reports green over nothing — the silent-skip shape one
    layer up."""
    assert _CONTAINER_STARTING_GATES, (
        "no blocking image gate starts a container, so "
        "test_a_blocking_gate_does_not_pull_by_default asserts nothing; either "
        "the detection in _starts_a_container has rotted or the gates stopped "
        "running containers")


@pytest.mark.parametrize("rel", _CONTAINER_STARTING_GATES)
def test_a_blocking_gate_does_not_pull_by_default(rel):
    """`docker run` FETCHES an absent reference. MEASURED 2026-08-21: the deleted
    anchor named 0.3.16 while this host had 0.3.13, and `docker run` began pulling
    it inside a hygiene gate. A gate that silently downloads gigabytes is a gate
    people route around, which is the same end state as deleting it."""
    src = (_PROGRAMS / rel).read_text(encoding="utf-8")
    assert "--pull" in src and "never" in src, (
        f"{rel} runs a container without `--pull never`, so an image this host "
        f"does not have becomes an unbounded fetch inside a gate")


def test_the_denominator_is_real():
    """This file's own premise. Every path it asserts about must exist, or the
    parametrised tests above pass vacuously over nothing."""
    for rel in _BLOCKING_IMAGE_GATES:
        assert (_PROGRAMS / rel).is_file(), rel
    assert hasattr(M, "judged_image") and hasattr(M, "unidentified_reason")


def test_the_old_mechanism_is_gone_and_not_merely_unused():
    """#927's original fix lived in a repo-root tool and an anchor file. Both are
    deleted; if either returns, the PR-per-release coupling returns with it and
    the tests above would still pass while the repo re-acquired the problem."""
    repo = _PROGRAMS.parents[3]
    assert not (repo / "tools" / "vibeic-eda" / "VERSION").exists()
    assert not (repo / "tools" / "vibeic-eda" / "sync_image_version.py").exists()
