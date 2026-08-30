#!/usr/bin/env python3
"""flow #486 (v0.2.98) — two-tree test posture: shared plugin-root resolver.

The installed plugin cache is a FLATTENED tree
(~/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/<ver>/...) with NO
monorepo ancestors, while the source tree is the full monorepo
(.../AI_IC_design/vibe-ic-marketplace/plugins/vibe-ic/...). Layout-sensitive
tests that hard-coded the source-monorepo path shape (parents[5] +
re-descend "vibe-ic-marketplace/plugins/vibe-ic", repo-root "tools/ci",
"docs/", "benchmark_phase1/", "plugins/.gitignore") raised IndexError /
FileNotFoundError on the cache tree.

This test pins the shared resolver's contract:
  1. ``plugin_root`` finds the plugin root from a SIMULATED flattened tree
     (built under ``tmp_path``) by walking up to the manifest — no monorepo
     ancestors required.
  2. A not-shipped-resource lookup yields the canonical NAMED ``pytest.skip``
     (NOT an exception) on a tree where the repo root / resource is absent.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

import _plugin_tree as pt


# --------------------------------------------------------------------------- #
# 1. Resolver finds the plugin root from a SIMULATED flattened tree.
# --------------------------------------------------------------------------- #
def _make_flat_plugin(tmp_path: Path, version: str = "0.2.98") -> Path:
    """Build a minimal flattened plugin tree (manifest + a nested file) with
    NO monorepo ancestors, mirroring the install cache shape."""
    root = tmp_path / "vibe-ic" / version
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": version})
    )
    (root / "programs" / "tests").mkdir(parents=True)
    nested = root / "programs" / "tests" / "fake_test.py"
    nested.write_text("# fake\n")
    return root


def test_plugin_root_resolves_from_flattened_tree(tmp_path):
    root = _make_flat_plugin(tmp_path)
    nested = root / "programs" / "tests" / "fake_test.py"
    # Start from a deeply nested file in the flattened tree; resolver must
    # walk UP to the manifest dir, NOT assume any monorepo path shape.
    found = pt.plugin_root(start=nested)
    assert found == root.resolve()


def test_plugin_root_resolves_when_started_from_a_directory(tmp_path):
    root = _make_flat_plugin(tmp_path)
    found = pt.plugin_root(start=root / "programs")
    assert found == root.resolve()


def test_plugin_root_raises_only_on_a_genuinely_broken_tree(tmp_path):
    """No manifest anywhere up the chain -> RuntimeError (broken tree), which
    is distinct from the two-tree-posture (a present-but-trimmed) condition."""
    orphan = tmp_path / "no" / "manifest" / "here"
    orphan.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        pt.plugin_root(start=orphan / "x.py")


def test_plugin_path_is_relative_to_resolved_root(tmp_path, monkeypatch):
    root = _make_flat_plugin(tmp_path)
    # Point the resolver at the flat tree by patching the module anchor.
    monkeypatch.setattr(pt, "__file__", str(root / "programs" / "tests" / "_plugin_tree.py"))
    p = pt.plugin_path("agents", "defaults", "class_reference.yaml")
    assert p == (root / "agents" / "defaults" / "class_reference.yaml").resolve() \
        or p == root.joinpath("agents", "defaults", "class_reference.yaml")


# --------------------------------------------------------------------------- #
# 2. Not-shipped resource lookups yield a NAMED skip, never an exception.
# --------------------------------------------------------------------------- #
def test_require_or_skip_named_skip_for_absent_in_plugin_resource(tmp_path, monkeypatch):
    root = _make_flat_plugin(tmp_path)
    monkeypatch.setattr(pt, "__file__", str(root / "programs" / "tests" / "_plugin_tree.py"))
    # An in-plugin path that does NOT exist on this trimmed tree.
    with pytest.raises(pytest.skip.Exception) as ei:
        pt.require_or_skip("agents", "defaults", "definitely_absent.yaml")
    assert pt.NOT_SHIPPED_REASON in str(ei.value)


def test_repo_resource_or_skip_named_skip_on_flattened_tree(tmp_path, monkeypatch):
    """On the flattened cache there is no repo root, so a repo-root resource
    (e.g. tools/ci/...) must yield the canonical NAMED skip, not an error."""
    root = _make_flat_plugin(tmp_path)
    monkeypatch.setattr(pt, "__file__", str(root / "programs" / "tests" / "_plugin_tree.py"))
    assert pt.repo_root() is None  # flattened: no vibe-ic-marketplace ancestor
    with pytest.raises(pytest.skip.Exception) as ei:
        pt.repo_resource_or_skip("tools", "ci", "check_version_sync_with_commit.sh")
    assert pt.NOT_SHIPPED_REASON in str(ei.value)


def test_repo_path_or_missing_is_nonexistent_on_flattened_tree(tmp_path, monkeypatch):
    """Module-level-safe: returns a guaranteed-non-existent path on the
    flattened tree so `.is_dir()` guards fire instead of IndexError.

    THE POINTER IS NOW CONTROLLED, AND IT ALWAYS SHOULD HAVE BEEN. This case
    read `VIBE_IC_BENCHMARK_DATA` from the ambient environment: an operator who
    exported it changed the answer without touching a line of code, so the case
    measured the host, not the resolver. It only became visible when
    `repo_path_or_missing` learned to answer `benchmark-data/...` from the
    published corpus — with a real clone exported, the "guaranteed non-existent"
    path came back as `<clone>/protocol_parity`, which exists.

    The invariant this case is actually for is unchanged and is asserted below:
    with NO corpus reachable, a flattened tree must yield a path that does not
    exist, so a caller's `.is_dir()` guard fires instead of an IndexError. The
    other half — a corpus IS reachable, so the data is genuinely there and must
    be handed over — is the paired case that follows.
    """
    root = _make_flat_plugin(tmp_path)
    monkeypatch.setattr(pt, "__file__", str(root / "programs" / "tests" / "_plugin_tree.py"))
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
    bp = pt.repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")
    assert not bp.is_dir()
    assert not bp.exists()
    # And the general case is untouched by the reroute: a NON-moved resource is
    # still the flattened-tree sentinel whether or not a corpus exists.
    other = pt.repo_path_or_missing("tools", "ci")
    assert not other.exists()


def test_PAIRED_GUARD_a_reachable_corpus_is_handed_over_on_a_flattened_tree(
        tmp_path, monkeypatch):
    """The other direction: `benchmark-data/...` resolves when a corpus does.

    Without this, the case above could pass because the resolver never answers
    at all — which is exactly what it did on every host from `c5d7f2d00` until
    the reroute: `benchmark-data/` is not in the repository, so every caller got
    a non-existent path and skipped, forever, and no test said so.

    The corpus pointer is absolute and independent of the repo root, so a
    flattened cache tree with a valid pointer CAN read the corpus; refusing it
    there would be an invented restriction.
    """
    root = _make_flat_plugin(tmp_path)
    monkeypatch.setattr(pt, "__file__", str(root / "programs" / "tests" / "_plugin_tree.py"))

    corpus = tmp_path / "corpus"
    (corpus / "ic" / "demo" / "v1.0.0_sky130A").mkdir(parents=True)
    (corpus / "PUBLISHING.md").write_text("x")
    (corpus / "protocol_parity" / "ucie" / "phase1" / "input_doc").mkdir(parents=True)
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(corpus))

    # The RENAMED prefix, which is the half a plain root swap does not fix.
    bp = pt.repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")
    assert bp == corpus / "protocol_parity", bp
    # And a path the corpus does not carry still comes back non-existent, so
    # this cannot turn an absence into a pass.
    missing = pt.repo_path_or_missing("benchmark-data", "no", "such", "tree")
    assert not missing.exists()


# --------------------------------------------------------------------------- #
# 3. Source-tree sanity: on the real (monorepo) tree the resolver agrees with
#    the conftest-derived plugin root and finds a known shipped resource.
# --------------------------------------------------------------------------- #
def test_resolver_agrees_with_real_plugin_root():
    pr = pt.plugin_root()
    # The manifest must exist under the resolved root in BOTH trees.
    assert (pr / ".claude-plugin" / "plugin.json").is_file()
    # A known shipped in-plugin resource resolves and exists.
    cls_ref = pt.plugin_path("agents", "defaults", "class_reference.yaml")
    assert cls_ref.is_file()


def test_not_shipped_reason_marker_is_stable():
    """The named reason is greppable + uniform across the swept families."""
    assert "flow #486" in pt.NOT_SHIPPED_REASON
    assert "installed cache" in pt.NOT_SHIPPED_REASON
