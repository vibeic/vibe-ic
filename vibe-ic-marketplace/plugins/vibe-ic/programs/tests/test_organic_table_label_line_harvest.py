"""ORGANIC — the `- <field>:` label above a rendered table is part of that
table's identifying semantics.

DEFECT (measured on cell sha256 x gf180mcuD, plugin 1.5.85):
`phase1_dialogue_render._bullets()` renders every record list as

    - <field_name>:
    <blank>
    | <union of the record's own keys> |
    | --- | --- |
    | ...data rows... |

because `_table()` builds the header row from the RECORD's own keys. The field
name — `test_vectors`, `negative_tests`, `opcodes`, `submodules`, … — the one
token that says what the table IS, therefore appears ONLY in the label line and
NEVER in the header row. `_harvest_test_cases_from_input_tables` keyed solely on
the header row, so `L10.test_vectors` (header
`id|name|source|command|block_hex|expected_digest_hex`) and `L10.negative_tests`
(header `id|name|stimulus|expected`) were BOTH silently dropped. L10 then
emitted `test_cases: []` + `no_test_cases_in_input: true` — a FALSE positive
claim about the input — collapsing Step-4 functional verification to a
connectivity-only skeleton for a design whose input shipped three FIPS 180-4
golden digests.

BIDIRECTIONAL, as required for any new gate:
  * `test_defect_shape_is_harvested`  — the DEFECT case must now PASS
    (pre-fix this asserts 0 == 4 and FAILS; that is the point).
  * `test_header_vocab_table_still_harvested` — the previously-working shape
    must keep working (no regression from widening the predicate).
  * `test_non_test_table_not_harvested` — a label that is NOT test-ish must
    still be rejected, so the widening cannot rubber-stamp every table.
  * `test_label_lookback_is_bounded` — a far-away label must not be claimed.
"""
import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


doc = _load("phase1_doc_one_shot_runner")
rnd = _load("phase1_dialogue_render")


# The EXACT payload shape that shipped in input/phase1_structured.yaml on
# cell sha256 x gf180mcuD. Note: not one per-record key carries a
# test/vector/case token — that is what made the table invisible.
_L10_PAYLOAD = {
    "test_vectors": [
        {"id": "TV-1", "name": "one-block message",
         "source": "FIPS PUB 180-4, Appendix B.1", "command": "CTRL_INIT",
         "block_hex": "61626380" + "00" * 52 + "0018",
         "expected_digest_hex": "ba7816bf8f01cfea414140de5dae2223"
                                "b00361a396177a9cb410ff61f20015ad"},
        {"id": "TV-2", "name": "empty message",
         "source": "FIPS PUB 180-4, section 5.1.1", "command": "CTRL_INIT",
         "block_hex": "80" + "00" * 63,
         "expected_digest_hex": "e3b0c44298fc1c149afbf4c8996fb924"
                                "27ae41e4649b934ca495991b7852b855"},
    ],
    "negative_tests": [
        {"id": "NT-1", "name": "unmapped address read",
         "stimulus": "cs=1 we=0 address=0x40",
         "expected": "error high for one cycle, no state change"},
        {"id": "NT-2", "name": "read-only write",
         "stimulus": "cs=1 we=1 address=0x20",
         "expected": "error high for one cycle, DIGEST0 unchanged"},
    ],
}


def _render_md(payload):
    return "\n".join(rnd._bullets(payload))


def test_renderer_really_omits_field_name_from_header():
    """Guards the PREMISE. If the renderer ever starts putting the field name
    in the header row this whole defect class evaporates and the fix below
    would be dead code — so assert the premise explicitly rather than
    assuming it."""
    md = _render_md(_L10_PAYLOAD)
    # `_table()` INDENTS every row by two spaces, so the row test must strip
    # first. Matching on a bare leading '|' silently selects nothing and the
    # premise below is then asserted over an empty list.
    headers = [ln for ln in md.split("\n")
               if ln.strip().startswith("|") and "---" not in ln
               and "TV-" not in ln and "NT-" not in ln]
    assert headers, "renderer emitted no header rows at all"
    for h in headers:
        assert "test_vectors" not in h and "negative_tests" not in h, (
            f"premise broken: field name leaked into header row {h!r}")
    # ...and the label lines ARE present, which is what the fix keys on.
    assert "- test_vectors:" in md
    assert "- negative_tests:" in md


def test_defect_shape_is_harvested():
    """THE DEFECT CASE. Pre-fix this harvests 0; post-fix it must harvest all
    4 rows, and the golden digest must survive into `expected` so the
    downstream oracle TB has something real to compare against."""
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(_L10_PAYLOAD)})
    assert len(got) == 4, (
        f"expected 4 harvested cases (2 test_vectors + 2 negative_tests), "
        f"got {len(got)}: {[g.get('name') for g in got]}")
    names = {g["name"] for g in got}
    assert names == {"tv_1", "tv_2", "nt_1", "nt_2"}, names
    # the golden digest must be carried, not just the row count
    tv1 = next(g for g in got if g["name"] == "tv_1")
    assert tv1["expected"].startswith("ba7816bf8f01cfea"), tv1["expected"]


def test_header_vocab_table_still_harvested():
    """REGRESSION GUARD. A table whose HEADER already carried the vocabulary
    worked before the fix and must still work after it."""
    md = "\n".join([
        "| test case | stimulus | expected |",
        "| --- | --- | --- |",
        "| reset_sweep | assert reset_n | FSM returns to IDLE |",
        "| decode_sweep | walk all addresses | error on unmapped |",
    ])
    got = doc._harvest_test_cases_from_input_tables({"vplan.md": md})
    assert len(got) == 2, [g.get("name") for g in got]
    assert {g["name"] for g in got} == {"reset_sweep", "decode_sweep"}


def test_non_test_table_not_harvested():
    """OVER-HARVEST GUARD. Widening the predicate to include the label must
    NOT turn every labelled table into an L10 test case. An electrical-spec
    table and a pin table are labelled and have an `expected`-ish column
    vocabulary nearby, yet are not test cases."""
    payload = {
        "electrical_specs": [
            {"parameter": "VDD", "min": "4.5", "typ": "5.0", "max": "5.5",
             "unit": "V"},
        ],
        "pin_table": [
            {"pin": "1", "name": "clk", "direction": "input", "width": "1"},
        ],
    }
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(payload)})
    assert got == [], f"over-harvested non-test tables: {got}"


def test_label_lookback_is_bounded():
    """A label separated from the table by a paragraph belongs to a DIFFERENT
    block and must not be claimed as that table's label."""
    md = "\n".join([
        "- test_vectors:",
        "",
        "some intervening prose that ends the block",
        "",
        "| id | name | source |",
        "| --- | --- | --- |",
        "| X-1 | a | b |",
    ])
    got = doc._harvest_test_cases_from_input_tables({"d.md": md})
    assert got == [], f"claimed a far-away label: {got}"


def test_preceding_table_label_helper_directly():
    lines = ["- test_vectors:", "", "| id | name |", "| --- | --- |"]
    assert doc._preceding_table_label(lines, 2) == "test vectors"
    # no label above the table
    assert doc._preceding_table_label(["| id | name |"], 0) == ""
    # dotted field paths flatten too (renderer emits `- a.b:` for nested keys)
    assert doc._preceding_table_label(
        ["- L10.test_vectors:", "", "| id |"], 2) == "L10 test vectors"
