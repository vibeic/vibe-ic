#!/usr/bin/env python3
"""The gate held a slot in the hygiene count while blind (vibe-ic#1076).

`input-doc claims vs installed PDK` reported NOT_CHECKED because it was wired
with no PDK backend at all: `DEFAULT_PDKS_ROOT = "/foss/pdks"` does not exist
on a CI host, so it took its vacuous early return before scanning anything —
`0 input document(s), 0 candidate claim(s)`, rc 2.

The declaration comment argued that state was correct because "the ARTEFACTS
are covered by nothing automatic". A sibling in the same hygiene script
disproves it: `pdk_via_patch_meets_layer_min_width_check` reaches the installed
PDKs from CI with `--from-image` and passes in the same run. The mechanism was
already accepted here; this checker simply had no flag for it.

MEASURED on 8HD-7 at 1adbf3444, over the whole repo tree, exit codes taken from
python directly rather than through a pipe:

    as wired before  :   0 documents, 0 claims,                       rc 2
    --from-image     : 134 documents, 7 claims, contradicted=2,       rc 1
    ... --advisory   : the same report, verdict still FAIL,           rc 0
    ... image absent :   0 documents, the WARN names the image,       rc 2

WHAT IS ASSERTED HERE, AND WHAT IS NOT. The live run is not a unit test — it
needs the anchored image and a docker daemon. What is pinned here is every part
that can go wrong SILENTLY and that no image is needed for: the flags exist,
the image is READ from the repo anchor rather than restated, the image is
PROBED before anything is started so a gate never pulls tens of gigabytes,
`--advisory` moves the exit code and nothing else, it refuses to move rc 2, and
the hygiene script actually passes both flags. The live numbers are recorded in
the PR and reproduced from the issue.

chip-AGNOSTIC: flag plumbing, exit-code tiers and the wiring text. No design,
PDK, vendor or process literal appears here.
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLUGIN_ROOT.parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
CHECK = PROGRAMS / "input_doc_pdk_claim_vs_installed_pdk_check.py"
SIBLING = PROGRAMS / "pdk_via_patch_meets_layer_min_width_check.py"
HYGIENE = REPO_ROOT / "tools" / "ci" / "repo_hygiene_gates.sh"
VERSION_PIN = REPO_ROOT / "tools" / "vibeic-eda" / "VERSION"

sys.path.insert(0, str(PROGRAMS))
import input_doc_pdk_claim_vs_installed_pdk_check as C  # noqa: E402

# <= 60s: `ci_harness_timeout_ceiling_check` derives the per-call ceiling from
# the harness bound as 180 // 3. Every subprocess below drives the CLI over an
# EMPTY tree with no backend, so it is vacuous and answers in under a second.
_BOUND_S = 55


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK), *args],
                          capture_output=True, text=True, timeout=_BOUND_S)


def test_the_checker_offers_the_mechanism_its_sibling_already_uses():
    """The narrow, non-negotiable part of the issue. `--container` needs a
    container somebody else started, and nobody starts one in CI, so the gate
    could not be wired the way the sibling that works is wired."""
    out = _cli("--help").stdout
    assert "--from-image" in out, out
    assert "--advisory" in out, out


def test_the_image_is_READ_from_the_repo_anchor_and_never_a_floating_tag():
    """`--from-image` decides WHICH artefacts the verdict is taken against, so
    the image is part of the verdict. Reading `tools/vibeic-eda/VERSION` means
    an anchor bump applies here with no edit and no registration, so this file
    cannot become a second place the version is wrong."""
    assert VERSION_PIN.is_file(), f"no anchor at {VERSION_PIN}"
    anchor = VERSION_PIN.read_text().strip()
    image, why = C.pinned_image()
    assert image is not None, why
    assert image.endswith(":" + anchor), (
        f"{image} does not carry the repo anchor {anchor}")
    # An explicit image still wins, or the flag would be decorative...
    assert C.pinned_image("x/y:1.2.3") == ("x/y:1.2.3", "")
    # ...and with no anchor above it there is a REASON, never a `:latest`
    # fallback whose bytes a third party controls.
    image2, why2 = C.pinned_image()
    assert ":latest" not in (image2 or ""), image2
    assert why2 == ""


def test_no_anchor_yields_a_reason_and_not_a_guess(monkeypatch, tmp_path):
    """The packaged-plugin case: no repo above the file. "I could not resolve
    an image" must arrive as a sentence, not as an image."""
    lonely = tmp_path / "programs" / "x.py"
    lonely.parent.mkdir(parents=True)
    lonely.write_text("")
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.setattr(C, "__file__", str(lonely))
    image, why = C.pinned_image()
    assert image is None
    assert "VERSION" in why and "floating tag" in why, why


