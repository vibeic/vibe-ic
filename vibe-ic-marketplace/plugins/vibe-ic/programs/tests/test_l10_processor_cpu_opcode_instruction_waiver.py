"""processor_cpu instruction-oracle waiver — the reach of
`cap:cpu_functional_oracle` in l10_tb_conformance_check, decided by RESOLVING
the case's pointer in the design's OWN L3 rather than by classifying its prose.

DEFECT (chip-AGNOSTIC, ic_class=processor_cpu). The `cap:cpu_functional_oracle`
waiver — which exists, is anchored by the runner's `sim/results.xml`
capability-gap token, and books CPU instruction cases as WAIVED-DEFERRED — was
STRUCTURALLY UNREACHABLE for every real CPU core. Its match side
(`is_functional_vector`) only recognises `kind in {functional_vector,
functional, functional_test, instruction_test, cpu_functional}`, but Phase 1's
`gen_l10_test_cases` renders a CPU core's L3 opcodes as command-response cases
with `kind in {happy_path, pre_wake_false, addr_max, len_max}`. The two
internal vocabularies never met, so the OPCODE-DERIVED half of a CPU core's L10
hard-FAILed Step 4 by construction, independent of RTL quality.

(The `functional_vector` path itself is NOT dead: Phase 1's
`_harvest_test_cases_from_input_tables` stamps that kind on every case it lifts
out of an input verification-plan table. Those cases carry no `opcode_hex`, so
they were never the population in question.)

WHY THIS IS NOT A FIFTH APPROXIMATION. Four earlier revisions each shipped a
different guess at "does this case have an oracle?" — two `kind` whitelists, a
narrowed whitelist, and a classifier over the case's `expected` TEXT — and each
was refuted because the guess's complement was wider than claimed. The last one
read `per <identifier_containing_underscore_or_dot>` as a deferral, but in
engineering prose "per" overwhelmingly means "for each": measured over this
repo's own corpus (363 194 string values in `benchmark-data/**/phase1/
generated_docs/L*.json`) that grammar fires 35 times and NOT ONE names an L3
response-template field — they are `per LCR.EPS`, `per CSW.AddrInc`,
`per ON_OFF_CONFIG`, `per ETG.2000`, `per CE_n`.

The root cause common to all four: the gate never read L3, so it could not tell
"L3 binds no reference output for this opcode" (waiver EARNED) from "L3 binds a
concrete one" (waiver UNEARNED). It now RESOLVES that pointer
(`resolve_case_oracle`), and the arms are separated by DATA on cases whose text
is byte-identical — see `test_the_real_emitters_split_two_byte_identical_
expectations`, which drives Phase 1's REAL `gen_l3_cmd_protocol` +
`gen_l10_test_cases` and gets one waived case and one failing case out of the
same `expected` string.

THE STRUCTURAL INVARIANT: **no text can GRANT the waiver; text can only
WITHHOLD it.** Only L-doc resolution admits a case; every text-derived
component (`_NO_OUTPUT_EXPECTATION_RE`, `_names_a_reference_output`) sits on the
refusing side, so a miss in any of them makes the waiver rarer, never wider.

§4.05 NO-LEAK — the BIDIRECTIONAL negative control:
  * FORWARD: a processor_cpu opcode case whose L3 entry binds NO concrete
    reference output is WAIVED-DEFERRED where it previously FAILed.
  * REVERSE: a case whose L3 entry DOES bind one STILL FAILs; an ABSENCE-oracle
    case STILL FAILs; an expectation naming no reference output STILL FAILs; an
    opcode absent from L3 STILL FAILs; a missing L3 fails CLOSED; a
    non-processor_cpu opcode happy-path STILL FAILs; an unanchored
    processor_cpu case STILL FAILs; an explicit-cmd_response digital case STILL
    FAILs — including via a NULL `category` with the class in `type`; a missing
    ic_class.json fails CLOSED.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "l10_tb_conformance_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import l10_tb_conformance_check as gate  # noqa: E402
import _l10_execution as execution  # noqa: E402

# The two expectation literals Phase 1's gen_l10_test_cases actually emits for
# an opcode-derived case (phase1_doc_one_shot_runner.py:49175 / :49190).
EXP_DEFERRED = "DUT replies per response_payload_template"
EXP_DEFERRED_BOUNDARY = ("DUT replies per response_payload_template "
                         "(boundary value is INSIDE the allowed range)")
EXP_ABSENCE = "DUT silent (no response frame)"

#: An L3 opcode entry whose response template binds NO concrete answer — one
#: byte carries a `source` pointer instead of a `value`. This is the shape
#: Phase 1's own emitter produces for any opcode with `tx_len >= 2`.
def _unbound_op(hex_):
    return {"hex": hex_, "name": "OP", "tx_len": 6,
            "response_payload_template": [
                {"byte_offset": 0, "value": "0x41",
                 "description": "response opcode echo"},
                {"byte_offset": 1, "source": "payload"},
                {"byte_offset": 2, "source": "crc8"}]}


#: …and one that BINDS a concrete answer (the `tx_len < 2` / `tx_len == 'var'`
#: shape, which is what every Strategy-2 opcode in the corpus looks like).
def _bound_op(hex_, value="0x41"):
    return {"hex": hex_, "name": "OP", "tx_len": 1,
            "response_payload_template": [
                {"byte_offset": 0, "value": value,
                 "description": "response opcode echo"}]}


UNBOUND_L3 = [_unbound_op("0x03"), _unbound_op("0x23")]


def _make_project(tmp_path, l10_cases, *, ic_class="processor_cpu",
                  cpu_oracle_anchor=True,
                  l3_opcodes=UNBOUND_L3,
                  tb_text="module tb_dummy;\nendmodule\n",
                  executed=None):
    """`executed` maps case id -> verdict and becomes the EXECUTION RECORD.

    The verdict source moved off testbench source text, so a fixture that
    wants a case CREDITED must state that something RAN it. Leaving it None
    models the shape these fixtures already had: a dummy testbench on disk
    and nothing reporting that any case was executed.
    """
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    l10 = gd / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": l10_cases}))
    if l3_opcodes is not None:
        (gd / "L3_CMD_PROTOCOL.json").write_text(
            json.dumps({"doc_class": "cmd_protocol", "opcodes": l3_opcodes}))

    sim = tmp_path / "phase2" / "stage1" / "sim"
    tb = sim / "tb"
    tb.mkdir(parents=True, exist_ok=True)
    (tb / "tb_dummy.v").write_text(tb_text)
    work = sim / "work"
    work.mkdir(parents=True, exist_ok=True)
    summary = work / "summary.txt"
    summary.write_text("")

    if cpu_oracle_anchor:
        (sim / "results.xml").write_text(
            "<results><verdict>CONNECTIVITY_PASS</verdict>"
            "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
            "<functional_verified>false</functional_verified></results>")

    if ic_class is not None:
        rep = tmp_path / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "ic_class.json").write_text(json.dumps({"ic_class": ic_class}))

    if executed:
        execution.write_record(
            tmp_path, l10,
            [{"id": case_id, "verdict": verdict, "sim_executed": True}
             for case_id, verdict in executed.items()], producer="test")

    return l10, tb, summary


def _run(tmp_path, l10, tb, summary, extra=()):
    out = tmp_path / "out.json"
    rc = gate.main(["--l10", str(l10), "--tb-dir", str(tb),
                    "--summary", str(summary), "--out", str(out),
                    "--project", str(tmp_path)] + list(extra))
    return rc, json.loads(out.read_text())


# ---------------------------------------------------------------------------
# The REAL Phase-1 emitters are the fixture, not a hand-written imitation
# ---------------------------------------------------------------------------
def _emit_real_l10(project, l3):
    """Drive Phase 1's OWN `gen_l10_test_cases` and return its case list.

    A hand-written imitation of the emitter's output is exactly how earlier
    revisions of this fix measured a population that does not occur."""
    p1 = pytest.importorskip("phase1_doc_one_shot_runner")
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    p1.gen_l10_test_cases(project, {}, l3)
    doc = json.loads(
        (project / "phase1" / "generated_docs"
         / "L10_TEST_CASES.json").read_text())
    return doc["test_cases"]


def _emit_real_l3(project, rows):
    """Drive Phase 1's OWN `gen_l3_cmd_protocol` over a command table and
    return the L3 it wrote to disk.

    `rows` are `RxLen<TAB>TxLen<TAB>TxAddr<TAB>Opcode<TAB>Name` lines — the
    spreadsheet shape Strategy 1 reads. Whether the resulting opcode binds a
    concrete reference output is decided by TxLen, by the emitter, exactly as
    it is on a real design: `tx_len >= 2` produces a template with `source`
    bytes (no concrete golden) and `tx_len < 2` produces a single concrete
    byte. That is the split this whole change turns on, and it is NOT something
    this test file chooses."""
    p1 = pytest.importorskip("phase1_doc_one_shot_runner")
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    doc = "# CMD table\nRxLen\tTxLen\tTxAddr\tOpcode\n" + "".join(
        f"{r}\n" for r in rows)
    p1.gen_l3_cmd_protocol(project, {"cmd_protocol.md": doc},
                           {"protocol_overview": {"half_duplex": True}})
    return json.loads((project / "phase1" / "generated_docs"
                       / "L3_CMD_PROTOCOL.json").read_text())


#: A command-table row whose document ALSO gives the request and response byte
#: groups. `_extract_hex_byte_groups` reads group[0] as TX-content and group[1]
#: as RX-content, so Phase 1 extracts the response bytes verbatim into
#: `response_payload_template_extracted` — and, since #812, MERGES them into
#: `response_payload_template` at every byte_offset they cover instead of
#: stamping a placeholder over them. This is the row shape the r6 negative
#: control needs; a row without both groups cannot exercise it.
#:
#: NOTE for anyone isolating an arm with this helper: because the response
#: group must land SECOND, a request group always lands FIRST and is filed as
#: `request_payload_template`, so r7's `byte_record_unattributed` arm is armed
#: on every entry this row produces. See `_without_the_positional_record`.
def _documented_row(tx_len, op_hex, rx_bytes, name="LOAD"):
    return (f"4\t{tx_len}\t00\t{op_hex}\t[0x{op_hex},0x00]\t"
            f"[{','.join(rx_bytes)}]\t{name} word")


def _real_cpu_project(tmp_path, rows, *, ic_class="processor_cpu",
                      anchor=True):
    """A project whose L3 AND L10 both come from the real Phase-1 emitters."""
    l3 = _emit_real_l3(tmp_path, rows)
    cases = _emit_real_l10(tmp_path, l3)
    sim = tmp_path / "phase2" / "stage1" / "sim"
    (sim / "tb").mkdir(parents=True, exist_ok=True)
    (sim / "tb" / "tb_dummy.v").write_text("module tb;\nendmodule\n")
    (sim / "work").mkdir(parents=True, exist_ok=True)
    (sim / "work" / "summary.txt").write_text("")
    if anchor:
        (sim / "results.xml").write_text(
            "<results><verdict>CONNECTIVITY_PASS</verdict>"
            "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
            "</results>")
    if ic_class is not None:
        (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
        (tmp_path / "reports" / "ic_class.json").write_text(
            json.dumps({"ic_class": ic_class}))
    return l3, cases, (tmp_path / "phase1" / "generated_docs"
                       / "L10_TEST_CASES.json"), sim


CPU_OPCODES = [{"name": "LOAD", "hex": "0x03"}, {"name": "STORE", "hex": "0x23"}]


# ---------------------------------------------------------------------------
# SHARED-DEFINITION PINS — the two constants this gate imports rather than owns
# ---------------------------------------------------------------------------
def test_response_template_keys_are_the_l3_gates_own():
    """ONE definition of where an opcode's reference output lives. Two readers
    of the same L3 field disagreeing about its name is the #761 defect one
    layer over, so this imports the OTHER reader and asserts equality."""
    l3rt = pytest.importorskip("l3_opcode_response_template_check")
    assert gate._RESPONSE_TEMPLATE_KEYS == l3rt._TEMPLATE_KEYS


def _reload_gate_with_import_blocked(monkeypatch, blocked):
    """Re-execute the gate module with `blocked` un-importable, so the
    import-failure FALLBACK literal is the one that runs."""
    import importlib.util
    real_import = __builtins__["__import__"] if isinstance(
        __builtins__, dict) else __builtins__.__import__

    def fake(name, *a, **kw):
        if name == blocked:
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", fake)
    spec = importlib.util.spec_from_file_location("_gate_nofallbackdeps",
                                                  str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_import_failure_fallback_is_the_same_key_set(monkeypatch):
    """…and the FALLBACK is pinned too. It is the branch that runs when the
    sibling module cannot be imported, so it is exactly the branch no in-process
    equality check reaches — which is how a fallback silently drifts from the
    definition it is supposed to mirror. This re-executes the module with the
    import blocked and compares what the fallback actually produced."""
    l3rt = pytest.importorskip("l3_opcode_response_template_check")
    fb = _reload_gate_with_import_blocked(
        monkeypatch, "l3_opcode_response_template_check")
    assert fb._l3rt is None, "fixture invalid: the import was not blocked"
    assert fb._RESPONSE_TEMPLATE_KEYS == l3rt._TEMPLATE_KEYS, (
        "the import-failure fallback has drifted from "
        "l3_opcode_response_template_check._TEMPLATE_KEYS")


def test_the_gate_and_the_flow_agree_about_a_concrete_golden():
    """`concrete_reference_output` must answer EXACTLY what the flow's own
    `design_one_shot_runner._golden_bytes_from_l3_opcode` answers — that
    function is what decides whether a full-stack vector can be scored, so a
    disagreement would mean the gate waives a case the flow could grade (or
    fails one it could not). Both are RUN, on the same inputs."""
    dr = pytest.importorskip("design_one_shot_runner")
    templates = [
        [{"byte_offset": 0, "value": "0x41"}],
        [{"byte_offset": 0, "value": 0x41}],
        # `isinstance(True, int)` — the flow reads this as 0x01, so this gate
        # must too. Diverging would be the FAIL-OPEN direction: an entry the
        # flow calls BOUND would become waivable here.
        [{"byte_offset": 0, "value": True}],
        [{"byte_offset": 0, "value": False}],
        [{"byte_offset": 0, "value": 0}],
        [{"byte_offset": 0, "value": "0x0"}],
        [{"byte_offset": 0, "value": 300}],
        [{"byte_offset": 0, "value": -1}],
        [{"byte_offset": 0, "value": None}],
        [{"byte_offset": 0, "value": ["0x41"]}],
        [{"byte_offset": 0, "value": "0x41"}, {"byte_offset": 1, "value": "0x02"}],
        [{"byte_offset": 0, "value": "0x41"}, {"byte_offset": 1, "source": "payload"}],
        [{"byte_offset": 0, "source": "crc8"}],
        [{"byte_offset": 0, "value": "notahex"}],
        [{"byte_offset": 0, "value": "0xZZ"}],
        [{"byte_offset": 0}],
        ["not a dict"],
        [],
        None,
        "response_payload_template",
    ]
    for tmpl in templates:
        assert (gate.concrete_reference_output(tmpl)
                == dr._golden_bytes_from_l3_opcode(
                    {"response_payload_template": tmpl})), tmpl


# ---------------------------------------------------------------------------
# THE HEADLINE: two BYTE-IDENTICAL expectations, split by the L-DOC
# ---------------------------------------------------------------------------
def test_the_real_emitters_split_two_byte_identical_expectations(tmp_path):
    """THE PROOF THAT THIS IS NOT ANOTHER TEXT CLASSIFIER.

    Phase 1's REAL `gen_l3_cmd_protocol` reads ONE command table and produces
    two opcodes whose response templates differ ONLY in whether every byte is a
    concrete literal; Phase 1's REAL `gen_l10_test_cases` then gives BOTH
    happy-path cases a BYTE-IDENTICAL `expected` string. No classifier over
    that string can separate them. Resolving the pointer in the design's own L3
    separates them by construction:

        0x40 tx_len=6 -> [{value 0x41}, {source payload}, {source crc8}]
                      -> no concrete golden -> UNBOUND -> WAIVED
        0x23 tx_len=1 -> [{value 0x24}]
                      -> concrete golden "24" -> BOUND  -> FAILs

    If this ever goes green with both cases on the same side, the fix has
    regressed to a fourth-round text heuristic."""
    l3, cases, l10, sim = _real_cpu_project(
        tmp_path, ["4\t6\t00\t40\tLOAD", "4\t1\t00\t23\tSTORE"])
    happy = {c["name"]: c for c in cases if c["kind"] == "happy_path"}
    assert set(happy) == {"send_load_happy", "send_store_happy"}, happy
    assert (happy["send_load_happy"]["expected"]
            == happy["send_store_happy"]["expected"] == EXP_DEFERRED), (
        "fixture invalid: the two expectations are no longer byte-identical, "
        "so this test no longer proves what it claims")

    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt")
    st = {r["id"]: r["status"] for r in data["results"]}
    res = {r["id"]: r["oracle_resolution"] for r in data["results"]}
    assert st["send_load_happy"] == "waived", (st, res)
    assert st["send_store_happy"] == "NOT_EXECUTED", (st, res)
    assert res["send_load_happy"] == "unbound:response_payload_template"
    assert res["send_store_happy"] == "bound:response_payload_template=24", (
        "the waiver must be refused ON THE DATA — naming BOTH the field that "
        "decided and the value it binds. Neither row here documents a response, "
        "so post-#812 the merge is a no-op and `24` is still the synthesised "
        "opcode+1 echo; the artefact must not imply the spec gave it")
    # …and the two declared-silence cases keep FAILing, from both opcodes.
    assert st["send_load_no_wake"] == st["send_store_no_wake"] == "NOT_EXECUTED"
    assert (data["not_executed"], data["waived"], rc) == (3, 1, 1), data
    assert data["cpu_oracle_binding_census"] == {
        "bound": 1, "unbound": 1, "absence": 2,
        "document_derived_records": "0/2"}, data


# ---------------------------------------------------------------------------
# r6's TRIPWIRE, FIRED — #812 landed and `response_payload_template` now
# TRACKS the design's document
# ---------------------------------------------------------------------------
def test_the_stamped_template_now_tracks_the_document(tmp_path):
    """r6's OWN MEASUREMENT, RE-RUN AND INVERTED.

    This test used to be `test_the_stamped_template_carries_no_information_
    about_the_design` and asserted `len(set(stamped)) == 1`. Its docstring left
    a tripwire: *"If this ever goes red because the stamped field started
    tracking the document, the upstream defect has been fixed and the
    `bound_by_document` arm below can be reconsidered — but not before."* It
    went red against #812. The arm was reconsidered — see
    `test_812_did_not_retire_the_bound_by_document_arm`, which measures it —
    and this assertion is repointed at the post-cure truth rather than pinned
    to the defect.

    PRE-#812 (history): `gen_l3_cmd_protocol`'s enrichment assigned the
    `tx_len`/`opcode+1` placeholder onto `response_payload_template`
    unconditionally, so three command tables whose DOCUMENTS differ produced a
    BYTE-IDENTICAL field — a field invariant across the documents, and
    therefore evidence about none of them.

    POST-#812: `_merge_response_payload_template` lets the document win every
    `byte_offset` it covers, so the same three documents now produce three
    DIFFERENT templates. The FIELD IS NOW EVIDENCE. The negative half is
    asserted too and is the load-bearing one: the document that says nothing
    still gets the placeholder, so the typed-shape guarantee survives the
    cure."""
    stamped = []
    extracted = []
    for i, rows in enumerate((
            [_documented_row(6, "40", ["0x41", "0xAA", "0xBB", "0xCC",
                                       "0xDD", "0x89"])],
            [_documented_row(6, "40", ["0x41", "0x11", "0x22", "0x33",
                                       "0x44", "0x55"])],
            ["4\t6\t00\t40\tLOAD"])):                 # no byte groups at all
        l3 = _emit_real_l3(tmp_path / f"doc{i}", rows)
        op = l3["opcodes"][0]
        stamped.append(json.dumps(op.get("response_payload_template")))
        extracted.append(json.dumps(op.get("response_payload_template_extracted")))

    assert len(set(extracted)) == 3, (
        f"fixture invalid: the three documents must differ: {extracted}")
    assert len(set(stamped)) == 3, (
        f"the canonical template must now VARY with the document — that is "
        f"#812. If this is back to 1 the merge has been reverted and the "
        f"`bound_by_document` arm is load-bearing again for the FULL case as "
        f"well as the partial one: {stamped}")
    # The two documented ones are fully concrete IN THE CANONICAL FIELD now —
    # "the spec gives no answer" was false of them all along, and after #812
    # the canonical field says so instead of hiding it in the sibling.
    assert gate.concrete_reference_output(json.loads(extracted[0])) \
        == "41,AA,BB,CC,DD,89"
    assert gate.concrete_reference_output(json.loads(stamped[0])) \
        == "41,AA,BB,CC,DD,89", (
        "post-#812 the canonical template must carry the document's bytes; "
        "if this is None again the merge is not running")
    # …and the NEGATIVE half: the document that gave nothing still gets the
    # untouched placeholder, so #812 did not cost the typed-shape guarantee.
    assert json.loads(extracted[2]) is None
    assert gate.concrete_reference_output(json.loads(stamped[2])) is None, (
        "an UNdocumented response must still resolve to no concrete golden, "
        "or the merge has started inventing bytes")
    assert {e["provenance"] for e in json.loads(stamped[2])} == {
        "synthesised_placeholder"}
    assert {e["provenance"] for e in json.loads(stamped[0])} == {"document"}


def test_a_documented_response_refuses_the_waiver_on_the_real_emitters(tmp_path):
    """THE r6 NEGATIVE CONTROL, on a `_real_cpu_project` row carrying BOTH byte
    groups.

    The document gives the response bytes; Phase 1 extracts them into
    `response_payload_template_extracted`; r5 resolved the (then-stamped)
    canonical field and WAIVED. A waiver justified by "the spec gives no
    answer" must not fire BECAUSE the spec gave one — least of all with the
    polarity that the better-documented the design, the more certainly it
    fires.

    #812 — the canonical field is no longer a placeholder here; the merge lets
    the document win all six offsets, so it now equals the sibling. The pin
    below is repointed at that: the refusal still fires, still through the
    `bound_by_document` arm, and the artefact still names the DOCUMENT's key —
    which is the part #812 does not make redundant, because a concrete
    canonical value alone cannot say whose byte it is."""
    l3, cases, l10, sim = _real_cpu_project(
        tmp_path, [_documented_row(6, "40", ["0x41", "0xAA", "0xBB", "0xCC",
                                             "0xDD", "0x89"])])
    op = l3["opcodes"][0]
    assert op.get("response_payload_template_extracted"), (
        "fixture invalid: the emitter did not extract the document's response "
        "bytes, so this control is not exercising r6 at all")
    assert gate.concrete_reference_output(
        op["response_payload_template"]) == "41,AA,BB,CC,DD,89", (
        "post-#812 the merge must have carried the document's six bytes into "
        "the canonical field; None here means the placeholder is being "
        "stamped over the document again")

    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt")
    st = {r["id"]: r["status"] for r in data["results"]}
    res = {r["id"]: r["oracle_resolution"] for r in data["results"]}
    assert st["send_load_happy"] == "NOT_EXECUTED", (st, res)
    assert res["send_load_happy"] == (
        "bound_by_document:response_payload_template_extracted="
        "41,AA,BB,CC,DD,89"), res
    assert (data["not_executed"], data["waived"], rc) == (2, 0, 1), data
    assert data["cpu_oracle_binding_census"] == {
        "bound_by_document": 1, "absence": 1,
        "document_derived_records": "1/1"}, data


def test_the_same_record_without_the_response_extraction_is_still_waivable(
        tmp_path):
    """ONE-VARIABLE CONTROL for the arm above: the identical table MINUS the
    response byte group, so the RECORD carries no document-derived response
    extraction and the waiver is reachable — which is what makes the refusal
    above attributable to that record and not to something incidental.

    ORGANIC #786 r7 — this test used to be named "…without_the_response_column"
    and its docstring said "now the document genuinely gives no reference
    output". THAT INFERENCE IS THE DEFECT r7 fixes: the extraction that would
    record one runs at one of seven opcode-construction sites, so its absence is
    equally consistent with a document that states the response somewhere the
    extractor does not look. The waiver is still reachable here — that is
    deliberate, and declining to gate it on a sibling opcode's extraction is
    argued in the r7 block — but the claim is now about the RECORD, and the
    census asserted below is what makes the missing input legible."""
    l3, cases, l10, sim = _real_cpu_project(tmp_path, ["4\t6\t00\t40\tLOAD"])
    assert "response_payload_template_extracted" not in l3["opcodes"][0]
    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt")
    st = {r["id"]: r["status"] for r in data["results"]}
    assert st["send_load_happy"] == "waived", data
    assert data["cpu_oracle_binding_census"] == {
        "unbound": 1, "absence": 1, "document_derived_records": "0/1"}, (
        "the waiver fired with ZERO document-derived records in the whole L3 — "
        "the number that says so must be on the artefact")


def test_a_single_group_row_files_the_document_bytes_as_the_request(tmp_path):
    """THE r7 DEFECT, at its source. `_extract_hex_byte_groups` is POSITIONAL:
    the caller takes group[0] as the request and group[1] as the response. A
    row whose ONLY byte group is the RESPONSE therefore has those bytes filed
    as `request_payload_template`, and no sibling is written — so r6's
    `bound_by_document` arm never fired and the case was WAIVED with the
    document's own bytes sitting in the dict the gate had just read."""
    l3 = _emit_real_l3(tmp_path, [
        "4\t6\t00\t40\t[0x41,0xAA,0xBB,0xCC,0xDD,0x89]\tLOAD word"])
    op = l3["opcodes"][0]
    assert "response_payload_template_extracted" not in op, (
        "fixture invalid: a sibling was written, so this is not the "
        "single-group row this test is about")
    assert gate.concrete_reference_output(
        op["request_payload_template"]) == "41,AA,BB,CC,DD,89", (
        "fixture invalid: the document's bytes are not on the entry")
    assert gate.document_reference_output(op) == (None, None)
    # …and the gate must REFUSE rather than book "the document said nothing".
    assert gate.unattributable_byte_record(op) == "request_payload_template"
    c = {"opcode_hex": "0x40", "expected": EXP_DEFERRED}
    verdict, detail = gate.resolve_case_oracle(c, l3["opcodes"])
    assert verdict == "byte_record_unattributed", (verdict, detail)
    assert "request_payload_template" in detail
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", l3["opcodes"]) is False


