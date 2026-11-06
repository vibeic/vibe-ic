#!/usr/bin/env python3
"""Tests for container_image_provenance.

The load-bearing property is NOT that the checker passes on a good container —
it is that it FAILS on each of the two real defects it was written for:

  * a container name that resolves to a DIFFERENT image than the one pinned
    (the silent stale-container substitution), and
  * an IMAGE ref passed where a CONTAINER name belongs (the soft degradation).

Each test therefore asserts the failing verdict with the defect present, and the
passing verdict with it absent. Docker is never required: `inspect_container` /
`_resolve_image_id` are stubbed so the checker's LOGIC is what is under test.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import container_image_provenance as cip  # noqa: E402


PINNED_ID = "sha256:4182c63b10d185fad2ff6247525b4f658a02eba4108b76d01b6712206eb06650"
STALE_ID = "sha256:2e3b906fd8e8b1a8df24599cec135efbbc9f778bc61c20a5f24ca71f4874f927"


def _ok(image_ref, image_id):
    return {"status": "ok", "container": "vibeic-eda", "image_ref": image_ref,
            "image_id": image_id, "running": True, "created": "2026-07-26T00:00:00Z"}


# ---------------------------------------------------------------- defect 1 --
def test_stale_container_running_wrong_image_is_MISMATCH(monkeypatch):
    """The silent substitution: the container exists and is healthy, but runs an
    OLDER image than the operator pinned. Must NOT pass."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("ghcr.io/vibeic/vibeic-eda:0.2.26", STALE_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: PINNED_ID)

    rec = cip.verify("vibeic-eda", require_image="vibeic-eda:0.2.30")
    assert rec["verdict"] == "MISMATCH", rec
    assert rec["image_match"] is False
    # the message must name BOTH images, or an operator cannot act on it
    assert "0.2.26" in rec["reason"] and "0.2.30" in rec["reason"]


def test_matching_image_passes_by_tag_and_by_id(monkeypatch):
    """Control for defect 1: same container, correct image -> PASS."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:0.2.30", PINNED_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: PINNED_ID)

    assert cip.verify("vibeic-eda", "vibeic-eda:0.2.30")["verdict"] == "PASS"
    # an id may be pinned instead of a tag, and must compare equal
    assert cip.verify("vibeic-eda", PINNED_ID)["verdict"] == "PASS"


def test_tag_differs_but_resolves_to_same_id_passes(monkeypatch):
    """A ghcr-qualified tag and a local tag naming the SAME image are the same
    toolchain — comparing by id must not raise a false alarm."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("ghcr.io/vibeic/vibeic-eda:0.2.30", PINNED_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: PINNED_ID)

    rec = cip.verify("vibeic-eda", "vibeic-eda:0.2.30")
    assert rec["verdict"] == "PASS", rec


# ---------------------------------------------------------------- defect 2 --
#: The ceiling the hint carries — see
#: test_the_hint_does_not_teach_operators_to_create_an_unbounded_container.
_CEIL = "--memory 48g --memory-swap 48g"

def test_image_ref_passed_as_container_name_fails_with_actionable_hint(monkeypatch):
    """An image ref matches no container. The verdict must be FAIL (not a soft
    fallback), and must say WHY so the operator is not sent hunting a phantom
    tool error downstream."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: {"status": "not_found", "container": n,
                                   "stderr": "Error: No such container: " + n})

    rec = cip.verify("vibeic-eda:0.2.30")
    assert rec["verdict"] == "FAIL", rec
    assert "IMAGE ref" in rec["reason"]
    assert "docker run -d --init" in rec["reason"]
    assert "--name <name>" in rec["reason"]


def test_the_actionable_hint_is_a_command_that_would_actually_run(monkeypatch):
    """A hint that does not work is worse than no hint: it looks actionable and
    leaves the operator exactly where they were.

    An earlier revision pinned `--skip sleep infinity` as the BROKEN form and a
    bare `sleep infinity` as the working one. That is backwards for any image
    that declares an ENTRYPOINT launcher — see
    test_the_hint_covers_the_entrypoint_launcher_case for the measurement. Which
    plain-docker form works is a property of the IMAGE, so this program must not
    commit to one: pin that BOTH are named, that the entrypoint case is called
    out, and that the repo's own restarter (which verifies the resulting
    container's image id rather than merely starting something) is offered
    first."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: {"status": "not_found", "container": n})
    ref = "ghcr.io/vibeic/vibeic-eda:0.2.30"
    reason = cip.verify(ref)["reason"]
    assert "docker run -d --init %s --name <name> %s sleep infinity" % (_CEIL, ref) in reason
    assert "docker run -d --init %s --name <name> %s --skip sleep infinity" % (_CEIL, ref) in reason
    assert "restart-eda.sh" in reason


