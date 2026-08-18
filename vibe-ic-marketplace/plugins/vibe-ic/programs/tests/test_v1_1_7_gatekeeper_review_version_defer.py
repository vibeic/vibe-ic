"""Owner directive 2026-06-17 — authoring PRs (field/core) carry NO version
bump; the gatekeeper assigns ALL versions at merge.

`gatekeeper_review.py --version-by-gatekeeper` is the AUTHORING-side review of
such a version-less PR: when cur==prev (no bump in the diff) the version-bump
gate DEFERS (rc -1 SKIP) instead of FAILing "not bumped", and the authoring
cadence floor is TARGETED. The gatekeeper's FINAL review — run WITHOUT the flag,
AFTER gatekeeper_assign_version.py writes the real version — still fully
ENFORCES the monotonic+equality bump. These tests pin both halves via the
version_bump_gate unit AND the review() orchestration (with injected versions).

§4.05 no-leak: the flag MUST NOT defer a genuinely-broken bump — a NON-monotonic
authoring bump (cur<prev) and a marketplace/plugin MISMATCH still FAIL even with
the flag set. chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import gatekeeper_review as GR  # noqa: E402


# ── version_bump_gate unit: the defer condition ───────────────────────────────
def test_versionless_authoring_pr_defers_with_flag():
    # cur==prev (no bump), flag ON -> SKIP (deferred to gatekeeper at merge).
    g = GR.version_bump_gate("1.1.6", "1.1.6", "1.1.6",
                             version_by_gatekeeper=True)
    assert g.rc == -1
    assert "deferred" in g.summary
    assert g.green  # rc -1 SKIP is non-blocking


def test_versionless_authoring_pr_fails_WITHOUT_flag():
    # Same no-bump, flag OFF -> the enforced path FAILs "not bumped".
    g = GR.version_bump_gate("1.1.6", "1.1.6", "1.1.6",
                             version_by_gatekeeper=False)
    assert g.rc == 1
    assert not g.green


def test_real_bump_passes_under_flag_enforced_rerun():
    # The gatekeeper's post-assignment re-run: a real monotonic bump
    # 1.1.6 -> 1.1.7 with marketplace in sync PASSes (flag OFF = enforced).
    g = GR.version_bump_gate("1.1.7", "1.1.6", "1.1.7",
                             version_by_gatekeeper=False)
    assert g.rc == 0, g.summary
    assert g.green


# ── §4.05: the flag must NOT defer a genuinely-broken bump ────────────────────
def test_flag_does_not_defer_nonmonotonic_authoring_bump():
    # An author who (wrongly) bumped DOWNWARD: cur<prev, flag ON. cur!=prev so
    # the defer condition does NOT apply -> still evaluated -> FAIL.
    g = GR.version_bump_gate("1.1.5", "1.1.6", "1.1.5",
                             version_by_gatekeeper=True)
    assert g.rc == 1, g.summary
    assert not g.green


def test_flag_does_not_defer_marketplace_mismatch():
    # cur==prev would defer, but here the author DID bump plugin.json to 1.1.7
    # while marketplace stayed 1.1.6 -> cur!=prev so evaluated -> equality FAIL.
    g = GR.version_bump_gate("1.1.7", "1.1.6", "1.1.6",
                             version_by_gatekeeper=True)
    assert g.rc == 1, g.summary
    assert not g.green


# ── review() orchestration: cadence + verdict on a version-less authoring PR ──
def _plugin_root():
    return PROGRAMS.parent  # …/plugins/vibe-ic


def test_review_versionless_authoring_pr_cadence_targeted():
    v = GR.review(
        "BASE", "HEAD",
        repo=Path("/nonexistent"), plugin_root=_plugin_root(),
        role="core-agent",
        version_by_gatekeeper=True,
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"],
        override_cur="1.1.6", override_prev="1.1.6")
    assert v.cadence == "TARGETED"
    vb = next(g for g in v.gates if g.name == "version_bump_monotonic_check")
    assert vb.rc == -1 and "deferred" in vb.summary


def test_review_versionless_authoring_pr_version_gate_not_blocking():
    # The version gate must not appear in `blocking` for a version-less PR.
    v = GR.review(
        "BASE", "HEAD",
        repo=Path("/nonexistent"), plugin_root=_plugin_root(),
        role="core-agent",
        version_by_gatekeeper=True,
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"],
        override_cur="1.1.6", override_prev="1.1.6")
    assert not any("version_bump_monotonic_check" in b for b in v.blocking)


def test_review_without_flag_versionless_pr_blocks_on_version():
    # Same version-less PR, flag OFF -> version gate FAILs and blocks.
    v = GR.review(
        "BASE", "HEAD",
        repo=Path("/nonexistent"), plugin_root=_plugin_root(),
        role="core-agent",
        version_by_gatekeeper=False,
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"],
        override_cur="1.1.6", override_prev="1.1.6")
    assert any("version_bump_monotonic_check" in b for b in v.blocking)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── data-only change-sets: the version gate is N/A, not FAIL ─────────────────
# A benchmark-data-only PR (e.g. #278) could never pass gatekeeper_review: the
# version gate demanded a bump even though the change ships nothing via
# `/plugin update`, and main's own convention lands these as unversioned
# `docs(benchmark-data): …` commits. That pressured the maintainer into either
# bypassing the gate or inflating the version for a change no user receives.

def test_ships_to_users_classification():
    assert GR.ships_to_users(["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"])
    assert GR.ships_to_users(["mcp/server.py"])
    assert GR.ships_to_users([".claude-plugin/marketplace.json"])
    assert GR.ships_to_users(["vibe-ic-marketplace/.claude-plugin/marketplace.json"])
    assert not GR.ships_to_users(["benchmark-data/ic/spm/v1/waivers.json"])
    assert not GR.ships_to_users(["docs/INSTALL.md", "tools/vibeic-eda/VERSION"])


def test_data_only_changeset_skips_version_gate():
    r = GR.version_bump_gate("1.5.75", "1.5.75", "1.5.75", False,
                              ["benchmark-data/ic/spm/v1/waivers.json"])
    assert r.rc == -1, f"data-only change-set should SKIP, got rc={r.rc}"
    assert "ships nothing" in r.summary


def test_shipping_changeset_still_enforced_without_bump():
    """The exemption must NOT weaken the gate for anything users receive."""
    r = GR.version_bump_gate("1.5.75", "1.5.75", "1.5.75", False,
                              ["vibe-ic-marketplace/plugins/vibe-ic/programs/x.py"])
    assert r.rc == 1, "a shipping change with no bump must still FAIL"


def test_files_omitted_preserves_legacy_behaviour():
    """Callers that pass no file list keep the original strict semantics."""
    r = GR.version_bump_gate("1.5.75", "1.5.75", "1.5.75", False)
    assert r.rc == 1