def test_the_single_group_row_no_longer_reaches_PASS_WITH_WAIVERS(tmp_path):
    """…and at the LAYER VERDICT, which is where it was blocking. r6 turned
    `origin/main`'s rc=1 into rc=3 PASS_WITH_WAIVERS for a design whose
    document states the response bytes."""
    l3, cases, l10, sim = _real_cpu_project(tmp_path, [
        "4\t6\t00\t74\t[0x75,0xAA,0xBB,0xCC,0xDD,0x89]\tGET_ID"])
    assert [c["kind"] for c in cases] == ["happy_path"], (
        f"fixture invalid: {[c['kind'] for c in cases]}")
    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt")
    assert (data["not_executed"], data["waived"], rc) == (1, 0, 1), data
    assert data["results"][0]["oracle_resolution"].startswith(
        "byte_record_unattributed:"), data


@pytest.mark.parametrize("key", ["request_payload_template"])
def test_every_positional_byte_group_key_refuses(key):
    """MUTATION GUARD, driven from a LITERAL. Each member of
    `_POSITIONAL_BYTE_GROUP_KEYS` must individually refuse."""
    assert key in gate._POSITIONAL_BYTE_GROUP_KEYS
    c = {"opcode_hex": "0x03", "expected": EXP_DEFERRED}
    l3 = [dict(_unbound_op("0x03"), **{key: [{"value": "0x41"}]})]
    assert gate.resolve_case_oracle(c, l3)[0] == "byte_record_unattributed"
    assert gate.is_cpu_instruction_oracle_case(c, "processor_cpu", l3) is False


