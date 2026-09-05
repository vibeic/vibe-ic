"""czregmap — six of seven register rows dropped, and two instruments blind to it.

MEASURED FIRST, on a real docs-only project (`ic/sha256/input/` of
`benchmark-data` at 8c4b608a4542, run through `phase1_one_shot_runner.py`).
Its `L5_register_map.md` declares SEVEN register rows. `L4_REGMAP.registers[]`
carried the name of exactly ONE of them:

    declared by the input   NAME0 NAME1 VERSION CTRL STATUS
                            BLOCK0..BLOCK15  DIGEST0..DIGEST7   (29 names)
    carried, before         CTRL                                ( 1 name)

Nothing said so. The run exited 0, printed `Coverage (overall): 100.0%`, and
the `registers[]` list was seven entries long — six of them synthesised
memory-map endpoints, which is why a count comparison sees nothing and a NAME
comparison sees everything.

1. THE EXTRACTOR. `phase1_doc_one_shot_runner._reg_row_re_rst_grid` accepted
   every COMPOUND access token and no SINGLE-LETTER one, so a summary table
   whose access column reads `R` on a read-only row and `W` on a write-only
   row matched only its `R/W` rows. That is ordinary register documentation —
   and it is the spelling a column HEADED `R/W` invites. Fixed as a parsing
   rule, not as a case for this table.

2. `l4_regmap_declared_register_coverage_check` said NOT_APPLICABLE — "the
   input states no register-map denominator" — over an input stating 29 of
   them, because its declared side reads address-valued HDL enums only. It was
   blind BY CONSTRUCTION: the population it measures cannot contain the thing
   that went missing, and the sentence it printed asserted that population's
   absence. It now separates NOT_MEASURED from NOT_APPLICABLE and names the
   rows, the registers, and which of them L4 does not carry.

3. `extraction_coverage_report` published `overall.pct = 100.0%` while its own
   `overall.measures` field says a literal is credited when it appears
   ANYWHERE in the union of the L docs. The disclaimer was true, was written
   by the producer, and never travelled with the number. It does now — in the
   markdown, on the line under the percentage, and on stdout. The percentage
   is NOT narrowed: it still answers "did this literal land anywhere at all",
   and narrowing it would redefine the metric rather than disclose it.

chip-AGNOSTIC: generic widget register vocabulary throughout; single-letter
read/write notation is register-documentation grammar, not a design's
spelling. No PDK, vendor, node or part appears.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))

import phase1_doc_one_shot_runner as P  # noqa: E402

COV_GATE = PLUGIN / "programs" / "l4_regmap_declared_register_coverage_check.py"


# The shape the defect was measured on, in generic vocabulary: a five-column
# summary table whose access column is headed `R/W` and whose rows spell the
# read-only and write-only cases with ONE letter.
_BARE_ACCESS_TABLE = """# Widget register map

| Address | Name | R/W | Width | Description |
|---|---|---|---|---|
| `0x00` | `IDLOW` | R | 32 | identifier word 0 |
| `0x01` | `IDHIGH` | R | 32 | identifier word 1 |
| `0x08` | `CONTROL` | R/W | 32 | control register |
| `0x09` | `FLAGS` | R | 32 | status register |
| `0x0c` | `PUSH` | W | 32 | write-only data port |
"""

# Every compound token the alternation already accepted, so the widening
# cannot be a substitution: these must still come out.
_COMPOUND_ACCESS_TABLE = """# Widget register map

| Address | Name | Access | Width | Description |
|---|---|---|---|---|
| `0x10` | `ALPHA` | RW | 32 | read-write |
| `0x11` | `BRAVO` | RO | 32 | read-only |
| `0x12` | `CHARLIE` | WO | 32 | write-only |
| `0x13` | `DELTA` | RW1C | 32 | write-one-to-clear |
| `0x14` | `ECHO` | WARL | 32 | write-any-read-legal |
| `0x15` | `FOXTROT` | MRW | 32 | privileged read-write |
"""

# NO-LEAK: a description-shaped cell that merely BEGINS with R or W is not an
# access token. The row must not become a register.
_PROSE_ACCESS_TABLE = """# Widget notes

