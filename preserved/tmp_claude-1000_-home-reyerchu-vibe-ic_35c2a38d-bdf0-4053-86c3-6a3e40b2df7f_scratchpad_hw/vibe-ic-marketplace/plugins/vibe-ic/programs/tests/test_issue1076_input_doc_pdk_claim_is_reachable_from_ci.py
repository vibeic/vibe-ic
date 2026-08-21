#!/usr/bin/env python3
"""The gate occupied a slot in the 74-gate count while blind (vibe-ic#1076).

`input-doc claims vs installed PDK` reported NOT_CHECKED because it was wired
with no PDK backend: `DEFAULT_PDKS_ROOT = "/foss/pdks"` does not exist on a CI
host, so it took its vacuous early return before scanning anything —
`0 input document(s), 0 candidate claim(s)`.

The declaration comment argued that state was correct because "the ARTEFACTS
are covered by nothing automatic". A sibling 350 lines earlier in the same file
disproves it: `pdk_via_patch_meets_layer_min_width_check.py` reaches the
installed PDKs from CI with `--from-image` and passes in the same run. The
mechanism was already accepted; this checker simply had no flag for it.

MEASURED with the image the repo pins:

    as wired before  : 0 documents, 0 claims,  rc=2 (NOT_CHECKED)
    with --from-image: 134 documents, 7 claims, contradicted=2, rc=1

The two contradictions are published run input justifying a LEVEL=1 corner-sim
standin on the premise that IHP SG13G2 ships no ngspice corner library. It
ships six.

WHAT IS ASSERTED HERE, AND WHAT IS NOT. The live docker run is not a unit test
— it needs the pinned image and several minutes. These tests pin the parts that
can go wrong silently and that no image is needed for: the flags exist, the
pin is READ rather than hardcoded, `--advisory` changes the exit code and
nothing else, and the wiring in the shell script says what it does. The live
numbers are recorded in the PR, reproduced from the issue.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLUGIN_ROOT.parents[2]
CHECK = PLUGIN_ROOT / "programs" / "input_doc_pdk_claim_vs_installed_pdk_check.py"
HYGIENE = REPO_ROOT / "tools" / "ci" / "repo_hygiene_gates.sh"
VERSION_PIN = REPO_ROOT / "tools" / "vibeic-eda" / "VERSION"

sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
import input_doc_pdk_claim_vs_installed_pdk_check as C  # noqa: E402


def test_the_checker_now_offers_the_mechanism_its_sibling_already_uses():
    """The narrow, non-negotiable part of the issue: it had no `--from-image`,
    so it could not be wired the way the sibling that works is wired."""
    out = subprocess.run([sys.executable, str(CHECK), "--help"],
                         capture_output=True, text=True, timeout=55).stdout
    assert "--from-image" in out, out
    assert "--advisory" in out, out


def test_the_pinned_image_is_READ_from_the_repo_not_hardcoded():
    """The sibling hardcodes `DEFAULT_IMAGE = "...:0.2.88"` and the anchor has
    since moved to 0.2.89 — so it is pinned to an image the repo no longer
    anchors, silently. Reading the pin means the anchor bump applies with no
    edit here, and this file never becomes the second place the version is
    wrong."""
    assert VERSION_PIN.is_file(), f"no pin at {VERSION_PIN}"
    image, why = C.pinned_image()
    assert image is not None, why
    assert image.endswith(":" + VERSION_PIN.read_text().strip()), (
        f"{image} does not carry the repo pin {VERSION_PIN.read_text().strip()}")
    # ...and an explicit --image still wins, or the flag would be decorative.
    assert C.pinned_image("x/y:1.2.3")[0] == "x/y:1.2.3"


def test_an_unreachable_image_is_disclosed_and_never_becomes_a_pass():
    """An image that will not start is not a clean PDK. The helper returns a
    reason; it must not raise, and must not hand back a container id."""
    cid, stop, why = C._start_pinned_container(
        "ghcr.io/vibeic/definitely-not-an-image:0.0.0-nope")
    assert cid is None and stop is None
    assert why, "an unreachable image produced no reason"


def _run_advisory_pair(tmp_path, extra):
    """Drive the CLI over an EMPTY tree with no backend, so it is vacuous and
    needs no docker — the exit-code plumbing is what is under test."""
    return subprocess.run(
        [sys.executable, str(CHECK), str(tmp_path), *extra],
        # <=60s, the per-call ceiling `ci_harness_timeout_ceiling_check`
        # derives as (harness bound 180s // 3 pytest invocations). The first
        # cut used 120 and put the SHIPPED TREE over that ceiling — a gate this
        # branch reddened rather than one it found. This call drives the CLI
        # over an EMPTY tree with no backend, so it is vacuous and fast; 120
        # bought nothing.
        capture_output=True, text=True, timeout=55)


def test_advisory_changes_the_exit_code_and_nothing_else(tmp_path):
    """BIDIRECTIONAL NEGATIVE CONTROL, half 1.

    An advisory gate stays honest only if the finding is still stated. If
    `--advisory` also softened the verdict word or dropped the findings, the
    roll-up would read as a gate that found nothing — which is the defect this
    issue is about, moved rather than fixed.
    """
    plain = _run_advisory_pair(tmp_path, [])
    adv = _run_advisory_pair(tmp_path, ["--advisory"])
    # Same tree, same backend, same verdict text either way.
    assert "VACUOUS" in (plain.stdout + plain.stderr)
    assert "VACUOUS" in (adv.stdout + adv.stderr)
    # `--advisory` downgrades ONLY rc 1 ("we looked and found something").
    # rc 2 is "we could not look", and laundering it into 0 would make
    # `run_tolerating_uncheckable` count this gate as CHECKED AND CLEAN over a
    # tree it never opened — vibe-ic#1076 reintroduced through the flag that
    # fixes it. The first cut of this test asserted the buggy direction while
    # its own message argued against it; the always-fires mutant is what
    # separated them.
    assert plain.returncode == 2, plain.stdout + plain.stderr
    assert adv.returncode == 2, (
        "advisory laundered a VACUOUS rc 2 into 0 — that is not tolerating a "
        "finding, it is hiding the absence of one:\n" + adv.stdout + adv.stderr)


def test_PAIRED_a_real_FAIL_is_what_advisory_actually_tolerates(monkeypatch,
                                                                tmp_path):
    """The other half. Narrowing advisory to rc 1 is trivially satisfiable by
    never downgrading anything, so the tolerated case is asserted too — with
    the verdict word and the finding still present in the output."""
    import io
    import contextlib
    fake = {"gate": C.GATE, "verdict": "FAIL", "reason": "synthetic",
            "counts": {"contradicted": 1, "corroborated": 0, "undecided": 0},
            "findings": [], "input_documents": 1}
    monkeypatch.setattr(C, "run", lambda *a, **k: fake)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = C.main([str(tmp_path), "--advisory"])
    out = buf.getvalue()
    assert rc == 0, f"a real FAIL was not tolerated by --advisory; rc={rc}"
    assert "The verdict above is FAIL" in out, out

    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc_plain = C.main([str(tmp_path)])
    assert rc_plain == 1, "without --advisory the same FAIL must still block"


def test_the_wiring_declares_from_image_AND_advisory():
    """BIDIRECTIONAL NEGATIVE CONTROL, half 2: the shell actually passes both.

    A checker that grew a flag nobody passes is the same NOT_CHECKED state with
    more code in it.
    """
    txt = HYGIENE.read_text()
    idx = txt.find("input_doc_pdk_claim_vs_installed_pdk_check.py")
    assert idx > 0, "the gate is no longer wired at all"
    call = txt[idx:idx + 400]
    assert "--from-image" in call, call
    assert "--advisory" in call, call


def test_the_stale_justification_comment_is_gone():
    """The comment asserted NOT_CHECKED was correct because the artefacts were
    unreachable. Leaving it beside a wiring that reaches them would leave the
    file arguing against itself, and the next reader would believe the prose."""
    txt = HYGIENE.read_text()
    assert "NOT_CHECKED in the roll-up is the correct state" not in txt, (
        "the superseded justification is still in the file")
    assert "vibe-ic#1076" in txt, "the replacement states no provenance"


def test_the_sibling_mechanism_this_claims_parity_with_still_exists():
    """PREMISE. The whole argument is 'a sibling in this file already does
    this'. If that sibling stops using --from-image, the parity claim above is
    prose about something that no longer happens."""
    sib = PLUGIN_ROOT / "programs" / "pdk_via_patch_meets_layer_min_width_check.py"
    assert sib.is_file(), sib
    assert "--from-image" in sib.read_text()
    assert "--from-image" in HYGIENE.read_text()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