def test_positional_key_set_matches_what_this_file_covers():
    assert set(gate._POSITIONAL_BYTE_GROUP_KEYS) == {"request_payload_template"}


def test_a_document_sibling_outranks_an_unattributed_record():
    """ORDER: when BOTH groups were found, the sibling exists and the more
    informative refusal must be the one reported — the reader needs to see the
    document's response bytes, not "the record cannot say"."""
    entry = dict(_unbound_op("0x03"),
                 request_payload_template=[{"value": "0x40"}],
                 response_payload_template_extracted=[{"value": "0x41"}])
    verdict, detail = gate.resolve_case_oracle(
        {"opcode_hex": "0x03", "expected": EXP_DEFERRED}, [entry])
    assert verdict == "bound_by_document", (verdict, detail)
    assert detail == "response_payload_template_extracted=41"


def test_the_waiver_sentence_claims_the_record_not_the_document(tmp_path):
    """r7 SCOPE. Absence of the extraction does not establish what the DOCUMENT
    said, so the waiver may not say it does. The shipped sentence used to read
    "the spec gives no answer to check against"; it must now claim the RECORD
    and name the unestablished part out loud."""
    l10, tb, summary = _make_project(tmp_path, _deferred_cases())
    rc, data = _run(tmp_path, l10, tb, summary)
    assert data["waived"] == 2, "fixture invalid: the waiver did not fire"
    for r in data["results"]:
        line = " ".join(r["evidence"])
        assert "NOT ESTABLISHED HERE" in line, line
        assert "no document-derived response extraction" in line, line
        assert "spec gives no answer" not in line, (
            "the over-claim r7 removed is back")
        assert "fact read off the design's document" not in line, line


def test_the_census_reports_how_much_input_the_refusal_arm_had(tmp_path):
    """A refusal arm SKIPPED because its input is absent looks identical, from
    the verdict alone, to one that ran and found nothing — and the input is
    absent on 100% of the corpus. `document_derived_records` is the number that
    tells those apart, so it must be on the artefact next to every waiver."""
    l10, tb, summary = _make_project(tmp_path, _deferred_cases())
    rc, data = _run(tmp_path, l10, tb, summary)
    assert data["cpu_oracle_binding_census"]["document_derived_records"] == "0/2"
    # …and it counts, rather than being a constant string.
    l3 = [dict(_unbound_op("0x03"),
               response_payload_template_extracted=[{"value": "0x41"}]),
          _unbound_op("0x23")]
    assert gate.document_record_provenance(l3) == "1/2"
    assert gate.document_record_provenance([]) == "0/0"
    assert gate.document_record_provenance(None) == "0/0"


def test_extracted_key_set_is_derived_from_the_shared_one():
    """The document-derived keys are DERIVED, never hand-listed, so they cannot
    drift from `_RESPONSE_TEMPLATE_KEYS` the way the gate and the emitter
    already drifted once."""
    assert gate._EXTRACTED_TEMPLATE_KEYS == tuple(
        k + "_extracted" for k in gate._RESPONSE_TEMPLATE_KEYS)
    assert len(gate._EXTRACTED_TEMPLATE_KEYS) == len(
        gate._RESPONSE_TEMPLATE_KEYS)
    # every one of them individually refuses
    for key in gate._EXTRACTED_TEMPLATE_KEYS:
        c = {"opcode_hex": "0x03", "expected": EXP_DEFERRED}
        l3 = [dict(_unbound_op("0x03"), **{key: [{"value": "0x41"}]})]
        assert gate.resolve_case_oracle(c, l3)[0] == "bound_by_document", key
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", l3) is False, key


def test_a_document_record_refuses_on_PRESENCE_not_on_concreteness():
    """The refusal keys on the key EXISTING, not on this file's concreteness
    contract. `_byte_list_to_payload_template` is called only when the row
    yielded response bytes, so presence already means "the document gave
    response bytes for this opcode" — making the refusal depend on
    concreteness would be a weaker guarantee for no gain."""
    for value in ([{"value": "0x41"}], [{"source": "payload"}], [], None,
                  "see table 5", [{"byte_offset": 0}]):
        c = {"opcode_hex": "0x03", "expected": EXP_DEFERRED}
        l3 = [dict(_unbound_op("0x03"),
                   response_payload_template_extracted=value)]
        verdict, detail = gate.resolve_case_oracle(c, l3)
        assert verdict == "bound_by_document", (value, verdict)
        assert "response_payload_template_extracted" in detail
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", l3) is False, value


def test_the_document_is_consulted_BEFORE_the_synthesised_sibling(tmp_path):
    """ORDER GUARD, on the REAL emitters, repointed to the post-#812 truth.

    A `tx_len=1` row whose DOCUMENT gives a response byte of `0x99`. PRE-#812
    Phase 1 stamped `[{value: 0x41}]` — the synthesised `opcode+1` echo — over
    `response_payload_template` and put the document's `0x99` in the extracted
    sibling, so the two fields DISAGREED and reading the wrong one printed
    `41`, a golden the document explicitly contradicts.

    POST-#812 the merge lets the document win offset 0, so the canonical field
    is now `99` — THE DOCUMENTED BYTE RATHER THAN THE SYNTHESISED ECHO, which
    is the whole point of the cure. The two fields agree, so on THIS fixture
    the order is no longer observable through the bytes; what it still decides
    is WHICH KEY the artefact names, and that is what is pinned here.
    `test_a_pre_812_l3_still_makes_the_order_load_bearing` keeps the
    bytes-level guard alive on the shape that still exhibits it."""
    l3 = _emit_real_l3(tmp_path, [_documented_row(1, "40", ["0x99"])])
    op = l3["opcodes"][0]
    assert gate.concrete_reference_output(
        op["response_payload_template"]) == "99", (
        "post-#812 the canonical field must be the DOCUMENTED byte 99, not "
        "the synthesised opcode+1 echo 41 — that substitution is the defect "
        "#812 cures")
    assert gate.concrete_reference_output(
        op["response_payload_template_extracted"]) == "99"

    c = {"opcode_hex": "0x40", "expected": EXP_DEFERRED}
    verdict, detail = gate.resolve_case_oracle(c, l3["opcodes"])
    assert verdict == "bound_by_document", (verdict, detail)
    assert detail == "response_payload_template_extracted=99", (
        f"the artefact quoted {detail!r} — the refusal must be attributed to "
        f"the DOCUMENT's own key. Post-#812 the canonical field holds the same "
        f"bytes, but a concrete value there may equally be the synthesised "
        f"echo, so naming `response_payload_template` would drop the one bit "
        f"of provenance the reader needs")
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", l3["opcodes"]) is False


def test_a_pre_812_l3_still_makes_the_order_load_bearing():
    """THE ORDER GUARD'S SURVIVING SUBJECT: an L3 written BEFORE #812.

    The cure changed the EMITTER, not the artefacts already on disk. A
    pre-#812 `L3_CMD_PROTOCOL.json` — and the tracked corpus is 107 such
    documents — still carries the placeholder stamped over a documented
    response, so its two fields still DISAGREE and reading the wrong one still
    prints a golden the document contradicts. This gate reads whatever L3 is on
    disk, so the guard is not historical.

    Hand-built rather than emitter-driven ON PURPOSE: the post-#812 emitter can
    no longer produce this shape, and a test that quietly re-derived its
    fixture from the fixed emitter would be asserting nothing."""
    entry = {"hex": "0x40", "name": "OP", "tx_len": 1,
             # what `gen_l3_cmd_protocol` wrote before the merge landed
             "response_payload_template": [{"byte_offset": 0, "value": "0x41"}],
             "response_payload_template_extracted": [
                 {"byte_offset": 0, "value": "0x99"}]}
    assert gate.concrete_reference_output(
        entry["response_payload_template"]) == "41"
    assert gate.concrete_reference_output(
        entry["response_payload_template_extracted"]) == "99", (
        "fixture invalid: the two fields must DISAGREE, or the order is not "
        "observable")

    c = {"opcode_hex": "0x40", "expected": EXP_DEFERRED}
    verdict, detail = gate.resolve_case_oracle(c, [entry])
    assert verdict == "bound_by_document", (verdict, detail)
    assert detail == "response_payload_template_extracted=99", (
        f"the artefact quoted {detail!r} — the document said 99 and the "
        f"synthesised echo said 41; a refusal must report the design's own "
        f"bytes, not Phase 1's placeholder")
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", [entry]) is False


