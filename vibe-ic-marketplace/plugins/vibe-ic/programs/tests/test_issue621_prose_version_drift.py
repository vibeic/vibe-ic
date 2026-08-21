"""#621 — the three READMEs advertised v1.4.x while the plugin shipped v1.9.36.

`marketplace_version_sync_check` guards every place the version is stated in
JSON, and it exists because an OUTER manifest "sat at 1.3.42 for six releases
while the maintained manifest advanced to 1.3.48". The same drift then happened
one file type over, unguarded and much further:

    README.md                       badge plugin-v1.5.12  |  Status: v1.4
    vibe-ic-marketplace/README.md   | Plugin version | 1.4.72 |
                                    ← the single plugin (v1.4.61)
    plugins/vibe-ic/README.md       plugin (**v1.4.61**)

Four different stale numbers, five minor versions behind, in the three documents
a reader meets first.

CORRECTING THE NUMBERS IS NOT THE FIX. They drifted because nothing compared
them; a hand edit resets the counter and leaves the next drift to be found by a
person again. This is the comparison, plus a `--fix` so the prose follows the
version bump instead of trailing it.

THE SOURCE OF TRUTH IS THE REPO'S OWN DECLARATION, not a glob. Measured on this
tree, `**/.claude-plugin/plugin.json` finds 79 files — the partner-plugin
skeleton (a legitimately different plugin at 0.1.0) and 39 stale agent worktrees
under `.claude/worktrees` carrying 1.6.84 through 1.7.99. "Which is the shipped
one?" cannot be answered by counting, and a majority vote among stale checkouts
is not an authority; the repo-root manifest's `plugins[].source` is.
"""
from __future__ import annotations

import importlib
import json
import pathlib

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]

P = importlib.import_module("plugin_version_prose_sync_check")


def _repo(tmp_path, version="1.9.37", *, source="plugins/vibe-ic"):
    (tmp_path / ".claude-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "vibe-ic", "source": f"./{source}"}]}))
    pj = tmp_path / source / ".claude-plugin"
    pj.mkdir(parents=True)
    (pj / "plugin.json").write_text(json.dumps({"version": version}))
    return tmp_path


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ── the source of truth ─────────────────────────────────────────────────────
def test_the_version_comes_from_the_repos_own_manifest(tmp_path):
    root = _repo(tmp_path, "2.0.1")
    v, note = P.shipped_version(root)
    assert v == "2.0.1", note


def test_an_unrelated_plugin_json_elsewhere_is_not_consulted(tmp_path):
    """LOAD-BEARING. The partner-plugin skeleton is a different plugin at
    0.1.0, and 39 stale agent worktrees carry old versions of THIS one. A glob
    would have to arbitrate between them; the manifest already has."""
    root = _repo(tmp_path, "2.0.1")
    other = root / "templates" / "skeleton" / ".claude-plugin"
    other.mkdir(parents=True)
    (other / "plugin.json").write_text(json.dumps({"version": "0.1.0"}))
    stale = root / ".claude" / "worktrees" / "agent-x" / "plugins" / "vibe-ic" \
        / ".claude-plugin"
    stale.mkdir(parents=True)
    (stale / "plugin.json").write_text(json.dumps({"version": "1.7.99"}))
    assert P.shipped_version(root)[0] == "2.0.1"


def test_a_manifest_that_declares_nothing_is_not_a_version(tmp_path):
    (tmp_path / ".claude-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": []}))
    v, note = P.shipped_version(tmp_path)
    assert v is None and "no plugins" in note


def test_two_declared_plugins_that_disagree_is_a_question_not_an_answer(tmp_path):
    root = _repo(tmp_path, "2.0.1")
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"plugins": [{"source": "./plugins/vibe-ic"}, {"source": "./other"}]}))
    o = root / "other" / ".claude-plugin"
    o.mkdir(parents=True)
    (o / "plugin.json").write_text(json.dumps({"version": "1.0.0"}))
    v, note = P.shipped_version(root)
    assert v is None and "disagree" in note


# ── the six claim forms, each taken from a real drift ───────────────────────
_DRIFTED = {
    "README.md": (
        "[![Plugin v1.5.12](https://img.shields.io/badge/plugin-v1.5.12-x.svg)]()\n"
        "[![MCP-EDA v1.0.0](https://img.shields.io/badge/mcp--eda-v1.0.0-x.svg)]()\n"
        "> **Status: v1.4 — mature.**\n"),
    "vibe-ic-marketplace/README.md": (
        "| Plugin version | **1.4.72** |\n"
        "    └── vibe-ic/     ← the single plugin (v1.4.61)\n"),
    "vibe-ic-marketplace/plugins/vibe-ic/README.md": (
        "# vibe-ic — AI-Native IC Design plugin (**v1.4.61**)\n"),
}