| Address | Name | Meaning | Width | Description |
|---|---|---|---|---|
| `0x30` | `WIDGETA` | Read the sensor | 32 | not an access column |
| `0x31` | `WIDGETB` | Writes are ignored | 32 | not an access column |
"""


def _l4_names(doc_text: str, doc_name: str = "widget_regs.md") -> set:
    """The register NAMES `gen_l4_regmap` actually emits for a document.

    Asserted on the parsed result rather than on the regex: the claim is
    about which registers reach L4, and a regex that matches while the
    downstream walker discards the row would satisfy a string assertion and
    not the claim.

    Every fixture filename here carries `reg`, MEASURED and not assumed: the
    same table under `d.md` yields NOTHING on base and on this branch alike,
    because the summary-table walker is reached through a filename hint. A
    no-leak control run under a name the walker never opens would be green
    for a reason that has nothing to do with the rule under test.
    """
    proj = Path(tempfile.mkdtemp())
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = P.gen_l4_regmap(proj, {doc_name: doc_text})
    doc = json.loads(Path(res.path).read_text(encoding="utf-8"))
    return {r.get("name") for r in (doc.get("registers") or [])
            if isinstance(r, dict) and r.get("name")}


# ---------------------------------------------------------------------------
# (1) the extractor
# ---------------------------------------------------------------------------

def test_bare_r_and_w_access_rows_reach_l4():
    """THE defect. Before the fix this set was `{"CONTROL"}`."""
    names = _l4_names(_BARE_ACCESS_TABLE)
    for expected in ("IDLOW", "IDHIGH", "CONTROL", "FLAGS", "PUSH"):
        assert expected in names, (
            f"{expected} is declared by a row of the summary table and did "
            f"not reach L4.registers[]; carried: {sorted(names)}")


# The real seven-row shape, in generic vocabulary: five scalar rows and two
# RANGE rows. Both range forms appear in one table in the measured input.
_SEVEN_ROW_TABLE = """# Widget register map