def _without_the_positional_record(op):
    """The same entry minus `request_payload_template`.

    Needed to ISOLATE `bound_by_document`. On emitter output a response sibling
    only ever exists when a SECOND byte group was found, which means a FIRST one
    was found too and filed positionally as the request — so r7's
    `byte_record_unattributed` arm would catch the case regardless and mask
    whatever `bound_by_document` does or does not do. Stripping that one key
    leaves the shape a hand-written or third-party L3 has, where
    `bound_by_document` is on its own."""
    return {k: v for k, v in op.items() if k != "request_payload_template"}


def test_812_did_not_retire_the_bound_by_document_arm(tmp_path):
    """THE RECONSIDERATION r6's TRIPWIRE ASKED FOR — MEASURED, ARM BY ARM.

    r6 said the `bound_by_document` arm "can be reconsidered" once the canonical
    field started tracking the document. It has. The answer is that the arm
    STAYS, and this is the measurement rather than the opinion: each fixture is
    built by the REAL post-#812 emitter, then `document_reference_output` is
    neutered — which is exactly "the arm removed" — and the verdict is read
    back.

      FULL doc (6 of 6 bytes)  arm off -> `bound`, still refused, and its detail
        is now TRUE. #812 DID make the arm redundant FOR THE VERDICT here.
      PARTIAL doc (2 of 6)     arm off -> `unbound`, WAIVED. The merge leaves
        `source` placeholders in the gaps, so `concrete_reference_output`
        answers None and `bound` cannot fire — a waiver justified by "the record
        binds no reference output" would fire on an opcode whose document stated
        41,99. #812 did NOT close this. This is the arm's residual population.
      NO doc                   arm off -> `unbound`, WAIVED, byte-identical
        either way. Nothing about the waiver's reachability depends on the arm.

    So the redundancy #812 creates is on the FULL case only, and removing the
    arm on the strength of it would re-open the exact defect r6 closed, one
    fixture over."""
    fixtures = {}
    for tag, rows in (
            ("full", [_documented_row(6, "40", ["0x41", "0xAA", "0xBB", "0xCC",
                                                "0xDD", "0x89"])]),
            ("partial", [_documented_row(6, "40", ["0x41", "0x99"])]),
            ("none", ["4\t6\t00\t40\tLOAD"])):
        op = _emit_real_l3(tmp_path / tag, rows)["opcodes"][0]
        fixtures[tag] = _without_the_positional_record(op)

    # The fixtures are what the docstring says they are — asserted, not assumed.
    assert gate.concrete_reference_output(
        fixtures["full"]["response_payload_template"]) == "41,AA,BB,CC,DD,89"
    assert gate.concrete_reference_output(
        fixtures["partial"]["response_payload_template"]) is None, (
        "fixture invalid: a PARTIALLY documented response must still leave "
        "`source` placeholders in the merged template, or it is not the case "
        "this test exists for")
    assert gate.concrete_reference_output(
        fixtures["partial"]["response_payload_template_extracted"]) == "41,99"
    assert "response_payload_template_extracted" not in fixtures["none"]

    c = {"opcode_hex": "0x40", "expected": EXP_DEFERRED}
    live = {t: gate.resolve_case_oracle(c, [e])[0]
            for t, e in fixtures.items()}
    assert live == {"full": "bound_by_document",
                    "partial": "bound_by_document",
                    "none": "unbound"}, live

    real = gate.document_reference_output
    try:
        gate.document_reference_output = lambda entry: (None, None)
        off = {t: gate.resolve_case_oracle(c, [e])
               for t, e in fixtures.items()}
        waived_off = {t: gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", [e]) for t, e in fixtures.items()}
    finally:
        gate.document_reference_output = real

    assert off["full"][0] == "bound", off["full"]
    assert off["full"][1] == "response_payload_template=41,AA,BB,CC,DD,89", (
        "…and post-#812 that detail is TRUE, which it was not before the cure")
    assert waived_off["full"] is False

    assert off["partial"][0] == "unbound", off["partial"]
    assert waived_off["partial"] is True, (
        "REMOVING THE ARM MUST STILL LOSE A REFUSAL. If this is False the "
        "partial case is being caught elsewhere and the arm really can go — "
        "check `bound` before believing it")

    assert off["none"][0] == "unbound"
    assert waived_off["none"] is True

    # …and with the arm LIVE the partial case is refused, naming the document.
    verdict, detail = gate.resolve_case_oracle(c, [fixtures["partial"]])
    assert (verdict, detail) == (
        "bound_by_document", "response_payload_template_extracted=41,99")
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", [fixtures["partial"]]) is False


def test_the_waiver_still_fires_when_the_document_gives_NOTHING(tmp_path):
    """THE NEGATIVE CONTROL, AT THE LAYER VERDICT — the case the arm exists for.

    Every refusal added by r6/r7 and every consequence of #812 moves in the
    WITHHOLDING direction, so the risk they carry is that the waiver stops being
    reachable at all and `cap:cpu_functional_oracle` quietly becomes dead. This
    drives the REAL emitters over a command table that documents NO response
    bytes and asserts the whole gate still books the case WAIVED-DEFERRED —
    same verdict, same census, same rc as before the cure.

    #812 must not have touched this path, and the assertions below are the
    proof: no extraction to merge means the placeholder stands unchanged, so
    `unbound` is reached exactly as it was."""
    l3, cases, l10, sim = _real_cpu_project(tmp_path, ["4\t6\t00\t40\tLOAD"])
    op = l3["opcodes"][0]
    assert "response_payload_template_extracted" not in op, (
        "fixture invalid: the document must give NOTHING for this control")
    assert gate.concrete_reference_output(
        op["response_payload_template"]) is None
    assert {e.get("provenance") for e in op["response_payload_template"]} == {
        "synthesised_placeholder"}, (
        "#812 tags what it merged; an undocumented response must be ALL "
        "placeholder or the merge is inventing document bytes")

    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt")
    st = {r["id"]: r["status"] for r in data["results"]}
    res = {r["id"]: r["oracle_resolution"] for r in data["results"]}
    assert st["send_load_happy"] == "waived", (st, res)
    assert res["send_load_happy"] == "unbound:response_payload_template"
    assert (data["not_executed"], data["waived"], rc) == (1, 1, 1), data
    assert data["cpu_oracle_binding_census"] == {
        "unbound": 1, "absence": 1, "document_derived_records": "0/1"}, data


def test_the_bound_detail_names_the_field_that_decided():
    """r5 printed `bound:41` for a golden the document never gave — the
    synthesised `opcode+1` echo. The verdict was fail-closed but the REASON was
    false, so the artefact must name WHICH field decided rather than assert
    "the spec gives this answer" on this gate's say-so."""
    c = {"opcode_hex": "0x03", "expected": EXP_DEFERRED}
    verdict, detail = gate.resolve_case_oracle(c, [_bound_op("0x03")])
    assert verdict == "bound"
    assert detail == "response_payload_template=41", detail


def test_the_same_case_flips_when_only_the_l3_changes(tmp_path):
    """ONE-VARIABLE CONTROL. Byte-identical L10 cases; the ONLY difference is
    what the design's own L3 binds. If the verdicts do not move, the gate is
    not reading L3."""
    cases = [{"name": "send_op_happy", "kind": "happy_path",
              "expected": EXP_DEFERRED, "opcode_hex": "0x03",
              "evidence": "L3.opcodes"}]
    a = tmp_path / "unbound"
    l10, tb, summary = _make_project(a, cases, l3_opcodes=[_unbound_op("0x03")])
    rc_a, data_a = _run(a, l10, tb, summary)
    b = tmp_path / "bound"
    l10, tb, summary = _make_project(b, cases, l3_opcodes=[_bound_op("0x03")])
    rc_b, data_b = _run(b, l10, tb, summary)
    assert (data_a["waived"], data_a["not_executed"], rc_a) == (1, 0, 3), data_a
    assert (data_b["waived"], data_b["not_executed"], rc_b) == (0, 1, 1), data_b


# ---------------------------------------------------------------------------
# Unit level — resolve_case_oracle: every arm, and which of them can WAIVE
# ---------------------------------------------------------------------------
#: EVERY verdict `resolve_case_oracle` can return, written out here rather than
#: read back out of the gate, together with whether it may reach the waiver.
#: Exactly one may. A new verdict with no entry here is an unreviewed widening.
ORACLE_VERDICTS = {
    "pinned": False,
    "absence": False,
    "no_l3": False,
    "opcode_unresolved": False,
    "bound_by_document": False,
    "byte_record_unattributed": False,
    "bound": False,
    "reference_not_named": False,
    "unbound": True,
}


def test_only_unbound_can_reach_the_waiver():
    """The invariant, as a test: `cpu_instruction_oracle_reference` honours
    exactly ONE `resolve_case_oracle` verdict, and the gate names it."""
    waivable = {v for v, ok in ORACLE_VERDICTS.items() if ok}
    assert waivable == {"unbound"}
    assert gate._WAIVABLE_RESOLUTION == "unbound"


def test_every_resolution_arm_carries_a_detail():
    """Every arm must SAY WHY on the artefact — and it is also what keeps the
    arms mutation-distinguishable. If the refusing arms returned a bare None, a
    predicate mutated to honour one of them would still not waive (there would
    be no reference to hand back) and the mutant would survive as an
    equivalent: a guard nothing can test."""
    probes = [
        ({"expected": EXP_DEFERRED, "opcode_hex": "0x03",
          "expected_bytes": "41"}, [_unbound_op("0x03")]),
        ({"expected": EXP_ABSENCE, "opcode_hex": "0x03"}, [_unbound_op("0x03")]),
        ({"expected": EXP_DEFERRED, "opcode_hex": "0x03"}, None),
        ({"expected": EXP_DEFERRED, "opcode_hex": "0x99"}, [_unbound_op("0x03")]),
        ({"expected": EXP_DEFERRED, "opcode_hex": "0x03"},
         [dict(_unbound_op("0x03"),
               response_payload_template_extracted=[{"value": "0x41"}])]),
        ({"expected": EXP_DEFERRED, "opcode_hex": "0x03"},
         [dict(_unbound_op("0x03"),
               request_payload_template=[{"value": "0x40"}])]),
        ({"expected": EXP_DEFERRED, "opcode_hex": "0x03"}, [_bound_op("0x03")]),
        ({"expected": "holds 0x2A", "opcode_hex": "0x03"}, [_unbound_op("0x03")]),
        ({"expected": EXP_DEFERRED, "opcode_hex": "0x03"}, [_unbound_op("0x03")]),
    ]
    seen = set()
    for case, l3 in probes:
        verdict, detail = gate.resolve_case_oracle(case, l3)
        seen.add(verdict)
        assert detail, (verdict, case)
    assert seen == set(ORACLE_VERDICTS), (
        "a verdict with no probe here is an unreviewed arm")


def test_a_case_with_no_instruction_signal_cannot_resolve():
    """The instruction-signal requirement, at its ONE enforcement point.
    `opcode_entry_for_case` reads `_INSTRUCTION_SIGNAL_FIELDS`; a case carrying
    none of them (or only falsy values) matches no L3 entry, so it lands on the
    `opcode_unresolved` arm and can never be waived — whatever its prose says
    and whatever the L3 binds."""
    l3 = [_unbound_op("0x03"), dict(_unbound_op("x"), hex="0x00")]
    for c in ({"kind": "happy_path", "expected": EXP_DEFERRED},
              {"kind": "happy_path", "expected": EXP_DEFERRED,
               "address": "0x03"},
              {"kind": "happy_path", "expected": EXP_DEFERRED,
               "opcode_hex": ""},
              {"kind": "happy_path", "expected": EXP_DEFERRED,
               "opcode_hex": None},
              {"kind": "happy_path", "expected": EXP_DEFERRED,
               "opcode_hex": 0}):
        assert gate.opcode_entry_for_case(c, l3) is None, c
        assert gate.resolve_case_oracle(c, l3)[0] == "opcode_unresolved", c
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", l3) is False, c


@pytest.mark.parametrize("verdict,case,l3", [
    ("pinned", {"expected": EXP_DEFERRED, "opcode_hex": "0x03",
                "expected_bytes": "41,02"}, [_unbound_op("0x03")]),
    ("absence", {"expected": EXP_ABSENCE, "opcode_hex": "0x03"},
     [_unbound_op("0x03")]),
    ("no_l3", {"expected": EXP_DEFERRED, "opcode_hex": "0x03"}, None),
    ("opcode_unresolved", {"expected": EXP_DEFERRED, "opcode_hex": "0x99"},
     [_unbound_op("0x03")]),
    ("bound_by_document", {"expected": EXP_DEFERRED, "opcode_hex": "0x03"},
     [dict(_unbound_op("0x03"),
           response_payload_template_extracted=[{"value": "0x41"}])]),
    ("byte_record_unattributed",
     {"expected": EXP_DEFERRED, "opcode_hex": "0x03"},
     [dict(_unbound_op("0x03"),
           request_payload_template=[{"value": "0x40"}])]),
    ("bound", {"expected": EXP_DEFERRED, "opcode_hex": "0x03"},
     [_bound_op("0x03")]),
    ("reference_not_named",
     {"expected": "register file holds 0x2A", "opcode_hex": "0x03"},
     [_unbound_op("0x03")]),
    ("unbound", {"expected": EXP_DEFERRED, "opcode_hex": "0x03"},
     [_unbound_op("0x03")]),
])
def test_every_resolution_arm_and_its_waiver_consequence(verdict, case, l3):
    got, _ = gate.resolve_case_oracle(case, l3)
    assert got == verdict, (got, case)
    assert (gate.is_cpu_instruction_oracle_case(case, "processor_cpu", l3)
            is ORACLE_VERDICTS[verdict])


def test_an_empty_l3_opcode_list_is_not_a_missing_l3():
    """`None` (no readable L3) and `[]` (an L3 that declares no opcodes) are
    different facts and the artefact must be able to say which. Both refuse the
    waiver; only one of them means the pointer could not be read at all."""
    c = {"expected": EXP_DEFERRED, "opcode_hex": "0x03"}
    assert gate.resolve_case_oracle(c, None)[0] == "no_l3"
    assert gate.resolve_case_oracle(c, [])[0] == "opcode_unresolved"


def test_the_pointer_resolves_across_opcode_notations():
    """The L10 case and the L3 entry are written by different emitters, so the
    pointer must not fail to resolve on NOTATION — that would silently turn
    every case into `opcode_unresolved` and make the waiver unreachable for a
    reason nobody could see."""
    for l3_form in ("0x03", "0X03", "03", "3"):
        for case_form in ("0x03", "0X03", "03", "3", "8'h03"):
            c = {"expected": EXP_DEFERRED, "opcode_hex": case_form}
            l3 = [dict(_unbound_op("x"), hex=l3_form)]
            assert gate.resolve_case_oracle(c, l3)[0] == "unbound", (
                l3_form, case_form)
    # …and a DIFFERENT byte must still not resolve.
    assert gate.resolve_case_oracle(
        {"expected": EXP_DEFERRED, "opcode_hex": "0x04"},
        [_unbound_op("0x03")])[0] == "opcode_unresolved"


def test_load_l3_opcodes_fails_closed_on_every_unreadable_shape(tmp_path):
    """A missing / malformed / non-dict L3 must answer None (fails CLOSED), and
    a readable L3 with no `opcodes` must answer `[]` — never a fabricated
    entry, which would be an oracle this gate invented."""
    assert gate.load_l3_opcodes(None) is None
    assert gate.load_l3_opcodes(str(tmp_path)) is None          # no phase1/
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    assert gate.load_l3_opcodes(str(tmp_path)) is None          # no L3_*.json
    p = gd / "L3_CMD_PROTOCOL.json"
    for body in ("{not json", '["a list, not a dict"]'):
        p.write_text(body)
        assert gate.load_l3_opcodes(str(tmp_path)) is None, body
    for body in ("{}", '{"opcodes": null}', '{"opcodes": "not a list"}'):
        p.write_text(body)
        assert gate.load_l3_opcodes(str(tmp_path)) == [], body
    p.write_text('{"opcodes": [{"hex": "0x03"}, "junk", 7]}')
    assert gate.load_l3_opcodes(str(tmp_path)) == [{"hex": "0x03"}]
    # the `fields`-nested payload shape some emitters write
    p.write_text('{"fields": {"opcodes": [{"hex": "0x05"}]}}')
    assert gate.load_l3_opcodes(str(tmp_path)) == [{"hex": "0x05"}]


# ---------------------------------------------------------------------------
# D1 — the prose probes the previous round's text classifier failed OPEN on
# ---------------------------------------------------------------------------
#: Ordinary engineering prose in which "per" means FOR EACH, or which defers to
#: something that is not a reference OUTPUT at all. Every one of these was
#: classified `deferred` -> WAIVED by the previous round's
#: `_DEFERRED_SPEC_REFERENCE_RE`. Each is a complete, observable assertion: the
#: gate must FAIL the case, not waive it.
#:
#: The last six are LIFTED FROM THIS REPO'S OWN CORPUS — the exact strings
#: `benchmark-data/**/phase1/generated_docs/L*.json` carries — so this is not a
#: hand-picked adversarial set.
DISTRIBUTIVE_PROSE = (
    "one byte per clock_cycle on the bus",
    "8 bits shifted out per sclk_edge",
    "PC increments per instr_retire",
    "energy per switching_event below 1pJ",
    "output updated per t_setup and t_hold",
    "one superframe transmitted per audio_sample_period",
    "behaviour as specified in spec.pdf",
    "confirm with owner per john.doe@example.com",
    "DUT replies per the datasheet",
    "one byte per cycle",
    "register file holds 0x2A after execution",
    "irq asserted within 3 cycles",
    "Optional 1 bit; even, odd, mark, or space per LCR.EPS/STICK.",
    "1, 1.5, or 2 bit-times HIGH (mark) per LCR.STB.",
    "auto-incremented per CSW.AddrInc.",
    "Internal counter incremented per TSCC.TCP",
    "SII EEPROM has valid ESI per ETG.2000; SII checksum correct.",
    "polarity per ON_OFF_CONFIG",
)


@pytest.mark.parametrize("expected", DISTRIBUTIVE_PROSE)
def test_distributive_prose_is_not_a_deferral(expected):
    """"per" almost always means FOR EACH, and a snake_case signal name is the
    commonest noun in RTL prose. None of these names a reference OUTPUT, so
    none of them is a deferral — each is a complete assertion the testbench
    owes evidence for, and the case FAILs.

    Driven against the MOST permissive L3 possible (the opcode resolves and
    binds nothing), so the only thing that can save these cases from the
    waiver is the requirement that the expectation name the reference."""
    c = {"kind": "happy_path", "opcode_hex": "0x03", "expected": expected}
    l3 = [_unbound_op("0x03")]
    assert gate.resolve_case_oracle(c, l3)[0] == "reference_not_named", expected
    assert gate.is_cpu_instruction_oracle_case(c, "processor_cpu", l3) is False


def test_distributive_prose_still_fails_end_to_end(tmp_path):
    """…and the same set, driven through the whole gate on a processor_cpu
    under the anchor. The POSITIVE CONTROL rides along so the test cannot pass
    by the cases being un-waivable for some unrelated reason."""
    cases = [{"name": f"prose_{i}", "kind": "happy_path", "opcode_hex": "0x03",
              "expected": e} for i, e in enumerate(DISTRIBUTIVE_PROSE)]
    cases.append({"name": "positive_control", "kind": "happy_path",
                  "opcode_hex": "0x03", "expected": EXP_DEFERRED})
    l10, tb, summary = _make_project(tmp_path, cases,
                                     l3_opcodes=[_unbound_op("0x03")])
    rc, data = _run(tmp_path, l10, tb, summary)
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["positive_control"]["status"] == "waived", (
        "fixture invalid: the waiver is unreachable here, so the FAILs below "
        "prove nothing")
    assert data["not_executed"] == len(DISTRIBUTIVE_PROSE), data
    assert data["waived"] == 1 and rc == 1


def test_a_waiver_may_only_cite_a_field_the_entry_actually_declares():
    """r6 SECONDARY. `_names_a_reference_output` used to fall through from the
    entry's declared key to EVERY other member of `_RESPONSE_TEMPLATE_KEYS`, so
    a case saying "compare the reply against `response_bytes` in table 5" was
    waived against an entry that declares only `response_payload_template` —
    and the evidence line NAMED A FIELD THAT IS NOT THERE. Bounded by the L3
    arm, so never a leak, but it made "no text can GRANT the waiver" true for
    misses and false for false hits, and a reviewable waiver may not cite a
    field the design does not have."""
    entry = _unbound_op("0x03")            # declares response_payload_template
    assert "response_bytes" not in entry
    c = {"opcode_hex": "0x03",
         "expected": "compare the reply against response_bytes in table 5"}
    verdict, detail = gate.resolve_case_oracle(c, [entry])
    assert verdict == "reference_not_named", (verdict, detail)
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", [entry]) is False
    # …the DECLARED key still waives, so the narrowing is not a blanket refusal
    assert gate.resolve_case_oracle(
        {"opcode_hex": "0x03", "expected": EXP_DEFERRED}, [entry]) == (
        "unbound", "response_payload_template")
    # …and an entry declaring a DIFFERENT key waives against THAT name only
    other = {"hex": "0x03", "response_bytes": [{"source": "payload"}]}
    assert gate.resolve_case_oracle(c, [other]) == (
        "unbound", "response_bytes")
    assert gate.resolve_case_oracle(
        {"opcode_hex": "0x03", "expected": EXP_DEFERRED}, [other])[0] == (
        "reference_not_named")


def test_an_entry_declaring_no_template_key_can_name_nothing():
    """…and therefore cannot be waived at all. An L10 case pointing at a field
    its own L3 entry does not declare is two L-docs disagreeing, not a
    capability gap."""
    entry = {"hex": "0x03", "name": "OP"}
    for exp in (EXP_DEFERRED, "reply per response_bytes", EXP_DEFERRED_BOUNDARY):
        c = {"opcode_hex": "0x03", "expected": exp}
        verdict, detail = gate.resolve_case_oracle(c, [entry])
        assert verdict == "reference_not_named", (exp, verdict)
        assert detail == "(L3 declares no template)", detail
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", [entry]) is False


def test_the_reference_name_must_be_a_whole_identifier():
    """MUTATION GUARD. The containment test is EXACT-IDENTIFIER, not substring:
    a longer name that merely CONTAINS a template key is a different field, and
    crediting it would re-open the widening this change closed."""
    l3 = [_unbound_op("0x03")]
    for exp in ("DUT replies per my_response_payload_template_v2",
                "see xresponse_payload_template",
                "see response_payload_templates"):
        c = {"opcode_hex": "0x03", "expected": exp}
        assert gate.resolve_case_oracle(c, l3)[0] == "reference_not_named", exp
    c = {"opcode_hex": "0x03", "expected": "per response_payload_template."}
    assert gate.resolve_case_oracle(c, l3)[0] == "unbound"


def test_an_empty_expectation_fails_closed():
    """An expectation with no text is an oracle with no answer. It is not
    evidence that a MODEL is missing."""
    l3 = [_unbound_op("0x03")]
    for exp in ("", None, "   "):
        c = {"expected": exp, "opcode_hex": "0x03"}
        assert gate.resolve_case_oracle(c, l3)[0] == "reference_not_named", exp
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", l3) is False


# ---------------------------------------------------------------------------
# D3 — the ABSENCE guard, every alternative individually load-bearing
# ---------------------------------------------------------------------------
#: One probe per alternative of `_NO_OUTPUT_EXPECTATION_RE`. EVERY probe also
#: NAMES `response_payload_template`, so the ONLY thing standing between it and
#: the waiver is the absence alternative under test: delete that alternative
#: and the case turns `unbound` -> waived and the test goes red. The previous
#: round's `\bsilent\b` alternative was never exercised at all — every probe it
#: had also matched a different alternative and named no reference, so it could
#: be deleted with the whole suite green.
ABSENCE_ALTERNATIVES = {
    "silent": "DUT is silent although response_payload_template is declared",
    "no <output-noun>": ("no response is produced even though "
                         "response_payload_template is declared"),
    "must/shall not <verb>": ("DUT shall not reply, response_payload_template "
                              "notwithstanding"),
    "remains/stays idle": ("the bus remains idle; response_payload_template "
                           "is unused"),
    "no change": ("no change on the pins; response_payload_template is not "
                  "consulted"),
}


@pytest.mark.parametrize("label,expected", sorted(ABSENCE_ALTERNATIVES.items()))
def test_every_absence_alternative_is_individually_load_bearing(label, expected):
    c = {"kind": "happy_path", "opcode_hex": "0x03", "expected": expected}
    l3 = [_unbound_op("0x03")]
    assert gate._NO_OUTPUT_EXPECTATION_RE.search(expected), label
    assert gate.resolve_case_oracle(c, l3)[0] == "absence", label
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", l3) is False, label
    # …and the SAME text minus the absence claim IS waivable, so each probe is
    # proving the absence alternative and not something incidental.
    assert gate.is_cpu_instruction_oracle_case(
        {"kind": "happy_path", "opcode_hex": "0x03",
         "expected": "DUT replies per response_payload_template"},
        "processor_cpu", l3) is True


def test_an_absence_expectation_that_also_names_the_reference_is_not_waived(
        tmp_path):
    """D3, END-TO-END. The dangerous shape is an ABSENCE assertion that ALSO
    names a reference — `resolve_case_oracle` would find the L3 binding
    nothing, so only the absence guard stops it. Driven on a verdict, because a
    §4.05 rule that only ever ran in a unit call is a rule nobody has seen
    fire."""
    cases = [
        {"name": "silent_but_named",
         "kind": "happy_path", "opcode_hex": "0x03",
         "expected": ("DUT silent; response_payload_template does not apply "
                      "to this opcode")},
        {"name": "positive_control", "kind": "happy_path",
         "opcode_hex": "0x03", "expected": EXP_DEFERRED},
    ]
    l10, tb, summary = _make_project(tmp_path, cases,
                                     l3_opcodes=[_unbound_op("0x03")])
    rc, data = _run(tmp_path, l10, tb, summary)
    st = {r["id"]: r["status"] for r in data["results"]}
    assert st["silent_but_named"] == "NOT_EXECUTED", data
    assert st["positive_control"] == "waived", data


# ---------------------------------------------------------------------------
# D2 — the constant sets, written out as literals so they cannot self-shrink
# ---------------------------------------------------------------------------
#: The instruction-signal field names, WRITTEN OUT HERE rather than read back
#: out of the gate. Iterating `gate._INSTRUCTION_SIGNAL_FIELDS` would make the
#: test shrink with the set, so deleting a member would silently delete its own
#: coverage — a rule nothing enforces.
INSTRUCTION_SIGNAL_FIELDS = (
    "opcode_hex", "opcode", "instruction", "instr", "instruction_hex",
    "encoding_pattern",
)

#: The same discipline for the PINNED-golden fields. The previous round wrote
#: `for field in gate._PINNED_ORACLE_FIELDS:` — the exact self-shrinking shape
#: its own comment forbade twelve lines earlier — so dropping `expected_bytes`
#: (the field the flow itself populates, via `_golden_bytes_from_l3_opcode` ->
#: `expected_bytes`) survived the entire suite, silently turning a case that
#: carries its own concrete golden into a WAIVED one.
PINNED_ORACLE_FIELDS = (
    # G19 — the typed (inputs, expected_outputs) pair a `known_answer_vector`
    # carries. Registered here because this file's own rule says a new member
    # with no literal above would be an unexercised widening: it is now driven
    # through the predicate like every sibling, so removing it goes red.
    "expected_outputs",
    "expected_bytes", "expected_hex", "expected_value", "expected_output",
    "expected_result", "golden", "golden_bytes", "reference_output",
)

#: …and for the opcode-bearing field union (D5).
OPCODE_BEARING_FIELDS = (
    "opcode", "cmd", "cmd_hex", "cmd_byte",
    "opcode_hex", "instruction", "instr", "instruction_hex",
    "encoding_pattern",
)


@pytest.mark.parametrize("field", INSTRUCTION_SIGNAL_FIELDS)
def test_every_instruction_signal_field_is_individually_load_bearing(field):
    """MUTATION GUARD (signal-field set). Each field name is driven through the
    predicate from a LITERAL in this file, so removing any one member of
    `_INSTRUCTION_SIGNAL_FIELDS` turns a waived case back into a FAIL and this
    test goes red."""
    c = {"kind": "happy_path", "expected": EXP_DEFERRED, field: "0x03"}
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", [_unbound_op("0x03")]) is True, (
        f"{field!r} no longer makes a case an instruction-execution case")


