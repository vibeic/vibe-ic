"""Phase-1 must never ingest its OWN documentation as the design's specification.

MEASURED DEFECT these tests pin (see programs/_input_corpus_scope.py)
--------------------------------------------------------------------
The Phase-1 raw-corpus ingester's bounded ``rglob("README*")`` fallback
excluded the runner's own OUTPUT (``phase1/``, ``phase2/``, ``reports/``) but
not the runner's own SOURCE. With the plugin checked out inside the run root,
a run whose entire real input was ONE natural-language request ingested TEN
documents — nine of them plugin READMEs, 97.2 % of the corpus by bytes. L1 then
described the tool, and ``ic_class`` was decided from the tool's text: the
crypto detector matched the literal ``SHA`` in the plugin's artifact-attestation
section, yielding ``crypto_accelerator``, whose registry declares
``rtl_gen=null`` — so RTL was WAIVED and Phase-2 FAILed on ``rtl/ missing``.

NEGATIVE CONTROL (flow-change-acceptance §1)
-------------------------------------------
``test_ingester_excludes_tooling_readme`` is the load-bearing control: it FAILS
against the pre-fix ingester (the tooling README IS ingested) and PASSES after.
It is paired with ``test_ingester_still_ingests_genuine_subfolder_readme``,
which proves the exclusion is narrow — the fallback's legitimate purpose
(sub-folder READMEs of a real HDL repo) still works. Neither is presented as a
standalone control.

chip-AGNOSTIC (§4): every fixture is synthesized neutral data — no design, PDK,
vendor, cell or pin literal. ``test_real_plugin_checkout_is_a_tooling_root``
is additionally driven by a REAL checked-in artefact via ``_hostpaths``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import _input_corpus_scope as ics  # noqa: E402
from _hostpaths import repo_path  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders — synthesized neutral data only
# ---------------------------------------------------------------------------

def _make_plugin_checkout(root: Path, name: str, text: str) -> Path:
    """A tooling checkout identified by its plugin MANIFEST, at any name."""
    d = root / name
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "some-tool", "version": "0.0.0"}),
        encoding="utf-8")
    (d / "README.md").write_text(text, encoding="utf-8")
    return d


def _make_triple_checkout(root: Path, name: str, text: str) -> Path:
    """A tooling checkout identified by the programs/flow/skills triple."""
    d = root / name
    for sub in ("programs", "flow", "skills"):
        (d / sub).mkdir(parents=True)
    (d / "README.md").write_text(text, encoding="utf-8")
    return d


def _make_design_project(root: Path) -> Path:
    """A neutral design project: one request doc, plus HDL-ish sub-folders."""
    (root / "input" / "docs").mkdir(parents=True)
    (root / "input" / "docs" / "00_request.md").write_text(
        "# Request\n\nA block that adds two numbers and reports when done.\n",
        encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------

def test_tooling_root_detected_by_plugin_manifest(tmp_path):
    """Detection is by STRUCTURE — the directory name is arbitrary."""
    _make_plugin_checkout(tmp_path, "anything_at_all", "docs")
    roots = ics.find_tooling_roots(tmp_path)
    assert [r["path"] for r in roots] == ["anything_at_all"]
    assert roots[0]["marker"] == "plugin_manifest"


def test_tooling_root_detected_by_structural_triple(tmp_path):
    _make_triple_checkout(tmp_path, "vendored_copy", "docs")
    roots = ics.find_tooling_roots(tmp_path)
    assert [r["path"] for r in roots] == ["vendored_copy"]
    assert roots[0]["marker"] == "program_flow_skill"


def test_two_of_three_triple_dirs_is_not_tooling(tmp_path):
    """ALL three are required — any two occur innocently in a design repo."""
    d = tmp_path / "maybe"
    for sub in ("programs", "flow"):
        (d / sub).mkdir(parents=True)
    assert ics.is_tooling_dir(d) is None
    assert ics.find_tooling_roots(tmp_path) == []


def test_design_repo_is_never_flagged(tmp_path):
    """FALSE-POSITIVE control (§2): an ordinary HDL repo has no tooling root."""
    _make_design_project(tmp_path)
    for sub in ("rtl", "sim", "docs", "constraints", "boards"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        (tmp_path / sub / "README.md").write_text("notes\n", encoding="utf-8")
    assert ics.find_tooling_roots(tmp_path) == []


def test_project_root_itself_is_never_a_tooling_root(tmp_path):
    """Running the flow from INSIDE the plugin must not exclude everything."""
    (tmp_path / ".claude-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}",
                                                             encoding="utf-8")
    assert ics.find_tooling_roots(tmp_path) == []


def test_path_matching_is_by_segment_not_substring(tmp_path):
    """`plugin_work` must not match `my_plugin_workbench`."""
    roots = [{"path": "plugin_work", "marker": "plugin_manifest"}]
    assert ics.path_is_tooling("plugin_work/README.md", roots) is not None
    assert ics.path_is_tooling("a/b/plugin_work/c/README.md", roots) is not None
    assert ics.path_is_tooling("my_plugin_workbench/README.md", roots) is None
    assert ics.path_is_tooling("docs/plugin_workflow.md", roots) is None


def test_path_matching_tolerates_ingester_key_prefix():
    """L-doc provenance carries an ingester key prefix; segments still match."""
    roots = [{"path": "plugin_work", "marker": "plugin_manifest"}]
    prov = "input/docs/__chip_root_docs__/plugin_work/mcp-eda/README.md"
    assert ics.path_is_tooling(prov, roots) is not None


def test_real_plugin_checkout_is_a_tooling_root():
    """REAL in-repo artefact (§4 / #400): this very plugin checkout carries the
    manifest, so the rule identifies it without any hand-authored fixture."""
    plugin_dir = repo_path("vibe-ic-marketplace", "plugins", "vibe-ic")
    if not plugin_dir.is_dir():
        pytest.skip(f"plugin checkout not present at {plugin_dir}")
    assert ics.is_tooling_dir(plugin_dir) == "plugin_manifest"


# ---------------------------------------------------------------------------
# Loud degradation (§6)
# ---------------------------------------------------------------------------

def test_scope_record_distinguishes_ran_empty_from_not_run(tmp_path):
    """`RAN` + empty is a positive statement; it must not read as `NOT_RUN`."""
    ran = ics.scope_record(tmp_path, [], [], status="RAN")
    not_run = ics.scope_record(tmp_path, [], [], status="NOT_RUN")
    assert ran["status"] == "RAN"
    assert not_run["status"] == "NOT_RUN"
    assert ran["excluded_roots"] == not_run["excluded_roots"] == []
    assert ran != not_run


def test_scope_record_names_every_excluded_file(tmp_path):
    roots = [{"path": "t", "marker": "plugin_manifest"}]
    rec = ics.scope_record(tmp_path, roots, ["t/README.md", "t/a/README.md"])
    assert rec["excluded_file_count"] == 2
    assert rec["excluded_files"] == ["t/README.md", "t/a/README.md"]
    assert rec["excluded_roots"] == roots


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL — the ingester end-to-end (§1)
# ---------------------------------------------------------------------------

def _run_ingester(project: Path):
    import phase1_doc_one_shot_runner as p1
    return p1.extract_text_pipeline(project, force=True)


_TOOLING_TOKEN = "ZZQTOOLINGDOCTOKEN"
_DESIGN_TOKEN = "ZZQDESIGNDOCTOKEN"


def test_ingester_excludes_tooling_readme(tmp_path):
    """FAILS pre-fix, PASSES post-fix — the load-bearing negative control.

    Pre-fix the rglob fallback ingests the tooling checkout's README, so
    ``_TOOLING_TOKEN`` appears in the corpus. Post-fix it must not.
    """
    _make_design_project(tmp_path)
    _make_plugin_checkout(tmp_path, "some_tool_checkout",
                          f"# Tool manual\n\n{_TOOLING_TOKEN}\n")
    out = _run_ingester(tmp_path)
    corpus = "\n".join(out.values())

    assert _TOOLING_TOKEN not in corpus, (
        "the ingester read the TOOL's own documentation as design input; "
        f"keys={sorted(out)}")


def test_ingester_still_ingests_genuine_subfolder_readme(tmp_path):
    """Paired sibling: the fallback's legitimate purpose still works.

    Without this, the negative control above would also pass if the fallback
    were simply deleted — which would be a regression, not a fix.
    """
    _make_design_project(tmp_path)
    (tmp_path / "rtl").mkdir(parents=True, exist_ok=True)
    (tmp_path / "rtl" / "README.md").write_text(
        f"# RTL notes\n\n{_DESIGN_TOKEN}\n", encoding="utf-8")
    _make_plugin_checkout(tmp_path, "some_tool_checkout",
                          f"# Tool manual\n\n{_TOOLING_TOKEN}\n")
    out = _run_ingester(tmp_path)
    corpus = "\n".join(out.values())

    assert _DESIGN_TOKEN in corpus, (
        "the genuine sub-folder README was dropped — the exclusion is too "
        f"broad; keys={sorted(out)}")
    assert _TOOLING_TOKEN not in corpus


def test_ingester_writes_the_scope_record(tmp_path):
    """§6: the exclusion is recorded, never silent."""
    _make_design_project(tmp_path)
    _make_plugin_checkout(tmp_path, "some_tool_checkout",
                          f"# Tool manual\n\n{_TOOLING_TOKEN}\n")
    _run_ingester(tmp_path)
    rec_p = tmp_path / "phase1" / "input_corpus_scope.json"
    assert rec_p.is_file(), "no input_corpus_scope.json written"
    rec = json.loads(rec_p.read_text(encoding="utf-8"))
    assert rec["status"] == "RAN"
    assert [r["path"] for r in rec["excluded_roots"]] == ["some_tool_checkout"]
    assert rec["excluded_file_count"] >= 1


# ---------------------------------------------------------------------------
# The ADVISORY purity gate
# ---------------------------------------------------------------------------

def _write_l_docs(project: Path, evidence_path: str) -> None:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "unit_under_test",
        "pin_table": [{"name": "a", "evidence": evidence_path}],
    }), encoding="utf-8")
    (d / "L2_FRS.json").write_text(json.dumps({"requirements": []}),
                                   encoding="utf-8")


def test_purity_gate_fires_on_tooling_provenance(tmp_path):
    import phase1_input_corpus_purity_check as gate
    _make_design_project(tmp_path)
    _make_plugin_checkout(tmp_path, "some_tool_checkout", "docs")
    _write_l_docs(tmp_path, "input/docs/some_tool_checkout/README.md")
    rec = gate.check(tmp_path)
    assert rec["verdict"] == "CONTAMINATED"
    names = {f["name"] for f in rec["findings"]}
    assert "TOOLING_PROVENANCE_IN_L_DOCS" in names
    assert rec["enforcement"] == "ADVISORY"


def test_purity_gate_clears_when_provenance_is_the_design(tmp_path):
    """Paired with the `fires` test above — never a standalone control."""
    import phase1_input_corpus_purity_check as gate
    _make_design_project(tmp_path)
    _make_plugin_checkout(tmp_path, "some_tool_checkout", "docs")
    _write_l_docs(tmp_path, "input/docs/00_request.md")
    rec = gate.check(tmp_path)
    assert rec["verdict"] == "PASS", rec["findings"]


def test_purity_gate_skips_when_no_tooling_subtree(tmp_path):
    """Honest SKIP, not a false PASS, when the route does not exist."""
    import phase1_input_corpus_purity_check as gate
    _make_design_project(tmp_path)
    _write_l_docs(tmp_path, "input/docs/00_request.md")
    rec = gate.check(tmp_path)
    assert rec["verdict"] == "SKIP"
    assert "reason" in rec


def test_purity_gate_declares_its_enforcement_level(tmp_path):
    """§5: BLOCKING vs ADVISORY is declared in the gate, not left to default."""
    import phase1_input_corpus_purity_check as gate
    assert "ADVISORY" in (gate.__doc__ or "")
    _make_design_project(tmp_path)
    assert gate.check(tmp_path)["enforcement"] == "ADVISORY"