| Address | Name | R/W | Width | Description |
|---|---|---|---|---|
| `0x00` | `IDLOW` | R | 32 | identifier word 0 |
| `0x01` | `IDHIGH` | R | 32 | identifier word 1 |
| `0x02` | `REVISION` | R | 32 | revision word |
| `0x08` | `CONTROL` | R/W | 32 | control register |
| `0x09` | `FLAGS` | R | 32 | status register |
| `0x10-0x1F` | `BLK0` ~ `BLK15` | W | 32 each | block input words |
| `0x20-0x27` | `RESULT0` ~ `RESULT7` | R | 32 each | result words |
"""


def test_the_seven_row_shape_carries_five_and_the_two_range_rows_are_the_residual():
    """The measured shape, by NAME on the parsed result — and the residual
    this branch does NOT fix, PINNED rather than only written down.

    Before the access fix this table yielded ONE register. After it, FIVE:
    the two RANGE rows are a different shape — `0x10-0x1F` is not a single
    hex address and `BLK0 ~ BLK15` is not a single identifier, so neither
    cell satisfies the row regex at all — and widening the access
    alternation cannot reach them.

    That residual is disclosed in the handback, and a disclosure nothing
    enforces is the shape this whole lane is about. So it is asserted BOTH
    ways here: the five that now arrive must arrive, and the range rows must
    still be absent. If someone later teaches the extractor address ranges,
    THIS TEST GOES RED and its author is told to update the disclosure with
    the fix — which is the intended outcome, not a regression.
    """
    names = _l4_names(_SEVEN_ROW_TABLE, "widget_seven_regs.md")
    assert {"IDLOW", "IDHIGH", "REVISION", "CONTROL", "FLAGS"} <= names, (
        f"the five scalar rows must all reach L4; carried: {sorted(names)}")
    still_absent = {f"BLK{i}" for i in range(16)} | {
        f"RESULT{i}" for i in range(8)}
    reached = still_absent & names
    assert not reached, (
        "the range rows now reach L4 — the residual CZ-07 disclosed is "
        f"fixed, and the disclosure must be updated to say so: {sorted(reached)}")


def test_the_residual_is_the_RANGE_FORM_and_not_those_names():
    """NO-LEAK for the residual claim, and it makes the claim precise.

    "BLK0..BLK15 do not reach L4" would be a weak statement if those names
    were simply unparseable. They are not: written as SIXTEEN ORDINARY ROWS
    the same names all arrive, bare `W` access included. What the extractor
    cannot read is the RANGE FORM — one row standing for sixteen registers —
    and that is exactly what the disclosure says.
    """
    header = ("# Widget register map\n\n"
              "| Address | Name | R/W | Width | Description |\n"
              "|---|---|---|---|---|\n")
    spelt = header + "".join(
        f"| `0x{16 + i:02x}` | `BLK{i}` | W | 32 | block word {i} |\n"
        for i in range(16))
    names = _l4_names(spelt, "widget_spelt_regs.md")
    assert {f"BLK{i}" for i in range(16)} <= names, (
        "spelled out as ordinary rows these names must all reach L4 — if "
        "they do not, the residual is not about the range form at all: "
        f"{sorted(names)}")


def test_the_instrument_names_the_residual_the_extractor_cannot_reach():
    """The two halves meet: what the extractor cannot parse, the repaired
    instrument NAMES. That is the whole argument of this branch in one
    assertion — the loss survives, and it stops being silent."""
    carried = [{"name": n, "address_int": a} for n, a in (
        ("IDLOW", 0x00), ("IDHIGH", 0x01), ("REVISION", 0x02),
        ("CONTROL", 0x08), ("FLAGS", 0x09))]
    proj = _docs_project(_SEVEN_ROW_TABLE, carried)
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    summary = json.loads(out.read_text())
    absent = summary["documentary_names_absent_from_l4"]
    assert absent == [f"BLK{i}" for i in range(16)] + [
        f"RESULT{i}" for i in range(8)], absent
    assert summary["documentary_declared_name_count"] == 29, summary
    assert "carries 5 of those 29 name(s); 24 do not appear" in cp.stdout, \
        cp.stdout


def test_compound_access_tokens_still_reach_l4():
    """NO-LEAK. Widening the alternation must not displace what it accepted."""
    names = _l4_names(_COMPOUND_ACCESS_TABLE, "widget_compound_regs.md")
    for expected in ("ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT"):
        assert expected in names, (
            f"{expected} used a compound access token that already worked "
            f"and is now absent; carried: {sorted(names)}")


def test_a_prose_cell_that_starts_with_r_or_w_is_not_an_access_token():
    """NO-LEAK, the other direction: the cell must BE the token."""
    names = _l4_names(_PROSE_ACCESS_TABLE, "widget_prose_regs.md")
    assert "WIDGETA" not in names and "WIDGETB" not in names, (
        "a description cell beginning with 'Read'/'Writes' was accepted as "
        f"an access token; carried: {sorted(names)}")


# ---------------------------------------------------------------------------
# (2) NOT_MEASURED is not NOT_APPLICABLE
# ---------------------------------------------------------------------------

def _docs_project(doc_text: str, l4_registers, doc_name="regmap.md"):
    proj = Path(tempfile.mkdtemp())
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / doc_name).write_text(doc_text,
                                                    encoding="utf-8")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L4_REGMAP.json").write_text(json.dumps(
        {"schema_version": 2, "doc_class": "regmap",
         "registers": l4_registers}), encoding="utf-8")
    return proj


def _run_cov(proj, out=None):
    cmd = [sys.executable, str(COV_GATE), str(proj)]
    if out:
        cmd += ["--json", str(out)]
    return subprocess.run(cmd, capture_output=True, text=True)


_ALL_FIVE = [{"name": n, "address_int": a} for n, a in (
    ("IDLOW", 0x00), ("IDHIGH", 0x01), ("CONTROL", 0x08),
    ("FLAGS", 0x09), ("PUSH", 0x0c))]


def test_documented_register_map_is_not_measured_not_not_applicable():
    proj = _docs_project(_BARE_ACCESS_TABLE, _ALL_FIVE)
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "[NOT_MEASURED]" in cp.stdout, cp.stdout
    assert "[SKIP]" not in cp.stdout, (
        "a documented register map was still announced as SKIP")
    summary = json.loads(out.read_text())
    assert summary["verdict"] == "NOT_MEASURED", summary["verdict"]
    den = summary["denominator"]
    # The rule was NOT applied. `examined` must stay 0 — crediting an
    # unapplied rule with a population is the substitution the whole
    # denominator contract exists against.
    assert den["examined"] == 0, den
    assert den["considered"] == 5, den
    assert set(summary["documentary_declared_names"]) == {
        "IDLOW", "IDHIGH", "CONTROL", "FLAGS", "PUSH"}, summary


def test_the_verdict_names_a_register_the_layer_dropped():
    """THE CONTROL. Drop one declared register from L4 and the instrument
    must name it. Before the repair it said the input declared none."""
    kept = [r for r in _ALL_FIVE if r["name"] != "FLAGS"]
    proj = _docs_project(_BARE_ACCESS_TABLE, kept)
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "FLAGS" in cp.stdout, (
        "a register the input declares and L4 does not carry was not named: "
        + cp.stdout)
    summary = json.loads(out.read_text())
    assert summary["documentary_names_absent_from_l4"] == ["FLAGS"], summary


def test_a_range_row_declares_every_register_in_the_range():
    """`| 0x10-0x1F | BLK0 ~ BLK15 | W | ... |` declares sixteen registers.

    Reporting it as one row is how a sixteen-register loss reads as a
    one-row difference."""
    doc = """# Widget register map