def test_an_unstartable_image_is_disclosed_and_never_becomes_a_pass():
    """An image that will not open is not a clean PDK. The helper returns a
    reason; it must not raise, and must not hand back a container id."""
    cid, stop, why = C.start_pinned_container(
        "ghcr.io/vibeic/definitely-not-an-image:0.0.0-nope")
    assert cid is None and stop is None
    assert why, "an unstartable image produced no reason"


def test_the_image_is_PROBED_before_anything_is_started(monkeypatch):
    """A bare `docker run` on an absent tag PULLS — measured here at ~23 GB and
    minutes, inside a gate whose whole job takes 23 s. A hygiene run that
    silently downloads that is a gate people switch off, so presence is probed
    first and an absent image is reported as the host fact it is.

    Asserted on the ARGV, because "we meant not to pull" is not a property.
    """
    calls = []

    class _CP:
        returncode = 1
        stdout = ""
        stderr = "no such image"

    monkeypatch.setattr(C.subprocess, "run",
                        lambda argv, **kw: calls.append(list(argv)) or _CP())
    cid, stop, why = C.start_pinned_container("some/image:1.0")
    assert cid is None and stop is None
    assert len(calls) == 1, f"something ran after the probe failed: {calls}"
    assert calls[0][:3] == ["docker", "image", "inspect"], calls[0]
    assert "not present on this host" in why, why


def test_a_present_image_is_started_with_pull_disabled(monkeypatch):
    """The other half: when the probe succeeds the container IS started, and
    the start still cannot reach the network."""
    calls = []

    class _CP:
        returncode = 0
        stdout = "deadbeefcafe\n"
        stderr = ""

    monkeypatch.setattr(C.subprocess, "run",
                        lambda argv, **kw: calls.append(list(argv)) or _CP())
    cid, stop, why = C.start_pinned_container("some/image:1.0")
    assert why == "" and cid == "deadbeefcafe" and stop is not None
    assert calls[0][:3] == ["docker", "image", "inspect"], calls[0]
    assert calls[1][:2] == ["docker", "run"], calls[1]
    assert "--pull" in calls[1] and "never" in calls[1], calls[1]
    # And the cleanup the `finally` in main() leans on really removes it.
    stop()
    assert calls[-1][:3] == ["docker", "rm", "-f"], calls[-1]
    assert calls[-1][3] == "deadbeefcafe", calls[-1]


def test_advisory_refuses_to_downgrade_a_VACUOUS_run(tmp_path):
    """BIDIRECTIONAL NEGATIVE CONTROL, half 1 — the half that makes the flag
    safe. rc 1 is "I looked and found something"; rc 2 is "I could not look".
    Downgrading rc 2 would make `run_tolerating_uncheckable` read 0 and count
    this gate as CHECKED AND CLEAN over a tree it never opened, which is
    vibe-ic#1076 reintroduced through the flag that fixes it.
    """
    plain = _cli(str(tmp_path))
    adv = _cli(str(tmp_path), "--advisory")
    assert "VACUOUS" in (plain.stdout + plain.stderr)
    assert "VACUOUS" in (adv.stdout + adv.stderr)
    assert plain.returncode == 2, plain.stdout + plain.stderr
    assert adv.returncode == 2, (
        "advisory laundered a VACUOUS rc 2 into 0 — that is not tolerating a "
        "finding, it is hiding the absence of one:\n" + adv.stdout + adv.stderr)


