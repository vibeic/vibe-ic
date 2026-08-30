"""Tests for phase1_parity_source_tier_check.py.

The checker's whole job is to fail when the source-tier record rots, so most of
these are NEGATIVE tests: build a parity tree, break one thing, assert it is
caught. A checker that only passes on good input proves nothing.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from _hostpaths import repo_path_opt  # noqa: E402

PROG = Path(__file__).resolve().parents[1] / "phase1_parity_source_tier_check.py"
_spec = importlib.util.spec_from_file_location("p1_tier_check", PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _mk_protocol(root: Path, name: str, with_docs: bool = True) -> None:
    if with_docs:
        d = root / name / "input" / "docs"
        d.mkdir(parents=True)
        (d / f"{name}_spec.txt").write_text("x")
    else:
        (root / name / "phase1").mkdir(parents=True)


def _write_tiers(root: Path, protocols: dict, counts: dict | None = None,
                 total: int | None = None) -> Path:
    doc = {"schema": "phase1_parity_source_tier/v1", "protocols": protocols}
    if counts is not None:
        doc["counts"] = counts
    if total is not None:
        doc["protocols_total"] = total
    p = root / "source_tier.json"
    p.write_text(json.dumps(doc))
    return p


def _entry(tier: str, evidence: str = "PDF /Title metadata") -> dict:
    return {"tier": tier, "note": "n", "evidence": evidence}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Two-protocol parity tree: one specification, one encyclopedia."""
    root = tmp_path / "phase1_parity"
    root.mkdir()
    _mk_protocol(root, "alpha")
    _mk_protocol(root, "beta")
    _write_tiers(
        root,
        {"alpha": _entry("specification"), "beta": _entry("encyclopedia")},
        counts={"specification": 1, "encyclopedia": 1, "vendor_document": 0,
                "reconstructed_text": 0, "unknown": 0},
        total=2,
    )
    return root


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def test_discovers_protocol_dirs_by_artifacts_not_by_name(tmp_path: Path):
    root = tmp_path / "p"
    root.mkdir()
    _mk_protocol(root, "alpha")
    _mk_protocol(root, "beta", with_docs=False)  # phase1/ only, docs purged
    (root / "_scratch").mkdir()                  # helper dir -> not a protocol
    (root / "notes").mkdir()                     # no artifacts -> not a protocol
    (root / "RESULT_x.md").write_text("hi")
    assert mod.discover_protocols(root) == ["alpha", "beta"]


def test_protocol_counted_even_when_input_documents_were_purged(tmp_path: Path):
    """A licensing purge removes input/docs; the tier record must still apply."""
    root = tmp_path / "p"
    root.mkdir()
    _mk_protocol(root, "alpha", with_docs=False)
    _write_tiers(root, {"alpha": _entry("encyclopedia")})
    rep = mod.check(root, root / "source_tier.json")
    assert rep["ok"] is True
    assert rep["counts"]["encyclopedia"] == 1


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------

def test_clean_tree_passes(tree: Path):
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is True
    assert rep["violations"] == []
    assert rep["protocols_total"] == 2


def test_untiered_protocol_is_caught(tree: Path):
    _mk_protocol(tree, "gamma")  # added to the tree, absent from the tier file
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is False
    assert rep["untiered"] == ["gamma"]
    assert any("gamma" in v and "no source-tier entry" in v for v in rep["violations"])


def test_orphaned_tier_entry_is_caught(tree: Path):
    data = json.loads((tree / "source_tier.json").read_text())
    data["protocols"]["deleted_proto"] = _entry("specification")
    (tree / "source_tier.json").write_text(json.dumps(data))
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is False
    assert rep["orphaned"] == ["deleted_proto"]


def test_unrecognised_tier_value_is_caught(tmp_path: Path):
    root = tmp_path / "p"
    root.mkdir()
    _mk_protocol(root, "alpha")
    _write_tiers(root, {"alpha": _entry("real_spec_probably")})
    rep = mod.check(root, root / "source_tier.json")
    assert rep["ok"] is False
    assert any("unknown tier value" in v for v in rep["violations"])


def test_tier_without_evidence_is_caught(tmp_path: Path):
    """A tier with no evidence is a guess; guesses are what this file exists to stop."""
    root = tmp_path / "p"
    root.mkdir()
    _mk_protocol(root, "alpha")
    _write_tiers(root, {"alpha": _entry("specification", evidence="  ")})
    rep = mod.check(root, root / "source_tier.json")
    assert rep["ok"] is False
    assert any("no evidence string" in v for v in rep["violations"])


def test_unknown_tier_is_allowed_but_listed(tmp_path: Path):
    """`unknown` is honest and must NOT fail the checker — but it must be visible."""
    root = tmp_path / "p"
    root.mkdir()
    _mk_protocol(root, "alpha")
    _write_tiers(root, {"alpha": _entry("unknown", evidence="no surviving artifact")})
    rep = mod.check(root, root / "source_tier.json")
    assert rep["ok"] is True
    assert rep["unknown_list"] == ["alpha"]


def test_self_inconsistent_counts_block_is_caught(tree: Path):
    data = json.loads((tree / "source_tier.json").read_text())
    data["counts"]["specification"] = 99
    (tree / "source_tier.json").write_text(json.dumps(data))
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is False
    assert any("counts.specification=99" in v for v in rep["violations"])


def test_wrong_protocols_total_is_caught(tree: Path):
    data = json.loads((tree / "source_tier.json").read_text())
    data["protocols_total"] = 87
    (tree / "source_tier.json").write_text(json.dumps(data))
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is False
    assert any("protocols_total=87" in v for v in rep["violations"])


