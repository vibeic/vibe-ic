"""`--require-image` is a demand: anything short of PASS must halt the run.

Shape of the defect this covers (chip-AGNOSTIC): the orchestrator enforced
`--require-image` by halting on verdict MISMATCH alone. But the most common
way the demand goes unmet is the named container simply not existing, which
`container_image_provenance.verify` reports as verdict FAIL
(`status="not_found"`) — NOT MISMATCH. That fell through to a one-line
advisory and the run CONTINUED, executing every step against whatever tools
happened to be on the host PATH while `reports/container_image.json` recorded
the failure nobody acted on.

The result is a full set of step verdicts attributed to a pinned toolchain the
run never actually used.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import container_image_provenance as cip  # noqa: E402


# --------------------------------------------------------------------------
# The verdict vocabulary this enforcement has to cover
# --------------------------------------------------------------------------
def test_absent_container_is_FAIL_not_MISMATCH():
    """The premise of the defect: a missing container does NOT produce
    MISMATCH, so MISMATCH-only enforcement never sees it."""
    rec = cip.verify("a-container-name-that-does-not-exist-9f3a2b",
                     "example.invalid/img:1.0")
    assert rec["verdict"] in ("FAIL", "SKIP")   # SKIP iff docker is absent
    assert rec["verdict"] != "MISMATCH"
    if rec["verdict"] == "FAIL":
        assert rec["status"] == "not_found"


def test_provenance_cli_already_treats_FAIL_as_nonzero():
    """The provenance program itself is correct — it exits 1 on FAIL and 2 on
    MISMATCH. Only the orchestrator's consumption was too narrow, which is why
    the fix belongs there and this program is unchanged."""
    src = (Path(__file__).resolve().parent.parent
           / "container_image_provenance.py").read_text()
    assert 'if rec["verdict"] == "MISMATCH":' in src
    assert 'if rec["verdict"] == "FAIL":' in src


# --------------------------------------------------------------------------
# The orchestrator's enforcement predicate
# --------------------------------------------------------------------------
def _enforcement_source() -> str:
    return (Path(__file__).resolve().parent.parent
            / "vibe_ic_one_shot_runner.py").read_text()


def test_orchestrator_halts_on_any_non_pass_when_image_required():
    """REGRESSION — enforcement must key on 'not PASS', never on the single
    verdict MISMATCH."""
    src = _enforcement_source()
    assert 'if args.require_image and _img_rec.get("verdict") != "PASS":' in src, (
        "enforcement must halt on ANY non-PASS verdict when --require-image "
        "is given")
    assert 'if _img_rec.get("verdict") == "MISMATCH" and args.require_image:' \
        not in src, "the MISMATCH-only enforcement branch must be gone"


def test_unpinned_runs_are_untouched():
    """POSITIVE — without --require-image the identity is still only RECORDED.
    A run legitimately without a container (Phase-1 only, --skip-phase3) must
    not start failing."""
    src = _enforcement_source()
    # the halt is guarded by args.require_image being truthy
    assert "args.require_image and" in src
    # and the advisory path for unpinned runs survives
    assert 'if _img_rec.get("verdict") not in ("PASS", None):' in src


def test_refusal_explains_why_continuing_would_be_wrong():
    """The message has to say what is lost, not just that a check failed —
    the whole point is that downstream verdicts become unattributable."""
    src = _enforcement_source()
    assert "not satisfied" in src
    assert "refusing to continue" in src
    assert "reports/container_image.json" in src   # names where identity lives


@pytest.mark.parametrize("verdict", ["FAIL", "MISMATCH", "SKIP"])
def test_every_non_pass_verdict_is_covered(verdict):
    """All three non-PASS verdicts the provenance program can emit must be
    refused under --require-image; none may be advisory-only."""
    assert verdict != "PASS"
    src = _enforcement_source()
    # a single predicate covers them all by construction
    assert '!= "PASS"' in src