| Address | Name | R/W | Width | Description |
|---|---|---|---|---|
| `0x00` | `CONTROL` | R/W | 32 | control |
| `0x10-0x1F` | `BLK0` ~ `BLK15` | W | 32 each | block input words |
"""
    proj = _docs_project(doc, [{"name": "CONTROL", "address_int": 0}])
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    summary = json.loads(out.read_text())
    names = summary["documentary_declared_names"]
    assert names == ["CONTROL"] + [f"BLK{i}" for i in range(16)], names
    assert summary["documentary_names_absent_from_l4"] == [
        f"BLK{i}" for i in range(16)], summary


def test_a_name_first_summary_table_declares_its_registers():
    """Column roles are MEASURED, not assumed.

    Found by sweeping the tracked corpus, not by reading: a register-tool
    summary writes `| Name | Offset | Length | Description |`, and a
    harvester that fixes the address at cell 0 reports ZERO registers for a
    document that declares 35."""
    doc = """# Widget registers

| Name                        | Offset | Length | Description       |
|:----------------------------|:-------|-------:|:------------------|
| wid.[`ALERT`](#alert)       | 0x0    |      4 | Alert register    |
| wid.[`KEY_0`](#key)         | 0x4    |      4 | Key word 0        |
| wid.[`KEY_1`](#key)         | 0x8    |      4 | Key word 1        |
| wid.[`STATUS`](#status)     | 0xc    |      4 | Status register   |
"""
    proj = _docs_project(doc, [{"name": "ALERT", "address_int": 0}])
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    summary = json.loads(out.read_text())
    assert summary["documentary_declared_names"] == [
        "ALERT", "KEY_0", "KEY_1", "STATUS"], summary
    assert summary["documentary_names_absent_from_l4"] == [
        "KEY_0", "KEY_1", "STATUS"], summary


def test_an_enum_value_table_is_not_a_register_table():
    """NO-LEAK, from the same sweep. `| Value | Name | Description |` has
    the SAME shape as a 3-column register table; only the heading over the
    first column separates them, and 21 encoding rows were reported as
    registers before this refusal existed."""
    doc = """# Widget control

| Value   | Name   | Description                        |
|:--------|:-------|:-----------------------------------|
| 0x1     | PER_1  | one-hot: reseed once per block     |
| 0x2     | PER_64 | one-hot: reseed once per 64 blocks |
| 0x4     | PER_8K | one-hot: reseed once per 8K blocks |
"""
    proj = _docs_project(doc, [{"name": "CONTROL", "address_int": 0}])
    cp = _run_cov(proj)
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout, (
        "an encoding table was reported as a declared register map: "
        + cp.stdout)


def test_a_field_table_headed_reset_is_not_a_register_table():
    """NO-LEAK. A per-register field table carries a hex column too."""
    doc = """# Widget CONTROL fields

| Bits | Type | Reset | Name  | Description        |
|:-----|:-----|:------|:------|:-------------------|
| 31:2 | rw   | 0x0   | RSVD  | Reserved           |
| 1    | rw   | 0x0   | START | Start the widget   |
| 0    | ro   | 0x0   | BUSY  | Widget is busy     |
"""
    proj = _docs_project(doc, [{"name": "CONTROL", "address_int": 0}])
    cp = _run_cov(proj)
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout, cp.stdout


def test_a_repeating_hex_column_is_not_an_address_column(tmp_path):
    """NO-LEAK, and it isolates the SECOND refusal.

    MEASURED, and it corrected me: the fixture above is refused by the
    HEADING vocabulary, not by the address rule, so deleting the address
    rule left it green and the rule looked inert. This one heads the same
    column `Init` — a word the refusal list does not carry — so the only
    thing that can refuse it is the address rule itself: two registers
    cannot share one address, and a column that reads 0x0 on every row
    declares none.
    """
    doc = """# Widget CONTROL fields

| Bits | Access | Init | Name  | Description      |
|:-----|:-------|:-----|:------|:-----------------|
| 31:2 | rw     | 0x0  | RSVD  | Reserved         |
| 1    | rw     | 0x0  | START | Start the widget |
| 0    | ro     | 0x0  | BUSY  | Widget is busy   |
"""
    proj = _docs_project(doc, [{"name": "CONTROL", "address_int": 0}])
    cp = _run_cov(proj)
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout, (
        "a field table's repeating reset column was read as an address "
        "column: " + cp.stdout)


def test_a_long_name_list_is_truncated_beside_an_untruncated_count():
    """A truncated list beside a full count reads as a truncation.

    A truncated list ALONE reads as the whole population, which is the
    substitution this gate exists against — one level down, in its own
    report."""
    import l4_regmap_declared_register_coverage_check as COV
    cap = COV._NAME_LIST_CAP
    n = cap + 40
    rows = "\n".join(f"| `0x{i:04x}` | `REG{i}` | R | 32 | row {i} |"
                     for i in range(n))
    doc = ("# Widget register map\n\n"
           "| Address | Name | R/W | Width | Description |\n"
           "|---|---|---|---|---|\n" + rows + "\n")
    proj = _docs_project(doc, [])
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    summary = json.loads(out.read_text())
    assert len(summary["documentary_declared_names"]) == cap, summary
    assert summary["documentary_declared_name_count"] == n, summary
    assert summary["documentary_names_absent_from_l4_count"] == n, summary
    assert f"naming {n} register(s)" in cp.stdout, cp.stdout


# ---------------------------------------------------------------------------
# (2b) the four states of the layer being measured against, kept apart
#
# Found by auditing my own repair rather than by being told: three of these
# four branches shipped with NO test, and two of them said the SAME sentence
# for two DIFFERENT facts. A disclosure branch nobody has proven can fire is
# not a disclosure, and "absent" collapsed into "could not be read" is the
# exact substitution this whole file was repaired for.
# ---------------------------------------------------------------------------

def _docs_project_raw_l4(doc_text: str, l4_bytes):
    """Like `_docs_project`, but writes L4 verbatim — or not at all."""
    proj = Path(tempfile.mkdtemp())
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "regmap.md").write_text(doc_text,
                                                       encoding="utf-8")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    if l4_bytes is not None:
        (gd / "L4_REGMAP.json").write_bytes(l4_bytes)
    return proj


def test_an_absent_layer_is_not_reported_as_an_unreadable_one():
    proj = _docs_project_raw_l4(_BARE_ACCESS_TABLE, None)
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "no L4_REGMAP.json was emitted at all" in cp.stdout, cp.stdout
    assert "did not parse" not in cp.stdout, (
        "an absent layer was described as a damaged one: " + cp.stdout)
    assert json.loads(out.read_text())["l4_state"] == "absent"


def test_an_unparseable_layer_is_not_reported_as_an_absent_one():
    proj = _docs_project_raw_l4(_BARE_ACCESS_TABLE, b"not json at all {{{")
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "is PRESENT and did not parse" in cp.stdout, cp.stdout
    assert "was emitted at all" not in cp.stdout, (
        "a damaged layer was described as an absent one: " + cp.stdout)
    summary = json.loads(out.read_text())
    assert summary["l4_state"] == "unparseable", summary
    # The exception is NAMED. "it did not parse" with no reason is the same
    # silence the denominator contract exists against.
    assert summary["denominator"]["details"]["l4_parse_error"], summary


def test_a_layer_of_the_wrong_json_type_is_unparseable_not_empty():
    """`[]` is valid JSON and is not a register map. Reading it as one would
    report ZERO carried registers — a number, from a file that states
    none."""
    proj = _docs_project_raw_l4(_BARE_ACCESS_TABLE, b"[]")
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "is PRESENT and did not parse" in cp.stdout, cp.stdout
    assert "carries 0 of" not in cp.stdout, (
        "a wrong-typed layer was measured as an empty one: " + cp.stdout)
    assert json.loads(out.read_text())["l4_state"] == "unparseable"


def test_a_layer_carrying_every_documented_name_still_says_the_rule_did_not_run():
    """The tempting branch. Every documented name IS present, and the honest
    answer is still NOT_MEASURED: matching by NAME is not the address-binding
    rule this gate applies, and reporting it as coverage would be the
    numerator-with-no-denominator shape one level over."""
    proj = _docs_project(_BARE_ACCESS_TABLE, _ALL_FIVE)
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "does carry all 5 of those name(s)" in cp.stdout, cp.stdout
    assert "by NAME only, which is not the rule this gate applies" in cp.stdout
    summary = json.loads(out.read_text())
    assert summary["verdict"] == "NOT_MEASURED", summary
    assert summary["documentary_names_absent_from_l4"] == [], summary
    assert summary["l4_state"] == "read", summary


def test_no_documented_register_table_stays_not_applicable():
    """NO-LEAK. `NOT_MEASURED` must not become the new always-on verdict."""
    doc = """# Widget overview

The widget converts an input stream to an output stream.

| Parameter | Value |
|---|---|
| Throughput | 100 items/s |
| Latency | 4 cycles |
"""
    proj = _docs_project(doc, [{"name": "CONTROL", "address_int": 0}])
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout, cp.stdout
    assert json.loads(out.read_text())["verdict"] == "NOT_APPLICABLE"


def test_the_vacuous_verdict_names_what_it_could_not_open():
    """The same defect class, one level DOWN and inside the repair.

    "no documentation staged under input/ declares a register row either" is
    a claim about the INPUT dressed over a fact about this gate's suffix
    list. A project whose register map is stated in a file type the
    harvester does not read gets exactly that sentence, and it is false in
    the same way `NOT_APPLICABLE` was. The zero must NAME what it could not
    open — "could not read it" is not "read it and it was empty".
    """
    doc = "# Widget overview\n\nThe widget converts a stream.\n"
    proj = _docs_project(doc, [], doc_name="overview.md")
    (proj / "input" / "docs" / "registers.pdf").write_bytes(b"%PDF-1.4\n")
    (proj / "input" / "docs" / "regmap_diagram.svg").write_text(
        "<svg><text>0x00 CTRL R/W</text></svg>", encoding="utf-8")
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "NOT LOOKED FOR" in cp.stdout, cp.stdout
    assert "registers.pdf" in cp.stdout, cp.stdout
    assert "regmap_diagram.svg" in cp.stdout, cp.stdout
    census = json.loads(out.read_text())["documentary_census"]
    assert census["opened_count"] == 1, census
    assert census["not_opened_count"] == 2, census


def test_the_vacuous_verdict_claims_no_unopened_document_when_there_is_none():
    """NO-LEAK. The census must never manufacture a document it did not
    skip — a fabricated disclosure is worse than none."""
    doc = "# Widget overview\n\nThe widget converts a stream.\n"
    proj = _docs_project(doc, [], doc_name="overview.md")
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    assert "NOT LOOKED FOR" not in cp.stdout, cp.stdout
    census = json.loads(out.read_text())["documentary_census"]
    assert census["not_opened"] == [] and census["not_opened_count"] == 0, census
    assert census["opened_count"] == 1, census


def test_an_hdl_input_is_not_reported_as_an_unopened_document():
    """NO-LEAK. A `.sv` under input/docs IS read — by the HDL harvester, and
    the same sentence already reports what that found. Naming it as
    unopened would be a disclosure that is not true."""
    doc = "# Widget overview\n\nThe widget converts a stream.\n"
    proj = _docs_project(doc, [], doc_name="overview.md")
    (proj / "input" / "docs" / "widget_pkg.sv").write_text(
        "package widget_pkg; typedef enum logic [1:0] "
        "{ M0 = 2'b00 } m_e; endpackage", encoding="utf-8")
    out = proj / "cov.json"
    cp = _run_cov(proj, out)
    assert cp.returncode == 2, cp.stdout
    census = json.loads(out.read_text())["documentary_census"]
    assert census["not_opened"] == [], census


def test_a_hex_address_in_running_prose_is_not_a_declaration():
    """NO-LEAK. A register map is a TABLE; one piped line in prose is not."""
    doc = ("# Widget\n\nThe base address is `0x40` | see the integration "
           "note | for details.\n")
    proj = _docs_project(doc, [{"name": "CONTROL", "address_int": 0}])
    cp = _run_cov(proj)
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout, cp.stdout


def test_the_hdl_declared_path_is_unchanged_when_hdl_declares_a_map():
    """NO-LEAK. The documentary harvester is a fallback, never a bypass:
    where HDL declares the map, the blocking rule still runs and still
    blocks."""
    pkg = """
package widget_pkg;
  typedef enum logic [11:0] {
    REG_ALPHA = 12'h300,
    REG_BRAVO = 12'h301,
    REG_CHARLIE = 12'h304,
    REG_DELTA = 12'h305,
    REG_ECHO = 12'h340,
    REG_FOXTROT = 12'h341,
    REG_GOLF = 12'h7a0,
    REG_HOTEL = 12'h7a1,
    REG_INDIA = 12'hb00,
    REG_JULIET = 12'hb03
  } map_e;
endpackage
"""
    proj = _docs_project(_BARE_ACCESS_TABLE, _ALL_FIVE)
    (proj / "input" / "docs" / "widget_pkg.sv").write_text(pkg,
                                                           encoding="utf-8")
    cp = _run_cov(proj)
    assert cp.returncode == 1, (
        "the HDL-declared blocking rule stopped running once a documented "
        "table was also present: " + cp.stdout)
    assert "declares 10" in cp.stdout, cp.stdout


# ---------------------------------------------------------------------------
# (2c) the umbrella's operator line
#
# MEASURED, not inferred — the claim "the marker survives into the operator
# line" was made from reading the code first, and reading it was not enough:
# an unrecognised marker also blocks the strip of the gate's own repeated
# name, and the two together cost 56 characters of a 200-character line. On
# this gate that is exactly the row and register counts it exists to publish.
# ---------------------------------------------------------------------------

def test_the_umbrella_operator_line_keeps_the_payload_not_the_prefix():
    import flow_compliance_check as FC
    proj = _docs_project(_BARE_ACCESS_TABLE, _ALL_FIVE)
    cp = _run_cov(proj)
    line = FC._p0_skip_reason_from_output(
        "l4_regmap_declared_register_coverage_check", cp.stdout, cp.stderr)
    # The WORD survives — it is the first thing the reason itself says, so it
    # does not depend on the bracket marker being kept.
    assert line.startswith("NOT_MEASURED, which is not NOT_APPLICABLE"), line
    # The house prefix does NOT survive: neither the bracket marker nor the
    # gate's own name is repeated into a line that already carries both.
    assert not line.startswith("["), line
    assert "l4_regmap_declared_register_coverage_check" not in line, line
    # And the payload reaches the line rather than being truncated away.
    assert "documentation staged under" in line, line


def test_a_line_without_the_marker_renders_identically():
    """NO-LEAK for the flow-level change: widening the marker must not touch
    a line that does not begin with one."""
    import flow_compliance_check as FC
    gate = "l4_regmap_declared_register_coverage_check"
    plain = f"{gate}: nothing in particular happened here"
    assert FC._p0_skip_reason_from_output(gate, plain, "") == (
        "nothing in particular happened here")
    banner = "=== some banner ===\n[SKIP] " + gate + ": the old shape\n"
    assert FC._p0_skip_reason_from_output(gate, banner, "") == "the old shape"


def test_widening_the_marker_moves_no_reason_class():
    """The operator line is fed to the reason taxonomy, so the cosmetic
    change was checked against it rather than assumed to be cosmetic.

    The invariant is NOT "every line classifies the same" — the taxonomy
    reads the message text, so different prose classifies differently by
    design, and asserting otherwise was my own first mistake here (a
    hand-written `there was nothing to check` classifies ZERO_DENOMINATOR,
    not EXECUTION_ERROR). The invariant is that WIDENING THE MARKER does not
    move the class for the SAME stdout — before against after, on identical
    input, which is the only thing this change could have broken.
    """
    import re
    import flow_compliance_check as FC
    import _flow_reason_taxonomy as RT

    gate = "l4_regmap_declared_register_coverage_check"
    ev = {"exit_code": 2, "skip_kind": "input-missing"}
    before_marker = re.compile(r"^\[(?:skip|n/?a|vacuous|info)\]\s*", re.I)

    def render_with(marker, stdout):
        raw = [ln.strip() for ln in stdout.strip().splitlines()
               if ln.strip()][0]
        line = marker.sub("", raw, count=1).strip()
        if line.lower().startswith(gate.lower()):
            line = line[len(gate):].lstrip(" :\u2014-").strip()
        return (line or raw)[:200]

    proj = _docs_project(_BARE_ACCESS_TABLE, _ALL_FIVE)
    for stdout in (_run_cov(proj).stdout,
                   f"[SKIP] {gate}: there was nothing to check",
                   f"{gate}: a line carrying no marker at all"):
        was = render_with(before_marker, stdout)
        now = render_with(FC._P0_SKIP_MARKER, stdout)
        assert (RT.infer_nonverdict_reason(verdict="SKIP", message=was,
                                           evidence=ev)
                == RT.infer_nonverdict_reason(verdict="SKIP", message=now,
                                              evidence=ev)), (was, now)


# ---------------------------------------------------------------------------
# (3) the percentage cannot be quoted without its scope
# ---------------------------------------------------------------------------

def _coverage_report(tmp_path: Path):
    """Run the real producer and return (markdown, json)."""
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "regmap.md").write_text(
        _BARE_ACCESS_TABLE, encoding="utf-8")
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "input_doc" / "regmap.txt").write_text(
        _BARE_ACCESS_TABLE, encoding="utf-8")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L4_REGMAP.json").write_text(json.dumps(
        {"registers": _ALL_FIVE}), encoding="utf-8")
    pct, report = P.emit_coverage_report(
        proj, {"regmap.txt": _BARE_ACCESS_TABLE}, [])
    md = (proj / "reports" / "phase1"
          / "extraction_coverage_report.md").read_text(encoding="utf-8")
    return md, report


def test_the_percentage_and_its_scope_are_emitted_on_adjacent_lines(tmp_path):
    """The property is ADJACENCY, not presence: a disclaimer three sections
    away is what the JSON already had, and the number was still quoted
    alone."""
    md, report = _coverage_report(tmp_path)
    lines = md.splitlines()
    pct_idx = [i for i, l in enumerate(lines) if "overall.pct" in l]
    assert pct_idx, md
    scope = lines[pct_idx[0] + 1]
    assert "what this percentage measures" in scope, (
        "the line under the percentage is not its scope: " + repr(scope))
    assert "ANYWHERE in the union" in scope, scope


def test_the_published_scope_is_the_producers_own_field(tmp_path):
    """One place the sentence is written down, so the two cannot drift."""
    md, report = _coverage_report(tmp_path)
    measures = report["overall"]["measures"]
    assert measures, report["overall"]
    assert measures in md, (
        "the markdown restates the scope instead of publishing the "
        "producer's field, so the two can drift apart")