def test_instruction_signal_set_matches_what_this_file_covers():
    """…and the set may not GROW without a test either: a new member with no
    literal above would be an unexercised widening of the waiver."""
    assert set(gate._INSTRUCTION_SIGNAL_FIELDS) == set(
        INSTRUCTION_SIGNAL_FIELDS)


@pytest.mark.parametrize("field", PINNED_ORACLE_FIELDS)
def test_every_pinned_oracle_field_is_individually_load_bearing(field):
    """MUTATION GUARD (pinned-golden set), driven from a LITERAL. A case that
    carries its own concrete golden has an oracle whatever its prose says and
    whatever L3 binds, so it is never waived — delete any member and this goes
    red."""
    c = {"expected": EXP_DEFERRED, field: "AA,BB", "opcode_hex": "0x03"}
    l3 = [_unbound_op("0x03")]
    assert gate.resolve_case_oracle(c, l3)[0] == "pinned", field
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", l3) is False, field


def test_pinned_oracle_set_matches_what_this_file_covers():
    assert set(gate._PINNED_ORACLE_FIELDS) == set(PINNED_ORACLE_FIELDS)


def test_a_pinned_golden_survives_end_to_end(tmp_path):
    """…on a verdict, not only at the unit boundary: the field the flow
    actually populates (`expected_bytes`) must keep its case FAILing when no
    testbench drove it, never turn it into a silent waiver."""
    cases = [{"name": "pinned_case", "kind": "happy_path",
              "opcode_hex": "0x03", "expected": EXP_DEFERRED,
              "expected_bytes": "41,02"},
             {"name": "positive_control", "kind": "happy_path",
              "opcode_hex": "0x03", "expected": EXP_DEFERRED}]
    l10, tb, summary = _make_project(tmp_path, cases,
                                     l3_opcodes=[_unbound_op("0x03")])
    rc, data = _run(tmp_path, l10, tb, summary)
    st = {r["id"]: r["status"] for r in data["results"]}
    assert st["pinned_case"] == "NOT_EXECUTED" and st["positive_control"] == "waived"


