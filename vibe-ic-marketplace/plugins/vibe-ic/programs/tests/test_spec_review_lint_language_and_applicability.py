"""spec_review_lint.py — the check must recognise the FACT, not one spelling.

Four measured defects, each of which made the lint report a finding no edit to
the design could ever clear, and each pinned here in BOTH directions: the fact
is recognised however it is written, AND the check still says no when the fact
is genuinely absent. A check that stopped saying no would be worse than the red
it replaced, so every "recognised" test below has an adversarial twin built from
a spec that really does have the flaw.

  1. corner-case synonyms were English-only regexes. A Traditional-Chinese
     corpus could never match them, so "reset during operation" and
     "back-to-back transactions" were UNCOVERABLE items rather than uncovered
     ones.
  2. wrap semantics stated as mathematics (`p = (x * y) mod 2^N`) is a
     statement of what happens on overflow; demanding the word "overflow"
     beside it asks for a synonym, not for information.
  3. "illegal inputs — defined vs undefined behaviour" presupposes an encoded
     input space in which some code points are illegal. On a pure datapath
     every bit pattern of the operands is legal, so the item must SELF-SKIP —
     and the skip must be VISIBLE (INFO), never silent.
  4. `_split_sentences` splits on "." and newline, so every markdown table row
     read as a prose "sentence" and every PPA table cell holding "10 ns" read
     as a timing statement with no reference edge. A table row is not prose,
     and a document that declares its reference edge once has declared it for
     the statements it contains (the same allowance `_check_signal_attrs`
     already makes for a global clock-domain statement).

The Traditional-Chinese strings below are TEST DATA — the thing being
recognised. Code, names and comments stay English.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_review_lint.py'
assert SCRIPT.exists()


def run(tmp_path, spec_text, ext='.md', *extra):
    spec = tmp_path / f'spec{ext}'
    spec.write_text(spec_text, encoding='utf-8')
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json', str(jf), *extra, str(spec)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text())['findings'] if jf.exists() else []
    return res, findings


def corner_ids(findings, code='corner-case-uncovered'):
    """The checklist ids reported under `code`."""
    return {f['message'].rsplit("item '", 1)[1].split("'", 1)[0]
            for f in findings if f['code'] == code}


# A minimal Traditional-Chinese spec that DOES state reset-during-operation and
# back-to-back, in the shape the spm design states them (L7 rows 43-44).
ZH_COVERED = """\
# 乘法器驗證計畫

本模組為 8-bit 乘法器。所有資料於上升沿取樣與輸出。

- 邊角 — 連續輸入:連續多筆乘法計算之間,內部狀態應正確 reset 或銜接。
- Reset 行為:reset 期間 / reset 解除瞬間 / reset 在計算進行中 assert 三種情況。
- 乘積定義為 p = (x * y) mod 2^N,溢位位元捨棄。
- 非法輸入:opcode 0xF 為保留編碼,行為未定義。
"""

# The SAME language, the SAME vocabulary (reset, 計算, 輸入), but the facts are
# genuinely absent: nothing says reset may be asserted mid-computation, and
# nothing says transactions may be consecutive. This is the adversarial twin —
# if the zh patterns were loose enough to match here, they would be worthless.
ZH_UNCOVERED = """\
# 乘法器驗證計畫

本模組為 8-bit 乘法器。所有資料於上升沿取樣與輸出。

- reset 由 rst_n 觸發,將所有暫存器歸零。
- 計算由 valid 啟動,結果於下一個 cycle 輸出。
- 輸入資料寬度為 8 位元。
- 溢位時輸出飽和 (saturate)。
- 非法輸入:opcode 0xF 為保留編碼,行為未定義。
"""


# ── defect 1: Traditional-Chinese corner-case statements ────────────────────
def test_zh_reset_during_operation_is_recognised(tmp_path):
    _, f = run(tmp_path, ZH_COVERED)
    assert 'reset-during-operation' not in corner_ids(f)


def test_zh_back_to_back_is_recognised(tmp_path):
    _, f = run(tmp_path, ZH_COVERED)
    assert 'back-to-back' not in corner_ids(f)


def test_zh_reset_during_operation_still_fires_when_absent(tmp_path):
    """ADVERSARIAL: a zh spec that names reset and names 計算 but never states
    reset DURING operation must still be reported."""
    res, f = run(tmp_path, ZH_UNCOVERED, '.md', '--strict')
    assert 'reset-during-operation' in corner_ids(f)
    assert res.returncode == 1


def test_zh_back_to_back_still_fires_when_absent(tmp_path):
    """ADVERSARIAL: 連續 never appears with a transaction noun here."""
    res, f = run(tmp_path, ZH_UNCOVERED, '.md', '--strict')
    assert 'back-to-back' in corner_ids(f)
    assert res.returncode == 1


def test_english_corner_case_statements_still_recognised(tmp_path):
    """Adding zh spellings must not cost the English ones."""
    _, f = run(tmp_path, """\