def test_the_hint_does_not_teach_operators_to_create_an_unbounded_container():
    """The hint is a copy-paste line; whatever it says becomes the fleet.

    MEASURED 2026-08-19: 45 EDA containers across seven machines were running
    with `HostConfig.Memory == 0`, and a yosys in one of them reached 109 GB of
    a 125 GB host and got the desktop session OOM-killed. A container with no
    cgroup limit does not share the host's memory, it IS the host's memory. A
    hint that omits the ceiling reproduces that configuration every time
    somebody follows it, which is the most likely way it got reproduced 45
    times.

    Both flags, or neither: `--memory` alone still lets the container reach the
    host's swap, and the freeze that preceded the crash was swap thrash.
    """
    import container_image_provenance as _cip
    src = Path(_cip.__file__).read_text(encoding="utf-8")
    for form in ("--memory ", "--memory-swap "):
        assert form in src, f"the container-start hint omits {form.strip()}"


def test_the_hint_covers_the_entrypoint_launcher_case(monkeypatch):
    """REGRESSION CONTROL for the assertion this test file previously got
    backwards.

    MEASURED on the image this repo ships (ghcr.io/vibeic/vibeic-eda:0.2.30,
    docker 29.6.2):

        Config.Entrypoint = [/dockerstartup/scripts/ui_startup.sh]
        Config.Cmd        = [--wait]
        run <image> --skip sleep infinity -> Running=true  Exit=0
        run <image> sleep infinity        -> Running=false Exit=1
             docker logs: [ERROR] Unexpected option "sleep"

    Because the image declares an ENTRYPOINT, trailing args are that launcher's
    FLAGS. The repo's own tooling already encodes this:
    tools/vibeic-eda/restart-eda.sh uses `CMD=( --skip sleep infinity )`.

    An image with NO entrypoint launcher needs the bare form instead, so the
    hint must name both and say which applies when. This test fails if the hint
    ever again asserts that exactly one of them is the runnable one."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: {"status": "not_found", "container": n})
    reason = cip.verify("ghcr.io/vibeic/vibeic-eda:0.2.30")["reason"]
    assert "ENTRYPOINT" in reason, (
        "the hint must disclose that the correct form depends on the image's "
        "entrypoint, not silently pick one")
    assert "Config.Entrypoint" in reason, (
        "the hint must tell the operator how to CHECK which case they are in")


def test_plain_missing_container_fails_without_the_image_hint(monkeypatch):
    """A plain (non-ref-looking) missing name still FAILs, but must not be given
    the misleading image-ref explanation."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: {"status": "not_found", "container": n})

    rec = cip.verify("nosuchbox")
    assert rec["verdict"] == "FAIL"
    assert "IMAGE ref" not in rec["reason"]


# ------------------------------------------------------------- no fake pass --
def test_missing_docker_is_SKIP_never_a_fabricated_pass(monkeypatch):
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: {"status": "docker_absent", "container": n})
    rec = cip.verify("vibeic-eda", "vibeic-eda:0.2.30")
    assert rec["verdict"] == "SKIP"
    assert "unverifiable" in rec["reason"]


