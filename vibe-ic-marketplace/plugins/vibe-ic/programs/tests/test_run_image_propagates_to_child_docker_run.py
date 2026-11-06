"""The run VERIFIED one image and silently ran another.

`--container` / `--require-image` pin the toolchain, and the runner RECORDS the
result in `reports/container_image.json`. Recording is not using. Steps that
shell out with `docker exec <container>` inherit the pin. Steps that shell out
with `docker run <IMAGE>` resolve an image of their OWN:
`fault_atpg_run._resolve_docker_image()` walks a candidate list and returns the
first tag that happens to be present LOCALLY, falling through to the upstream
`hpretl/iic-osic-tools:latest` — a DIFFERENT DISTRIBUTION, shipping stock tools
without this project's forks, not an older build of ours.

MEASURED on caravel_user_project x sky130A (plugin v1.9.65, die 2920x3520):

    reports/container_image.json
        "image_ref": "ghcr.io/vibeic/vibeic-eda:0.2.58",
        "image_match": true, "verdict": "PASS"
    locally present candidates
        ghcr.io/vibeic/vibeic-eda:0.2.60  absent
        vibeic-eda:0.2.60                 absent
        vibeic/vibeic-eda:0.2.60          absent
        hpretl/iic-osic-tools:latest      PRESENT   <-- what DFT actually used
    `fault chain --help` | grep -c skip-boundary
        ghcr.io/vibeic/vibeic-eda:0.2.58  1
        hpretl/iic-osic-tools:latest      0

Consequence: `fault chain` rc=64 `Unknown option '--skip-boundary'` -> no scan
netlist -> Step 11 DFT FAIL -> **24 downstream steps PASS-VOIDED**. And the
report blamed the operator's image ("this build of the `fault` binary predates
the flag"), which was FALSE — the pinned image has the flag.

Re-running the same step with the run's own image, changing nothing else:

    published: True   skip_boundary: True
    Internal scan chain successfully constructed. Length: 33
    Boundary scan register NOT inserted

Same class as choosing a tech LEF by filesystem order: the artefact is selected
by what is lying around on the host, so a different host implements a different
chip — and the run's own declaration is not what governs.
"""
from __future__ import annotations

import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_SCAN_SRC = (_PROGRAMS / "fault_scan_chain_insert.py").read_text(
    encoding="utf-8")




# ── the propagation ───────────────────────────────────────────────────────














# ── no-leak boundary (§4.05): what it must NOT overwrite ──────────────────






# ── the diagnostic must not name a cause it did not measure ───────────────
def test_the_skip_boundary_error_names_the_image_that_actually_ran():
    """The old text asserted "this build of the `fault` binary predates the
    flag". On the measured run that was false: the pinned image HAS the flag,
    a different one ran. A diagnostic naming the wrong cause is worse than one
    naming none — the reader checks their image, finds it new enough, and
    stops."""
    # RE-ANCHORED on the CONTAINER branch. The message is now route-branched:
    # on the LOCAL route no image runs at all, so naming one would be the very
    # defect this test exists to prevent, pointing the other way. A fixed-width
    # slice from `image_used` no longer spans the right text, so the branch is
    # located by its own delimiter instead of by character arithmetic.
    seg = _container_arm(_SCAN_SRC)
    assert "_fatpg.DOCKER_IMAGE" in seg, "the error must name the image used"
    assert "reports/container_image.json" in seg, "and what to compare it to"


def _container_arm(src: str) -> str:
    """The `--skip-boundary` diagnostic's CONTAINER branch, by delimiter."""
    assert 'if err_report.get("exec_route") == "local":' in src, (
        "the diagnostic is no longer route-branched")
    return src.split('if err_report.get("exec_route") == "local":')[1]               .split("            else:")[1]


def _local_arm(src: str) -> str:
    return src.split('if err_report.get("exec_route") == "local":')[1]               .split("            else:")[0]


def test_the_local_route_names_no_image_and_no_docker_command():
    """The mirror of the test above, and the reason it had to be re-anchored:
    with no docker client no image is started, and `DOCKER_IMAGE` is whatever
    the resolver fell back to when the registry was unreachable. Naming it, or
    offering a `docker run` the reader cannot execute, is a diagnostic naming
    the wrong cause — which this file exists to refuse."""
    seg = _local_arm(_SCAN_SRC)
    assert "No image ran" in seg
    assert "DOCKER_IMAGE" not in seg, seg
    assert "docker run" not in seg, seg


def test_the_error_lists_BOTH_causes_not_just_the_age_one():
    """The defect was a SINGLE-cause claim, not the mention of age. Age is a
    real cause; it just is not the only one that produces this error, and it
    was not the one that produced it on the measured run. The report must
    carry both so the reader checks the image identity before the version."""
    seg = _container_arm(_SCAN_SRC)
    assert "predates" in seg, "the age cause is still offered"
    assert "DIFFERENT " in seg.upper() or "different image" in seg.lower(), \
        "the wrong-image cause must be offered too"


def test_the_symptom_detector_does_not_assert_a_cause():
    """`skip_boundary_unsupported_in_log` detects the tool's error string. Its
    docstring used to conclude the cause from it ("this build of `fault`
    predates the flag"); that conclusion is how the wrong cause reached the
    report."""
    i = _SCAN_SRC.index("def skip_boundary_unsupported_in_log")
    doc = _SCAN_SRC[i:i + 1200]
    assert "SYMPTOM only" in doc
    assert "does NOT establish the cause" in doc.replace("not", "NOT")
