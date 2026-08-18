#!/usr/bin/env python3
"""v0.1.77 — L10 harvests typed test cases from input verification-plan tables.

Non-command-driven datapaths (hash, CPU SoC) have no L3 opcodes, so the old
opcode-only L10 yielded 0 test cases even when the input verification plan
carried an explicit test-vector table. The extractor is chip-AGNOSTIC: it keys
on bilingual column SEMANTICS (test/expected/input), never on chip literals,
and reads input docs only (no RTL oracle).
"""
from __future__ import annotations
import sys
from pathlib import Path
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import phase1_doc_one_shot_runner as P  # noqa: E402

_EN = """# Verification Plan
| Test | Input | Expected |
|---|---|---|
| empty hash | abc | ba7816bf |
| long message | 1M bytes | cdc76e5c |
| boundary 55B | 55 bytes | deadbeef |
| boundary 64B | 64 bytes | feedface |
| random equiv | 1000 msgs | 100% pass |
"""

_ZH = """# 驗證計畫
| 測試 | 輸入 | 預期 digest |
|---|---|---|
| 空字串 abc | 0x616263 | ba7816bf |
| 單一區塊 | 448-bit | 248d6a61 |
| 模式切換 | MODE=0 | 23097d22 |
"""

_CONFIG_NOISE = """# Config table (must NOT be harvested)
| 欄位 | 必填 | 範例 |
|---|---|---|
| top_module | yes | sha256 |
| reset_polarity | yes | active_low |
"""


def test_english_test_vector_table():
    cases = P._harvest_test_cases_from_input_tables({"L7.md": _EN})
    assert len(cases) == 5
    assert cases[0]["name"] == "empty_hash"
    assert cases[0]["expected"] == "ba7816bf"
    assert all(c["kind"] == "functional_vector" for c in cases)


def test_bilingual_zh_table():
    cases = P._harvest_test_cases_from_input_tables({"L7.md": _ZH})
    assert len(cases) == 3
    assert cases[0]["expected"] == "ba7816bf"


def test_config_table_not_harvested():
    # header 欄位/必填/範例 = field/required/example — not a test table
    cases = P._harvest_test_cases_from_input_tables({"L5.md": _CONFIG_NOISE})
    assert cases == []


def test_no_table_no_cases():
    assert P._harvest_test_cases_from_input_tables({"L1.md": "no tables here"}) == []


def test_dedup_and_cap():
    big = "| Test | Expected |\n|---|---|\n" + "\n".join(
        f"| case {i} | exp{i} |" for i in range(40))
    cases = P._harvest_test_cases_from_input_tables({"L7.md": big})
    assert len(cases) == 24  # capped
    names = [c["name"] for c in cases]
    assert len(names) == len(set(names))  # deduped


def test_chip_agnostic_no_literals_in_extractor_source():
    src = (PROG_DIR / "phase1_doc_one_shot_runner.py").read_text()
    # locate the harvester function body
    start = src.index("def _harvest_test_cases_from_input_tables")
    end = src.index("def gen_l10_test_cases", start)
    body = src[start:end]
    for lit in ("sha256", "serv", "subservient", "nist", "ee628"):
        assert lit not in body.lower(), f"chip literal {lit!r} leaked into extractor"