# ---------------------------------------------------------------------------
# D5 — the opcode-evidence field mismatch
# ---------------------------------------------------------------------------
def test_opcode_bearing_field_set_matches_what_this_file_covers():
    assert set(gate._OPCODE_BEARING_FIELDS) == set(OPCODE_BEARING_FIELDS)
    assert set(gate._INSTRUCTION_SIGNAL_FIELDS) <= set(
        gate._OPCODE_BEARING_FIELDS), (
        "the case that MAY reach the waiver must be able to earn TB evidence: "
        "an instruction-signal field the evidence reader cannot see is a case "
        "waived for a naming mismatch")


def test_case_has_opcode_evidence_reads_the_emitters_own_field():
    """THE DEFECT: `_INSTRUCTION_SIGNAL_FIELDS` admitted `opcode_hex` while
    `case_has_opcode_evidence` read only `opcode`/`cmd`/`cmd_hex`/`cmd_byte`,
    so every case Phase 1's emitter produces — all of which key the byte as
    `opcode_hex` — could not earn `opcode in tb` no matter what the testbench
    drove. Renaming the field flipped the identical case."""
    blob = "initial begin\n  drive_byte(8'h40);\nend\n"
    assert gate.case_has_opcode_evidence({"opcode_hex": "0x40"}, blob) is True
    assert gate.case_has_opcode_evidence({"opcode": "0x40"}, blob) is True
    # …and a byte the TB does NOT drive is still no evidence.
    assert gate.case_has_opcode_evidence({"opcode_hex": "0x23"}, blob) is False


def test_the_digital_signal_reader_sees_the_emitters_field_too(tmp_path):
    """§4.05 NO-LEAK, the OTHER reader. `_has_digital_signal` refuses the A/M
    and checklist relaxations for a case carrying a digital signal; while it
    read only `_CMD_OPCODE_FIELDS`, a case keyed `opcode_hex` — i.e. every case
    the emitter produces — could carry a spurious `kind=verification_intent`
    and be A/M-waived on an anchored --skip-analog. Both readers now share
    `_OPCODE_BEARING_FIELDS`, so the mislabel no longer works."""
    assert gate._has_digital_signal({"opcode_hex": "0x03"}, False) is True
    assert gate._has_digital_signal({"instruction_hex": "0x03"}, False) is True
    assert gate._has_digital_signal({"note": "hello"}, False) is False
    # END-TO-END on a verdict: the mislabelled case must still FAIL, while a
    # genuine A/M case beside it is still waived (so the test is not passing
    # by the A/M waiver being unreachable).
    cases = [{"name": "mislabelled_digital", "kind": "verification_intent",
              "opcode_hex": "0x03", "expected": "line/load regulation"},
             {"name": "genuine_am", "kind": "verification_intent",
              "expected": "line/load regulation within spec"}]
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    l10 = gd / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": cases}))
    sim = tmp_path / "phase2" / "stage1" / "sim"
    (sim / "tb").mkdir(parents=True)
    (sim / "tb" / "tb_dummy.v").write_text("module tb;\nendmodule\n")
    (sim / "work").mkdir(parents=True)
    (sim / "work" / "summary.txt").write_text("")
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict></results>")
    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt",
                    extra=["--skip-analog"])
    st = {r["id"]: r["status"] for r in data["results"]}
    assert st["genuine_am"] == "waived", data
    assert st["mislabelled_digital"] == "NOT_EXECUTED", data


def test_a_driven_opcode_case_passes_instead_of_being_waived(tmp_path):
    """END-TO-END. A processor_cpu happy-path case that was actually EXECUTED
    must PASS — execution evidence supersedes the capability gap.

    The evidence is now the execution record rather than the opcode literal
    appearing in testbench source: a driven byte in the TB text says the
    generator emitted a number, not that the vector ran. The guard this test
    exists for — evidence beats the waiver — is unchanged.
    """
    tb_text = ("module tb;\n  dut u(.clk(clk));\n"
               "  initial drive_byte(8'h03);\nendmodule\n")
    cases = [{"name": "send_load_happy", "kind": "happy_path",
              "opcode_hex": "0x03", "expected": EXP_DEFERRED}]
    l10, tb, summary = _make_project(tmp_path, cases, tb_text=tb_text,
                                     executed={"send_load_happy": "PASS"})
    rc, data = _run(tmp_path, l10, tb, summary)
    assert data["results"][0]["status"] == "pass", data
    assert any("EXECUTED+PASSED" in e for e in data["results"][0]["evidence"])
    assert (data["ok"], data["waived"], data["not_executed"], rc) == (1, 0, 0, 0)


# ---------------------------------------------------------------------------
# The other three gates (class / §4.05 category / instruction signal)
# ---------------------------------------------------------------------------
def test_predicate_fires_for_an_unbound_oracle_regardless_of_kind():
    """The criterion is the L-DOC BINDING, so it must NOT depend on the kind
    token — including `happy_path` and `pre_wake_false`, the two an earlier
    revision hard-coded."""
    unbound = [_unbound_op("0x03")]
    bound = [_bound_op("0x03")]
    for kind in ("happy_path", "pre_wake_false", "addr_max", "len_max",
                 "cmd_response", "error_path", "state_transition", ""):
        c = {"kind": kind, "opcode_hex": "0x03", "expected": EXP_DEFERRED}
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", unbound) is True, kind
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", bound) is False, kind
        absence = {"kind": kind, "opcode_hex": "0x03", "expected": EXP_ABSENCE}
        assert gate.is_cpu_instruction_oracle_case(
            absence, "processor_cpu", unbound) is False, kind