def _drifted_repo(tmp_path, version="1.9.37"):
    root = _repo(tmp_path, version)
    for rel, txt in _DRIFTED.items():
        _write(root, rel, txt)
    return root


def test_every_drifted_claim_is_found(tmp_path):
    """THE ISSUE, reproduced: six claims across three documents."""
    root = _drifted_repo(tmp_path)
    verdict, findings, stats = P.audit(root)
    assert verdict == "FINDINGS"
    assert stats["claims_compared"] == 6, stats
    assert len(findings) == 6, [f["detail"] for f in findings]
    assert {f["claim"] for f in findings} == {
        "shields badge", "badge link text", "version table row", "title",
        "tree diagram", "status line"}


def test_a_finding_names_the_file_the_line_and_both_versions(tmp_path):
    root = _drifted_repo(tmp_path)
    f = P.audit(root)[1][0]
    assert f["file"] and f["line"] > 0 and f["states"] and f["shipped"]


def test_the_status_line_is_compared_on_what_it_claims(tmp_path):
    """`Status: v1.9` asserts major.minor and no patch. Failing it for omitting
    a patch it never claimed would make the gate unsatisfiable."""
    root = _repo(tmp_path, "1.9.37")
    _write(root, "README.md", "> **Status: v1.9 — mature.**\n")
    assert P.audit(root)[0] == "PASS"


# ── what must NOT be a finding ──────────────────────────────────────────────
def test_another_products_version_is_left_alone(tmp_path):
    """These documents legitimately name the MCP-EDA badge, the EDA image tag,
    and historical releases. A gate that matched any version-shaped string
    would fail on all of them and be switched off."""
    root = _repo(tmp_path, "1.9.37")
    _write(root, "README.md",
           "[![MCP-EDA v1.0.0](https://img.shields.io/badge/mcp--eda-v1.0.0-x.svg)]()\n"
           "docker pull ghcr.io/vibeic/vibeic-eda:0.2.54\n"
           "Landed in v1.3.85 — APPROACH C.\n")
    verdict, findings, stats = P.audit(root)
    assert verdict == "PASS", findings
    assert stats["claims_compared"] == 0


def test_documents_that_state_no_version_are_a_disclosed_pass(tmp_path, capsys):
    """A PASS over zero comparisons must say so rather than read as agreement."""
    root = _repo(tmp_path, "1.9.37")
    _write(root, "README.md", "# vibe-ic\n\nNo version here.\n")
    rc = P.main([str(root)])
    assert rc == P.RC_OK
    assert "VACUOUS_PASS" in capsys.readouterr().out


def test_an_unknown_shipped_version_is_not_a_pass(tmp_path, capsys):
    _write(tmp_path, "README.md", "# x (**v1.0.0**)\n")
    assert P.main([str(tmp_path)]) == P.RC_CANNOT_CHECK


# ── --fix, so the prose follows the bump instead of trailing it ─────────────
def test_fix_rewrites_every_claim_and_nothing_else(tmp_path):
    root = _drifted_repo(tmp_path, "1.9.37")
    before = (root / "README.md").read_text()
    touched = P.fix(root, "1.9.37")
    assert set(touched) == set(_DRIFTED)
    assert P.audit(root)[0] == "PASS"
    after = (root / "README.md").read_text()
    assert "mcp--eda-v1.0.0" in after, "an unrelated badge was rewritten"
    assert before.count("\n") == after.count("\n"), "the file was restructured"


def test_fix_refuses_when_the_shipped_version_is_unknown(tmp_path, capsys):
    _write(tmp_path, "README.md", "# x (**v1.0.0**)\n")
    assert P.main([str(tmp_path), "--fix"]) == P.RC_CANNOT_CHECK
    assert "refusing to rewrite" in capsys.readouterr().err
    assert "(**v1.0.0**)" in (tmp_path / "README.md").read_text()


def test_fix_is_idempotent(tmp_path):
    root = _drifted_repo(tmp_path, "1.9.37")
    P.fix(root, "1.9.37")
    snapshot = {r: (root / r).read_text() for r in _DRIFTED}
    assert P.fix(root, "1.9.37") == {}
    assert {r: (root / r).read_text() for r in _DRIFTED} == snapshot


# ── the shipped tree ────────────────────────────────────────────────────────
def test_the_real_repo_agrees_with_its_own_plugin_json():
    """The ratchet. This is what #621 makes true and what keeps it true."""
    if not (_REPO / ".claude-plugin" / "marketplace.json").is_file():
        return
    verdict, findings, _stats = P.audit(_REPO)
    assert verdict == "PASS", [f["detail"] for f in findings]
