#!/usr/bin/env python3
"""vibe-ic — the gate whose subject is "could not verify" != "verification failed",
and which had no test of its own at all.

`gate_cli_mutation_probe` reported it SILENT with NO_TEST: 501 gate-shaped
programs exist here and this was one that nothing exercised. Its own docstring
states the distinction it exists to preserve:

    FAIL    — a compare RAN and the layout does not match the schematic.
    BLOCKED — no compare could run; the inputs cannot produce a netlist.

So the property under test is the one it is about: a structurally incapable tech
file must exit 1 (BLOCKED), a usable one must exit 0, and an UNREADABLE one must
also exit 0 — because "I could not open it" is not evidence that the tool cannot
either, and blocking on it would turn a host/container path difference into a
design verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import extraction_input_capability_check as E  # noqa: E402
# vibe-ic#1128 — these skips mean A VERIFICATION DID NOT HAPPEN, not that
# one passed. Declared through `not_verified_tier` so the run's roll-up
# cannot count them under `passed`; see that module's docstring.
from not_verified_tier import skip_not_verified  # noqa: E402
PULL_REMEDY = 'docker pull ghcr.io/vibeic/vibeic-eda:$(cat tools/vibeic-eda/VERSION)'
RUN_REMEDY = 'bash tools/vibeic-eda/restart-eda.sh'


_STUB_TECH = """\
tech
    format 31
    sky130A
end

planes
end

types
end

contact
end

extract
end
"""

#: The REAL sky130A tech file, resolved from the running image rather than
#: hand-written. My first version invented one and I added `connect`, `styles`,
#: a `substrate` statement and a `device` line one at a time, each from the
#: report's own `missing` list — four rounds of fitting a fixture to a checker,
#: which measures how well I can satisfy it, not whether a real PDK passes.
_REAL_TECH_IN_IMAGE = "/foss/pdks/sky130A/libs.tech/magic/sky130A.tech"
_IMAGE = "ghcr.io/vibeic/vibeic-eda:0.3.13"


def _real_tech(tmp_path):
    """Copy the PDK's own tech file out of the image, or skip."""
    import subprocess
    import pytest
    out = tmp_path / "sky130A.tech"
    # 300s here tripped `ci_harness_timeout_ceiling_check`: the CI harness bound
    # is 180s, so an inner bound above it does not fail the TEST, it outlives the
    # harness and kills the SESSION — a much worse failure than the skip this
    # helper already knows how to produce. `cat` out of a LOCAL image takes ~2s;
    # the only way to need minutes is an image pull, and a machine without the
    # image is exactly the case this helper skips. So the bound comes down under
    # the 60s ceiling AND a timeout joins the skip path instead of propagating.
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "cat", _IMAGE,
             _REAL_TECH_IN_IMAGE],
            capture_output=True, text=True, timeout=45)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        skip_not_verified(f"could not read the tech file out of the "
                          f"image: {type(exc).__name__}", PULL_REMEDY)
    if r.returncode != 0 or len(r.stdout) < 1000:
        skip_not_verified("the EDA image is not available here",
                          PULL_REMEDY)
    out.write_text(r.stdout)
    return out



def test_a_structurally_empty_tech_is_blocked(tmp_path):
    """The defect this gate exists for: sections declared, nothing in them.

    Magic then cannot resolve the design's layers, `ext2spice` yields nothing,
    and the flow reports LVS_EXTRACTION_NO_NETLIST as FAIL — a run that verified
    NOTHING shelved beside a run that verified something and found it broken.
    """
    t = tmp_path / "stub.tech"
    t.write_text(_STUB_TECH)
    rc = E.main([str(t)])
    assert rc == 1, f"an empty-sectioned tech file exited {rc}, not BLOCKED"


def test_the_real_sky130a_tech_is_usable(tmp_path):
    """The other direction, and the one that matters: a gate that always blocks
    would stop every extraction on every PDK.

    Driven by the PDK's OWN tech file rather than a fixture I tuned until it
    passed — the second is a test of my patience with the checker.
    """
    assert E.main([str(_real_tech(tmp_path))]) == 0


def test_an_unreadable_tech_does_not_block(tmp_path):
    """Stated in the program's own contract, and load-bearing.

    The tech file routinely lives inside the tool container while this check
    runs on the host. Treating "not readable here" as BLOCKED would convert a
    path difference into a design verdict — the exact substitution the gate
    exists to prevent, pointed the other way.
    """
    # A path that does not exist, not a chmod: `chmod 000` does not stop root,
    # so on a root session that fixture reads the file happily and the test
    # measures nothing. A missing path raises the same OSError the contract
    # names, for every uid.
    rep = E.check_magic_tech_file(tmp_path / "not_here.tech",
                                  ["extract all", "ext2spice"])
    assert rep.usable is True, "an unopenable tech file BLOCKED the flow"
    assert rep.inconclusive is True, "it was reported as a positive capability"


def test_a_missing_file_is_a_usage_error_not_a_verdict(tmp_path):
    """rc 2 — the question could not be asked. Distinct from rc 1, which says
    the inputs were examined and cannot produce a netlist."""
    assert E.main([str(tmp_path / "nope.tech")]) == 2
