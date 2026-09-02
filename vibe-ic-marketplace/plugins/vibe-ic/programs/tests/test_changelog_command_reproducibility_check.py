"""Tests for changelog_command_reproducibility_check.py (v1.6.43)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "programs"))

import changelog_command_reproducibility_check as g  # noqa: E402


def _make_plugin(tmp_path: Path, changelog_text: str) -> Path:
    p = tmp_path / "vibe-ic"
    (p / "programs").mkdir(parents=True)
    (p / ".claude-plugin").mkdir(parents=True)
    (p.parent / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (p / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": "1.6.43"}))
    (p.parent / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "test-marketplace"}))
    (p / "CHANGELOG.md").write_text(changelog_text)
    return p


def test_pass_when_target_exists(tmp_path):
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ bash tools/ci/run.sh\n```\n")
    (p / "tools" / "ci").mkdir(parents=True)
    (p / "tools" / "ci" / "run.sh").write_text("#!/bin/bash\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_fail_when_bash_target_missing(tmp_path):
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ bash tools/ci/missing.sh\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "MISSING_SCRIPT"
    assert "missing.sh" in findings[0].command


def test_fail_when_python_script_missing(tmp_path):
    p = _make_plugin(
        tmp_path,
        "## v1\n\n```\n$ python3 programs/ghost.py .\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "MISSING_SCRIPT"


def test_pass_when_python_script_exists(tmp_path):
    p = _make_plugin(
        tmp_path,
        "## v1\n\n```\n$ python3 programs/real.py .\n```\n")
    (p / "programs" / "real.py").write_text("print('ok')\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_skip_unaudited_verbs(tmp_path):
    """`git status` / `docker ps` etc. are out of scope and don't fail."""
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ git status\n$ docker ps\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_python_module_invocation_skipped(tmp_path):
    """`python3 -m pytest` is a module run, not a path — out of scope."""
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ python3 -m pytest tests/\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_vacuous_pass_when_no_changelog(tmp_path):
    p = tmp_path / "empty"
    p.mkdir()
    verdict, findings = g.audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []

# --- the exit code is what the flow reads, and no test drove main()

def test_main_exits_non_zero_on_a_finding(tmp_path, monkeypatch):
    """`gate_cli_mutation_probe` reported this gate SILENT: neutering `main()`
    reddened nothing in its own test file.

    Every test above drives `audit()` and asserts the VERDICT it returns. The
    flow reads the EXIT CODE, and nothing exercised the mapping between them —
    the gate could have started answering 0 to every finding with the suite
    still green.
    """
    import changelog_command_reproducibility_check as M
    # Empty findings with a FAIL verdict: the verdict is what main()
    # maps to the exit code, and constructing this module's own finding
    # dataclass by guessing its fields tests my guess, not the gate.
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("FAIL", []))
    assert M.main([str(tmp_path)]) == 1


def test_main_exits_zero_when_clean(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails."""
    import changelog_command_reproducibility_check as M
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import changelog_command_reproducibility_check as M
    assert M.main([str(tmp_path / "does_not_exist")]) == 2


# --- the document's own directory is a plausible CWD (vibe-ic#2019) ---------


def _make_repo(tmp_path: Path) -> Path:
    """A plugin at its REAL depth under an isolated repo root.

    `_make_plugin` above puts the plugin directly under `tmp_path`, so the
    `plugin_root.parent.parent.parent` the gate computes as the repo root lands
    on pytest's SHARED tmp base — two tests writing `docs/` there would see
    each other's files, and a negative control that passes because a sibling
    test left a script behind proves nothing. Every row below needs a `docs/`
    tree, so it needs a repo root of its own."""
    repo = tmp_path / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs").mkdir(parents=True)
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin.parent.parent / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": "1.15.81"}))
    (plugin.parent.parent / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "test-marketplace"}))
    (plugin / "CHANGELOG.md").write_text("## v1\n\nnothing quoted here.\n")
    return plugin


def _docs_md(plugin_root: Path, rel: str, text: str) -> Path:
    """Write `<repo root>/docs/<rel>`, which `_audit_files` sweeps."""
    p = plugin_root.parent.parent.parent / "docs" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


_QUOTE = "```\n$ python3 tools/drv_records.py --selftest\n```\n"


def test_a_doc_relative_target_beside_the_document_resolves(tmp_path):
    """A transcript run from INSIDE the directory the document lives in.

    MEASURED, and it is why this pair exists: v1.15.79 moved the four PPA
    campaign trees under `docs/campaigns/`, which put every campaign RESULT.md
    into the `docs/**/*.md` sweep for the first time. One of them quotes
    `$ python3 tools/drv_records.py --selftest`, an honest transcript of a
    command run from inside that campaign directory where the script sits
    exactly where the line says. Against the six fixed roots it read
    MISSING_SCRIPT — a demand to rewrite a line the author did not type."""
    plugin = _make_repo(tmp_path)
    doc = _docs_md(plugin, "campaigns/camp/RESULT.md", _QUOTE)
    (doc.parent / "tools").mkdir(parents=True)
    (doc.parent / "tools" / "drv_records.py").write_text("print('ok')\n")
    verdict, findings = g.audit(plugin)
    assert verdict == "PASS", findings


def test_a_target_at_no_root_at_all_is_still_missing(tmp_path):
    """The other direction, or the row above is met by a resolver that
    resolves everything.

    Byte-identical to it except that the script exists NOWHERE — not beside
    the document, not at either root. This is the shape of the SECOND finding
    the same move produced (a repo-root-relative path that was true before the
    tree moved and is true from nowhere after it), and it must keep failing or
    the new CWD is a widening rather than a repair."""
    plugin = _make_repo(tmp_path)
    _docs_md(plugin, "campaigns/camp/RESULT.md", _QUOTE)
    verdict, findings = g.audit(plugin)
    assert verdict == "FAIL"
    assert [f.rule for f in findings] == ["MISSING_SCRIPT"], findings


def test_a_sibling_documents_directory_does_not_resolve_it(tmp_path):
    """The CWD admitted is THIS document's directory, not any document's.

    Without this, "beside a document" would degenerate into "anywhere under
    docs/", and a citation runnable only from someone else's directory would
    pass while being unrunnable from its own."""
    plugin = _make_repo(tmp_path)
    other = _docs_md(plugin, "campaigns/other/NOTES.md", "no commands here.\n")
    (other.parent / "tools").mkdir(parents=True)
    (other.parent / "tools" / "drv_records.py").write_text("print('ok')\n")
    _docs_md(plugin, "campaigns/camp/RESULT.md", _QUOTE)
    verdict, findings = g.audit(plugin)
    assert verdict == "FAIL"
    assert [f.rule for f in findings] == ["MISSING_SCRIPT"], findings