def test_predicate_class_gate_is_EXACT_equality():
    """MUTATION GUARD (class-gate exactness). `ic_class != 'processor_cpu'`
    must not survive being loosened to a substring / prefix / suffix test: a
    label that merely CONTAINS the token is a DIFFERENT class and the waiver is
    registered for one class only."""
    c = {"kind": "happy_path", "opcode_hex": "0x03", "expected": EXP_DEFERRED}
    l3 = [_unbound_op("0x03")]
    assert gate.is_cpu_instruction_oracle_case(c, "processor_cpu", l3) is True
    for other in ("digital_cmd_driven", "unknown_protocol_class",
                  "digital_arithmetic_primitive", "", "PROCESSOR_CPU",
                  "processor_cpu_wrapper", "soc_processor_cpu",
                  "processor_cpu ", "processor"):
        assert gate.is_cpu_instruction_oracle_case(c, other, l3) is False, other


def test_predicate_excludes_every_explicit_digital_class_token(tmp_path):
    """MUTATION GUARD (§4.05 exclusion). EVERY member of
    `_DIGITAL_CLASS_TOKENS` used as an EXPLICIT category must block the waiver
    — a genuine digital command the TB must exercise is never masked, even for
    a processor_cpu under the anchor. Driven END-TO-END as well as at the unit
    boundary, because a §4.05 rule that only ever ran in a unit call is a rule
    nobody has seen fire on a verdict."""
    assert gate._DIGITAL_CLASS_TOKENS, "the exclusion set must not be empty"
    l3 = [_unbound_op("0x03")]
    cases = []
    for i, token in enumerate(sorted(gate._DIGITAL_CLASS_TOKENS)):
        c = {"category": token, "opcode_hex": "0x03", "expected": EXP_DEFERRED}
        assert gate.is_cpu_instruction_oracle_case(
            c, "processor_cpu", l3) is False, (
            f"explicit category={token!r} reached the waiver")
        cases.append(dict(c, name=f"explicit_{i}_{token}"))
    # …and the SAME shape with no explicit category IS waivable, so the test
    # cannot pass by the cases being un-waivable for some other reason.
    cases.append({"name": "no_explicit_category", "kind": "happy_path",
                  "opcode_hex": "0x03", "expected": EXP_DEFERRED})
    l10, tb, summary = _make_project(tmp_path, cases, l3_opcodes=l3)
    rc, data = _run(tmp_path, l10, tb, summary)
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["no_explicit_category"]["status"] == "waived"
    assert data["not_executed"] == len(gate._DIGITAL_CLASS_TOKENS), (
        f"every explicitly-categorised digital case must still FAIL: {data}")
    assert rc == 1


def test_predicate_null_category_falls_through_to_type(tmp_path):
    """`dict.get(k, default)` returns the STORED None when the key EXISTS with
    a null value, so `case.get("category", case.get("type", ""))` never
    consults `type` for `{"category": null, "type": "cmd_response"}` — a
    genuine digital command that walked straight through the §4.05 exclusion.
    `explicit_class_token` coalesces properly."""
    c = {"category": None, "type": "cmd_response", "opcode_hex": "0x03",
         "expected": EXP_DEFERRED}
    assert gate.explicit_class_token(c) == "cmd_response"
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", [_unbound_op("0x03")]) is False
    # END-TO-END: the case must still FAIL.
    l10, tb, summary = _make_project(
        tmp_path, [dict(c, name="nullcat_cmd_response")])
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1 and data["not_executed"] == 1 and data["waived"] == 0


def test_explicit_class_token_never_reads_the_kind_fallback():
    """`kind` is where Phase 1's generic emitter puts an OPCODE label, so
    reading it as a class token would exclude the very population this waiver
    exists for. (`case_kind` DOES fall back to kind — these two must differ.)"""
    c = {"kind": "happy_path", "opcode_hex": "0x03", "expected": EXP_DEFERRED}
    assert gate.case_kind(c) == "happy_path"
    assert gate.explicit_class_token(c) == ""
    assert gate.is_cpu_instruction_oracle_case(
        c, "processor_cpu", [_unbound_op("0x03")]) is True


def test_the_4_05_category_gate_is_inert_for_emitter_produced_cases(tmp_path):
    """HONESTY PIN, not a capability claim. `gen_l10_test_cases` stamps only
    `kind` and never writes `category`/`type` at all, so for every case that
    emitter produces the §4.05 category exclusion cannot fire. It protects
    HAND-AUTHORED L10s (the test above) and nothing the emitter makes — if this
    ever changes, this test fails and the claim above must be rewritten."""
    cases = _emit_real_l10(tmp_path / "p", {"opcodes": CPU_OPCODES,
                                            "addr_max": "0xFF",
                                            "len_max": "0x40"})
    assert cases, "fixture invalid: the emitter produced nothing"
    for c in cases:
        assert "category" not in c and "type" not in c, c
        assert gate.explicit_class_token(c) == ""


# ---------------------------------------------------------------------------
# D4 — does the gate keep failable cases?  Measured on the REAL emitters.
# ---------------------------------------------------------------------------
def test_a_real_no_bounds_cpu_still_has_failable_cases(tmp_path):
    """A real processor_cpu L3 declares OPCODES and no `addr_max`/`len_max`,
    so `gen_l10_test_cases` emits ONLY happy_path + pre_wake_false for it. A
    `kind` whitelist containing both waived 100% of the layer (`rc=1 fail=4` ->
    `rc=3 fail=0 waived=4`), leaving the gate unable to fail a CPU core at all.

    Resolving the pointer keeps the layer failable from BOTH directions: the
    declared-silence cases FAIL because their expectation names no reference
    output, and the happy-path case for the opcode whose L3 entry BINDS a
    concrete answer FAILs because the spec does give the answer."""
    l3, cases, l10, sim = _real_cpu_project(
        tmp_path, ["4\t6\t00\t40\tLOAD", "4\t1\t00\t23\tSTORE"])
    assert l3.get("addr_max") in (None, "") and l3.get("len_max") in (None, ""), (
        "fixture invalid: a no-bounds L3 must declare no bounds")
    assert len(cases) == 4, f"fixture invalid: {[c['kind'] for c in cases]}"
    assert not any(c["kind"] in ("addr_max", "len_max") for c in cases)

    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt")
    assert data["not_executed"] == 3, (
        f"the gate must retain failable cases on a real no-bounds CPU: {data}")
    assert data["waived"] == 1 and rc == 1, data


def test_zero_failable_is_a_property_of_the_l3_and_it_is_stated(tmp_path):
    """HONESTY PIN — the "no failable case left" condition is REACHABLE, and
    this measures it rather than claiming it cannot happen.

    Phase 1's own opcode strategies set `pre_wake_allowed` (Strategy 1 for
    opcode 0x74, Strategy 2 for a `GET_ID*` mnemonic). Such an opcode gets NO
    `pre_wake_false` case, and with no declared bounds the emitter produces
    only the happy path. If that opcode's L3 entry ALSO binds no concrete
    reference output, every case in the layer is waived: MEASURED
    `rc=3 fail=0 waived=1`.

    That is different in kind from the round-3 defect it resembles. There the
    layer was all-waived because this GATE's vocabulary covered every kind it
    emits; here it is all-waived because the DESIGN'S OWN L3 binds no answer
    for any opcode — a fact of the document, which the gate now states out loud
    in `cpu_oracle_binding_census`, and which one bound opcode reverses."""
    l3, cases, l10, sim = _real_cpu_project(tmp_path, ["4\t6\t00\t74\tGET_ID"])
    assert [c["kind"] for c in cases] == ["happy_path"], (
        f"fixture invalid: {[c['kind'] for c in cases]}")
    assert l3["opcodes"][0]["pre_wake_allowed"] is True

    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt")
    assert (data["not_executed"], data["waived"], rc) == (0, 1, 3), data
    assert data["cpu_oracle_binding_census"] == {
        "unbound": 1, "document_derived_records": "0/1"}, (
        "the all-waived condition must be legible in the artefact, not "
        "something a reader has to reconstruct")

    # …and it reverses the moment the L3 binds ONE answer — which is what
    # makes it a property of the L-doc rather than of this gate.
    other = tmp_path / "bound"
    l3b, casesb, l10b, simb = _real_cpu_project(
        other, ["4\t1\t00\t74\tGET_ID"])
    rc_b, data_b = _run(other, l10b, simb / "tb",
                        simb / "work" / "summary.txt")
    assert (data_b["not_executed"], data_b["waived"], rc_b) == (1, 0, 1), data_b
    assert data_b["cpu_oracle_binding_census"] == {
        "bound": 1, "document_derived_records": "0/1"}, data_b


def test_a_real_bounded_l3_splits_by_binding_not_by_kind(tmp_path):
    """Same command table plus declared bounds. The split runs across SIX
    kinds and is decided per-opcode by what the L3 binds — `pre_wake_false` and
    `addr_max(negative)` carry a byte-identical `expected` and are answered
    identically, which is the coherence a kind whitelist could not have."""
    p1 = pytest.importorskip("phase1_doc_one_shot_runner")
    l3 = _emit_real_l3(tmp_path, ["4\t6\t00\t40\tLOAD", "4\t1\t00\t23\tSTORE"])
    l3["addr_max"] = "0xFF"
    l3["len_max"] = "0x40"
    (tmp_path / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
     ).write_text(json.dumps(l3))
    cases = _emit_real_l10(tmp_path, l3)
    assert len(cases) == 12, f"fixture invalid: {len(cases)}"

    sim = tmp_path / "phase2" / "stage1" / "sim"
    (sim / "tb").mkdir(parents=True, exist_ok=True)
    (sim / "tb" / "tb_dummy.v").write_text("module tb;\nendmodule\n")
    (sim / "work").mkdir(parents=True, exist_ok=True)
    (sim / "work" / "summary.txt").write_text("")
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap></results>")
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "processor_cpu"}))

    rc, data = _run(tmp_path,
                    tmp_path / "phase1" / "generated_docs"
                    / "L10_TEST_CASES.json",
                    sim / "tb", sim / "work" / "summary.txt")
    by_name = {c["name"]: c for c in cases}
    st = {r["id"]: r["status"] for r in data["results"]}
    for name, c in by_name.items():
        names_ref = "response_payload_template" in (c.get("expected") or "")
        binds = c["opcode_hex"] == "0x23"          # tx_len=1 -> concrete
        # Not waived -> the case simply was never executed (nothing ran it),
        # which is the un-credited state that used to be spelled "fail".
        want = "waived" if (names_ref and not binds) else "NOT_EXECUTED"
        assert st[name] == want, (name, c.get("expected"), st[name], want)
    assert (data["waived"], data["not_executed"]) == (3, 9), data
    assert rc == 1
    # the same `expected` on two different kinds -> the same verdict
    assert (by_name["send_load_no_wake"]["expected"]
            == by_name["send_load_addr_above_max"]["expected"])
    assert st["send_load_no_wake"] == st["send_load_addr_above_max"] == "NOT_EXECUTED"


# ---------------------------------------------------------------------------
# REVERSE (the bidirectional negative control the acceptance bar names)
# ---------------------------------------------------------------------------
def _deferred_cases():
    return [
        {"name": "send_load_happy", "kind": "happy_path",
         "stimulus": "host sends 0x03", "expected": EXP_DEFERRED,
         "opcode_hex": "0x03", "evidence": "L3.opcodes"},
        {"name": "send_store_happy", "kind": "happy_path",
         "stimulus": "host sends 0x23", "expected": EXP_DEFERRED,
         "opcode_hex": "0x23", "evidence": "L3.opcodes"},
    ]


def test_reverse_non_processor_cpu_opcode_happy_still_fails(tmp_path):
    l10, tb, summary = _make_project(tmp_path, _deferred_cases(),
                                     ic_class="digital_cmd_driven")
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1 and data["not_executed"] == 2 and data["waived"] == 0


def test_reverse_processor_cpu_unanchored_still_fails(tmp_path):
    l10, tb, summary = _make_project(tmp_path, _deferred_cases(),
                                     cpu_oracle_anchor=False)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1 and data["not_executed"] == 2 and data["waived"] == 0


def test_reverse_missing_ic_class_fails_closed(tmp_path):
    l10, tb, summary = _make_project(tmp_path, _deferred_cases(),
                                     ic_class=None)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1 and data["not_executed"] == 2 and data["waived"] == 0