def test_identity_is_recorded_even_when_no_require_image_given(monkeypatch):
    """Recording is unconditional — that is what makes a published number
    attributable to a toolchain after the fact."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:0.2.30", PINNED_ID))
    rec = cip.verify("vibeic-eda")
    assert rec["verdict"] == "PASS"
    assert rec["image_id"] == PINNED_ID
    assert rec["image_ref"] == "vibeic-eda:0.2.30"


# ------------------------------------------------------------------- CLI ----
@pytest.mark.parametrize("verdict_rec,expected_rc", [
    ({"verdict": "PASS", "reason": "r"}, 0),
    ({"verdict": "SKIP", "reason": "r"}, 0),
    ({"verdict": "FAIL", "reason": "r"}, 1),
    ({"verdict": "MISMATCH", "reason": "r"}, 2),
])
def test_cli_exit_codes_and_json_always_written(monkeypatch, tmp_path,
                                                verdict_rec, expected_rc):
    monkeypatch.setattr(cip, "verify", lambda c, r: dict(verdict_rec))
    out = tmp_path / "sub" / "container_image.json"
    rc = cip.main(["--container", "c", "--json", str(out)])
    assert rc == expected_rc
    # the record is written for EVERY verdict, including the failing ones
    assert json.loads(out.read_text())["verdict"] == verdict_rec["verdict"]


def test_looks_like_image_ref_discriminates():
    assert cip.looks_like_image_ref("vibeic-eda:0.2.30")
    assert cip.looks_like_image_ref("ghcr.io/vibeic/vibeic-eda")
    assert not cip.looks_like_image_ref("vibeic-eda")
    assert not cip.looks_like_image_ref("vibeic_eda_0230b")


# ------------------------------------------------- defect 3: registry digest --
# A REGISTRY (manifest) digest and a CONFIG digest are both `sha256:<64 hex>`
# and they are DIFFERENT numbers for the same image. The plugin's own pin,
# `_eda_pin.IMAGE_DIGEST`, is the registry one; `docker inspect --format
# '{{.Image}}'` reports the config one, and `docker image inspect <manifest
# digest>` does not resolve. So passing the plugin's OWN pin to the plugin's
# OWN --require-image was refused as "(unresolved)" — with a message claiming
# the run "would silently execute a DIFFERENT toolchain than the one pinned"
# about a container running exactly the pinned bytes.
#
# MEASURED 2026-09-16 on 8HD-6 (lane icsha3), one container, one process:
#   _eda_pin.pinned_image_present() -> ('…@sha256:89a8fd72…', '')     # held
#   cip.verify('icsha3-eda', _eda_pin.IMAGE_DIGEST) -> MISMATCH
# The alarm is indistinguishable from a real stale-container substitution,
# which is the one thing this program exists to detect.
PIN_MANIFEST = "sha256:" + "89a8fd72" * 8
OTHER_MANIFEST = "sha256:" + "beeab663" * 8


def _held(*digests):
    """Stub `_repo_digests_of`: the RepoDigests docker records on the image."""
    return lambda image: (tuple(digests), "")


def test_container_running_the_pinned_bytes_matches_a_bare_manifest_digest(monkeypatch):
    """THE DEFECT. The container runs the pinned image; its RepoDigests carry
    the pinned manifest digest; `--require-image <that digest>` must PASS."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:0.3.49", PINNED_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: None)
    monkeypatch.setattr(cip, "_repo_digests_of",
                        _held("ghcr.io/vibeic/vibeic-eda@" + PIN_MANIFEST,
                              "192.168.1.112:5000/vibeic-eda@" + PIN_MANIFEST))

    rec = cip.verify("vibeic-eda", require_image=PIN_MANIFEST)
    assert rec["verdict"] == "PASS", rec
    assert rec["image_match"] is True
    # the record must say HOW it matched, or a reader cannot tell this apart
    # from a plain tag comparison
    assert rec["matched_by"] == "repo_digest", rec