def test_advisory_tolerates_a_REAL_fail_and_still_states_it(monkeypatch,
                                                            tmp_path):
    """BIDIRECTIONAL NEGATIVE CONTROL, half 2. Narrowing advisory to rc 1 is
    trivially satisfiable by never downgrading anything, so the tolerated case
    is asserted too — with the verdict word and the finding still in the
    output, because an advisory gate is honest only while the finding is
    stated."""
    fail = {"gate": C.GATE, "verdict": "FAIL", "reason": "synthetic",
            "counts": {"contradicted": 1, "corroborated": 0, "undecided": 0},
            "claims": [], "documents_scanned": 1}
    monkeypatch.setattr(C, "run", lambda *a, **k: fail)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = C.main([str(tmp_path), "--advisory"])
    out = buf.getvalue()
    assert rc == 0, f"a real FAIL was not tolerated by --advisory; rc={rc}"
    assert "The verdict above is FAIL" in out, out

    with contextlib.redirect_stdout(io.StringIO()):
        rc_plain = C.main([str(tmp_path)])
    assert rc_plain == 1, "without --advisory the same FAIL must still block"


def test_the_wiring_actually_passes_from_image_AND_advisory():
    """A checker that grew a flag nobody passes is the same NOT_CHECKED state
    with more code in it. Read as bash reads it — `\\` continuations folded —
    so a flag stranded on an unreached line cannot pass this."""
    logical = " ".join(
        ln.rstrip()[:-1] if ln.rstrip().endswith("\\") else ln.rstrip() + "\n"
        for ln in HYGIENE.read_text().splitlines())
    idx = logical.find("input_doc_pdk_claim_vs_installed_pdk_check.py")
    assert idx > 0, "the gate is no longer wired at all"
    call = logical[idx:logical.find("\n", idx)]
    assert "--from-image" in call, call
    assert "--advisory" in call, call


def test_the_gate_keeps_its_uncheckable_exemption():
    """`--from-image` does not make rc 2 unreachable — a host without the
    anchored image still cannot look. The exemption must therefore stay, or
    `_gate_dispatch` raises a wiring error the moment a cold host runs it."""
    lines = HYGIENE.read_text().splitlines()
    hits = [i for i, ln in enumerate(lines)
            if ln.lstrip().startswith('run_tolerating_uncheckable '
                                      '"input-doc claims vs installed PDK"')]
    assert len(hits) == 1, f"expected exactly one wiring, found {len(hits)}"
    assert lines[hits[0] - 1].lstrip().startswith("uncheckable_until "), (
        "the exemption no longer sits immediately above the gate")


def test_the_superseded_justification_no_longer_reads_as_current():
    """The old comment asserted NOT_CHECKED was correct because the artefacts
    were unreachable. Left standing beside a wiring that reaches them, the file
    would argue against itself and the next reader would believe the prose."""
    txt = HYGIENE.read_text()
    assert "vibe-ic#1076" in txt, "the replacement states no provenance"
    stale = "NOT_CHECKED in the roll-up is the correct state"
    if stale in txt:
        assert "SUPERSEDED" in txt, (
            "the superseded justification is still stated as current")


def test_the_sibling_mechanism_this_claims_parity_with_still_exists():
    """PREMISE. The whole argument is "a sibling in this file already does
    this". If that sibling stops using --from-image, the parity claim is prose
    about something that no longer happens."""
    assert SIBLING.is_file(), SIBLING
    assert "--from-image" in SIBLING.read_text()
    hy = HYGIENE.read_text()
    assert "pdk_via_patch_meets_layer_min_width_check.py" in hy
    assert "--from-image --advisory" in hy


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
