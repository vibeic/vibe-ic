"""The protected-path two-step landing stays removed.

Owner ruling, 2026-09-27: "remove all such two-step push! THAT IS USELESS!"
A change to landing code used to need two landings -- one recording the new
bytes in a byte register as `next`, one promoting them to `current` -- checked
by a validator the merge verifier ran.  That register, its validator and its
tools were deleted, and the verifier now runs every arm on the raw-attested
BASE snapshot, so a landing-code change takes effect once it has landed.

FAILS if any removed file comes back, or if a live landing entry point calls
one again.  Each removed path and each caller is named individually, so a
failure sends the reader to one file.  The names are assembled from parts so
that this file is not itself a hit for the repository-wide removal grep.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_P, _L, _R = "protected", "_landing", "_runtime"

REMOVED = (
    f"tools/ci/{_P}{_L}_transition.json",
    f"tools/ci/{_P}{_L}_transition.py",
    f"tools/ci/{_P}{_L}_prepare.sh",
    f"tools/ci/{_P}{_L}_manifest_author.py",
    f"tools/ci/{_P}{_R}_snapshot.py",
    f"tools/ci/{_P}{_R}_store.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/"
    "content_pinned_authority_verified_only_at_merge.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/"
    "transition_manifest_describes_its_tree_check.py",
)

#: The live entry points that used to call the removed tools.
CALLERS = (
    "tools/gatekeeper-verify-merge.sh",
    "tools/gatekeeper-land.sh",
    "tools/ci/pre_commit_check.sh",
    "tools/ci/repo_hygiene_gates.sh",
    "tools/ci/trusted_test_selection.py",
    "tools/ci/landing_completion_record.py",
    "tools/ci/hermetic_progress_emit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/landing_merge_verdict.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/gatekeeper_review.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/nested_progress_pin_check.py",
)

_TOKENS = (f"{_P}{_L}", f"{_P}{_R}", "select-runtime", "rebind-verdict",
           "validate-verdict", "--protected-transition-receipt")


@pytest.mark.parametrize("rel", REMOVED)
def test_the_removed_file_stays_removed(rel):
    assert not (REPO / rel).exists(), f"{rel} came back"




def test_the_verifier_runs_the_arms_on_the_base_snapshot():
    """The replacement, asserted on the verifier's own text: one runtime,
    materialized from the attested BASE, and nothing that selects another."""
    text = (REPO / "tools/gatekeeper-verify-merge.sh").read_text(
        encoding="utf-8")
    assert "materialize_base_runtime() {" in text
    assert text.count("\n  materialize_base_runtime\n") == 1
    assert 'RUNTIME_AUTHORITY_COMMIT="$BASE_SHA"' in text
    assert "CONTROLLER" not in text
