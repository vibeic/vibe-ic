"""ROUND 2 — bounding the `--base-evidence` hole, with paired controls.

Round 1 proved the DEFAULT path degrades STRICT on every way I could break the
base arm (16/16). It also found that `--base-evidence` accepts a bundle it
never validates. These cases fence off exactly which artefact's absence costs
which refusal, and pair every leniency with the run that refuses.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from test_adv_unknown_buys_leniency import (  # noqa: F401
    DIFFERENTIAL, _git, _junit, _run, synthetic)


def _host():
    return subprocess.run(["uname", "-n"], capture_output=True,
                          text=True).stdout.strip()


def _honest_bundle(root, base, tmp_path, name, *, base_junit):
    """A bundle produced by the driver's own `--base-arm-only`."""
    out = tmp_path / name
    cp, _ = _run(root, base, base_junit=base_junit,
                 extra=("--base-arm-only", str(out)))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    return out


# ------------------------------------------ THE PAIRED CONTROL FOR THE HOLE


def test_control_a_complete_same_host_bundle_refuses_the_silencing_candidate(
        synthetic, tmp_path):
    """With the WHOLE bundle present the silencing candidate is refused. This
    is the control that makes the stripped-bundle pass a real loss."""
    root, base = synthetic
    out = _honest_bundle(root, base, tmp_path, "full", base_junit=_junit("failed"))
    cp, stamp = _run(root, base, cand_junit=_junit("skipped"),
                     extra=("--base-evidence", str(out)))
    assert cp.returncode == 1, cp.stdout
    assert "SILENCED RATHER THAN FIXED" in cp.stdout
    assert not stamp.exists()


@pytest.mark.parametrize("drop", ["base.xml", "selection_base.txt",
                                  "base.xml+selection_base.txt"])
def test_dropping_bundle_artefacts_must_not_land_the_silencing_candidate(
        synthetic, tmp_path, drop):
    """Exactly the run above, with one or two files removed from the bundle —
    the shape a partial scp / rsync / stale cache directory produces."""
    root, base = synthetic
    out = _honest_bundle(root, base, tmp_path, "drop" + drop.replace("+", ""),
                         base_junit=_junit("failed"))
    for name in drop.split("+"):
        (out / name).unlink()
    cp, stamp = _run(root, base, cand_junit=_junit("skipped"),
                     extra=("--base-evidence", str(out)))
    assert cp.returncode != 0, (
        f"dropping {drop} from the bundle landed a candidate that silences a "
        f"red test\n{cp.stdout}")
    assert not stamp.exists()


def test_a_truncated_bundle_junit_without_a_selection_is_not_subtracted_as_whole(
        synthetic, tmp_path):
    """vibe-ic#1443's own defect: a base arm that ran only SOME of its files
    must not be subtracted as though whole. The junit-level completeness check
    that catches it is armed by `--base-selection`, which the bundle carries."""
    root, base = synthetic
    out = _honest_bundle(root, base, tmp_path, "trunc", base_junit=_junit("failed"))
    (out / "selection_base.txt").unlink()
    (out / "base.xml").write_text(_junit("passed", with_case=False))
    cp, stamp = _run(root, base, cand_junit=_junit("skipped"),
                     extra=("--base-evidence", str(out)))
    assert cp.returncode != 0, cp.stdout
    assert not stamp.exists()


# -------------------------------------------------- how far does it degrade


def test_a_stripped_bundle_still_refuses_an_outright_new_failure(
        synthetic, tmp_path):
    """BOUNDING THE HOLE HONESTLY. The stripped bundle degrades the test tier
    to demand-green, so a candidate that is simply RED is still refused. The
    leniency is confined to the silenced/weakened/base-completeness axis — the
    one that judges what the branch DELETED rather than what it broke."""
    root, base = synthetic
    out = tmp_path / "stripped2"
    out.mkdir()
    (out / "base_sha").write_text(base + "\n")
    (out / "host").write_text(_host() + "\n")
    cp, stamp = _run(root, base, cand_junit=_junit("failed"),
                     extra=("--base-evidence", str(out)))
    assert cp.returncode == 1, cp.stdout
    assert "NEW FAILURE(S) THIS BRANCH OWNS" in cp.stdout
    assert not stamp.exists()


def test_a_bundle_with_no_host_file_degrades_strict(synthetic, tmp_path):
    """The control proving it is specifically `host == this host` that opens
    the door: with no host at all the run takes the foreign branch and refuses
    the same candidate."""
    root, base = synthetic
    out = _honest_bundle(root, base, tmp_path, "nohost", base_junit=_junit("failed"))
    (out / "host").unlink()
    cp, stamp = _run(root, base, cand_junit=_junit("failed"),
                     extra=("--base-evidence", str(out)))
    assert cp.returncode == 1, cp.stdout
    assert "A RED BASELINE IS NOT PORTABLE" in cp.stdout


def test_the_manifest_arm_return_codes_are_never_read(synthetic, tmp_path):
    """`--base-arm-only` records `a1_rc`/`a2_rc` and exits 0 whatever they are;
    the consumer reads only `a1_worktree`. A bundle whose base arms both FAILED
    is consumed as evidence."""
    root, base = synthetic
    out = _honest_bundle(root, base, tmp_path, "rc", base_junit=_junit("failed"))
    manifest = (out / "manifest").read_text()
    assert "a1_rc=" in manifest and "a2_rc=" in manifest
    driver = Path(DIFFERENTIAL).read_text()
    consumer = driver[driver.index("--base-evidence: consume one"):]
    assert "a1_rc" not in consumer and "a2_rc" not in consumer, \
        "if this now fails the consumer learned to read them — good"