# Adder spec

TopModule adds on the rising edge of clk. Reset during operation aborts the sum.
Back-to-back transfers are accepted with no gap between them. The result
saturates on overflow. Command 0xF is an illegal opcode and is ignored.
""")
    assert corner_ids(f) == set()


# ── defect 2: wrap semantics stated as modulo arithmetic ────────────────────
MOD_SPEC = """\
# Multiplier spec

TopModule computes p = (x * y) mod 2^N on the rising edge of clk.
Reset during operation clears p. Back-to-back multiplications are accepted.
Command 0x3 is an illegal opcode and is ignored.
"""


def test_modulo_arithmetic_states_wrap_semantics(tmp_path):
    _, f = run(tmp_path, MOD_SPEC)
    assert 'full-empty-overflow-underflow' not in corner_ids(f)


def test_wrap_semantics_still_fires_without_any_wrap_statement(tmp_path):
    """ADVERSARIAL: an 8-bit adder with an 8-bit sum and NO statement of what
    the sum holds when the addition exceeds 8 bits."""
    res, f = run(tmp_path, """\
# Adder spec

TopModule is an 8-bit adder sampled on the rising edge of clk. Reset during
operation aborts the addition. Back-to-back additions are accepted with no gap
between them. Command 0xF is an illegal opcode and is ignored.
The sum is 8 bits wide.
""", '.md', '--strict')
    assert 'full-empty-overflow-underflow' in corner_ids(f)
    assert res.returncode == 1


# ── defect 3: illegal-inputs self-skips, VISIBLY, with no encoding layer ────
PURE_DATAPATH = """\
# Multiplier spec

TopModule computes p = (x * y) mod 2^N on the rising edge of clk. Every bit
pattern of x and y is a legal operand. Reset during operation clears p.
Back-to-back multiplications are accepted with no gap between them.
"""

# A REAL command layer: a layer noun with enumerated code points beside it, and
# no word anywhere about what an undefined command does.
REAL_OPCODE_LAYER = """\
# Command decoder spec

TopModule decodes a 4-bit command word on the rising edge of clk.
Reset during operation returns the decoder to idle. Back-to-back commands are
accepted with no gap between them. The accumulator wraps modulo 2^8.

Opcode table:
  0x0 = NOP
  0x1 = START
  0x2 = STOP
  0x3 = FLUSH
"""


def test_illegal_inputs_self_skips_on_a_pure_datapath(tmp_path):
    res, f = run(tmp_path, PURE_DATAPATH, '.md', '--strict')
    assert 'illegal-inputs' not in corner_ids(f)
    assert res.returncode == 0


def test_the_illegal_inputs_skip_is_visible_and_says_why(tmp_path):
    """A silent skip is indistinguishable from a pass. The skip must be
    REPORTED, name the item, and give the reason — at INFO, which by
    construction cannot move the exit code."""
    _, f = run(tmp_path, PURE_DATAPATH)
    skips = [x for x in f if x['code'] == 'corner-case-not-applicable']
    assert len(skips) == 1
    assert skips[0]['severity'] == 'INFO'
    assert 'illegal-inputs' in skips[0]['message']
    assert 'NOT CHECKED' in skips[0]['message']
    assert 'encoding layer' in skips[0]['message']


def test_illegal_inputs_still_fires_on_a_real_opcode_layer(tmp_path):
    """ADVERSARIAL: a design that really does have an opcode encoding and
    really does not define what an undefined opcode does. The self-skip must
    NOT reach it — it is a WARN, not an INFO."""
    res, f = run(tmp_path, REAL_OPCODE_LAYER, '.md', '--strict')
    assert 'illegal-inputs' in corner_ids(f)
    assert corner_ids(f, 'corner-case-not-applicable') == set()
    assert res.returncode == 1


def test_a_covered_illegal_inputs_item_is_never_downgraded_to_a_skip(tmp_path):
    """Coverage is decided first: a spec that addresses the item has shown the
    item applies to it, whatever the applicability heuristic would say."""
    _, f = run(tmp_path, PURE_DATAPATH.rstrip() + "\n"
               "An out-of-range size parameter is illegal and is rejected.\n")
    assert corner_ids(f) == set()
    assert corner_ids(f, 'corner-case-not-applicable') == set()


# ── defect 4: table rows / fences are not prose; document-level edge ────────
def timing(findings):
    return [x for x in findings if x['code'] == 'timing-no-ref-edge']


def test_a_markdown_table_row_is_not_a_prose_timing_statement(tmp_path):
    """A PPA table cell holding "10 ns" is a cell, not a claim about when
    something happens, and there is nowhere in it for a reference edge to go."""
    _, f = run(tmp_path, """\