def test_repo_at_digest_reference_form_matches_the_same_way(monkeypatch):
    """`<repo>@sha256:…` is the other spelling of the same demand, and the
    container may have been started from a TAG, so neither string equality nor
    the config-id comparison can see it."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:0.3.49", PINNED_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: None)
    monkeypatch.setattr(cip, "_repo_digests_of",
                        _held("ghcr.io/vibeic/vibeic-eda@" + PIN_MANIFEST))

    rec = cip.verify("vibeic-eda",
                     require_image="192.168.1.112:5000/vibeic-eda@" + PIN_MANIFEST)
    assert rec["verdict"] == "PASS", rec
    assert rec["matched_by"] == "repo_digest", rec


def test_the_plugins_own_pin_constant_is_accepted_by_its_own_require_image(monkeypatch):
    """Reads `_eda_pin.IMAGE_DIGEST` itself, so the two cannot drift apart
    again: whatever the pin becomes, --require-image must accept it for a
    container running an image that carries it.

    The pin is STATED at `_eda_pin` (the `_stated_eda_image` pattern), not
    inherited from this host's docker: `IMAGE_DIGEST` is still read through
    `_eda_pin`'s own attribute, but the verdict no longer depends on whether
    the host running the test has docker (inside the image it has none)."""
    import _eda_pin
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _stated_eda_image import state_the_image
    state_the_image(monkeypatch)
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:pinned", PINNED_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: None)
    monkeypatch.setattr(cip, "_repo_digests_of",
                        _held("ghcr.io/vibeic/vibeic-eda@" + _eda_pin.IMAGE_DIGEST))

    rec = cip.verify("vibeic-eda", require_image=_eda_pin.IMAGE_DIGEST)
    assert rec["verdict"] == "PASS", rec


# ---- the other direction: the repo-digest path must still REFUSE -----------
def test_stale_container_is_still_MISMATCH_through_the_repo_digest_path(monkeypatch):
    """The control that makes the fix a fix and not a hole: the container runs a
    DIFFERENT image, whose RepoDigests carry a different manifest digest. It
    must still MISMATCH, and the message must name what it DID find."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:0.3.54", STALE_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: None)
    monkeypatch.setattr(cip, "_repo_digests_of",
                        _held("ghcr.io/vibeic/vibeic-eda@" + OTHER_MANIFEST))

    rec = cip.verify("vibeic-eda", require_image=PIN_MANIFEST)
    assert rec["verdict"] == "MISMATCH", rec
    assert rec["image_match"] is False
    assert "matched_by" not in rec
    # actionable: the operator must be able to see WHICH bytes are there
    assert OTHER_MANIFEST in rec["reason"], rec["reason"]


def test_image_with_no_repo_digests_is_MISMATCH_not_a_fabricated_pass(monkeypatch):
    """A locally-built image records no RepoDigests. "I could not find the
    digest" is not "the digest is there"."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:local", STALE_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: None)
    monkeypatch.setattr(cip, "_repo_digests_of", lambda image: ((), ""))

    rec = cip.verify("vibeic-eda", require_image=PIN_MANIFEST)
    assert rec["verdict"] == "MISMATCH", rec
    assert rec["image_repo_digests"] == []


def test_unreadable_repo_digests_is_MISMATCH_and_says_why(monkeypatch):
    """docker unavailable / image gone: refuse, and record the reason rather
    than letting an unanswerable probe read as a clean refusal."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:0.3.49", PINNED_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: None)
    monkeypatch.setattr(cip, "_repo_digests_of",
                        lambda image: ((), "docker binary not on PATH"))

    rec = cip.verify("vibeic-eda", require_image=PIN_MANIFEST)
    assert rec["verdict"] == "MISMATCH", rec
    assert rec["repo_digest_probe"] == "docker binary not on PATH"
    assert "docker binary not on PATH" in rec["reason"]


def test_registry_digest_of_reads_both_spellings_and_refuses_neither_shape():
    """The digest vocabulary is `_eda_pin`'s; this pins the two shapes the
    comparison relies on and the shapes it must NOT accept."""
    assert cip._registry_digest_of(PIN_MANIFEST) == PIN_MANIFEST
    assert cip._registry_digest_of("repo/x@" + PIN_MANIFEST) == PIN_MANIFEST
    assert cip._registry_digest_of("vibeic-eda:0.3.49") is None
    assert cip._registry_digest_of("") is None
    assert cip._registry_digest_of(None) is None
    # a repository-less `@sha256:…` is malformed, not a reference (#2085)
    assert cip._registry_digest_of("@" + PIN_MANIFEST) is None


def test_a_tag_require_image_never_takes_the_repo_digest_path(monkeypatch):
    """`--require-image vibeic-eda:0.3.49` names no digest, so the new path
    must not fire at all — a tag mismatch stays a tag mismatch."""
    probed = []
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: _ok("vibeic-eda:0.3.54", STALE_ID))
    monkeypatch.setattr(cip, "_resolve_image_id", lambda r: None)
    monkeypatch.setattr(cip, "_repo_digests_of",
                        lambda image: (probed.append(image), ((), ""))[1])

    rec = cip.verify("vibeic-eda", require_image="vibeic-eda:0.3.49")
    assert rec["verdict"] == "MISMATCH", rec
    assert probed == [], "a tag demand must not probe repo digests"
