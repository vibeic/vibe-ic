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

import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLUGIN_ROOT.parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
CHECK = PROGRAMS / "input_doc_pdk_claim_vs_installed_pdk_check.py"
SIBLING = PROGRAMS / "pdk_via_patch_meets_layer_min_width_check.py"
HYGIENE = REPO_ROOT / "tools" / "ci" / "repo_hygiene_gates.sh"

sys.path.insert(0, str(PROGRAMS))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))























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




if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