# Backend results

Reset during operation is supported. Back-to-back transfers are allowed with no
gap between them. The counter wraps modulo 2^16. Command 0x7 is illegal.

| Std-cell library | Target clock period |
|---|---|
| `sky130_fd_sc_hd` | 10 ns |
| `gf180mcu_*` | 24 ns |
""")
    assert timing(f) == []


def test_a_fenced_code_block_is_not_a_prose_timing_statement(tmp_path):
    _, f = run(tmp_path, """\
# Constraints

Reset during operation is supported. Back-to-back transfers are allowed with no
gap between them. The counter wraps modulo 2^16. Command 0x7 is illegal.

```
set_input_delay 2 ns -clock core_clock [get_ports d]
```
""")
    assert timing(f) == []


def test_timing_prose_without_a_reference_edge_still_fires(tmp_path):
    """ADVERSARIAL: a real prose sentence stating a real timing requirement,
    in a document that never declares a reference edge anywhere."""
    res, f = run(tmp_path, """\
# Interface timing

The data bus must be stable for a setup time of 2 ns before it is captured.

Reset during operation is supported. Back-to-back transfers are allowed with no
gap between them. The counter wraps modulo 2^16. Command 0x7 is illegal.
""", '.md', '--strict')
    assert len(timing(f)) == 1
    assert 'setup time of 2 ns' in timing(f)[0]['message']
    assert res.returncode == 1


def test_a_document_level_reference_edge_governs_the_document(tmp_path):
    """Mirrors `clock_ref_global` in `_check_signal_attrs`: one declaration of
    the reference edge covers the statements in the document."""
    _, f = run(tmp_path, """\
# Interface timing

All data is sampled and driven on the rising edge of clk.

The data bus must be stable for a setup time of 2 ns before it is captured.

Reset during operation is supported. Back-to-back transfers are allowed with no
gap between them. The counter wraps modulo 2^16. Command 0x7 is illegal.
""")
    assert timing(f) == []


def test_an_sdc_create_clock_is_a_document_level_reference_edge(tmp_path):
    _, f = run(tmp_path, """\
# Constraints

```sdc
create_clock [get_ports clk] -name core_clock -period 10
```

Set_input_delay uses 20 percent of the clock period, so 2 ns setup time applies
to every input. Reset during operation is supported. Back-to-back transfers are
allowed with no gap between them. The counter wraps modulo 2^16.
Command 0x7 is illegal.
""")
    assert timing(f) == []


def test_a_latency_figure_alone_does_not_anchor_a_document(tmp_path):
    """ADVERSARIAL: `_REF_EDGE_DOC` must be TIGHTER than `_REF_EDGE`. If a bare
    "3 clock cycles" counted as a document-level declaration, one latency figure
    would silence the check for the whole file."""
    res, f = run(tmp_path, """\
# Interface timing

The result is valid 3 clock cycles after the request.

The data bus must be stable for a setup time of 2 ns before it is captured.

Reset during operation is supported. Back-to-back transfers are allowed with no
gap between them. The counter wraps modulo 2^16. Command 0x7 is illegal.
""", '.md', '--strict')
    assert any('setup time of 2 ns' in x['message'] for x in timing(f))
    assert res.returncode == 1


def test_a_traditional_chinese_reference_edge_is_a_reference_edge(tmp_path):
    """"於上升沿取樣" states the same structural fact as "on the rising edge"."""
    _, f = run(tmp_path, """\
# 介面時序

所有資料於上升沿取樣與輸出。

資料匯流排在被取樣前需維持 setup time 2 ns。

- Reset 行為:reset 在計算進行中 assert。
- 邊角 — 連續輸入:連續多筆傳輸之間無間隔。
- 乘積定義為 p = (x * y) mod 2^N。
- 非法輸入:opcode 0xF 為保留編碼。
""")
    assert timing(f) == []


# ── the design statements this was measured against ────────────────────────
def test_the_spm_design_statements_are_recognised_verbatim(tmp_path):
    """The four sentences the spm design actually contains (L2:21, L3:21,
    L7:43, L7:44). Every one states the substance a checklist item asks for;
    before the fix not one of them could be matched."""
    _, f = run(tmp_path, """\
# spm

| `clk` | 1-bit | input | 系統時脈;所有資料於上升沿取樣與輸出 |

p = (x * y) mod 2^N    (N-bit modulo arithmetic multiplication)

| 邊角 — 連續輸入 | 100% PASS | 連續多筆乘法計算之間,內部狀態應正確 reset 或銜接 |
| Reset 行為 | 100% PASS | reset 期間 / reset 解除瞬間 / reset 在計算進行中 assert 三種情況 |
""")
    assert corner_ids(f) == set()
    assert timing(f) == []
    assert corner_ids(f, 'corner-case-not-applicable') == {'illegal-inputs'}
