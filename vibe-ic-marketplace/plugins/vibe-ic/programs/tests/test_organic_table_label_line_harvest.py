"""ORGANIC — the `- <field>:` label above a rendered table is part of that
table's identifying semantics, and the golden value must be read by HEADER
SEMANTICS rather than by position.

DEFECT (measured on cell sha256 x gf180mcuD, plugin 1.5.85):
`phase1_dialogue_render._bullets()` renders every record list as

    - <field_name>:
    | <union of the record's own keys> |
    | --- | --- |
    | ...data rows... |

because `_table()` builds the header row from the RECORD's own keys. The field
name — `test_vectors`, `negative_tests`, `opcodes`, `submodules`, … — the one
token that says what the table IS, therefore appears ONLY in the label line and
NEVER in the header row. `_harvest_test_cases_from_input_tables` keyed solely on
the header row, so `L10.test_vectors` (header
`id|name|source|command|block_hex|expected_digest_hex|note`) and
`L10.negative_tests` (header `id|name|stimulus|expected`) were BOTH silently
dropped. L10 then emitted `test_cases: []` + `no_test_cases_in_input: true` — a
FALSE positive claim about the input — collapsing Step-4 functional
verification to a connectivity-only skeleton for a design whose input shipped
three FIPS 180-4 golden digests.

SECOND DEFECT, in the same harvest: `expected` was read positionally as
`cells[-1]`. The measured table carries a TRAILING COMMENTARY column (`note`)
left EMPTY on every row, so every golden value collapsed to "" — an oracle with
no answer, which cannot fail. The fixture below therefore carries that empty
trailing column, exactly as the measured input did; without it the positional
read accidentally lands on the digest and the header-semantic selection has no
coverage at all.

BIDIRECTIONAL, as required for any new gate:
  * `test_defect_shape_is_harvested`  — the DEFECT case must now PASS
    (pre-fix this asserts 0 == 4 and FAILS; that is the point).
  * `test_measured_shape_carries_an_empty_trailing_column` — PREMISE for the
    one below: the last cell of a data row really is empty.
  * `test_expected_is_selected_by_header_semantics_not_position` — reverting
    the selection to `cells[-1]` yields '' and FAILS here.
  * `test_header_vocab_table_still_harvested` /
    `test_header_only_input_column_still_harvested` — the previously-working
    shapes must keep working (no regression from touching the predicate).
  * `test_non_test_table_not_harvested`, `test_bench_instrument_list_...`,
    `test_ownership_matrix_...`, `test_build_artifact_list_...` — the label
    must not rubber-stamp a table on its own; the last three ARE harvested by
    a label-only predicate and must not be.
  * `test_label_lookback_is_bounded` /
    `test_lookback_bound_is_the_deciding_branch` — a far-away label must not
    be claimed, and DISTANCE ALONE must be what rejects it (no intervening
    prose doing the rejecting on the bound's behalf).
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


_TV1_DIGEST = ("ba7816bf8f01cfea414140de5dae2223"
               "b00361a396177a9cb410ff61f20015ad")
_TV2_DIGEST = ("e3b0c44298fc1c149afbf4c8996fb924"
               "27ae41e4649b934ca495991b7852b855")

# The EXACT payload shape that shipped in input/phase1_structured.yaml on
# cell sha256 x gf180mcuD. Two properties of the real shape matter and BOTH
# are reproduced here:
#   1. not one per-record key carries a test/vector/case token — that is what
#      made the table invisible to a header-only predicate;
#   2. `test_vectors` carries a TRAILING `note` column that is EMPTY on every
#      row — that is what made the positional `cells[-1]` read of `expected`
#      collapse every golden digest to "".
_L10_PAYLOAD = {
    "test_vectors": [
        {"id": "TV-1", "name": "one-block message",
         "source": "FIPS PUB 180-4, Appendix B.1", "command": "CTRL_INIT",
         "block_hex": "61626380" + "00" * 52 + "0018",
         "expected_digest_hex": _TV1_DIGEST,
         "note": ""},
        {"id": "TV-2", "name": "empty message",
         "source": "FIPS PUB 180-4, section 5.1.1", "command": "CTRL_INIT",
         "block_hex": "80" + "00" * 63,
         "expected_digest_hex": _TV2_DIGEST,
         "note": ""},
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


def _cells(row_line):
    return [c.strip() for c in row_line.strip().strip("|").split("|")]


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


def test_measured_shape_carries_an_empty_trailing_column():
    """PREMISE for `test_expected_is_selected_by_header_semantics_not_position`.

    The measured table's last column is a commentary `note` column left EMPTY
    on every row. If this fixture ever loses that column the positional read
    lands on the digest by accident and the header-semantic selection becomes
    untested — which is exactly how that half of the fix shipped uncovered."""
    md = _render_md(_L10_PAYLOAD)
    hdr = next(ln for ln in md.split("\n") if "expected_digest_hex" in ln)
    cols = _cells(hdr)
    assert cols[-1] == "note", cols
    assert cols.index("expected_digest_hex") == len(cols) - 2, cols
    for tag, digest in (("TV-1", _TV1_DIGEST), ("TV-2", _TV2_DIGEST)):
        row = _cells(next(ln for ln in md.split("\n") if f"| {tag} " in ln))
        assert len(row) == len(cols), (tag, row)
        # what a POSITIONAL read of `expected` would return:
        assert row[-1] == "", (tag, row)
        # ...and what the header-semantic read must return instead:
        assert row[cols.index("expected_digest_hex")] == digest, (tag, row)


def test_defect_shape_is_harvested():
    """THE DEFECT CASE. Pre-fix this harvests 0; post-fix it must harvest all
    4 rows."""
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(_L10_PAYLOAD)})
    assert len(got) == 4, (
        f"expected 4 harvested cases (2 test_vectors + 2 negative_tests), "
        f"got {len(got)}: {[g.get('name') for g in got]}")
    names = {g["name"] for g in got}
    assert names == {"tv_1", "tv_2", "nt_1", "nt_2"}, names


def test_expected_is_selected_by_header_semantics_not_position():
    """The anti-rubber-stamp half of the fix, on the REAL measured shape.

    The last cell of every `test_vectors` row is the empty `note` cell, so a
    positional `cells[-1]` read yields '' — a golden value that cannot fail.
    Only selection by header semantics (`expected_digest_hex`) can produce the
    digests asserted here, in FULL: a prefix assertion would still pass on a
    truncated cell, and a non-emptiness assertion alone would not prove the
    RIGHT column was picked."""
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(_L10_PAYLOAD)})
    by_name = {g["name"]: g for g in got}
    assert by_name["tv_1"]["expected"] == _TV1_DIGEST, by_name["tv_1"]
    assert by_name["tv_2"]["expected"] == _TV2_DIGEST, by_name["tv_2"]
    # ...and no harvested case may carry a blank oracle at all
    blank = [g["name"] for g in got if not g["expected"].strip()]
    assert not blank, f"harvested cases with a blank oracle: {blank}"


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


def test_header_only_input_column_still_harvested():
    """REGRESSION GUARD for the OTHER legacy arm: a header carrying
    test + input and NO expected column qualified before the fix and must
    still qualify. The oracle-column corroboration demanded of the LABEL path
    must not leak onto the header path."""
    md = "\n".join([
        "| 測試 | 輸入 |",
        "| --- | --- |",
        "| idle_hold | cs=0 |",
    ])
    got = doc._harvest_test_cases_from_input_tables({"vplan.md": md})
    assert len(got) == 1, [g.get("name") for g in got]


def test_non_test_table_not_harvested():
    """OVER-HARVEST GUARD. An electrical-spec table and a pin table carry no
    test vocabulary in label OR header and must stay rejected."""
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


# ── OVER-HARVEST GUARDS for the surface the LABEL WIDENING actually opens ──
# Each of the next three IS harvested (1 case each) by a predicate that lets
# the label satisfy the whole test-table test on its own, and by no earlier
# predicate: the label carries the test/scenario/firmware token and the header
# carries an `input`-class column — or, for `firmware_images`, the one label
# token doubles as both halves of the predicate. None of the three is a
# functional test case and none has an ORACLE column for a golden value to
# come from, which is precisely the corroboration now required.

def test_bench_instrument_list_not_harvested():
    """A bench-instrument list is not a functional test case."""
    payload = {"test_equipment": [
        {"instrument": "scope", "model": "MSO-X 3054T", "input": "clk probe"},
        {"instrument": "psu", "model": "E3631A", "input": "vdd rail"},
    ]}
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(payload)})
    assert got == [], f"bench-instrument list became L10 cases: {got}"


def test_ownership_matrix_not_harvested():
    """An ownership matrix is not a functional test case."""
    payload = {"scenario_matrix": [
        {"name": "boot", "input": "power-on", "owner": "alice"},
        {"name": "shutdown", "input": "pwr_dn", "owner": "bob"},
    ]}
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(payload)})
    assert got == [], f"ownership matrix became L10 cases: {got}"


def test_build_artifact_list_not_harvested():
    """A build-artifact list is not a functional test case."""
    payload = {"firmware_images": [
        {"name": "img0", "source": "build/main.elf", "size": "4 KB"},
        {"name": "img1", "source": "build/loader.elf", "size": "2 KB"},
    ]}
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(payload)})
    assert got == [], f"build-artifact list became L10 cases: {got}"


def test_label_widening_still_admits_a_labelled_table_with_an_oracle():
    """The tightening must not close the door the fix opened: a labelled
    record list WITH an oracle column is still harvested even though its
    header carries no test vocabulary at all."""
    payload = {"test_vectors": [
        {"id": "TV-9", "stimulus": "0x00", "expected_digest_hex": "deadbeef"},
    ]}
    got = doc._harvest_test_cases_from_input_tables(
        {"design_description.md": _render_md(payload)})
    assert len(got) == 1, got
    assert got[0]["expected"] == "deadbeef", got


# ── LOOK-BACK BOUND ────────────────────────────────────────────────────────
_LOOKBACK_TABLE = [
    "| id | name | expected |",
    "| --- | --- | --- |",
    "| X-1 | assert reset_n | FSM returns to IDLE |",
]


def _lookback_doc(nblank):
    """Label, then `nblank` BLANK lines, then the table. Nothing else — so the
    only thing that can vary the outcome is the DISTANCE."""
    return "\n".join(["- test_vectors:"] + [""] * nblank + _LOOKBACK_TABLE)


def test_label_lookback_is_bounded():
    """A label too far above the header row belongs to a DIFFERENT block.

    Asserted as a CONTRAST on distance alone: identical lines, nothing but
    blanks in between, only the blank count differs. Without the contrast the
    rejection could be coming from something other than the bound — and it
    was: the original fixture put prose between label and table, so the prose
    (not the bound) did the rejecting and the bound was never evaluated."""
    near = doc._harvest_test_cases_from_input_tables({"d.md": _lookback_doc(3)})
    assert len(near) == 1, (
        f"3 blank lines are inside the bound and must still claim the label, "
        f"got {near}")
    far = doc._harvest_test_cases_from_input_tables({"d.md": _lookback_doc(4)})
    assert far == [], f"claimed a label 4 blank lines away: {far}"


def test_lookback_bound_is_the_deciding_branch():
    """The same assertion at the helper level, so a failure points straight at
    the bound. Every case below is byte-identical apart from the blank-line
    count, so the DISTANCE TEST is the only branch that can decide them;
    deleting `if hdr_idx - j > 3: return ''` flips the second group."""
    for nblank in (0, 1, 2, 3):
        lines = ["- test_vectors:"] + [""] * nblank + [_LOOKBACK_TABLE[0]]
        assert doc._preceding_table_label(lines, len(lines) - 1) == (
            "test vectors"), f"blank_lines={nblank} is inside the bound"
    for nblank in (4, 5, 9):
        lines = ["- test_vectors:"] + [""] * nblank + [_LOOKBACK_TABLE[0]]
        assert doc._preceding_table_label(lines, len(lines) - 1) == "", (
            f"blank_lines={nblank} is beyond the bound and must be rejected")


def test_label_separated_by_prose_not_claimed():
    """The other rejection route: a non-blank, non-label line ends the block."""
    md = "\n".join([
        "- test_vectors:",
        "",
        "some intervening prose that ends the block",
        "",
    ] + _LOOKBACK_TABLE)
    got = doc._harvest_test_cases_from_input_tables({"d.md": md})
    assert got == [], f"claimed a label across prose: {got}"


def test_preceding_table_label_helper_directly():
    lines = ["- test_vectors:", "", "| id | name |", "| --- | --- |"]
    assert doc._preceding_table_label(lines, 2) == "test vectors"
    # no label above the table
    assert doc._preceding_table_label(["| id | name |"], 0) == ""
    # dotted field paths flatten too (renderer emits `- a.b:` for nested keys)
    assert doc._preceding_table_label(
        ["- L10.test_vectors:", "", "| id |"], 2) == "L10 test vectors"


# ── GATEKEEPER Step-2.7 addition (landed with this change) ───────────────────
# The header-semantics fix shipped a positional FALLBACK for the case where the
# header-picked oracle cell is blank. Measured against an independent fixture at
# review time: that fallback lifted the trailing COMMENTARY cell into `expected`
# ("TBD-not-an-oracle" became the golden value) — the same defect this change
# removes, inverted. A blank oracle can never FAIL; a fabricated one can never
# PASS, and a false FAIL is what sends someone to fix a design that is not
# broken. Never fabricate: keep the row, mark the absence.

_BLANK_ORACLE_DOC = "\n".join([
    "- test_vectors:", "",
    "| id | name | block_hex | expected_digest_hex | note |",
    "| --- | --- | --- | --- | --- |",
    "| 1 | good | ab | " + "b" * 64 + " |  |",
    "| 2 | blankexp | cd |  | TBD-not-an-oracle |",
])


def test_blank_oracle_cell_is_never_filled_from_the_note_column():
    """THE regression this guards: row 2's oracle column is empty and its
    trailing `note` carries prose. The prose must NOT become the golden
    value."""
    cases = doc._harvest_test_cases_from_input_tables({"d.md": _BLANK_ORACLE_DOC})
    assert len(cases) == 2, cases
    by_stim = {c["stimulus"]: c for c in cases}
    assert by_stim["blankexp"]["expected"] == ""
    assert "TBD-not-an-oracle" not in str(cases)


def test_blank_oracle_is_marked_not_silently_dropped():
    """Two failure modes are BOTH refused: fabricating an oracle, and dropping
    the row (which would re-create the false `no_test_cases_in_input`). The
    absence is disclosed on the row instead."""
    cases = doc._harvest_test_cases_from_input_tables({"d.md": _BLANK_ORACLE_DOC})
    by_stim = {c["stimulus"]: c for c in cases}
    assert by_stim["blankexp"].get("oracle_absent") is True
    # ...and a row that HAS its oracle is untouched — no spurious marker.
    assert by_stim["good"]["expected"] == "b" * 64
    assert "oracle_absent" not in by_stim["good"]


def test_no_oracle_column_at_all_keeps_the_positional_read():
    """Zero regression on the legacy shape: when the header names NO
    oracle-class column, the positional last-cell read still applies and no
    absence marker is emitted."""
    d = "\n".join([
        "- test_vectors:", "",
        "| id | name | result |",
        "| --- | --- | --- |",
        "| 1 | t1 | 0xdeadbeef |",
    ])
    cases = doc._harvest_test_cases_from_input_tables({"d.md": d})
    if cases:  # this shape may or may not be admitted; if it is, it must be sane
        assert cases[0]["expected"] == "0xdeadbeef"
        assert "oracle_absent" not in cases[0]
