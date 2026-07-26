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
    assert "docker run -d --name" in rec["reason"]


def test_the_actionable_hint_is_a_command_that_would_actually_run(monkeypatch):
    """A hint that does not work is worse than no hint: it looks actionable and
    leaves the operator exactly where they were.

    The salvaged draft suggested `docker run -d --name <name> <image> --skip
    sleep infinity`, whose container COMMAND is the literal `--skip` — the
    container exits immediately. Pin that the suggestion is a runnable form and
    that it points at the repo's own restarter, which verifies the resulting
    container's image id rather than merely starting something."""
    monkeypatch.setattr(cip, "inspect_container",
                        lambda n: {"status": "not_found", "container": n})
    reason = cip.verify("ghcr.io/vibeic/vibeic-eda:0.2.30")["reason"]
    assert "--skip sleep infinity" not in reason
    assert "docker run -d --name <name> ghcr.io/vibeic/vibeic-eda:0.2.30 " \
           "sleep infinity" in reason
    assert "restart-eda.sh" in reason


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