def test_reverse_missing_l3_fails_closed(tmp_path):
    """The gate's new input is the L-doc, so its ABSENCE is a new failure mode.
    With no L3 there is no pointer to resolve and no case may be waived."""
    l10, tb, summary = _make_project(tmp_path, _deferred_cases(),
                                     l3_opcodes=None)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1 and data["not_executed"] == 2 and data["waived"] == 0
    assert data["cpu_oracle_binding_census"] == {
        "no_l3": 2, "document_derived_records": "0/0"}, data


def test_reverse_an_l3_that_binds_the_answer_still_fails(tmp_path):
    """THE D5 REVERSE — the one the previous rounds could not make: a CPU L3
    that DOES declare a concrete response for the opcode. The waiver's
    registered justification is false here, so the case FAILs."""
    l10, tb, summary = _make_project(
        tmp_path, _deferred_cases(),
        l3_opcodes=[_bound_op("0x03"), _bound_op("0x23", "0x24")])
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1 and data["not_executed"] == 2 and data["waived"] == 0, data
    assert data["cpu_oracle_binding_census"] == {
        "bound": 2, "document_derived_records": "0/2"}, data


def test_reverse_an_opcode_absent_from_l3_still_fails(tmp_path):
    """A case whose opcode does not appear in the design's own L3 has no
    pointer to resolve. That is a mismatch between two L-docs, not a capability
    gap, and it fails CLOSED."""
    l10, tb, summary = _make_project(tmp_path, _deferred_cases(),
                                     l3_opcodes=[_unbound_op("0xEE")])
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 1 and data["not_executed"] == 2 and data["waived"] == 0
    assert data["cpu_oracle_binding_census"] == {
        "opcode_unresolved": 2, "document_derived_records": "0/1"}, data


def test_resolve_ic_class_fails_closed_on_every_unreadable_shape(tmp_path):
    """EVERY way of not knowing the class must answer "" — never a class, and
    least of all the one class that activates a waiver. A `resolve_ic_class`
    that guessed on an absent project root would waive on a tree it never
    read."""
    assert gate.resolve_ic_class(None) == ""
    assert gate.resolve_ic_class("") == ""
    assert gate.resolve_ic_class(str(tmp_path)) == ""          # no reports/
    rep = tmp_path / "reports"
    rep.mkdir()
    assert gate.resolve_ic_class(str(tmp_path)) == ""          # no file
    for body in ("{not json", '["a list, not a dict"]',
                 '{"ic_class": null}', '{"ic_class": "  "}', "{}"):
        (rep / "ic_class.json").write_text(body)
        assert gate.resolve_ic_class(str(tmp_path)) == "", body
    (rep / "ic_class.json").write_text('{"ic_class": "Processor_CPU"}')
    assert gate.resolve_ic_class(str(tmp_path)) == "processor_cpu"


def test_resolve_ic_class_survives_a_recursive_json(tmp_path):
    """D6. The handler was `except (OSError, ValueError)`, NARROWER than the
    docstring's own promise and than its sibling `conditional_feature_declared`
    (`except Exception`): a deeply nested `ic_class.json` makes `json.loads`
    raise `RecursionError`, which is neither, so an unreadable class file
    ESCAPED and crashed the gate instead of failing closed."""
    rep = tmp_path / "reports"
    rep.mkdir()
    depth = 100_000
    body = "[" * depth + "]" * depth
    with pytest.raises(RecursionError):
        json.loads(body)          # the fixture must actually raise it
    assert not isinstance(RecursionError(), (OSError, ValueError)), (
        "fixture invalid: RecursionError is not outside the narrow handler")
    (rep / "ic_class.json").write_text(body)
    assert gate.resolve_ic_class(str(tmp_path)) == ""


def test_evaluate_without_a_project_root_cannot_waive():
    """END-TO-END on the un-rooted path: with NO project root there is no class
    file, no L3, and therefore no waiver — the cases are not credited."""
    results, ok, fail = gate.evaluate(
        _deferred_cases(), "", "",
        cpu_oracle_anchor_desc="anchor: <declared>", project_root=None)
    # No waiver may fire, and nothing may be credited. The un-waived cases
    # are NOT_EXECUTED (nothing ran them) rather than FAIL — the guard this
    # test exists for is that the waiver did not fire.
    assert (ok, fail) == (0, 0), results
    assert gate.count_not_executed(results) == 2, results
    assert not any(r["status"] == "waived" for r in results), results


def test_forward_unbound_oracle_cases_waived_under_anchor(tmp_path):
    l10, tb, summary = _make_project(tmp_path, _deferred_cases())
    rc, data = _run(tmp_path, l10, tb, summary)
    assert rc == 3 and data["not_executed"] == 0 and data["waived"] == 2
    for r in data["results"]:
        assert r["capability_gap"] == "cap:cpu_functional_oracle"
        # the evidence must NAME the reference the L3 leaves unbound, so the
        # waiver is reviewable against the design's own document.
        assert any("response_payload_template" in e for e in r["evidence"]), r
        assert r["oracle_resolution"] == "unbound:response_payload_template"


def test_opcode_case_with_real_evidence_not_waived(tmp_path):
    """A processor_cpu opcode case that was actually EXECUTED is a genuine
    PASS — execution evidence supersedes the deferral, it is NOT waived.

    Note what the old fixture used for "real evidence": a TB COMMENT reading
    `// [TB send_load_happy] PASS`. That is the testbench asserting its own
    coverage, and it is exactly what this change stops crediting. The comment
    is kept in the fixture, and it is now the execution record — not the
    comment — that earns the PASS.
    """
    tb_text = ("module tb;\n  dut u(.clk(clk));\n"
               "  // [TB send_load_happy] PASS\n"
               "  initial $display(\"send_load_happy\");\nendmodule\n")
    l10, tb, summary = _make_project(tmp_path, _deferred_cases()[:1],
                                     tb_text=tb_text,
                                     executed={"send_load_happy": "PASS"})
    rc, data = _run(tmp_path, l10, tb, summary)
    assert data["results"][0]["status"] == "pass"
    assert (data["ok"], data["waived"], data["not_executed"], rc) == (1, 0, 0, 0)


# ---------------------------------------------------------------------------
# #786 x #761 — a case waived for want of an ORACLE still has no TESTBENCH
# ---------------------------------------------------------------------------
def test_a_waived_case_with_no_testbench_still_reports_the_producer_gap(
        tmp_path):
    l10, tb, summary = _make_project(tmp_path, _deferred_cases())
    rc, data = _run(tmp_path, l10, tb, summary)
    assert data["waived"] == 2, "fixture invalid: the cases must be waived"
    out_of_scope = [r for r in data["results"]
                    if r.get("producer_scaffold_scope") == "out"]
    assert out_of_scope, (
        "fixture invalid: the producer's scaffold scope could not be read, so "
        "this test is not exercising the interaction")
    for r in out_of_scope:
        assert any("NO PRODUCER" in e for e in r["evidence"]), r["evidence"]
        assert any("waiver does not supply one" in e for e in r["evidence"])
    assert data["producer_scope_gap"] == len(out_of_scope), (
        f"producer_scope_gap={data['producer_scope_gap']} but "
        f"{len(out_of_scope)} case(s) have no testbench — the count went to "
        f"zero on exactly the population it was written for")


def test_a_passing_case_never_claims_a_producer_gap(tmp_path):
    """OVER-BREADTH GUARD. `pass` is the one outcome reached by FINDING
    evidence, so it is the one outcome for which "no testbench was written for
    it" is false. It must never carry the line, nor be counted, even though it
    is just as far outside the producer's scaffold scope as its waived sibling
    — which is exactly what makes this the discriminating case."""
    l10, tb, summary = _make_project(
        tmp_path, _deferred_cases(), executed={"send_load_happy": "PASS"})
    rc, data = _run(tmp_path, l10, tb, summary)
    passing = [r for r in data["results"] if r["status"] == "pass"]
    assert passing, "fixture invalid: no case reached `pass`"
    for r in passing:
        assert r.get("producer_scaffold_scope") == "out", \
            "fixture invalid: the passing case must be OUT of scope"
        assert not any("NO PRODUCER" in e for e in r["evidence"]), r["evidence"]
    assert data["producer_scope_gap"] == len(data["results"]) - len(passing)


def test_the_producer_gap_does_not_creep_onto_the_analog_population(tmp_path):
    """SCOPE PIN. `result_has_no_testbench` admits `fail` and exactly ONE
    waiver — this change's own. An A/M-track case WAIVED under an anchored
    --skip-analog has a producer scoped for it (the analog track, deferred),
    so counting it would answer a different question with #761's number and
    would silently move the count on every analog project."""
    cases = [{"name": "am_regulation_intent", "kind": "verification_intent",
              "expected": "line/load regulation within spec"}]
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    l10 = gd / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": cases}))
    sim = tmp_path / "phase2" / "stage1" / "sim"
    (sim / "tb").mkdir(parents=True)
    (sim / "tb" / "tb_dummy.v").write_text("module tb;\nendmodule\n")
    (sim / "work").mkdir(parents=True)
    (sim / "work" / "summary.txt").write_text("")
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<functional_verified>false</functional_verified></results>")
    rc, data = _run(tmp_path, l10, sim / "tb", sim / "work" / "summary.txt",
                    extra=["--skip-analog"])
    waived = [r for r in data["results"] if r["status"] == "waived"]
    assert waived and all(
        r["capability_gap"] == gate.CAP_ANALOG_VERIFICATION_INTENT
        for r in waived), f"fixture invalid: {data}"
    assert all(r.get("producer_scaffold_scope") == "out" for r in waived), (
        "fixture invalid: the A/M case must be OUT of the producer's scope, "
        "or this pin holds vacuously")
    assert data["producer_scope_gap"] == 0, (
        f"the A/M-track waiver was counted into #761's producer_scope_gap "
        f"({data['producer_scope_gap']}) — that population is not this "
        f"change's to move")
    for r in waived:
        assert not any("NO PRODUCER" in e for e in r["evidence"]), r["evidence"]


def test_result_has_no_testbench_admits_only_this_changes_waiver():
    assert gate.result_has_no_testbench({"status": "fail"}) is True
    assert gate.result_has_no_testbench(
        {"status": "waived",
         "capability_gap": gate.CAP_CPU_FUNCTIONAL_ORACLE}) is True
    for cap in (gate.CAP_ANALOG_VERIFICATION_INTENT,
                gate.CAP_CONDITIONAL_FEATURE_UNDECLARED, None):
        assert gate.result_has_no_testbench(
            {"status": "waived", "capability_gap": cap}) is False, cap
    for st in ("pass", "checklist_gap"):
        assert gate.result_has_no_testbench(
            {"status": st,
             "capability_gap": gate.CAP_CPU_FUNCTIONAL_ORACLE}) is False, st


# ---------------------------------------------------------------------------
# The SCOPE DISAGREEMENT line must attribute its number to the right population
# ---------------------------------------------------------------------------
def test_scope_disagreement_line_is_not_mis_attributed(tmp_path, capsys):
    """`producer_scope_gap` counts FAILs AND out-of-scope CPU-oracle waivers,
    so narrating it against `fail_count` printed "12 of the 8 failure(s)".
    The line must name the split it actually counted."""
    cases = _deferred_cases() + [
        {"name": f"send_silent_{i}", "kind": "pre_wake_false",
         "opcode_hex": "0x03", "expected": EXP_ABSENCE} for i in range(3)]
    l10, tb, summary = _make_project(tmp_path, cases)
    rc, data = _run(tmp_path, l10, tb, summary)
    assert (data["not_executed"], data["waived"]) == (3, 2), data
    assert data["producer_scope_gap"] == 5, data
    err = capsys.readouterr().err
    assert "SCOPE DISAGREEMENT" in err
    assert "of the 3 failure(s) are cases" not in err, (
        "the gap count was narrated against fail_count again")
    # THREE populations, each named as itself. Booking the never-executed
    # cases under the ORACLE waiver would attribute a capability gap to cases
    # whose actual problem is that nothing ran them — the same class of
    # mis-attribution this test is named for.
    assert ("5 case(s) — 3 NOT_EXECUTED and 2 WAIVED-DEFERRED for want "
            "of an oracle") in err, err
    # The run total names BOTH populations: reporting "0 failure(s)" while
    # three cases block the step would be true and useless.
    assert ("This run has 0 executed failure(s) and 3 never-executed "
            "case(s) in total.") in err, err
