"""v1.1.68 — structured_table_extractor (one extractor for the whole table tier)
+ the step-1 convergence machinery (log_disagreements + convergence_summary).

The generic table extractor classifies every pipe table by a header SIGNATURE to a
specific element_type (register/command/encoding/test-vector/...) or generic, so the
program baseline covers the table tier at once. The convergence machinery turns the
dual-pass ai_only finds into a data-driven new-extractor queue and a convergence
metric (the deterministic layer has converged for a type once it no longer appears
as ai_only).
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import structured_table_extractor as T   # noqa: E402
import spec_artifact_dual_pass as DP       # noqa: E402


def _types(text):
    return [t["element_type"] for t in T.extract_tables(text)]


def test_signature_classifies_register_map():
    t = ("| Register | Address | Access | Reset |\n| CTRL | 0x00 | R/W | 0x00 |\n"
         "| STAT | 0x04 | RO | 0x00 |\n")
    tabs = T.extract_tables(t)
    assert tabs and tabs[0]["element_type"] == "register_map"
    assert tabs[0]["row_count"] == 2
    assert tabs[0]["rows"][0]["Address"] == "0x00"


def test_signature_classifies_command_and_encoding_and_testvector():
    cmd = "| Opcode | Operation |\n| 0x1 | ADD |\n| 0x2 | SUB |\n"
    enc = "| Code | Meaning |\n| 00 | IDLE |\n| 01 | RUN |\n"
    tv = "| Input | Expected Output |\n| 3 | 9 |\n| 4 | 16 |\n"
    assert _types(cmd) == ["command_opcode_table"]
    assert _types(enc) == ["encoding_table"]
    assert _types(tv) == ["test_vector_table"]


def test_no_misfire_on_fsm_or_truth_table():
    fsm = "  state | next state in=0, next state in=1 | output\n  A | A, B | 0\n  B | C, B | 0\n"
    truth = "  x3 | x2 | x1 | f\n  0 | 0 | 0 | 1\n  0 | 0 | 1 | 0\n"
    # these are NOT one of the signature types -> generic (never a wrong-confident label)
    assert _types(fsm) == ["structured_table"]
    assert _types(truth) == ["structured_table"]


def test_ambiguous_header_stays_generic():
    # a header matching >1 signature must NOT be confidently labelled
    # matches command (command+operation) AND register (address+access) -> generic
    t = "| Command | Operation | Address | Access |\n| ADD | add | 0x0 | RW |\n"
    assert _types(t) == ["structured_table"]


def test_empty_when_no_table():
    assert T.extract_tables("just prose, no tables here at all.") == []


def test_table_tier_in_dual_pass_baseline_specific_only():
    doc = ("| Opcode | Operation |\n| 0x1 | ADD |\n| 0x2 | SUB |\n")
    base = DP.program_baseline(doc)
    assert any(e["element_type"] == "command_opcode_table" for e in base)
    # generic structured_table is NOT emitted into the baseline
    assert all(e["element_type"] != "structured_table" for e in base)


def test_convergence_machinery(tmp_path):
    # two reconcile reports: register_map missed twice, timing once
    reports = [
        {"agreement_rate": 0.5, "ai_only_new_extractor_candidates":
            [{"element_type": "register_map"}, {"element_type": "timing_constraints"}]},
        {"agreement_rate": 0.8, "ai_only_new_extractor_candidates":
            [{"element_type": "register_map"}]},
    ]
    summ = DP.convergence_summary(reports)
    assert summ["runs"] == 2 and not summ["converged"]
    ranked = dict(summ["program_blind_spots_ranked"])
    assert ranked["register_map"] == 2 and ranked["timing_constraints"] == 1
    # logging appends to the data-driven backlog
    bl = tmp_path / "backlog.jsonl"
    n = DP.log_disagreements(reports[0], str(bl), doc_id="d1")
    assert n == 2 and bl.exists() and len(bl.read_text().strip().splitlines()) == 2


def test_converged_flag_when_no_blind_spots():
    reports = [{"agreement_rate": 1.0, "ai_only_new_extractor_candidates": []}]
    assert DP.convergence_summary(reports)["converged"] is True
