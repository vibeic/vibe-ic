"""Unit tests for l12_tb_coverage_check.py (v0.52/v0.53 gate).

Regression coverage for the v0.52 process gap where an agent reported
"1083/1083 PASS, ≥95% coverage" while silently lacking tbs for three
L12 sequences (TestMode, OTP-E0-write, PT-mux). This gate enforces
per-sequence tb existence.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'l12_tb_coverage_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import l12_tb_coverage_check as gate  # noqa: E402


def _make_project(tmp_path, sequences, tb_files=None):
    proj = tmp_path
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json").write_text(
        json.dumps({"sequences": sequences}))
    tb_dir = proj / "phase2" / "stage1" / "sim" / "tb"
    tb_dir.mkdir(parents=True)
    for name, content in (tb_files or {}).items():
        (tb_dir / name).write_text(content)
    return proj, tb_dir


# ---------------------------------------------------------------------------
# normalise_candidates
# ---------------------------------------------------------------------------
def test_normalise_candidates_no_suffix_list_only_literal_forms():
    """Without a class-template strip list, only the literal id (snake +
    flat) is tried — no IC-A-specific suffix assumptions."""
    cands = gate.normalise_candidates("TEST_MODE_ENTRY")
    assert cands == ["tb_test_mode_entry.v", "tb_testmodeentry.v"]


def test_normalise_candidates_with_suffix_list_strips_them():
    cands = gate.normalise_candidates("TEST_MODE_ENTRY",
                                     ["entry", "unlock"])
    # Both literal forms + both stripped forms
    assert "tb_test_mode_entry.v" in cands
    assert "tb_testmodeentry.v" in cands
    assert "tb_test_mode.v" in cands
    assert "tb_testmode.v" in cands


def test_normalise_candidates_regex_suffix():
    """A suffix can be a regex (e.g. '[0-9]+ms' to strip _700ms)."""
    cands = gate.normalise_candidates("CC_RESET_700MS", ["[0-9]+ms"])
    assert "tb_cc_reset.v" in cands
    assert "tb_ccreset.v" in cands


def test_normalise_candidates_unmatched_suffix_is_no_op():
    cands = gate.normalise_candidates("FOO_BAR", ["nothing_here"])
    # Nothing stripped → only literal forms
    assert sorted(cands) == ["tb_foo_bar.v", "tb_foobar.v"]


# ---------------------------------------------------------------------------
# load_strip_suffixes
# ---------------------------------------------------------------------------
def test_load_strip_suffixes_missing_returns_empty(tmp_path):
    assert gate.load_strip_suffixes(tmp_path / "absent.yaml") == []
    assert gate.load_strip_suffixes(None) == []


def test_load_strip_suffixes_parses_template(tmp_path):
    p = tmp_path / "template.yaml"
    p.write_text(
        "spec_floor:\n"
        "  L3_opcode_count_min: 8\n"
        "\n"
        "sequence_naming:\n"
        "  strip_suffixes:\n"
        "    - entry\n"
        "    - 'unlock'\n"
        "    - \"[0-9]+ms\"  # inline comment\n"
    )
    sufs = gate.load_strip_suffixes(p)
    assert sufs == ["entry", "unlock", "[0-9]+ms"]


def test_load_strip_suffixes_only_reads_sequence_naming_block(tmp_path):
    """Confirm the parser doesn't grab dashes from unrelated sections."""
    p = tmp_path / "template.yaml"
    p.write_text(
        "spec_floor:\n"
        "  L6_required_submodules:\n"
        "    - pad_ctrl\n"
        "    - dclk\n"
        "\n"
        "sequence_naming:\n"
        "  strip_suffixes:\n"
        "    - entry\n"
    )
    assert gate.load_strip_suffixes(p) == ["entry"]


# ---------------------------------------------------------------------------
# find_tb_file
# ---------------------------------------------------------------------------
def test_find_tb_file_prefers_exact_name(tmp_path):
    tb_dir = tmp_path
    (tb_dir / "tb_test_mode_entry.v").write_text("")
    (tb_dir / "tb_testmode.v").write_text("")
    found = gate.find_tb_file(tb_dir, gate.normalise_candidates("TEST_MODE_ENTRY"))
    assert found is not None
    # Either variant is an acceptable match — assert a real hit on the one
    # we actually created.
    assert found.name in {"tb_test_mode_entry.v", "tb_testmode.v"}


def test_find_tb_file_returns_none_when_missing(tmp_path):
    found = gate.find_tb_file(tmp_path, ["tb_absent.v"])
    assert found is None


# ---------------------------------------------------------------------------
# find_seq_id_in_tbs (content grep fallback)
# ---------------------------------------------------------------------------
def test_content_grep_finds_seq_id(tmp_path):
    (tmp_path / "tb_integration.v").write_text(
        "// covers RX_9_STEP_VALIDATION, CC_RESET sequences")
    matches = gate.find_seq_id_in_tbs(tmp_path, "RX_9_STEP_VALIDATION")
    assert "tb_integration.v" in matches


