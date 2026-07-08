"""Two-layer governance-doc reconciliation pin (v1.3.45).

Owner clarification (2026-07-08): Vibe-IC's governance has TWO layers, and the
docs must never again collapse them into "everyone direct-pushes" (the v1.2.42
regression this reconciliation fixes):

  • Layer 1 — the PUBLIC / released contribution model external users follow:
      find a bug → file a **backlog** (a report, no code) OR open a **PR** (a
      fix, with code); the merged **repo-gatekeeper / maintainer** triages
      backlogs and reviews + LANDS PRs into the next version. External users do
      NOT hold the maintainer role and do NOT push to `main`.
  • Layer 2 — the maintainer-INTERNAL improvement-phase shortcut: the maintainer
      DIRECT-PUSHES its own fixes to `main` (every gate retained; only the PR
      ceremony dropped). NOT the public model.

This guard pins that BOTH layers stay documented in each governance touchpoint,
so a future edit cannot silently re-bake direct-push as the universal/public
model, nor drop the backlog/PR public intake, nor delete the external-PR
machinery. It is marker-presence over the doc markdown — chip-AGNOSTIC, no
chip / vendor / SKU literal.

The repo-root public docs (README / CONTRIBUTING / runbook) live ABOVE the plugin
tree; when the plugin is extracted standalone they may be absent, so those checks
skip-if-absent. The in-plugin agent + skill docs are always present and are
hard-pinned.
"""
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]   # .../plugins/vibe-ic
_REPO_ROOT = Path(__file__).resolve().parents[5]     # repo root (may be absent standalone)


def _flat(text: str) -> str:
    """Whitespace-collapsed lower view so a marker that wraps across lines (or
    sits inside a markdown blockquote) still matches as a substring. The `>`
    blockquote marker is dropped first — otherwise a phrase that wraps onto a
    `> ` continuation line reads as 'layer-2 > internal' and the substring
    breaks (same normalisation as convergence_doctrine_present_check._flat)."""
    return " ".join(text.lower().replace(">", " ").split())


# ── in-plugin governance docs (ALWAYS present) ───────────────────────────────
# Each must carry BOTH the Layer-1 public intake (backlog/PR) AND the Layer-2
# maintainer-internal direct-push framing, so neither half can be dropped.
_PLUGIN_DOCS = {
    "agents/core-agent.md": [
        "two contribution layers",
        "layer-2",            # direct-push = maintainer-internal
        "layer-1",            # public intake retained
        "backlog",
        "external contributors never push to `main`",
    ],
    "agents/repo-gatekeeper.md": [
        "two contribution layers",
        "layer 1 — the public / released contribution model",
        "layer 2 — the maintainer-internal improvement-phase shortcut",
        "external users hold neither half",
    ],
    "agents/gatekeeper-agent.md": [
        "two-layer note",
        "layer-1",            # PR merge-queue machinery = layer-1 (retained)
        "layer-2 internal direct push",
        "documented-but-not-currently-activated",
    ],
    "agents/benchmark-agent.md": [
        "contribution-layer note",
        "layer-1",            # version-less PR = layer-1 report-with-fix
        "version-less pr",
        "layer-2 direct push",
    ],
    "skills/core-agent-loop/SKILL.md": [
        "contribution-layer framing",
        "layer-2",
        "layer-1",
        "polls open **backlog** items",
        # the direct-push ship step itself must survive (also pinned by
        # test_v1_1_6_core_agent_pr_method.py)
        "direct push",
    ],
    "skills/gatekeeper-loop/SKILL.md": [
        "two-layer framing",
        "layer 2",
        "layer 1",
        "external contributors never push to `main`",
    ],
    "skills/community-backlog-submit/SKILL.md": [
        "the public contribution model (layer 1)",
        "report-only",
        "report-with-fix",
        "you do not push to `main`",
    ],
    "skills/benchmark-enhancement-capture/SKILL.md": [
        "contribution-layer scope",
        "maintainer-internal (layer-2)",
        "version-less pr",
    ],
    "skills/field-agent-loop/SKILL.md": [
        "contribution-layer note",
        "**layer-1** intake role",
        "never pushes to `main`",   # _flat() collapses the blockquote line-wrap
    ],
}

# ── repo-root public docs (skip-if-absent in a standalone plugin extraction) ──
_REPO_DOCS = {
    "README.md": [
        "two contribution layers",
        "layer 1 — the public contribution model",
        "layer 2 — the maintainer-internal improvement-phase shortcut",
        "backlog",
        "version-less pr",
        "push to `main`",
    ],
    "CONTRIBUTING.md": [
        "two intake paths",
        "backlog (a report, no code)",
        "pr (a proposed fix, with code)",
        "do **not** push to `main`",
        "community-backlog-submit",
    ],
    "docs/GATEKEEPER_CUTOVER_RUNBOOK.md": [
        "two-layer status",
        "layer-1",            # this runbook = layer-1 external-PR machinery
        "layer-2",            # current: maintainer internal direct-push
        "documented but not currently activated",
        "do **not** delete",
    ],
}


@pytest.mark.parametrize("rel,markers", sorted(_PLUGIN_DOCS.items()))
def test_plugin_governance_doc_documents_both_layers(rel, markers):
    doc = _PLUGIN_ROOT / rel
    assert doc.exists(), f"governance doc missing: {doc}"
    flat = _flat(doc.read_text(errors="replace"))
    missing = [m for m in markers if _flat(m) not in flat]
    assert not missing, f"{rel} lost two-layer marker(s): {missing}"


@pytest.mark.parametrize("rel,markers", sorted(_REPO_DOCS.items()))
def test_repo_root_public_doc_teaches_layer1_not_direct_push(rel, markers):
    doc = _REPO_ROOT / rel
    if not doc.exists():
        pytest.skip(f"repo-root doc absent (standalone plugin extraction): {doc}")
    flat = _flat(doc.read_text(errors="replace"))
    missing = [m for m in markers if _flat(m) not in flat]
    assert not missing, f"{rel} lost two-layer marker(s): {missing}"


def test_marker_check_is_a_real_gate_negative():
    # sanity: a marker that is NOT in the doc is reported missing, so the green
    # results above are meaningful and not vacuous.
    flat = _flat((_PLUGIN_ROOT / "agents/core-agent.md").read_text())
    assert "this-two-layer-marker-is-not-in-the-doc-xyz" not in flat


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
