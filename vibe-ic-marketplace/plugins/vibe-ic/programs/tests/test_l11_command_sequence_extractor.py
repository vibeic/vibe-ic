#!/usr/bin/env python3
"""v0.1.83 — L11 harvests behavioral_sequences from a register-command table
in the input docs (OTP-less register-command IC, e.g. a hash core). Keyed on
operation+how/method column semantics; chip-AGNOSTIC; input-docs only."""
from __future__ import annotations
import sys
from pathlib import Path
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import phase1_doc_one_shot_runner as P  # noqa: E402

_CMD_ZH = """## 命令
| 操作 | 方式 | 描述 |
|---|---|---|
| INIT new hash | 寫 ADDR_CTRL bit0=1 | 開始新 hash |
| NEXT continue | 寫 ADDR_CTRL bit1=1 | 繼續下一個 block |
| Read status | 讀 ADDR_STATUS | bit0=READY |
| Read digest | 讀 ADDR_DIGEST0..7 | 256-bit digest |
"""

_CMD_EN = """## Commands
| Operation | Method | Effect |
|---|---|---|
| start | write CTRL bit0 | begin compute |
| poll | read STATUS | ready flag |
| fetch | read RESULT | 256-bit out |
"""

_NOT_CMD = """## Config
| 欄位 | 必填 | 範例 |
|---|---|---|
| top_module | yes | foo |
| reset | yes | active_low |
"""


def test_zh_command_table():
    seqs = P._harvest_command_sequences_from_input_tables({"L4.md": _CMD_ZH})
    assert len(seqs) == 4
    assert seqs[0]["name"] == "init_new_hash"
    assert seqs[0]["kind"] == "register_command"
    assert "ADDR_CTRL" in seqs[0]["trigger"]


def test_en_command_table():
    seqs = P._harvest_command_sequences_from_input_tables({"L4.md": _CMD_EN})
    assert len(seqs) == 3
    assert seqs[0]["name"] == "start"


def test_config_table_not_a_command_table():
    # 欄位 (field) is not an operation column → must not harvest
    assert P._harvest_command_sequences_from_input_tables({"L5.md": _NOT_CMD}) == []


def test_no_table():
    assert P._harvest_command_sequences_from_input_tables({"x.md": "prose"}) == []


def test_dedup():
    dup = ("| 操作 | 方式 |\n|---|---|\n"
           "| go | a |\n| go | b |\n| stop | c |\n")
    seqs = P._harvest_command_sequences_from_input_tables({"L4.md": dup})
    names = [s["name"] for s in seqs]
    assert names == ["go", "stop"]  # second 'go' deduped