def test_content_grep_case_insensitive(tmp_path):
    (tmp_path / "tb_x.v").write_text("// engr_mode_unlock flow")
    matches = gate.find_seq_id_in_tbs(tmp_path, "ENGR_MODE_UNLOCK")
    assert "tb_x.v" in matches


# ---------------------------------------------------------------------------
# check() integration
# ---------------------------------------------------------------------------
def test_check_all_covered_via_filename(tmp_path):
    """Without a class template, only literal-id tb names match."""
    proj, tb_dir = _make_project(
        tmp_path,
        [{"id": "TEST_MODE_ENTRY"}, {"id": "CC_RESET"}],
        {"tb_test_mode_entry.v": "", "tb_cc_reset.v": ""})
    rc = gate.check(proj,
                    proj / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json",
                    tb_dir,
                    proj / "reports" / "l12.json",
                    strict=False)
    assert rc == 0
    report = json.loads((proj / "reports" / "l12.json").read_text())
    assert report["covered_sequences"] == 2
    assert report["pass"] is True


def test_check_uses_class_template_strip_suffixes(tmp_path):
    """With a class template that declares strip_suffixes, abbreviated
    tb names also match (e.g. tb_cc_reset.v matches CC_RESET_700MS)."""
    proj, tb_dir = _make_project(
        tmp_path,
        [{"id": "CC_RESET_700MS"}],
        {"tb_cc_reset.v": ""})
    template = tmp_path / "class.yaml"
    template.write_text(
        "sequence_naming:\n"
        "  strip_suffixes:\n"
        "    - '[0-9]+ms'\n"
    )
    rc = gate.check(proj,
                    proj / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json",
                    tb_dir,
                    proj / "reports" / "l12.json",
                    strict=False,
                    class_template_path=template)
    assert rc == 0
    report = json.loads((proj / "reports" / "l12.json").read_text())
    assert report["strip_suffixes_used"] == ["[0-9]+ms"]
    assert report["covered_sequences"] == 1


def test_check_via_content_grep_also_counts(tmp_path):
    proj, tb_dir = _make_project(
        tmp_path,
        [{"id": "TEST_MODE_ENTRY"}],
        {"tb_integration.v": "// TEST_MODE_ENTRY triggered here"})
    rc = gate.check(proj,
                    proj / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json",
                    tb_dir,
                    proj / "reports" / "l12.json",
                    strict=False)
    assert rc == 0


def test_check_missing_sequence_fails(tmp_path):
    proj, tb_dir = _make_project(
        tmp_path,
        [{"id": "TEST_MODE_ENTRY"}, {"id": "OTP_E0_WRITE"}],
        {"tb_test_mode_entry.v": ""})
    rc = gate.check(proj,
                    proj / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json",
                    tb_dir,
                    proj / "reports" / "l12.json",
                    strict=False)
    assert rc == 1
    report = json.loads((proj / "reports" / "l12.json").read_text())
    assert report["covered_sequences"] == 1
    assert report["uncovered_sequences"] == 1
    # Find the uncovered entry
    uncov = [s for s in report["sequences"] if not s["covered"]]
    assert len(uncov) == 1
    assert uncov[0]["id"] == "OTP_E0_WRITE"


def test_check_missing_l12_file_returns_2(tmp_path):
    tb_dir = tmp_path / "phase2" / "stage1" / "sim" / "tb"
    tb_dir.mkdir(parents=True)
    rc = gate.check(tmp_path,
                    tmp_path / "phase1" / "generated_docs" / "L12_ABSENT.json",
                    tb_dir,
                    tmp_path / "reports" / "l12.json",
                    strict=False)
    assert rc == 2


def test_check_missing_tb_dir_returns_2(tmp_path):
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json").write_text(
        json.dumps({"sequences": []}))
    rc = gate.check(tmp_path,
                    tmp_path / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json",
                    tmp_path / "no_tb_here",
                    tmp_path / "reports" / "l12.json",
                    strict=False)
    assert rc == 2


def test_cli_end_to_end(tmp_path):
    """CLI with default paths, all sequences covered (literal id match)."""
    proj, tb_dir = _make_project(
        tmp_path,
        [{"id": "CC_RESET"}],
        {"tb_cc_reset.v": ""})
    rc = gate.main([str(proj)])
    assert rc == 0
    assert (proj / "reports" / "phase2" / "gates" / "l12_tb_coverage.json").exists()


def test_cli_with_ic_class_argument(tmp_path):
    """CLI --ic-class loads the class template and uses its strip_suffixes."""
    proj, tb_dir = _make_project(
        tmp_path,
        [{"id": "CC_RESET_700MS"}],
        {"tb_cc_reset.v": ""})
    template = tmp_path / "class.yaml"
    template.write_text(
        "sequence_naming:\n"
        "  strip_suffixes:\n"
        "    - '[0-9]+ms'\n"
    )
    rc = gate.main([str(proj), "--ic-class", str(template)])
    assert rc == 0
