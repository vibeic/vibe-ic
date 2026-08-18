"""Shared bilingual (CJK + English) documentation-table header lexicon.

Issue #500 (MEDIUM): the GFM / pipe-table header classifiers across the
sibling table families in ``phase1_doc_one_shot_runner.py`` (register
map, opcode/instruction, memory map, field / doc tables, parameter
tables, bullet ports) were ENGLISH-ONLY. The pin family already received
CJK + multi-word group vocabulary in #491 round-3
(``_V0_3_2_HEADER_*_TOKENS``); the siblings shared the same English-only
assumption and silently dropped CJK-headed tables.

This module is the ONE canonical source of column-role header vocabulary,
covering both English and Traditional/Simplified-Chinese documentation
words for each generic column ROLE:

    name / direction / width / description / address / access /
    default / opcode / value / register / parameter / type /
    field / range / units

Every per-family header token-set constant in the runner derives its
vocabulary from these role sets (``ROLE_TOKENS`` / the ``tokens_for``
helper), so a new CJK or English synonym added here propagates to every
classifier at once.

DOCTRINE — chip-AGNOSTIC: every entry is GENERIC documentation vocabulary
(column-heading words that appear across vendor datasheets, register
maps, ISA tables). NO per-chip / per-vendor / per-SKU string is permitted
here; ``programs/source_chip_agnostic_check.py`` governs.

REUSE — the pin family's #491 round-3 CJK tokens are folded into the
``NAME`` / ``DIRECTION`` / ``WIDTH`` / ``DESCRIPTION`` role sets below
(not duplicated): ``_V0_3_2_HEADER_*_TOKENS`` in the runner now derive
from this lexicon, preserving the exact #491 behaviour.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, Set

# ---------------------------------------------------------------------------
# Canonical per-role header vocabulary. Keys are the canonical column ROLE
# names; values are the full bilingual token set for that role. All tokens
# are lower-cased (callers lower-case the cell before lookup) and stripped
# of emphasis / backticks by the caller. Multi-word English phrases are
# included verbatim (callers compare the whole cell, not word-by-word).
# ---------------------------------------------------------------------------

# --- name / identifier column ------------------------------------------------
_NAME = {
    # English single-word + multi-word.
    "signal", "signals", "port", "ports", "pin", "pins", "name",
    "port name", "signal name", "pin name",
    "port group", "pin group", "signal group", "port groups",
    # v0.3.4 — #491 R4: sub-port family (group-detail tables headed
    # `Sub-port | ...` under a port-group row).
    "sub-port", "sub port", "subport", "sub-ports", "sub ports",
    "mnemonic", "identifier", "label",
    # #491 round-3 — universal CJK port/name vocabulary (REUSED, not
    # duplicated: the runner's _V0_3_2_HEADER_NAME_TOKENS now derives
    # from this set).
    "訊號", "信號", "埠", "接腳", "腳位", "引腳", "名稱", "訊號名稱",
    "信號名稱", "埠名", "信号", "端口", "管脚", "标识", "標識",
}

# --- direction column --------------------------------------------------------
_DIRECTION = {
    "direction", "dir", "mode", "i/o", "io", "in/out", "type",
    # #491 round-3 — CJK direction vocabulary (REUSED).
    "方向", "輸入/輸出", "輸入輸出", "输入/输出", "输入输出", "输入",
    "輸入", "輸出", "输出", "流向",
}

# --- width column ------------------------------------------------------------
_WIDTH = {
    "width", "bits", "size", "[bits]", "msb:lsb", "bit", "bit width",
    # #491 round-3 — CJK width vocabulary (REUSED).
    "寬度", "位寬", "位元寬度", "位元數", "宽度", "位宽", "位数",
    "位元", "位數",
}

# --- description column ------------------------------------------------------
_DESCRIPTION = {
    "description", "desc", "function", "purpose", "notes", "note",
    "meaning", "comment", "comments", "summary", "definition",
    "remark", "remarks",
    # #491 round-3 — CJK description vocabulary (REUSED).
    "描述", "說明", "功能", "備註", "用途", "说明", "备注", "注释",
    "註釋", "含義", "含义", "意義", "意义",
}

# --- address / offset column -------------------------------------------------
_ADDRESS = {
    "csr address", "address", "addr", "number", "num", "csr num",
    "csr number", "offset", "base", "base address",
    # CJK address vocabulary.
    "位址", "地址", "偏移", "偏移量", "編號", "编号", "基址",
    "基底位址", "暫存器位址", "寄存器地址",
}

# --- access / privilege column -----------------------------------------------
_ACCESS = {
    "access", "privilege", "priv", "rw", "type", "mode", "permission",
    "attribute", "attributes", "r/w",
    # CJK access vocabulary.
    "存取", "權限", "权限", "讀寫", "读写", "屬性", "属性",
    "存取權限", "访问", "訪問",
}

# --- default / reset-value column --------------------------------------------
_DEFAULT = {
    "default", "reset", "reset value", "default value", "initial",
    "initial value", "init",
    # CJK default vocabulary.
    "預設", "预设", "預設值", "预设值", "重置值", "复位值", "復位值",
    "初始", "初始值", "缺省", "缺省值",
}

# --- opcode / encoding column ------------------------------------------------
_OPCODE = {
    "opcode", "op code", "op-code", "encoding", "code", "instruction",
    "command", "cmd", "funct", "funct3", "funct7",
    # CJK opcode vocabulary.
    "操作碼", "操作码", "編碼", "编码", "指令", "命令", "指令碼",
    "指令码",
}

# --- value column ------------------------------------------------------------
_VALUE = {
    "value", "values", "val", "data",
    # CJK value vocabulary.
    "值", "數值", "数值", "資料", "数据", "取值",
}

# --- register column ---------------------------------------------------------
_REGISTER = {
    "register", "csr", "reg", "field",
    # CJK register vocabulary.
    "暫存器", "寄存器", "字段", "欄位", "栏位",
}

# --- parameter / generic / config column ------------------------------------
_PARAMETER = {
    "parameter", "parameters", "param", "generic", "generics",
    "config", "configuration", "constant", "constants", "macro",
    "macros",
    # CJK parameter vocabulary.
    "參數", "参数", "配置", "常數", "常数", "巨集", "宏", "泛型",
}

# --- field column (bit field / table field) ---------------------------------
_FIELD = {
    "field", "fields", "bit", "bits", "bitfield", "bit field",
    # CJK field vocabulary.
    "欄位", "栏位", "字段", "位元", "位域",
}

# --- range column ------------------------------------------------------------
_RANGE = {
    "range", "min", "max", "minimum", "maximum",
    # CJK range vocabulary.
    "範圍", "范围", "最小", "最大", "最小值", "最大值",
}

# --- units column ------------------------------------------------------------
_UNITS = {
    "units", "unit",
    # CJK units vocabulary.
    "單位", "单位",
}


# Public, immutable per-role lexicon. Callers MUST source their token
# sets from here (the structural test in
# ``test_bilingual_header_lexicon.py`` asserts every classifier token
# set derives from these entries).
ROLE_TOKENS: Dict[str, FrozenSet[str]] = {
    "name": frozenset(_NAME),
    "direction": frozenset(_DIRECTION),
    "width": frozenset(_WIDTH),
    "description": frozenset(_DESCRIPTION),
    "address": frozenset(_ADDRESS),
    "access": frozenset(_ACCESS),
    "default": frozenset(_DEFAULT),
    "opcode": frozenset(_OPCODE),
    "value": frozenset(_VALUE),
    "register": frozenset(_REGISTER),
    "parameter": frozenset(_PARAMETER),
    "field": frozenset(_FIELD),
    "range": frozenset(_RANGE),
    "units": frozenset(_UNITS),
}


def tokens_for(*roles: str) -> FrozenSet[str]:
    """Return the union of the bilingual header tokens for ``roles``.

    Used by per-family classifiers to assemble exactly the column-role
    vocabulary they need from the single shared lexicon, e.g.::

        _V1_6_566_HEADER_ADDR_TOKENS = tokens_for("address")
        _DOC_TABLE_HEADER_TOKENS = tokens_for(
            "name", "direction", "description", ...)

    Unknown role names raise ``KeyError`` so a typo fails loud rather
    than silently producing an empty set. Chip-AGNOSTIC."""
    out: Set[str] = set()
    for role in roles:
        out |= ROLE_TOKENS[role]
    return frozenset(out)


def cjk_tokens() -> FrozenSet[str]:
    """Every CJK (non-ASCII) header token across all roles — used by the
    structural test to assert each multilingual family carries CJK
    coverage. Chip-AGNOSTIC."""
    out: Set[str] = set()
    for toks in ROLE_TOKENS.values():
        for t in toks:
            if any(ord(ch) > 0x2E7F for ch in t):
                out.add(t)
    return frozenset(out)


def all_tokens() -> FrozenSet[str]:
    """The full bilingual vocabulary across every role. Chip-AGNOSTIC."""
    out: Set[str] = set()
    for toks in ROLE_TOKENS.values():
        out |= toks
    return frozenset(out)