def test_missing_tier_file_reports_cleanly(tmp_path: Path):
    root = tmp_path / "p"
    root.mkdir()
    _mk_protocol(root, "alpha")
    rep = mod.check(root, root / "source_tier.json")
    assert rep["ok"] is False
    assert any("tier file missing" in v for v in rep["violations"])


# --------------------------------------------------------------------------
# publication — the RESULT markdown must not drift from the data
# --------------------------------------------------------------------------

def test_markdown_without_marker_is_ignored(tree: Path):
    (tree / "RESULT_other.md").write_text("# Other\nspecification: 999\n")
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is True
    assert rep["result_md_checked"] == []


def test_matching_markdown_counts_pass(tree: Path):
    (tree / "RESULT_sweep.md").write_text(
        "# Sweep\n\n<!-- source-tier-counts -->\n"
        "- **specification** — 1\n- **encyclopedia** — 1\n"
        "- **vendor_document** — 0\n- **reconstructed_text** — 0\n- **unknown** — 0\n"
    )
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is True
    assert rep["result_md_checked"] == ["RESULT_sweep.md"]


def test_drifted_markdown_count_is_caught(tree: Path):
    """The core rot case: someone edits the prose, the data stays put."""
    (tree / "RESULT_sweep.md").write_text(
        "# Sweep\n\n<!-- source-tier-counts -->\n"
        "- **specification** — 2\n- **encyclopedia** — 1\n"
    )
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is False
    assert any("publishes specification=2 but the data says 1" in v
               for v in rep["violations"])


def test_markdown_omitting_a_populated_tier_is_caught(tree: Path):
    """Publishing only the flattering tiers is exactly the failure being prevented."""
    (tree / "RESULT_sweep.md").write_text(
        "# Sweep\n\n<!-- source-tier-counts -->\n- **specification** — 1\n"
    )
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is False
    assert any("omits 'encyclopedia'" in v for v in rep["violations"])


def test_counts_section_ends_at_next_heading(tree: Path):
    """Numbers after the section must not be scraped as tier counts."""
    (tree / "RESULT_sweep.md").write_text(
        "# Sweep\n\n<!-- source-tier-counts -->\n"
        "- **specification** — 1\n- **encyclopedia** — 1\n"
        "- **vendor_document** — 0\n- **reconstructed_text** — 0\n- **unknown** — 0\n"
        "\n## Later section\nspecification: 42\n"
    )
    rep = mod.check(tree, tree / "source_tier.json")
    assert rep["ok"] is True


@pytest.mark.parametrize("line", [
    "- **specification** — 1",
    "specification: 1",
    "`specification`: **1**",
    "1 specification",
])
def test_count_shapes_are_recognised(line: str):
    md = f"<!-- source-tier-counts -->\n{line}\n"
    assert mod.published_counts(md).get("specification") == 1


def test_published_counts_empty_without_marker():
    assert mod.published_counts("specification: 5\n") == {}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_exit_codes_and_json_report(tree: Path, tmp_path: Path, capsys):
    out = tmp_path / "rep.json"
    assert mod.main([str(tree), "--json", str(out)]) == 0
    assert json.loads(out.read_text())["counts"]["specification"] == 1
    assert "PASS" in capsys.readouterr().out

    _mk_protocol(tree, "gamma")
    assert mod.main([str(tree)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_bad_root_returns_2(tmp_path: Path):
    assert mod.main([str(tmp_path / "nope")]) == 2


# --------------------------------------------------------------------------
# rc 2 IS A DECLINE, AND IT MUST NOT READ AS A FINDING.
#
# MEASURED on the v1.13.3 landing sweep: the row this gate occupies printed
#
#     ERROR: not a directory: protocol_parity
#
# `ERROR` is also what the program's PARSE branch prints, and that one IS a
# defect in the subject; `protocol_parity` is the raw argv, so the refusal named an
# argument rather than a place. A reader could tell neither apart. These two
# tests are the control on both halves -- they hold on any host because the
# subject is a tmp_path, and they fail on the pre-fix message.
# --------------------------------------------------------------------------
def test_absent_root_declines_without_claiming_anything_about_a_record(
        tmp_path: Path, capsys):
    missing = tmp_path / "protocol_parity"
    assert mod.main([str(missing)]) == 2
    err = capsys.readouterr().err
    assert "PARITY_ROOT_ABSENT" in err, err
    # THE LOCUS: the resolved absolute path, not the argument as typed.
    assert str(missing.resolve()) in err, err
    # It must not read as a verdict about the record, in either direction.
    assert "NOTHING WAS OPENED" in err, err
    assert "PASS" not in err and "FAIL" not in err, err


def test_an_unreadable_record_still_says_ERROR_and_names_the_file(
        tmp_path: Path, capsys):
    """The OTHER rc 2. A record WAS opened, so this one is a defect in the
    subject and must NOT be reworded into the decline above."""
    _mk_protocol(tmp_path, "alpha")
    tier = tmp_path / "source_tier.json"
    tier.write_text("{not json")
    assert mod.main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("ERROR: reading "), err
    assert str(tier) in err, err
    assert "PARITY_ROOT_ABSENT" not in err, err


# --------------------------------------------------------------------------
# the real corpus
# --------------------------------------------------------------------------

REAL = repo_path_opt("benchmark-data/evaluation/phase1_parity")


@pytest.mark.skipif(not (REAL / "source_tier.json").is_file(),
                    reason="phase1_parity corpus not present")
def test_real_phase1_parity_corpus_is_fully_tiered_and_published():
    rep = mod.check(REAL, REAL / "source_tier.json")
    assert rep["violations"] == []
    assert rep["protocols_total"] == 87
    assert "RESULT_sweep_v1_2_34.md" in rep["result_md_checked"]
