#!/usr/bin/env python3
"""l10_tb_conformance_check.py — v0.53 plugin gate

Verifies that EVERY deterministic test vector enumerated in
`generated_docs/L10_TEST_CASES.json` has actually been exercised by the
testbench suite under `sim/tb/`.

Coverage rules per test case:
  - For a `cmd_response` case with opcode 0xXX: require evidence that the
    host packet byte sequence was driven into DUT, AND that the expected
    response was checked. Accepted evidence:
      (a) the opcode literal (`8'hXX`, `8'h<XX>`, or the hex byte in a
          `tb_vec` array) appears in at least one `sim/tb/tb_*.v`, AND
      (b) `sim/work/summary.txt` or `reports/sim/summary.txt` records
          a passing case whose id matches the L10 `id` field (case-
          insensitive substring).
  - For `error_path` / `state_transition` / `timing_sequence` /
    `analog_interaction` cases, require the case `id` to appear in at
    least one tb file (comment or task name) — documented trace-to-
    requirement.

This gate complements `cmd_response_conformance_check.py` which only
verifies CRC-residue correctness of the host vectors; it does NOT verify
that the tb harness actually drove them. l10_tb_conformance_check.py
closes that gap.

Usage:
    python3 l10_tb_conformance_check.py \\
        --l10 generated_docs/L10_TEST_CASES.json \\
        --tb-dir sim/tb \\
        --summary sim/work/summary.txt \\
        --out reports/gates/l10_tb_conformance.json

Exit code:
    0 — every L10 case has tb evidence
    1 — one or more cases lacked evidence
    2 — input artefacts missing / malformed
    3 — PASS_WITH_WAIVERS: every genuine-digital case had evidence AND the only
        cases without a digital-TB id-substring trace are `verification_intent`
        cases whose oracle lives on the analog / mixed-signal (A/M) track that
        was explicitly deferred via --skip-analog, anchored to a reviewable
        capability-gap bridge (sim/results.xml). Mirrors #651's class-aware
        rc=3 + `PASS_WITH_WAIVERS:` sentinel so flow_compliance_check promotes
        Step 4 to WAIVED-DEFERRED (Overall PASS_WITH_WAIVERS) instead of a
        hard Step-4 FAIL that cascades to blocked Phase-3 steps.

ORGANIC #773 — class/kind-aware A/M-track waiver:
    Before this fix the gate demanded a digital-TB id-substring trace for
    EVERY L10 case regardless of `kind` and emitted only rc 0/1/2. A
    `kind=verification_intent` case (satisfiable only by the --skip-analog'd
    A/M track — e.g. LDO line/load regulation + SNDR, multi-corner TT/SS/FF,
    tool disclosure, golden-GDS cross-check) therefore hard-FAILed Step 4
    even though the runner's own verdict was PASS_WITH_WAIVERS. The adjacent
    sibling `cpu_functional_oracle_waiver_check` (#651) is class-aware; this
    gate now mirrors it.

    §4.05 NO-LEAK (load-bearing): the relaxation is kind-scoped. A genuine
    digital case (`cmd_response` / `error_path` / `state_transition` / …) with
    no tb evidence must STILL FAIL — even under --skip-analog. The waiver only
    credits `verification_intent` cases, and only when a reviewable
    capability-gap anchor (sim/results.xml) is present; an unanchored blanket
    waiver is NOT honoured (would re-FAIL), so the relaxation can never mask a
    missing digital testbench.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# #206 — share the SUBSTANCE detector with vacuous_testbench_check so the two
# gates never disagree about whether a testbench actually drives the DUT. Import
# by bare name (programs/ is on sys.path under the flow runner; add this file's
# own dir as a fallback for a bare script invocation).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import vacuous_testbench_check as _vtb
except Exception:  # pragma: no cover — never let a helper import break the gate
    _vtb = None

# ORGANIC #761 — this gate and the TB PRODUCER read the SAME L10 layer with two
# private scopes: the producer filtered on the single literal `functional_vector`
# and SKIPped ("no functional_vector L10 cases — nothing to produce"), while this
# gate graded every case in the layer and FAILed all 95. Neither statement was
# false; together they were unreadable, because the SKIP stated a fact about the
# FILTER in the shape of a fact about the LAYER.
#
# The scope is now DECLARED once, in the producer (`testbench_gen.SCAFFOLD_KINDS`
# / `producer_scope`), and imported here. This gate's VERDICT is unchanged — it
# still grades every case and a case with no TB evidence still FAILs — but its
# output now NAMES BOTH SCOPES, so a Step-4 FAIL that is a scope mismatch can no
# longer read as an extraction gap. Narrowing this gate to the producer's scope
# was considered and rejected: a design that ships no testbench for 95 declared
# cases must still be marked down.
try:
    import testbench_gen as _tbg
except Exception:  # pragma: no cover — never let a helper import break the gate
    _tbg = None


# ----- helpers ------------------------------------------------------


#: ORGANIC #761 — the keys an L10 may carry its case list under, taken from the
#: PRODUCER so the two readers cannot disagree about where the cases ARE while
#: agreeing about how to grade them. The producer read only `test_cases`/`cases`
#: and this gate read all five, so an L10 keyed `vectors` was 0 cases to one and
#: N to the other — the same defect this issue is about, one field over. The
#: literal is the import-failure fallback only.
_L10_CASE_LIST_KEYS = tuple(
    getattr(_tbg, "L10_CASE_LIST_KEYS", None)
    or ("test_cases", "cases", "vectors", "cmd_response", "tests"))


def load_l10(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    # Accept either a flat list or a dict with "test_cases" / "cases" / "vectors"
    if isinstance(data, list):
        return data
    for key in _L10_CASE_LIST_KEYS:
        if key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError("L10 JSON did not contain a recognisable test-case list")


# #209 — a generated TB that drives the DUT but carries NO case oracle marks
# itself with this literal (emitted by `testbench_gen.ORACLE_NONE_MARKER`). Such
# a file is a REAL testbench — it instantiates the DUT and can fail — so it must
# still count as a driver for the #206 vacuity test. But it verifies only the
# substance floor (no output is X after reset), NOT the case's expected
# behaviour, so its text must NOT reach the evidence blob: the blob credits a
# case whenever the case id appears in it, and the case id is this file's own
# module name. Without this exclusion the #209 fix would silently convert every
# previously-uncovered case into "covered" — trading a vacuous testbench for
# vacuous coverage, which is the same lie one layer up.
_ORACLE_NONE_MARKER = "VIBEIC_TB_ORACLE: NONE"


def read_all_tb_text(tb_dir: str) -> Tuple[Dict[str, str], str]:
    """Return (per-file text map, evidence blob) of every .v / .sv under tb_dir.

    `per_file` holds EVERY testbench (it feeds the #206 substance test: does
    anything here drive the DUT). The blob holds only files that carry a real
    case oracle — a self-declared oracle-less scaffold (#209) is excluded, so
    its presence can never be mistaken for coverage.
    """
    per_file: Dict[str, str] = {}
    blob_parts: List[str] = []
    for p in sorted(Path(tb_dir).rglob("*")):
        if p.is_file() and p.suffix in (".v", ".sv", ".svh"):
            try:
                txt = p.read_text(errors="replace")
            except Exception:
                continue
            per_file[str(p)] = txt
            if _ORACLE_NONE_MARKER not in txt:
                blob_parts.append(txt)
    return per_file, "\n".join(blob_parts)


def read_summary(summary_path: str) -> str:
    p = Path(summary_path)
    if not p.exists():
        return ""
    return p.read_text(errors="replace")


# ----- evidence matching -------------------------------------------

OPCODE_RE = re.compile(r"0?x?([0-9A-Fa-f]{2})")


def opcode_patterns(byte_hex: str) -> List[re.Pattern]:
    """Return regex patterns that match `byte_hex` in common Verilog forms."""
    m = OPCODE_RE.fullmatch(byte_hex.strip())
    if not m:
        return []
    h = m.group(1).upper()
    forms = [
        rf"8'h{h}",
        rf"8'h{h.lower()}",
        rf"8'b{int(h, 16):08b}",
        rf"\b0x{h}\b",
        rf"\b{h}\b",
    ]
    return [re.compile(f) for f in forms]


#: The command-protocol field names a case has always been able to carry its
#: opcode byte under. `_OPCODE_BEARING_FIELDS` (defined below, once
#: `_INSTRUCTION_SIGNAL_FIELDS` exists) is the UNION of these with the
#: instruction-signal names — see the comment there for why the two lists
#: being different was a defect.
_CMD_OPCODE_FIELDS = ("opcode", "cmd", "cmd_hex", "cmd_byte")


def case_has_opcode_evidence(case: Dict[str, Any], tb_blob: str) -> bool:
    """Check if the case's opcode or host packet bytes appear in any tb file."""
    # Find the opcode hex from common field names
    opcode = None
    for field in _OPCODE_BEARING_FIELDS:
        if field in case and case[field] is not None:
            opcode = str(case[field])
            break
    # Or first byte of host packet
    if not opcode:
        for field in ("host_packet", "host", "tx_bytes", "cmd_bytes"):
            v = case.get(field)
            if isinstance(v, list) and v:
                opcode = str(v[0])
                break
            if isinstance(v, str) and v:
                opcode = v.split()[0]
                break
    if not opcode:
        return False
    for pat in opcode_patterns(opcode):
        if pat.search(tb_blob):
            return True
    return False


def case_id_appears(case_id: str, tb_blob: str, summary: str) -> bool:
    if not case_id:
        return False
    needle = re.escape(case_id.lower())
    if re.search(needle, tb_blob.lower()):
        return True
    if re.search(needle, summary.lower()):
        return True
    return False


def summary_has_pass(case_id: str, summary: str) -> bool:
    """Grep summary.txt for `<case_id>.*PASS` pattern."""
    if not case_id or not summary:
        return False
    pat = re.compile(rf"{re.escape(case_id)}.*PASS", re.I)
    return bool(pat.search(summary))


# ----- ORGANIC #773 — verification_intent / A-M-track classification -------

# The capability-gap token the gate stamps on an analog-verification-intent
# waiver. A chip-AGNOSTIC capability identifier (a KIND/track class name),
# NOT a chip/vendor/SKU literal — mirrors #651's `cap:cpu_functional_oracle`.
CAP_ANALOG_VERIFICATION_INTENT = "cap:analog_verification_intent_oracle"

# Kind/category/type tokens (case-insensitive) that denote a case whose oracle
# lives on the analog / mixed-signal (A/M) verification track — the cases a
# digital testbench can NEVER carry an id-substring trace for, and which the
# A/M track satisfies. Kept as a small synonym set (a KIND vocabulary), never
# a per-chip literal.
_VERIFICATION_INTENT_KINDS = frozenset({
    "verification_intent",
    "analog_verification_intent",
    "am_verification_intent",
    "analog_verification",
    "mixed_signal_verification",
})


def case_kind(case: Dict[str, Any]) -> str:
    """Normalised kind/category/type token for a case (lowercased)."""
    raw = case.get("kind", case.get("category", case.get("type", "")))
    return str(raw or "").strip().lower()


def is_verification_intent(case: Dict[str, Any]) -> bool:
    """True iff this case's KIND denotes an A/M-track verification-intent case
    (chip-AGNOSTIC — a kind vocabulary, never a chip/vendor/SKU literal)."""
    return case_kind(case) in _VERIFICATION_INTENT_KINDS


# ----- ORGANIC #778 companion — CPU functional-oracle waiver ---------------
# (mirrors #773's analog A/M-track waiver, for the processor_cpu / CPU-CORE
# interface class). A `processor_cpu`-class IC's L10 cases are frequently ALL
# `kind=functional_vector` (an instruction-execution oracle, not an
# opcode/cmd_response oracle a digital TB can id-substring-trace) — the
# runner's own generic connectivity TB (`step_reference_tb`) already declares
# this as a reviewable capability gap (`cap:cpu_functional_oracle` in
# `sim/results.xml`) when it cannot bind a per-IC oracle. This gate
# coordinates with that declaration instead of independently hard-FAILing
# every functional_vector case regardless of whether a per-case golden WAS
# authored (see `is_conditional_optional_case` below and
# `cpu_boot_latency_oracle_tb_gen` / `arith_oracle_tb_gen`, which author REAL
# goldens for the sub-classes they can ground — a case with genuine TB
# evidence never reaches this waiver at all).
CAP_CPU_FUNCTIONAL_ORACLE = "cap:cpu_functional_oracle"

# ORGANIC #761 — ONE definition, imported from the producer. The literal below is
# the import-failure fallback only, and is the same five tokens; a divergence
# between this set and `testbench_gen.SCAFFOLD_KINDS` is exactly the two-private-
# scopes defect #761 was filed for, so
# `tests/test_issue761_l10_producer_checker_scope.py` asserts they are equal by
# importing and running both modules.
_FUNCTIONAL_VECTOR_KINDS = frozenset(
    getattr(_tbg, "SCAFFOLD_KINDS", None) or {
        "functional_vector",
        "functional",
        "functional_test",
        "instruction_test",
        "cpu_functional",
    })


def is_functional_vector(case: Dict[str, Any]) -> bool:
    """True iff this case's KIND denotes a functional test vector whose
    oracle is instruction-execution-shaped (chip-AGNOSTIC — a kind
    vocabulary, never a chip/vendor/SKU literal)."""
    return case_kind(case) in _FUNCTIONAL_VECTOR_KINDS


# ----- processor_cpu instruction-oracle recognition, RESOLVED IN THE L-DOC ---
# INTERNAL-VOCABULARY RECONCILIATION (the defect this section fixes).
#
# The `is_functional_vector` whitelist above assumes a CPU core's L10 cases
# carry `kind=functional_vector` (or a synonym). Phase 1 DOES emit that kind —
# `_harvest_test_cases_from_input_tables` stamps it on every case it lifts out
# of an input verification-plan table — so the `functional_vector` path is NOT
# dead code, and a claim that it "never fires" would be wrong. What those cases
# do not carry is an OPCODE: they come from a document's own test table, not
# from L3.
#
# The gap is on the other half of a CPU's L10. `gen_l10_test_cases` renders a
# processor_cpu core's L3 OPCODES as COMMAND-RESPONSE cases stamped with
# opcode-derived kinds (`happy_path`, `pre_wake_false`, `addr_max`, `len_max`).
# None is in `_FUNCTIONAL_VECTOR_KINDS`, so for every real CPU core the
# opcode-derived cases hard-FAILed Step 4 by construction, independent of RTL
# quality, and the `cap:cpu_functional_oracle` waiver — which exists, is
# anchored, and books CPU instruction cases as WAIVED-DEFERRED — could not
# reach a single one of them.
#
# ============ WHY THIS READS THE L-DOC INSTEAD OF THE CASE'S PROSE ============
#
# FOUR previous revisions of this fix each shipped a different APPROXIMATION of
# "does this case have an oracle?", and each was refuted because the
# approximation's complement was wider than claimed:
#
#   r1  a `kind` whitelist                  — no ISA-model justification for the
#                                             boundary kinds it admitted
#   r2  a narrower `kind` whitelist         — kept `pre_wake_false` and dropped
#                                             `addr_max(negative)`, which the
#                                             emitter gives a BYTE-IDENTICAL
#                                             `expected`
#   r3  same                                — on a no-bounds CPU the whitelist
#                                             covered 100% of what is emitted
#   r4  classify the case's own `expected`  — "per <identifier_with_underscore>"
#       text by SHAPE                         reads "per" as a deferral verb,
#                                             but in engineering prose "per"
#                                             overwhelmingly means "for each",
#                                             and a snake_case signal name is
#                                             the commonest noun in RTL prose
#
# MEASURED, on this repo's own corpus (`benchmark-data`, 363 194 string values
# in `phase1/generated_docs/L*.json`): r4's deferral grammar fires 35 times and
# NOT ONE of those 35 names an L3 response-template field. They are
# `per LCR.EPS`, `per CSW.AddrInc`, `per ON_OFF_CONFIG`, `per ETG.2000`,
# `per CE_n`, `auto-incremented per CSW.AddrInc` — ordinary distributive prose
# about registers and standards. Every one of them was WAIVE-eligible under r4.
#
# The root cause is common to all four: the gate never read L3, so it could not
# tell "L3 binds no reference output for this opcode" (the waiver is EARNED)
# from "L3 binds a concrete one" (the waiver is UNEARNED) — and it substituted
# a guess about the case's WORDS for a fact that is available as DATA.
#
# THE R5 RULE — RESOLVE THE POINTER.
#
# The emitter's `expected` for a `happy_path` case is a POINTER, not an answer:
# `"DUT replies per response_payload_template"`, with `evidence: "L3.opcodes"`.
# So resolve it, in the design's OWN L3:
#
#     `resolve_case_oracle` → BOUND_BY_DOCUMENT
#                                      Phase 1 extracted response bytes for
#                                      this opcode FROM THE DESIGN'S DOCUMENT →
#                                      the spec DID give an answer → FAIL.
#                                      Checked FIRST — see the r6 block at
#                                      `_EXTRACTED_TEMPLATE_KEYS` for why the
#                                      other two arms cannot establish this.
#                           → BYTE_RECORD_UNATTRIBUTED
#                                      the entry holds document-derived bytes
#                                      whose SIDE the record cannot establish →
#                                      "the record cannot say" is not "the
#                                      document said nothing" → FAIL (r7)
#                           → BOUND    the L3 field the case points at names a
#                                      determinate value → FAIL
#                           → UNBOUND  the opcode resolves, the RECORD holds no
#                                      document-derived response bytes for it,
#                                      and the field the case names binds no
#                                      determinate answer → this, and only
#                                      this, is the registered capability gap →
#                                      WAIVABLE. Note the scope: this is a
#                                      claim about the RECORD. Whether the
#                                      DOCUMENT stated a response is NOT
#                                      established — see the r7 block.
#                           → anything else → FAIL (fails CLOSED)
#
# This is not a re-shaped heuristic; it is a different KIND of predicate, and
# the difference is checkable: the two arms are separated by DATA on cases whose
# text is BYTE-IDENTICAL. Driving Phase 1's real `gen_l3_cmd_protocol` over one
# command table (`test_l10_processor_cpu_opcode_instruction_waiver.py::
# test_the_real_emitters_split_two_byte_identical_expectations`) yields
#
#     0x40  tx_len=6 → template [{value 0x41}, {source payload}, …, {source crc8}]
#                    → no concrete golden → UNBOUND → waived
#     0x23  tx_len=1 → template [{value 0x24}]
#                    → concrete golden "24" → BOUND  → FAILs
#
# and `gen_l10_test_cases` gives BOTH cases the identical `expected` string.
# No classifier over that string can separate them; the L-doc separates them by
# construction. `_golden_bytes_from_l3_opcode` — the flow's OWN answer to "does
# the spec give a reference output for this opcode?", which
# `design_one_shot_runner` already uses to decide whether a full-stack vector
# can be scored — is the concreteness contract, and
# `test_the_gate_and_the_flow_agree_about_a_concrete_golden` pins the two
# implementations equal by running both.
#
# THE STRUCTURAL INVARIANT THAT KEEPS THIS FROM BECOMING A FIFTH GUESS:
#
#     ** NO TEXT CAN GRANT THE WAIVER. TEXT CAN ONLY WITHHOLD IT. **
#
# The only thing that ADMITS a case is L-doc resolution. Every text-derived
# component below (`_NO_OUTPUT_EXPECTATION_RE`, `_names_a_reference_output`)
# appears on the WITHHOLDING side only, so a miss in any of them makes the
# waiver RARER, never wider — the failure direction is CLOSED by construction,
# which is precisely what r1-r4 could not say.
#
#   PINNED   — the case carries its own concrete golden (`expected_bytes` …).
#              The answer is in the case; NEVER waived.
#   ABSENCE  — the expectation asserts the DUT PRODUCES NOTHING ("DUT silent
#              (no response frame)"). Gradeable by OBSERVING the interface; no
#              model of anything is required. NEVER waived.
#   BOUND_BY_DOCUMENT
#            — Phase 1 extracted response bytes for this opcode out of the
#              design's own document. The spec DID give an answer. NEVER waived,
#              and checked FIRST so the artefact quotes the document's bytes
#              under the document's own key. Post-#812 this arm is the ONLY one
#              that catches a PARTIALLY documented response — see the block
#              above, where that is measured arm-by-arm.
#   BYTE_RECORD_UNATTRIBUTED
#            — the entry holds document-derived bytes whose SIDE the record
#              cannot establish (a single-group row is filed positionally as
#              the request). NEVER waived (r7).
#   BOUND    — the L3 field the case points at names a determinate value.
#              NEVER waived.
#   UNBOUND  — the opcode resolves in L3, the RECORD holds no document-derived
#              response bytes for it, its reference-output field binds no
#              determinate answer, AND the case's own expectation NAMES that
#              field. This is what
#              `design_one_shot_runner._golden_bytes_from_l3_opcode` books as
#              "no concrete golden in L3 response_payload_template". WAIVABLE
#              — as a statement about the RECORD; see the r7 block for what
#              that does and does not establish about the DOCUMENT.
#   everything else (no L3 / opcode not in L3 / expectation names no reference
#              output / empty expectation) — FAILS CLOSED.
#
# chip-AGNOSTIC throughout: an L-doc path, L3 schema FIELD NAMES imported from
# the gate that exists to check that field, and the design's own data — never a
# chip/vendor/SKU literal.

#: An expectation that asserts NO OUTPUT. Observation is the whole oracle.
#: WITHHOLDING-ONLY (see the invariant above): a match refuses the waiver, a
#: miss merely falls through to L-doc resolution, which is the actual gate.
_NO_OUTPUT_EXPECTATION_RE = re.compile(
    r"(?i)(?:"
    r"\bsilent\b"
    r"|\bno\s+(?:response|reply|output|frame|activity|transaction|data)\b"
    r"|\b(?:must|shall|does|should|will)\s+not\s+"
    r"(?:respond|reply|answer|drive|assert|output|transmit)\b"
    r"|\b(?:remains?|stays?)\s+(?:idle|quiet|silent)\b"
    r"|\bno\s+change\b"
    r")")

#: Fields through which a case carries its OWN concrete golden. A case that
#: pins its answer has an oracle whatever its expectation prose says.
_PINNED_ORACLE_FIELDS = (
    # G19 — a `known_answer_vector` case carries its answer as a TYPED
    # (inputs, expected_outputs) pair read off the design's own declared
    # oracle. That is the sharpest possible pinning, and the waiver's
    # registered justification — "the oracle is the instruction-set model this
    # pass did not author" — is false for it: the reference output is stated.
    # This is the existing hook (#786 r5 (b)), one more field, and it makes the
    # waiver RARER, never wider.
    "expected_outputs",
    "expected_bytes",
    "expected_hex",
    "expected_value",
    "expected_output",
    "expected_result",
    "golden",
    "golden_bytes",
    "reference_output",
)

# Structured instruction/opcode signal fields (chip-AGNOSTIC FIELD NAMES, never
# a chip/vendor/SKU literal). A case that carries one of these genuinely encodes
# an instruction-execution stimulus — not an arbitrary happy case.
_INSTRUCTION_SIGNAL_FIELDS = (
    "opcode_hex",
    "opcode",
    "instruction",
    "instr",
    "instruction_hex",
    "encoding_pattern",
)

# ORGANIC #786 r5 (D5) — the field names through which a case can carry the
# opcode/instruction BYTE a testbench would have to drive. ONE definition, the
# UNION of the two lists that used to disagree.
#
# THE DEFECT: `_INSTRUCTION_SIGNAL_FIELDS` (which decides a case IS an
# instruction-execution case, and therefore that it may reach the waiver)
# admits `opcode_hex`, while `case_has_opcode_evidence` (which decides whether
# the testbench actually DROVE that byte, and therefore that the case PASSES)
# read only `_CMD_OPCODE_FIELDS`. Phase 1's `gen_l10_test_cases` keys the byte
# as `opcode_hex` on EVERY case it emits, so every emitter-produced case was
# STRUCTURALLY unable to earn `opcode in tb` evidence even when the TB drove
# the byte — renaming the field to `opcode` flipped the identical case from
# False to True. A case was therefore WAIVED for a naming mismatch 220 lines
# up, rather than PASSED on the evidence that was sitting in the testbench.
# Both readers now use this union, so they cannot disagree again.
_OPCODE_BEARING_FIELDS = _CMD_OPCODE_FIELDS + tuple(
    f for f in _INSTRUCTION_SIGNAL_FIELDS if f not in _CMD_OPCODE_FIELDS)

# ORGANIC #786 r5 — the L3 keys an opcode's REFERENCE OUTPUT is declared under.
# ONE definition, imported from `l3_opcode_response_template_check`, whose whole
# job is to check that this field exists and is populated. Two readers of the
# same L3 field disagreeing about where it lives is the #761 defect one layer
# over, so the literal below is the import-failure fallback ONLY and
# `test_response_template_keys_are_the_l3_gates_own` pins them equal by import.
try:
    import l3_opcode_response_template_check as _l3rt
except Exception:  # pragma: no cover — never let a helper import break the gate
    _l3rt = None

_RESPONSE_TEMPLATE_KEYS = tuple(
    getattr(_l3rt, "_TEMPLATE_KEYS", None)
    or ("response_payload_template", "response_template",
        "response_byte_template", "tx_payload_template",
        "response_payload", "response_bytes"))

# ORGANIC #786 r6/r7 + #812 — WHAT `response_payload_template` IS, AND SINCE
# WHEN.
#
# 🟢 THE UPSTREAM CURE LANDED. r6 shipped this block headed "THE FIELD ABOVE IS
# NOT THE DESIGN'S DOCUMENT" and closed it with "THE CURE IS UPSTREAM, AND THIS
# IS NOT IT", naming the fix it wanted: the enrichment should FILL a gap, not
# overwrite an extracted value. #812
# (`phase1_doc_one_shot_runner._merge_response_payload_template`) IS that fix.
# Everything r6 wrote about this field in the present tense is now HISTORY, and
# is labelled as such below — a comment still describing a defect that has been
# fixed is worse than no comment, because the next reader acts on it.
#
# ── HISTORY (r5/r6, pre-#812). WHAT THE FIELD USED TO BE ────────────────────
# r5 resolved the case's pointer into `response_payload_template` and called
# that "reading the L-doc". It was not. `gen_l3_cmd_protocol`'s per-opcode
# enrichment ASSIGNED a synthesised placeholder onto that field
# unconditionally:
#
#     tx_len >= 2 -> [{value: opcode+1}, {source: payload} …, {source: crc8}]
#     otherwise   -> [{value: opcode+1}]
#
# Three command tables whose documents gave three DIFFERENT response byte
# groups produced a BYTE-IDENTICAL field, so it carried zero information about
# the design and BOTH r5 arms were decided by `tx_len` rather than by the
# document: `unbound` fired for `tx_len >= 2` whatever the document said, and
# `bound` fired for `tx_len < 2` on the synthesised `opcode+1` echo — so with a
# documented response of `0x99` the gate reported `bound:41`. The document's
# own bytes went to the sibling `response_payload_template_extracted`, which no
# consumer read. The polarity was inverted: the more completely a design
# documented its protocol, the more certainly r5 waived it.
#
# ── PRESENT (post-#812). WHAT THE FIELD IS NOW ──────────────────────────────
# The enrichment MERGES per `byte_offset`
# (`gen_l3_cmd_protocol` -> `_merge_response_payload_template`): the DOCUMENT
# wins every offset it covers, the synthesised placeholder survives only in the
# gaps, the result spans the union of both offset domains, and every entry is
# tagged `provenance` = `document` | `synthesised_placeholder`. The extraction
# site is unchanged — the document's bytes still land in
# `response_payload_template_extracted` first — but they are no longer
# discarded.
#
# `test_the_stamped_template_now_tracks_the_document` is r6's own measurement,
# re-run and INVERTED: the same three documents now produce three DIFFERENT
# `response_payload_template`s, and the one that documents nothing still gets
# the placeholder, byte-for-byte as before.
#
# ── WHAT THAT DOES TO THE ARMS, MEASURED PER ARM ────────────────────────────
# `test_812_did_not_retire_the_bound_by_document_arm` neuters one arm at a time
# and reads the verdict back, on entries carrying the post-#812 canonical
# shape:
#
#   * FULLY documented response -> the merged field is now fully concrete, so
#     `bound` ALSO refuses and its detail is now TRUE. `bound_by_document` is
#     redundant FOR THE VERDICT here — but not for the provenance, below.
#   * PARTIALLY documented response (document gives 2 of 6 bytes) -> the merge
#     leaves `source` placeholders in the gaps, so `concrete_reference_output`
#     still answers None and `bound` CANNOT fire. With `bound_by_document`
#     removed the case is WAIVED — a waiver justified by "the record binds no
#     reference output" firing on an opcode whose document stated `41,99`.
#     #812 did NOT close this; it is the arm's residual population and the
#     measured reason the arm stays.
#   * document gives NOTHING -> `unbound`, waivable, byte-identical with and
#     without the arm. Unchanged by #812, and the control that keeps the waiver
#     reachable at all.
#
# WHY THE ARM STILL RUNS FIRST. Post-#812 a concrete `response_payload_template`
# may be the document's bytes OR the synthesised `opcode+1` echo (a `tx_len < 2`
# opcode with no documented response is still stamped `[{value: opcode+1}]`),
# and `concrete_reference_output` cannot tell them apart — it reads `value`, and
# both have one. The `_extracted` sibling exists ONLY because the document
# spoke, so consulting it first is what keeps
# `bound_by_document:…_extracted=99` on the artefact rather than
# `bound:response_payload_template=…`, which after #812 no longer says whose
# bytes those are.
#
# This gate deliberately does NOT read #812's new `provenance` tag. The sibling
# already carries the same fact, it is the field that survives on L3 artefacts
# written BEFORE the cure, and adding a second reader of a brand-new key is
# exactly how the #761 two-readers-disagree defect starts.
#
# LEGACY ARTEFACTS. An L3 emitted before #812 still carries the placeholder
# stamped over a documented response. There the two fields DISAGREE and the
# order is load-bearing for TRUTH, not merely for provenance —
# `test_a_pre_812_l3_still_makes_the_order_load_bearing` pins it on exactly
# that shape.
#
# The invariant r6 established is untouched by any of this: the
# document-derived sibling can only ever REFUSE the waiver, never grant it.
#
# Refusal keys on PRESENCE, not on concreteness. The presence of the key is
# itself the fact — `_byte_list_to_payload_template` is called only when the
# row yielded response bytes, and emits a `value` for every one of them — so
# "the document gave response bytes for this opcode" needs no help from this
# file's concreteness contract to be true.
#
# 🔴 WHAT THE ABSENCE OF THE SIBLING DOES NOT ESTABLISH — and r7's correction.
#
# r6 shipped this arm describing its own output as "a fact read off the
# design's document" and had the waiver print "the spec gives no answer to
# check against". THAT IS NOT WHAT ABSENCE ESTABLISHES, and my own earlier note
# ("moves toward a missed refusal, not a fabricated one") understated it twice
# over: a missed refusal IS the wrong waiver, and it reaches rc=3.
#
# MEASURED at the LAYER VERDICT, through the real emitters, both ways
# `origin/main` FAILs and r6 books PASS_WITH_WAIVERS:
#
#   (1) a bare command row PLUS a response section elsewhere in the same
#       document stating the six bytes verbatim
#         -> no sibling -> `unbound` -> rc=3 fail=0 waived=1
#   (2) the response byte group as the ONLY group on the row.
#       `_extract_hex_byte_groups` is POSITIONAL, so those bytes are filed as
#       `request_payload_template` ON THE SAME ENTRY and no sibling is written
#         -> r6: `unbound` -> rc=3. The document's bytes were sitting in the
#            very dict the gate had just read.
#
# SCOPE, measured rather than assumed: `gen_l3_cmd_protocol` has SEVEN
# `opcodes.append(` construction sites and writes
# `response_payload_template_extracted` at exactly ONE of them — and only from
# a group landing SECOND on the same table row. 0 of 203 corpus entries carry
# it. So the r6 refusal arm is skipped on 100% of the corpus, which is the
# shape of a refusal that is an admitting path in disguise.
#
# #812 DID NOT MOVE EITHER NUMBER, and that was checked rather than assumed.
# The cure changed the MERGE, not the EXTRACTION: re-counted by AST on the
# post-#812 `gen_l3_cmd_protocol` the answer is still seven construction sites
# and one write site, and re-counted over the tracked corpus
# (`git ls-files benchmark-data` -> `phase1/generated_docs/L3_*.json`, 107 docs,
# 203 opcode entries) still 0 carry the sibling. Both sentences above therefore
# STAND as written; only the consequence drawn from them changed, because the
# canonical field now testifies too — see the post-#812 section higher up.
#
# (An earlier draft of this block said NINE. That came from a substring grep
#  for `opcodes.append(`, which also matches the two `enriched_opcodes.append(`
#  calls in the enrichment's re-emission loop — not construction sites. Counted
#  by AST within the function: seven. Recorded rather than quietly corrected,
#  because a claim about what was measured is this arm's whole subject.)
#
# r7 does two things, and deliberately not a third:
#
#   * CLOSES (2) — the case where the record contradicts the claim from the
#     same dict. When an entry carries document-derived bytes whose ROLE the
#     extractor assigned POSITIONALLY (`_POSITIONAL_BYTE_GROUP_KEYS`) and no
#     response sibling, the record cannot say whether those bytes are the
#     request or the response, so the waiver is REFUSED
#     (`byte_record_unattributed`). "The record cannot say" may never be booked
#     as "the document said nothing".
#
#   * SCOPES THE CLAIM to what the record establishes. The waiver's evidence
#     line and the registered justification now say only that the L3 record
#     binds no reference output and carries no document-derived response
#     extraction for this opcode, and state explicitly that whether the input
#     DOCUMENT stated one is NOT established here. `cpu_oracle_binding_census`
#     carries `document_derived_records: "k/N"` so a reviewer can see at a
#     glance when the refusal arm had no input at all (the corpus answer is
#     0/N, every time).
#
#   * does NOT gate the waiver on "the extractor demonstrably spoke about this
#     design" (>=1 entry carrying a sibling). That was considered and declined:
#     it closes (1) but NOT (2) — which is the worse of the two and which the
#     refusal above closes outright — while making the waiver depend on a
#     SIBLING OPCODE's extraction, collapsing it to unreachable on any
#     uniformly-undocumented or single-opcode L3, and requiring every forward
#     fixture in the test file to be rebuilt. That is mechanism churn buying a
#     partial result. Case (1) is instead left VISIBLE: it is inside the scoped
#     claim, and the census names the missing input.
#
# The residual after r7 is therefore exactly this and no more: a document that
# states its response bytes somewhere `_extract_hex_byte_groups` does not look
# leaves no record, and this gate cannot distinguish that from a document that
# states none — so it does not claim to. Widening the extractor is what closes
# it; asserting it here is what r6 did wrong.
#
# The admission also still rests on `response_payload_template` binding no
# determinate value. Pre-#812 that was a fact about `tx_len` and nothing else,
# which is why r6 refused to cite it as evidence. Post-#812 it is a fact about
# `tx_len` AND about what the document said — strictly more information than r6
# had — but it is STILL not cited as evidence, for the reason above: a concrete
# value there may be document-derived or may be the synthesised `opcode+1` echo,
# and this gate does not read the tag that separates them. It is retained ONLY
# because dropping it would WIDEN the waiver (a `tx_len < 2` entry would become
# waivable), so it sits on the fail-closed side.
#
# DERIVED from `_RESPONSE_TEMPLATE_KEYS`, never hand-listed, so the two sets
# cannot drift apart the way the gate and the emitter already did once.
_EXTRACTED_SUFFIX = "_extracted"
_EXTRACTED_TEMPLATE_KEYS = tuple(k + _EXTRACTED_SUFFIX
                                 for k in _RESPONSE_TEMPLATE_KEYS)

# ORGANIC #786 r7 — keys under which Phase 1 files document-derived bytes whose
# ROLE it assigned POSITIONALLY, not from the document.
# `_extract_hex_byte_groups` returns an ordered list and the caller takes
# `groups[0]` as the request and `groups[1]` as the response
# (`phase1_doc_one_shot_runner.py:24435-24454`), so a row carrying exactly ONE
# byte group has those bytes filed as the REQUEST whatever they actually are.
# When such a record is present and no response sibling is, the design's record
# CANNOT SAY whether the bytes it holds are the request or the response — and
# "the record cannot say" must never be booked as "the document said nothing".
# The entry is refused. Where BOTH groups were found the response sibling
# exists and `document_reference_output` has already refused, so this arm fires
# only on the ambiguous single-group row.
_POSITIONAL_BYTE_GROUP_KEYS = ("request_payload_template",)


def concrete_reference_output(template: Any) -> Optional[str]:
    """The concrete byte string a response template BINDS, or None when it
    binds no determinate answer.

    Same contract as `design_one_shot_runner._golden_bytes_from_l3_opcode`,
    and pinned equal to it by a test that RUNS both: a golden exists only when
    EVERY byte of the template is a concrete hex literal. One byte carrying a
    `source` pointer (`payload` / `crc8`) instead of a `value` means the spec
    gives no reference output — which is exactly the sentence the flow itself
    writes into `results.json` for such an opcode.

    NOTE the deliberate ABSENCE of a `bool` special-case. `isinstance(True,
    int)` is True, so a `value: true` byte is read as 0x01 — by the flow and
    therefore by this function. Diverging here (answering "no concrete golden"
    for a bool) would have been the FAIL-OPEN direction: it would turn an
    entry the flow considers BOUND into a waivable one. The two must agree, and
    where they agree the disagreement cannot become a waiver."""
    if not isinstance(template, list) or not template:
        return None
    out: List[str] = []
    for ent in template:
        if not isinstance(ent, dict):
            return None
        v = ent.get("value")
        if isinstance(v, int):
            out.append(f"{v & 0xFF:02X}")
            continue
        if isinstance(v, str) and v.lower().startswith("0x"):
            try:
                out.append(f"{int(v, 16) & 0xFF:02X}")
                continue
            except ValueError:
                return None
        return None
    return ",".join(out) if out else None


def load_l3_opcodes(project_root: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """The design's OWN `L3.opcodes` list, or None when there is no readable
    L3 at all.

    None and `[]` are DIFFERENT answers and the difference is load-bearing:
    None means the pointer cannot be resolved (fails CLOSED — every case FAILs),
    `[]` means the L3 was read and declares no opcodes (so no case's opcode can
    resolve, which also FAILs, but for a reason the artefact can state).

    Globs the `L3_*` prefix rather than hard-coding a filename, mirroring
    `l_doc_consumer_contract.load_l_doc`, and accepts the `fields`-nested and
    flat payload shapes the emitters actually write."""
    if not project_root:
        return None
    gd = Path(project_root) / "phase1" / "generated_docs"
    if not gd.is_dir():
        return None
    for hit in sorted(gd.glob("L3_*.json")):
        if not hit.is_file():
            continue
        try:
            doc = json.loads(hit.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        payload = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
        ops = payload.get("opcodes")
        if ops is None and payload is not doc:
            ops = doc.get("opcodes")
        if isinstance(ops, list):
            return [o for o in ops if isinstance(o, dict)]
        return []
    return None


def _normalise_opcode_token(raw: Any) -> str:
    """Canonical form of an opcode/instruction literal, for MATCHING only.

    `0x03` / `0X03` / `03` / `3` / `8'h03` all denote the same byte, and the
    L10 case and the L3 entry are written by different emitters. Normalise both
    sides through here so a pointer does not fail to resolve on notation."""
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    m = re.fullmatch(r"(?:\d+'[hb])?0?x?([0-9a-f]+)", s.replace("_", ""))
    if m:
        return m.group(1).lstrip("0") or "0"
    return s


def opcode_entry_for_case(case: Dict[str, Any],
                          opcodes: List[Dict[str, Any]]
                          ) -> Optional[Dict[str, Any]]:
    """The L3 opcode entry THIS case's instruction signal points at, else None.

    Matched on the L3 entry's own identifying literals (`hex`, then
    `encoding_pattern`), never on a name this file hard-codes."""
    tokens = {
        _normalise_opcode_token(case.get(f))
        for f in _INSTRUCTION_SIGNAL_FIELDS
        if case.get(f)
    }
    tokens.discard("")
    if not tokens:
        return None
    for op in opcodes:
        for key in ("hex", "encoding_pattern"):
            v = op.get(key)
            if v in (None, "", [], {}):
                continue
            if _normalise_opcode_token(v) in tokens:
                return op
    return None


def document_reference_output(entry: Dict[str, Any]
                              ) -> Tuple[Optional[str], Optional[str]]:
    """``(key, concrete_golden)`` for the response bytes Phase 1 EXTRACTED FROM
    THE DESIGN'S DOCUMENT, else ``(None, None)``.

    This is the only field on an opcode entry that testifies UNAMBIGUOUSLY to
    what the document said. Post-#812 the canonical `response_payload_template`
    carries the document's bytes too — but merged with the synthesised
    placeholder, and a concrete `value` there may be either, so it cannot answer
    this question on its own (see the block above). `key` being non-None is the
    load-bearing answer — the golden is reported alongside it so the refusal can
    quote what the document gave."""
    for key in _EXTRACTED_TEMPLATE_KEYS:
        if key in entry:
            return key, concrete_reference_output(entry.get(key))
    return None, None


def unattributable_byte_record(entry: Dict[str, Any]) -> Optional[str]:
    """The key under which this entry carries document-derived bytes whose ROLE
    the record cannot establish, else None.

    See `_POSITIONAL_BYTE_GROUP_KEYS`. This is a REFUSAL input only: its
    presence means the design's record holds bytes it cannot attribute, which
    is not the same fact as "the document stated no response" and may not be
    booked as one."""
    for key in _POSITIONAL_BYTE_GROUP_KEYS:
        if entry.get(key):
            return key
    return None


def reference_output_binding(entry: Dict[str, Any]
                             ) -> Tuple[Optional[str], Optional[str]]:
    """``(declared_key, concrete_golden)`` for one L3 opcode entry.

    `declared_key` is the response-template key the entry actually carries
    (None when it carries none); `concrete_golden` is the byte string that key
    binds (None when it binds no determinate answer, or when there is no key).

    NOTE what this is and is not: it reads the L3 field AS WRITTEN, and says
    nothing about that value's PROVENANCE. On a `gen_l3_cmd_protocol`-produced
    L3 the field is a MERGE (post-#812) of the document's bytes over a
    synthesised placeholder, so a concrete answer from here may be the
    document's or may be the synthesised `opcode+1` echo. A `bound` answer is
    therefore "the field the case points at names a determinate value", NOT
    "the document gives this answer". `document_reference_output` is the one
    that can say the latter, and `resolve_case_oracle` consults it FIRST."""
    for key in _RESPONSE_TEMPLATE_KEYS:
        if key in entry:
            return key, concrete_reference_output(entry.get(key))
    return None, None


def _names_a_reference_output(expected: str,
                              declared_key: Optional[str]) -> Optional[str]:
    """The response-output field name THIS case's own expectation NAMES, else
    None.

    WITHHOLDING-ONLY, and scoped to the ONE key the L3 entry actually declares.

    ORGANIC #786 r6 — it used to fall through to every other member of
    `_RESPONSE_TEMPLATE_KEYS` as well, so `"compare the reply against
    response_bytes in table 5"` waived and its evidence line NAMED A FIELD THE
    ENTRY DOES NOT HAVE. Bounded by the L3 arm, so never a leak — but it made
    the invariant "no text can GRANT the waiver" true for misses and false for
    false hits, and a reviewable waiver may not cite a field that is not there.
    The candidate is now the declared key alone; an entry that declares no
    template key can have no reference named for it at all, and its case FAILs.

    The name is an L3 SCHEMA FIELD NAME taken off the entry — not a grammar
    over English and not a shape test over identifiers, which is precisely what
    failed in r4. The match is exact-identifier containment, so
    `per clock_cycle`, `per LCR.EPS`, `per ON_OFF_CONFIG` and `as specified in
    spec.pdf` name no reference output and are therefore NOT deferrals: they
    fall through and the case FAILs."""
    if not expected or not declared_key:
        return None
    if re.search(r"(?<![A-Za-z0-9_])" + re.escape(declared_key)
                 + r"(?![A-Za-z0-9_])", expected, re.IGNORECASE):
        return declared_key
    return None


#: The ONE `resolve_case_oracle` verdict that may reach the waiver. Named so
#: the rule is a value a test can pin rather than a literal buried in a
#: comparison.
_WAIVABLE_RESOLUTION = "unbound"


def resolve_case_oracle(case: Dict[str, Any],
                        l3_opcodes: Optional[List[Dict[str, Any]]]
                        ) -> Tuple[str, Optional[str]]:
    """Resolve THIS case's oracle against the design's OWN L3.

    Returns ``(verdict, detail)``. ``_WAIVABLE_RESOLUTION`` is the ONLY verdict
    the waiver honours; `detail` then names the reference-output field the L3
    leaves unbound, so the waiver's evidence line can name the thing the case's
    own text said its answer would come from instead of asserting the absence
    of an oracle on this gate's say-so.

    EVERY arm carries a `detail`, and that is deliberate rather than
    decorative. It makes each refusal SAY WHY on the artefact — ``bound:41``
    is the concrete golden the L3 does give, ``absence:DUT silent`` is the
    phrase that made the case observable, ``reference_not_named:
    response_payload_template`` is the field the L3 leaves unbound that the
    case never pointed at. It also keeps the arms MUTATION-DISTINGUISHABLE: if
    the refusing arms returned a bare None, a predicate mutated to honour one
    of them would still not waive (there would be no reference to return) and
    the mutant would survive as an equivalent — a guard nothing can test.

    Every arm except the waivable one refuses the waiver, so a defect anywhere
    in this function makes the waiver RARER."""
    if any(case.get(f) not in (None, "", [], {}) for f in _PINNED_ORACLE_FIELDS):
        pinned = next(f for f in _PINNED_ORACLE_FIELDS
                      if case.get(f) not in (None, "", [], {}))
        return "pinned", pinned
    expected = str(case.get("expected", "") or "").strip()
    m = _NO_OUTPUT_EXPECTATION_RE.search(expected)
    if m:
        return "absence", m.group(0)
    if l3_opcodes is None:
        return "no_l3", "no readable L3 in phase1/generated_docs"
    entry = opcode_entry_for_case(case, l3_opcodes)
    if entry is None:
        return "opcode_unresolved", f"{len(l3_opcodes)} L3 opcode(s), none match"
    # ORGANIC #786 r6, still first after #812 — did the DESIGN'S DOCUMENT give
    # the response bytes for this opcode? If it did, the waiver's registered
    # justification is false, whatever the canonical template resolves to. It
    # runs FIRST for two measured reasons: it is the ONLY arm that catches a
    # PARTIALLY documented response (the merge leaves `source` placeholders in
    # the gaps, so `bound` cannot fire), and it is what puts the document's own
    # key and bytes on the artefact instead of a merged field that no longer
    # says whose bytes it is holding.
    doc_key, doc_golden = document_reference_output(entry)
    if doc_key is not None:
        return "bound_by_document", f"{doc_key}={doc_golden or 'present'}"
    # ORGANIC #786 r7 — the entry may hold document-derived bytes the record
    # cannot attribute to a side (a single-group row files them as the
    # request). Refuse: "the record cannot say" is not "the document said
    # nothing", and r6 waived exactly this while the bytes sat in the dict it
    # had just read.
    unattributed = unattributable_byte_record(entry)
    if unattributed is not None:
        return ("byte_record_unattributed",
                f"{unattributed} (role assigned positionally; no response "
                f"sibling — the record cannot say which side these bytes are)")
    declared_key, golden = reference_output_binding(entry)
    if golden is not None:
        # The field the case points at names a determinate value. On a
        # Phase-1-emitted L3 that value may be synthesised (pre-#812 it always
        # was; post-#812 it is whichever of the document and the placeholder
        # covered the offset), so the detail names the KEY as well as the bytes
        # — a reader must be able to see WHICH field decided, not be told "the
        # spec gives this answer" on this gate's say-so. Where the DOCUMENT is
        # what decided, the arm above has already fired and named the
        # document's own key, so reaching here means the document did not
        # speak for this opcode.
        return "bound", f"{declared_key}={golden}"
    named = _names_a_reference_output(expected, declared_key)
    if named is None:
        return "reference_not_named", declared_key or "(L3 declares no template)"
    return _WAIVABLE_RESOLUTION, named


def explicit_class_token(case: Dict[str, Any]) -> str:
    """The case's EXPLICIT class token — ``category``, else ``type``. Never the
    ``kind`` fall-back `case_kind` applies, because `kind` is where Phase 1's
    generic emitter puts an opcode label and reading it here would exclude the
    very population this section exists for.

    NULL-SAFE, and that is the point: ``dict.get(k, default)`` returns the
    STORED value when the key EXISTS with a null value, so the idiom
    ``case.get("category", case.get("type", ""))`` used elsewhere in this file
    resolves ``{"category": null, "type": "cmd_response"}`` to ``None`` and
    never consults ``type`` at all — a genuine digital command that then walked
    straight through the §4.05 exclusion below."""
    for field in ("category", "type"):
        v = case.get(field)
        if v is not None and str(v).strip():
            return str(v).strip().lower()
    return ""


def cpu_oracle_anchor(project_root: Optional[str]) -> Optional[str]:
    """Auto-detect the CPU functional-oracle capability gap from
    `sim/results.xml`. Returns a short, reviewable description string when
    the anchor is found AND carries ``cap:cpu_functional_oracle``, else None.

    Mirrors `analog_skip_anchor()` but is SPECIFIC to the CPU-oracle gap: it
    fires ONLY when results.xml explicitly declares
    ``<capability_gap>cap:cpu_functional_oracle</capability_gap>``. No CLI
    flag is needed — the gate auto-detects from the runner's own artefact.
    §4.05 NO-LEAK: without the explicit token this returns None and the gate
    runs at full strictness; a bare CONNECTIVITY-PASS alone does NOT activate
    this waiver (only the analog waiver reads that verdict)."""
    if not project_root:
        return None
    pr = Path(project_root)
    for p in (pr / "phase2/stage1/sim/results.xml",
              pr / "sim/results.xml",
              pr / "reports/sim/results.xml"):
        if not p.is_file():
            continue
        try:
            xml = p.read_text(errors="replace")
        except OSError:
            continue
        if _read_xml_field(xml, "capability_gap") == CAP_CPU_FUNCTIONAL_ORACLE:
            return f"{p} (capability_gap={CAP_CPU_FUNCTIONAL_ORACLE})"
    return None


# ----- ORGANIC #778 companion — conditional-optional feature-case waiver ---
# An L10 case's own stimulus/expected text sometimes carries an explicit
# CONDITIONAL marker referencing an OPTIONAL, Plugin-selectable feature —
# e.g. "(若 Plugin 選 <token>) ..." / "(if the plugin selects <token>) ...".
# The design's own L2/spec doc typically REQUIRES the Plugin to record its
# selection of such an optional feature in a structured declaration
# (`declaration.json`); when no such declaration exists, this gate cannot
# determine whether THIS build actually selected the referenced feature.
# Demanding TB evidence regardless would either (a) hard-FAIL a legitimately
# NOT-selected optional feature (a false defect — the design never claimed
# to implement it), or (b) require FABRICATING a golden for hardware that
# may not exist (a §4.05 violation). The honest disposition is a scoped,
# reviewable WAIVER — distinct from the broader `cap:cpu_functional_oracle`
# gap above, since the root cause here is a MISSING DECLARATION, not a
# missing oracle for a confirmed feature.
#
# chip-AGNOSTIC: pure grammar match (a parenthetical conditional-selection
# marker) + a declaration-file presence check. The extracted TOKEN is
# whatever the design's own doc happens to name (e.g. 'M', 'Zicsr', 'C' for
# a RISC-V core, or an entirely different axis on a different IC) — never a
# hard-coded extension/feature name.
CAP_CONDITIONAL_FEATURE_UNDECLARED = "cap:conditional_feature_undeclared"

_RE_CONDITIONAL_OPTIONAL = re.compile(
    r"\(\s*(?:若\s*(?:plugin|design|implementation)?\s*(?:選|採用|選用)"
    r"|if\s+(?:the\s+)?(?:plugin|design|implementation)\s+"
    r"(?:selects?|chooses?|includes?|adopts?))\s*([A-Za-z0-9_]+)\s*\)",
    re.IGNORECASE,
)


def is_conditional_optional_case(case: Dict[str, Any]) -> Optional[str]:
    """Returns the referenced feature TOKEN when this case's stimulus/
    expected text carries the explicit "(if Plugin selects <token>)"
    conditional-selection grammar; else None."""
    text = f"{case.get('stimulus', '')} {case.get('expected', '')}"
    m = _RE_CONDITIONAL_OPTIONAL.search(text)
    return m.group(1) if m else None


def conditional_feature_declared(project_root: Optional[str],
                                 token: str) -> bool:
    """True iff the design's OWN `declaration.json` (or equivalent structured
    Phase-2 config) affirmatively mentions `token` — i.e. the Plugin
    recorded a decision about this feature for this build. False
    (undeclared) when no such record exists, in which case the gate cannot
    confirm applicability and the case is WAIVED rather than hard-required
    or fabricated.

    WORD-BOUNDARY match (never a bare substring test): a short token like
    'M' or 'C' would otherwise trivially match almost any JSON blob (e.g.
    the field name `isa_extensions` itself contains a 'c'). The token must
    appear as its own delimited word/value."""
    if not project_root or not token:
        return False
    pr = Path(project_root)
    pat = re.compile(
        r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    for p in (pr / "plugin_output" / "declaration.json",
              pr / "declaration.json"):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(data, (dict, list)):
            continue
        blob = json.dumps(data)
        if pat.search(blob):
            return True
    return False


# ORGANIC #773 r2 — a DIGITAL class vocabulary (the cmd_response family). A case
# resolving to one of these by its category/type — OR carrying an opcode/cmd
# field — is a digital command-response case whose conformance is satisfiable by
# the digital TB; it must NEVER be A/M-waived even if it ALSO carries a spurious
# `kind=verification_intent`. chip-AGNOSTIC: a class vocabulary, no SKU literal.
_DIGITAL_CLASS_TOKENS = frozenset({
    "cmd_response", "cmd_rsp", "happy", "happy_path", "error_path",
    "state_transition", "timing_sequence", "register_access", "command",
})


def _has_digital_signal(case: Dict[str, Any], is_cmd_rsp: bool) -> bool:
    """True iff the case carries a DIGITAL signal (is_cmd_rsp by category-priority,
    an opcode/cmd field, or a digital category/type token) — so a
    kind=verification_intent mislabel cannot defeat the digital requirement.

    ORGANIC #786 r5 (D5) — reads the SAME `_OPCODE_BEARING_FIELDS` union as
    `case_has_opcode_evidence`. Widening it here is strictly FAIL-CLOSED: this
    predicate only ever REFUSES the A/M and checklist relaxations, so a case
    that carries `opcode_hex` can no longer slip past the digital requirement
    on a mislabelled `kind`."""
    if is_cmd_rsp:
        return True
    for field in _OPCODE_BEARING_FIELDS:
        if case.get(field):
            return True
    cat = str(case.get("category", case.get("type", "")) or "").strip().lower()
    return cat in _DIGITAL_CLASS_TOKENS


def resolve_ic_class(project_root: Optional[str]) -> str:
    """Read the design's ic_class from ``reports/ic_class.json`` — the Phase-1
    SINGLE-SOURCE-OF-TRUTH class label (the same artefact detect_ic_class
    persists and _write_l_doc's R13 gate reads). Returns ``""`` when the file
    is absent/unreadable, so the processor_cpu instruction-oracle path below
    stays INERT (fails CLOSED — a missing class file can never activate a
    waiver). chip-AGNOSTIC: reads a CLASS label, never a chip/vendor/SKU
    literal.

    ORGANIC #786 r5 (D6) — the handler is `except Exception`, matching its
    sibling `conditional_feature_declared`. `(OSError, ValueError)` was
    NARROWER than this docstring's own promise: `json.loads` on a deeply
    nested `ic_class.json` raises `RecursionError`, which is neither, so an
    unreadable class file ESCAPED and crashed the gate instead of failing
    closed. Every escape route out of "unreadable" must land on `""`."""
    if not project_root:
        return ""
    p = Path(project_root) / "reports" / "ic_class.json"
    try:
        data = json.loads(p.read_text())
    except Exception:
        return ""
    if isinstance(data, dict):
        return str(data.get("ic_class", "") or "").strip().lower()
    return ""


def cpu_instruction_oracle_reference(
        case: Dict[str, Any],
        ic_class: str,
        l3_opcodes: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """The reference-output field the design's OWN L3 leaves UNBOUND for this
    case, when the case is a processor_cpu instruction-execution oracle the
    ``cap:cpu_functional_oracle`` waiver describes — else None.

    Returns the reference (rather than a bare bool) so the waiver's evidence
    line can NAME the thing the case's own text said its answer would come
    from, instead of asserting the absence of an oracle on this gate's say-so.

    FOUR independent gates, ALL required, and the last one is the one that
    carries the justification:

      (1) ``ic_class == 'processor_cpu'`` — EXACT equality with the class the
          waiver is registered for (single-source-of-truth class label). Any
          other class — including one that merely CONTAINS the token, e.g. a
          hypothetical ``processor_cpu_wrapper`` — is rejected, so a
          non-processor_cpu opcode happy-path with no evidence STILL FAILs.
      (2) §4.05 NO-LEAK — the case does NOT carry an EXPLICIT digital
          cmd_response category/type (see `explicit_class_token`, which is
          null-safe). A genuine digital command the TB must exercise is never
          masked, even for a processor_cpu under the anchor.

          HONEST LIMIT, because this gate is easy to over-credit: Phase 1's
          `gen_l10_test_cases` stamps ONLY `kind` and never writes `category`
          or `type` at all, so for every case that emitter produces this gate
          is INERT by construction. It protects HAND-AUTHORED L10s and L10s
          from any other producer — which is a real population (a `cmd_response`
          category is exactly how `evaluate` decides `is_cmd_rsp`) but it is
          NOT the population the emitter generates, and a test that only feeds
          it emitter-shaped cases proves nothing about it.
      (3) the case carries a structured instruction/opcode SIGNAL — it is
          genuinely an instruction-execution case, not an arbitrary happy case.
          This is enforced INSIDE `resolve_case_oracle`, by
          `opcode_entry_for_case`, which reads the same
          `_INSTRUCTION_SIGNAL_FIELDS` and answers None (-> the
          `opcode_unresolved` arm) for a case that carries none. It used to be
          a separate early return here; that line was provably UNREACHABLE-BY-
          MUTATION — deleting it changed no verdict on any input, because a
          case with no signal can never match an L3 entry — and a guard no
          test can kill is a rule nobody is checking. One enforcement point,
          exercised by `test_a_case_with_no_instruction_signal_cannot_resolve`.
      (4) `resolve_case_oracle` returns ``_WAIVABLE_RESOLUTION``: the case's opcode
          RESOLVES to an entry in the design's own L3, that entry's RECORD holds
          no document-derived response bytes for the opcode and no unattributed
          byte record, its reference-output field binds no determinate answer,
          and the case's own expectation names that field. A PINNED golden, an
          ABSENCE expectation, a document-derived record, an unattributable
          byte record, an L3 field that BINDS a value, an opcode that does not
          resolve, an expectation that names no reference output, and a missing
          L3 are ALL rejected here — which is what stops the waiver from
          covering the declared-silence half of a CPU's opcode cases, and what
          stops it from covering a case whose answer the record gives.

    SCOPE (ORGANIC #786 r7): "no reference output" is a claim about the L3
    RECORD, never about the input document — see the r7 block at
    `_POSITIONAL_BYTE_GROUP_KEYS` for what absence does and does not establish,
    and `document_record_provenance` for the number that makes it legible.

    ``l3_opcodes`` is the design's own opcode list (`load_l3_opcodes`), passed
    in by the caller so the L3 is read once per run rather than once per case.
    Passing None means "no L3 could be resolved" and fails CLOSED.

    The runner's ``cap:cpu_functional_oracle`` anchor gate (``cpu_waiver_active``)
    is applied by the caller, so a processor_cpu run WITHOUT that declaration
    still FAILs. chip-AGNOSTIC throughout (a class label, L-doc field names, and
    the design's own data — never a chip/vendor/SKU literal)."""
    if ic_class != "processor_cpu":
        return None
    if explicit_class_token(case) in _DIGITAL_CLASS_TOKENS:
        return None
    verdict, detail = resolve_case_oracle(case, l3_opcodes)
    if verdict != _WAIVABLE_RESOLUTION:
        return None
    return detail


def is_cpu_instruction_oracle_case(
        case: Dict[str, Any],
        ic_class: str,
        l3_opcodes: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Boolean face of `cpu_instruction_oracle_reference` (see it for the
    gates and the justification)."""
    return cpu_instruction_oracle_reference(
        case, ic_class, l3_opcodes) is not None


# ----- ORGANIC #808 — verification_checklist (DV-milestone) classification ----
#
# NEW gap, surfaced after #799 unblocked Step-4. Phase 1 emits a project's
# verification checklist table (e.g. an OpenTitan-style DV checklist) as L10
# `kind=verification_checklist` rows. Those rows are DV PROCESS MILESTONES
# (status Done / N/A / Waived / blank), NOT TB-traceable functional vectors:
# no testbench can ever carry an id-substring / opcode trace for a process
# milestone. The TB-evidence demand therefore counted EVERY checklist row as
# "lack evidence" → 103/103 → Step-4 hard-FAIL on opentitan_aes.
#
# Fix: scope verification_checklist rows OUT of the TB-evidence requirement and
# instead credit the row's CARRIED status. chip-AGNOSTIC — a KIND vocabulary +
# a status vocabulary, never a chip/vendor/SKU literal.

# Kind/category/type tokens (case-insensitive) that denote a DV-milestone
# checklist row whose satisfaction is its carried status, not a TB trace.
_VERIFICATION_CHECKLIST_KINDS = frozenset({
    "verification_checklist",
    "dv_checklist",
    "checklist",
    "milestone",
    "verification_milestone",
})

# Carried statuses that mark a checklist row as SATISFIED or explicitly DEFERRED
# (so the row is credited, not counted as a TB-evidence miss). A status
# vocabulary, chip-AGNOSTIC.
_CHECKLIST_SATISFIED_STATUSES = frozenset({
    "done", "complete", "completed", "pass", "passed", "ok", "yes",
    "n/a", "na", "not applicable", "waived", "waiver", "deferred",
})

# Carried statuses that mark a checklist row as an EXPLICIT shortfall — it must
# still surface as a checklist gap (don't blanket-pass every row). §4.05 NO-LEAK.
_CHECKLIST_FAIL_STATUSES = frozenset({
    "fail", "failed", "error", "blocked", "no", "incomplete", "not done",
})


def is_verification_checklist(case: Dict[str, Any]) -> bool:
    """True iff this case's KIND denotes a DV-milestone checklist row
    (chip-AGNOSTIC — a kind vocabulary, never a chip/vendor/SKU literal)."""
    return case_kind(case) in _VERIFICATION_CHECKLIST_KINDS


def checklist_status(case: Dict[str, Any]) -> str:
    """Normalised carried status of a checklist row (lowercased; '' when blank).

    A blank/None status is a checklist gap but NOT a TB-evidence failure."""
    raw = case.get("status", case.get("state", case.get("result", "")))
    return str(raw or "").strip().lower()


def classify_checklist(case: Dict[str, Any]) -> str:
    """Classify a verification_checklist row by its carried status.

    Returns one of:
      'satisfied'      — Done / N/A / Waived / Pass …  (credited, not a miss)
      'checklist_gap'  — blank/None, or an explicit FAIL/blocked status
                         (surfaced as a checklist shortfall; NOT a TB-evidence
                         failure, so it cannot mask a missing digital TB).
    §4.05 NO-LEAK: this classifier is reached ONLY for verification_checklist
    rows. A functional_vector / functional / cmd_response case never gets here,
    so the TB-evidence demand is unchanged for genuine functional vectors."""
    st = checklist_status(case)
    if st in _CHECKLIST_SATISFIED_STATUSES:
        return "satisfied"
    # blank/None, an explicit fail status, or any unrecognised status → gap.
    return "checklist_gap"


def _read_xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip() if m else "")


def analog_skip_anchor(project_root: Optional[str], anchor_path: Optional[str]) -> Optional[str]:
    """ORGANIC #773 — resolve a REVIEWABLE capability-gap anchor for the
    analog-verification-intent waiver (mirrors #651's reviewable
    sim/results.xml bridge). Returns a short, reviewable description string
    when an anchor is found, else None.

    An honest analog-deferred waiver is reviewable only when the runner left a
    capability-gap bridge behind: a `sim/results.xml` carrying a
    `<capability_gap>` and/or a CONNECTIVITY-class verdict. Without that anchor
    the waiver is unanchored and is NOT honoured (the caller re-FAILs), so the
    relaxation cannot become a blanket unreviewable pass."""
    cands: List[str] = []
    if anchor_path:
        cands.append(anchor_path)
    if project_root:
        pr = Path(project_root)
        cands += [
            str(pr / "phase2/stage1/sim/results.xml"),
            str(pr / "sim/results.xml"),
            str(pr / "reports/sim/results.xml"),
        ]
    for c in cands:
        p = Path(c)
        if not p.is_file():
            continue
        try:
            xml = p.read_text(errors="replace")
        except OSError:
            continue
        cap = _read_xml_field(xml, "capability_gap")
        verdict = _read_xml_field(xml, "verdict").upper().replace("_", "-")
        if cap or verdict in ("CONNECTIVITY-PASS", "PASS-WITH-WAIVERS"):
            tag = cap or verdict
            return f"{p} (capability_gap/verdict={tag})"
    return None


# ORGANIC #773 r3 — the anchor for the OTHER half of the same question.
#
# THE DEFECT THIS CLOSES, MEASURED. #773 relieved a `verification_intent` case
# of the digital-TB evidence requirement only when the A/M track was DEFERRED
# via --skip-analog. So a run that SKIPPED the analog work was credited, and a
# run that actually DID it — nine real ngspice PVT corners per block, on the
# staged foundry corner sections — was FAILED, for lacking evidence in a
# digital testbench directory that by this gate's own docstring can NEVER
# carry it. Doing the work scored strictly worse than not doing it, and the
# resulting Step-4 FAIL is what stopped the design entering Phase 3.
#
# The kind of the case did not change with the flag, and neither did who owns
# its oracle. What changes is only WHERE the reviewable anchor points: to the
# skip declaration when the track was deferred, and to the track's OWN
# evidence when it ran. This resolves the second one.
#
# It is deliberately EVIDENCE-anchored and not merely "the flag was absent":
# a run that neither skipped analog nor produced any analog evidence resolves
# NOTHING here and FAILs exactly as it does today.
def analog_ran_anchor(project_root: Optional[str]) -> Optional[str]:
    """Reviewable anchor for an A/M-track case whose track actually RAN.

    Returns a short reviewable description when the analog track left
    per-block corner evidence produced by a real simulator, else None.

    This NEVER credits the case as passed and it makes NO claim that the
    analog result was good: the A/M track keeps its own verdict, its own
    gates, and its own place in the audit. A design whose analog stage is
    failing still fails on the analog stage — this only stops a DIGITAL
    testbench gate from charging a second, duplicate failure for a
    measurement it cannot make either way.
    """
    if not project_root:
        return None
    blocks: List[str] = []
    real = 0
    for cr in sorted(Path(project_root).glob(
            "phase3/analog/*/corner_results.json")):
        try:
            data = json.loads(cr.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        corners = data.get("corners") if isinstance(data, dict) else None
        if not isinstance(corners, list) or not corners:
            continue
        # A corner record that no simulator produced is not evidence that the
        # track ran; it is a file. Require the producer's own marker.
        ran = [c for c in corners if isinstance(c, dict)
               and (c.get("simulator_run") is True
                    or str(c.get("_provenance", "")).startswith("real_"))]
        if not ran:
            continue
        blocks.append(cr.parent.name)
        real += len(ran)
    if not blocks:
        return None
    return (f"{len(blocks)} analog block(s) {sorted(blocks)} carry "
            f"{real} simulator-produced corner record(s) under "
            f"phase3/analog/*/corner_results.json (A/M track RAN)")


# ----- CLI ----------------------------------------------------------


def producer_scope_report(
        cases: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """ORGANIC #761 — the TB PRODUCER's own scope record over the SAME case
    list this gate grades, read from the producer's single definition
    (`testbench_gen.producer_scope`). None when the producer module is not
    importable — the gate then runs exactly as before, minus the scope
    annotation; it NEVER changes a verdict on the strength of this record."""
    if _tbg is None:
        return None
    try:
        return _tbg.producer_scope(cases)
    except Exception:  # pragma: no cover — a helper must not break the gate
        return None


def scaffold_kinds_of(scope: Optional[Dict[str, Any]]) -> Optional[frozenset]:
    """The producer's scaffold kind scope from a `producer_scope` record."""
    if not scope:
        return None
    kinds = scope.get("scaffold_kinds")
    return frozenset(kinds) if kinds else None


def result_has_no_testbench(result: Dict[str, Any]) -> bool:
    """ORGANIC #761 x #786 — did this case end with NO TESTBENCH WRITTEN FOR IT
    AT ALL, as opposed to a testbench that was found (`pass`) or a producer
    elsewhere in the flow that owns it?

    `"fail"` is #761's original population, unchanged. `"waived"` is added for
    EXACTLY ONE capability gap — `cap:cpu_functional_oracle` — because that is
    the waiver the processor_cpu instruction-oracle path introduces, and it
    turns exactly the population #761 was written for (a CPU core's opcode
    cases, for which the TB producer wrote nothing) from `fail` into `waived`.
    Without this, #761's diagnostic and count would have gone silent on the one
    design that motivated it.

    The OTHER waivers are deliberately NOT here, and the distinction is not
    cosmetic — #761's number answers "no producer in the flow was scoped to
    write a testbench for this":
      * `cap:analog_verification_intent` — a producer IS scoped for it, the
        A/M track, and it was DEFERRED via --skip-analog. Counting it would
        answer a different question with #761's number, and would silently
        move the count on every analog project this change has no business
        touching.
      * `cap:conditional_feature_undeclared` — the case may describe a feature
        this build never selected; "nobody was scoped to test it" is not what
        happened.
    `"pass"` is excluded because it is the one outcome reached by FINDING
    evidence, which is the one thing that makes the sentence false;
    `"checklist_gap"` is reported on its own path and never reaches this
    code."""
    status = result.get("status")
    if status == "fail":
        return True
    return (status == "waived"
            and result.get("capability_gap") == CAP_CPU_FUNCTIONAL_ORACLE)


def document_record_provenance(l3_opcodes: Optional[List[Dict[str, Any]]]
                               ) -> str:
    """``"k/N"`` — how many of the design's L3 opcode entries carry a
    document-derived response extraction at all.

    ORGANIC #786 r7. The `bound_by_document` refusal can only fire on an entry
    that HAS such a record, and the extraction that writes one runs at exactly
    one of seven opcode-construction sites — 0 of 203 corpus entries carry it.
    A refusal arm that is skipped because its input is absent looks identical,
    from the verdict alone, to a refusal arm that ran and found nothing. This
    number is what tells those two apart, so it is emitted next to every
    waiver instead of left to be reconstructed.

    #812 gave the same number a SECOND reading, at no cost: the sibling this
    counts is exactly what `_merge_response_payload_template` merges into the
    canonical template, so ``k`` is also how many of the design's opcodes have
    a `response_payload_template` carrying any document-derived byte at all.
    ``0/N`` now means both "the refusal arm had no input" and "the merge had
    nothing to merge" — the corpus answer to both is still 0/N, re-measured
    post-#812 over the same 203 tracked entries."""
    if not l3_opcodes:
        return "0/0"
    k = sum(1 for op in l3_opcodes if document_reference_output(op)[0])
    return f"{k}/{len(l3_opcodes)}"


def cpu_oracle_binding_census(cases: List[Dict[str, Any]],
                              l3_opcodes: Optional[List[Dict[str, Any]]]
                              ) -> Dict[str, Any]:
    """ORGANIC #786 r5 (D4) — how the design's OWN L3 answered, per case that
    carries an instruction signal. A histogram of `resolve_case_oracle`
    verdicts, emitted into the gate artefact.

    This exists so "the gate had NO failable case in this layer" is a number a
    reviewer can read off the artefact instead of reconstructing. Under this
    change a layer ends all-waived only when the design's own L3 binds no
    reference output for ANY of its opcodes — a condition of the L-DOC, not of
    this gate's vocabulary, and one the census states out loud.

    ORGANIC #786 r7 — it also carries `document_derived_records: "k/N"`, the
    PROVENANCE of the refusal arms. A `bound_by_document` refusal can only fire
    on an entry that has such a record, and 0 of 203 corpus entries do, so
    without this number a refusal arm that was SKIPPED for want of input reads
    exactly like one that ran and found nothing. The key is emitted whenever
    there is a resolvable L3, including when the histogram is empty.

    ANNOTATION ONLY: no verdict reads it."""
    census: Dict[str, Any] = {}
    for c in cases:
        if not any(c.get(f) for f in _INSTRUCTION_SIGNAL_FIELDS):
            continue
        verdict, _ = resolve_case_oracle(c, l3_opcodes)
        census[verdict] = census.get(verdict, 0) + 1
    if census or l3_opcodes:
        census["document_derived_records"] = document_record_provenance(
            l3_opcodes)
    return census


def count_producer_scope_gap(results: List[Dict[str, Any]]) -> int:
    """ORGANIC #761 — cases with NO TESTBENCH that the TB producer was never
    scoped to write one for. These are STILL gaps (this gate does not stop
    caring); the count exists so the disagreement between the two readers of
    L10 is a first-class number in the artefact instead of something a reader
    has to reconstruct from a SKIP line and a gate JSON. See
    `result_has_no_testbench` for which outcomes qualify and why."""
    return sum(1 for r in results
               if result_has_no_testbench(r)
               and r.get("producer_scaffold_scope") == "out")


def evaluate(
    cases: List[Dict[str, Any]],
    tb_blob: str,
    summary: str,
    skip_analog: bool = False,
    analog_anchor: Optional[str] = None,
    analog_anchor_kind: str = "deferred",
    cpu_oracle_anchor_desc: Optional[str] = None,
    project_root: Optional[str] = None,
    producer_scaffold_kinds: Optional[frozenset] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Return (results, ok_count, fail_count).

    The per-case ``status`` field ("pass" / "fail" / "waived" /
    "checklist_gap") and the project-level ``waive_count`` / checklist-gap
    count are derivable from the returned ``results`` list (see
    ``count_waived`` / ``count_checklist_gaps``); the 3-tuple return shape is
    preserved for backward compatibility with existing callers.

    ORGANIC #808 — ``kind=verification_checklist`` (DV-milestone) rows are
    scoped OUT of the TB-evidence requirement: a DV process milestone is not
    TB-traceable. A satisfied/deferred row (Done/N/A/Waived/Pass) is credited
    into ``ok_count``; a blank/None-or-explicit-FAIL row is carried separately
    as a checklist gap (status ``checklist_gap``, review_required) and is NOT
    folded into ``fail_count`` — so a checklist row can never mask a missing
    digital testbench (§4.05 NO-LEAK), and functional_vector / functional /
    cmd_response cases STILL require TB evidence (unchanged).

    ORGANIC #773 — when ``skip_analog`` is set AND ``analog_anchor`` resolves
    to a reviewable capability-gap bridge, a `verification_intent` (A/M-track)
    case that lacks a digital-TB id-substring trace is credited as WAIVED-
    DEFERRED instead of FAILing. §4.05 NO-LEAK: a genuine digital case
    (anything NOT `verification_intent`) with no tb evidence STILL FAILs even
    under --skip-analog, and an UNANCHORED verification_intent case (no
    reviewable bridge) also still FAILs — the relaxation is kind-scoped and
    anchor-gated so it can never mask a missing digital testbench.

    ORGANIC #761 — ``producer_scaffold_kinds`` is the TB producer's own scaffold
    scope (`testbench_gen.SCAFFOLD_KINDS`, passed in by ``main``). It is pure
    ANNOTATION: each result gains ``kind`` and ``producer_scaffold_scope``
    ("in"/"out"), and an out-of-scope case that ended with NO TESTBENCH
    EVIDENCE (`result_has_no_testbench` — FAILed, or WAIVED for want of the
    CPU instruction-set oracle) gains a `NO PRODUCER:` line naming both scopes.
    NO verdict reads it — passing it or omitting it yields byte-identical
    ``status`` for every case. That is deliberate: the fix for two readers
    disagreeing about one layer's scope is to make the disagreement legible,
    not to let the consumer stop grading."""
    results: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    checklist_gap_count = 0
    # #773 r3 — ANCHOR-gated, not FLAG-gated. `skip_analog` is still what
    # selects WHICH anchor `main` resolved; it is no longer an independent
    # precondition, because the A/M track owns this case's oracle in both
    # states. An unanchored run (neither deferred nor evidenced) still has
    # waiver_active False and still FAILs, exactly as before.
    waiver_active = bool(analog_anchor)
    cpu_waiver_active = bool(cpu_oracle_anchor_desc)
    # Single-source-of-truth class label — gates the processor_cpu opcode-
    # instruction oracle path so it can never fire for another class (fails
    # CLOSED to "" when unavailable).
    ic_class = resolve_ic_class(project_root)
    # ORGANIC #786 r5 — the design's OWN L3 opcode list, read ONCE. This is the
    # thing four previous rounds substituted a text heuristic for: it is what
    # decides whether the spec BINDS a reference output for a case's opcode.
    # None (no readable L3) fails CLOSED — no case can be waived.
    l3_opcodes = load_l3_opcodes(project_root)

    def _scaffold_scope(case: Dict[str, Any]) -> Optional[str]:
        """ORGANIC #761 — "in" / "out" of the TB producer's scaffold scope, or
        None when the producer's scope could not be read. ANNOTATION ONLY: it
        is recorded on the result and never consulted by the pass/fail
        decision, so it cannot become a back door that waives a case."""
        if producer_scaffold_kinds is None:
            return None
        return "in" if case_kind(case) in producer_scaffold_kinds else "out"

    for c in cases:
        case_id = str(c.get("id", c.get("name", "")))
        category = c.get("category", c.get("type", c.get("kind", "")))
        is_cmd_rsp = category.lower() in ("cmd_response", "cmd_rsp", "happy", "happy_path") if category else False

        # ORGANIC #808 — verification_checklist (DV-milestone) rows are scoped
        # OUT of the TB-evidence demand: a DV process milestone is not
        # TB-traceable, so credit the row's CARRIED status instead. A
        # satisfied/deferred row (Done/N/A/Waived/Pass) is credited as ok; a
        # blank/None-or-explicit-FAIL row surfaces as a checklist gap (NOT a
        # TB-evidence failure, so it can never mask a missing digital TB).
        # §4.05 NO-LEAK: only kind=verification_checklist reaches this branch —
        # functional_vector / functional / cmd_response cases fall through to the
        # unchanged TB-evidence logic below.
        #
        # CRITICAL (§4.05 no-leak, mirrors the #773 r2 _has_digital_signal
        # guard): a case carrying a GENUINE DIGITAL signal (is_cmd_rsp, an
        # opcode/cmd field, or a digital category token) is a real functional
        # vector that the digital TB MUST exercise — a spurious
        # `kind=verification_checklist` mislabel must NOT exempt it from the
        # TB-evidence demand. So the checklist branch fires ONLY for a row that
        # carries no digital signal; a digital case falls through and still
        # FAILs without TB evidence.
        if is_verification_checklist(c) and not _has_digital_signal(c, is_cmd_rsp):
            cls = classify_checklist(c)
            st = checklist_status(c) or "none"
            if cls == "satisfied":
                results.append({
                    "id": case_id,
                    "category": category,
                    "kind": case_kind(c),
                    "evidence": [
                        f"verification_checklist DV-milestone satisfied "
                        f"(status={st}); not TB-traceable, credited by carried "
                        f"status (ORGANIC #808)"
                    ],
                    "pass": True,
                    "status": "pass",
                    "waived": False,
                    "checklist_gap": False,
                    "review_required": False,
                    "capability_gap": None,
                    "producer_scaffold_scope": _scaffold_scope(c),
                })
                ok_count += 1
            else:
                results.append({
                    "id": case_id,
                    "category": category,
                    "kind": case_kind(c),
                    "evidence": [
                        f"verification_checklist DV-milestone NOT satisfied "
                        f"(status={st}); surfaced as a checklist shortfall, NOT "
                        f"a TB-evidence failure (ORGANIC #808; review_required)"
                    ],
                    "pass": False,
                    "status": "checklist_gap",
                    "waived": False,
                    "checklist_gap": True,
                    "review_required": True,
                    "capability_gap": None,
                    "producer_scaffold_scope": _scaffold_scope(c),
                })
                checklist_gap_count += 1
            continue

        evidence: List[str] = []
        if is_cmd_rsp:
            if case_has_opcode_evidence(c, tb_blob):
                evidence.append("opcode in tb")
            if summary_has_pass(case_id, summary):
                evidence.append("summary pass record")
        # For any category, ID substring counts as evidence of trace-to-req
        if case_id_appears(case_id, tb_blob, summary):
            evidence.append("id substring in tb/summary")
        ok = bool(evidence)
        status = "pass" if ok else "fail"
        waived = False
        # ORGANIC #773 — class/kind-aware A/M-track waiver. ONLY a
        # verification_intent case with no digital evidence, under an
        # anchored --skip-analog, is credited as WAIVED-DEFERRED. §4.05
        # NO-LEAK: a non-verification_intent (digital) case never reaches
        # here, and an unanchored verification_intent case (waiver_active
        # False) FAILs as before.
        # ORGANIC #773 r2 (Step-2.7) — a `kind=verification_intent` MISLABEL must
        # not let a genuinely-DIGITAL case escape: refuse the waiver for any case
        # carrying a digital signal (is_cmd_rsp by category-priority, an
        # opcode/cmd field, or a digital category/type), so a digital
        # cmd_response with no TB evidence STILL FAILs even if it also carries a
        # spurious verification_intent kind.
        cap_gap: Optional[str] = None
        if (not ok and waiver_active and is_verification_intent(c)
                and not _has_digital_signal(c, is_cmd_rsp)):
            waived = True
            status = "waived"
            cap_gap = CAP_ANALOG_VERIFICATION_INTENT
            _why = ("analog track deferred via --skip-analog"
                    if analog_anchor_kind == "deferred"
                    else "analog track RAN and owns this case's oracle; its "
                         "own verdict is unaffected by this credit")
            evidence = [
                "WAIVED-DEFERRED: verification_intent A/M-track oracle "
                f"({CAP_ANALOG_VERIFICATION_INTENT}); {_why}; "
                f"reviewable anchor: {analog_anchor}"
            ]
        # ORGANIC #778 companion — conditional-optional feature case, whose
        # own text references an optional Plugin-selectable feature that the
        # design's declaration.json does not confirm as selected for this
        # build. Checked BEFORE the broader cpu-functional-oracle waiver so
        # the more PRECISE reason (missing declaration, not missing oracle)
        # is reported when both could apply.
        elif not ok and not waived:
            _cond_token = is_conditional_optional_case(c)
            if _cond_token and not conditional_feature_declared(
                    project_root, _cond_token):
                waived = True
                status = "waived"
                cap_gap = CAP_CONDITIONAL_FEATURE_UNDECLARED
                evidence = [
                    f"WAIVED-DEFERRED: case text references an optional "
                    f"Plugin-selectable feature ('{_cond_token}') that the "
                    f"design's declaration.json does not confirm as selected "
                    f"for this build ({CAP_CONDITIONAL_FEATURE_UNDECLARED}); "
                    f"cannot fabricate a golden for an unconfirmed feature "
                    f"(§4.05) — review_required"
                ]
            # ORGANIC #778 companion — CPU functional-oracle waiver: a
            # `functional_vector` case with no per-case golden and no
            # conditional-feature disposition, under an anchored
            # `cap:cpu_functional_oracle` capability gap, is credited as
            # WAIVED-DEFERRED (the oracle genuinely requires a full
            # instruction-set model this pass did not author). §4.05
            # NO-LEAK: a non-functional-vector case with no evidence STILL
            # FAILs, and an unanchored waiver (no results.xml) also FAILs.
            elif cpu_waiver_active and is_functional_vector(c):
                waived = True
                status = "waived"
                cap_gap = CAP_CPU_FUNCTIONAL_ORACLE
                evidence = [
                    "WAIVED-DEFERRED: functional_vector CPU instruction-set "
                    f"oracle ({CAP_CPU_FUNCTIONAL_ORACLE}); CPU oracle "
                    f"deferred (capability gap); reviewable anchor: "
                    f"{cpu_oracle_anchor_desc}"
                ]
            # INTERNAL-VOCABULARY RECONCILIATION — a processor_cpu core whose
            # L3 opcodes Phase 1 rendered as command-response cases IS an
            # instruction-execution oracle the runner could not bind, whenever
            # the case's OWN expectation defers the answer to a structured spec
            # reference it does not carry. Under the anchored
            # cap:cpu_functional_oracle gap it is credited WAIVED-DEFERRED —
            # reaching the same waiver the `functional_vector`-kinded case
            # above reaches, which the OPCODE-DERIVED half of a CPU's L10 could
            # never reach. §4.05 NO-LEAK: gated on ic_class==processor_cpu AND
            # the anchor AND an opcode signal AND absence of an explicit
            # digital cmd_response category AND a DEFERRED oracle, so a
            # non-processor_cpu opcode case, an unanchored case, a genuine
            # cmd_response case, and every case whose expectation is an
            # observable ABSENCE all continue to FAIL.
            else:
                _oracle_ref = (
                    cpu_instruction_oracle_reference(c, ic_class, l3_opcodes)
                    if cpu_waiver_active else None)
                if _oracle_ref:
                    waived = True
                    status = "waived"
                    cap_gap = CAP_CPU_FUNCTIONAL_ORACLE
                    # ORGANIC #786 r7 — SCOPED TO WHAT THE RECORD ESTABLISHES.
                    # r6 said "the spec gives no answer to check against",
                    # which absence does not establish: the extraction that
                    # would have recorded one runs at one of seven opcode
                    # construction sites, so its absence is equally consistent
                    # with a document that states the response somewhere the
                    # extractor does not look. The sentence now claims the
                    # RECORD, names the unestablished part out loud, and leaves
                    # the reader to the census for how much input the refusal
                    # arm had.
                    evidence = [
                        "WAIVED-DEFERRED: processor_cpu instruction-execution "
                        f"oracle case ({CAP_CPU_FUNCTIONAL_ORACLE}); Phase 1 "
                        f"rendered this CPU L3 opcode as a command-response "
                        f"case (kind={case_kind(c)!r}) whose expectation "
                        f"defers its answer to {_oracle_ref!r}. RESOLVED in "
                        f"the design's own L3 opcode entry: that field binds "
                        f"no concrete reference output, and the entry carries "
                        f"no document-derived response extraction for this "
                        f"opcode. WHETHER THE INPUT DOCUMENT STATED ONE IS NOT "
                        f"ESTABLISHED HERE — the extraction that would record "
                        f"it runs at one of seven opcode-construction sites "
                        f"(see cpu_oracle_binding_census.document_derived_"
                        f"records). On this record there is no reference "
                        f"output to grade against, and grading it needs the "
                        f"reference instruction-set model this pass could not "
                        f"bind (capability gap); review_required; reviewable "
                        f"anchor: {cpu_oracle_anchor_desc}"
                    ]
        # ORGANIC #761 — record WHICH scope this case fell in, and, when the
        # case ends with NO TESTBENCH outside the producer's scaffold scope,
        # say so in the case's own evidence list. The verdict is untouched:
        # `status` was decided above and this only appends the sentence a
        # reader previously had to reconstruct from a SKIP line one step up
        # the pipeline.
        #
        # #786 x #761 — this used to key on `status == "fail"` alone. Under the
        # processor_cpu instruction-oracle waiver above, exactly the population
        # #761 was written for (a CPU core's opcode cases, for which the TB
        # producer wrote nothing) turns `waived`, and the diagnostic went
        # silent on it. A case waived for want of an ORACLE is still a case
        # with no TESTBENCH — two independent gaps — so both are now reported,
        # each in its own words. `result_has_no_testbench` decides which
        # outcomes qualify, and it admits ONLY this change's own waiver, so the
        # A/M-track and conditional-feature populations are untouched.
        _scope_side = _scaffold_scope(c)
        if _scope_side == "out" and result_has_no_testbench(
                {"status": status, "capability_gap": cap_gap}):
            _what = ("this gate grades every L10 case, so the case FAILs — no "
                     "testbench was written for it and none was fabricated"
                     if status == "fail" else
                     f"the case is WAIVED-DEFERRED ({cap_gap}) for want of an "
                     f"oracle, but no testbench was written for it either and "
                     f"the waiver does not supply one")
            evidence = list(evidence) + [
                f"NO PRODUCER: kind={case_kind(c) or '(none)'} is outside the TB "
                f"producer's scaffold scope "
                f"({', '.join(sorted(producer_scaffold_kinds))}); {_what} "
                f"(ORGANIC #761)"
            ]
        # ORGANIC #786 r5 — record HOW the design's own L3 answered this case's
        # pointer, for every case that carries an instruction signal. Pure
        # ANNOTATION (the verdict was decided above); it exists so a reader can
        # see that a FAIL was `bound` (the spec DOES give the answer) rather
        # than `unbound`, without re-deriving it.
        _resolution: Optional[str] = None
        if any(c.get(f) for f in _INSTRUCTION_SIGNAL_FIELDS):
            _v, _d = resolve_case_oracle(c, l3_opcodes)
            _resolution = f"{_v}:{_d}" if _d else _v
        results.append(
            {
                "id": case_id,
                "category": category,
                "kind": case_kind(c),
                "producer_scaffold_scope": _scope_side,
                "oracle_resolution": _resolution,
                "evidence": evidence,
                "pass": ok,
                "status": status,
                "waived": waived,
                "review_required": waived,
                "capability_gap": cap_gap,
            }
        )
        if ok:
            ok_count += 1
        elif waived:
            # A WAIVED-DEFERRED case is neither a pass nor a fail: it is
            # carried separately (count_waived) and reported via the rc=3
            # PASS_WITH_WAIVERS path, NOT folded into fail_count (which is
            # reserved for genuine, un-waivable digital misses — §4.05).
            pass
        else:
            fail_count += 1
    return results, ok_count, fail_count


def count_waived(results: List[Dict[str, Any]]) -> int:
    """Number of results carrying the ORGANIC #773 WAIVED-DEFERRED status."""
    return sum(1 for r in results if r.get("status") == "waived")


def count_checklist_gaps(results: List[Dict[str, Any]]) -> int:
    """ORGANIC #808 — number of verification_checklist DV-milestone rows that
    are NOT satisfied (blank/None or an explicit FAIL status). These are
    checklist shortfalls (review_required) — surfaced separately, NOT folded
    into fail_count (which is reserved for genuine TB-evidence misses)."""
    return sum(1 for r in results if r.get("status") == "checklist_gap")


def _tb_files_under(d: Path) -> bool:
    """True when directory `d` directly or recursively holds a testbench
    .v/.sv (a tb_*.v or anything with a `module tb` / `_tb`)."""
    if not d.is_dir():
        return False
    for p in d.rglob("*"):
        if p.is_file() and p.suffix in (".v", ".sv"):
            return True
    return False


import _path_layout as _pl  # noqa: E402


def _resolve_tb_dir(given: str) -> Optional[str]:
    """ORGANIC #572 — the default --tb-dir (phase2/stage1/sim/tb) is rigid;
    a project that keeps testbenches at the sim/ ROOT (phase2/stage1/sim/)
    reported 4/4 false 'lack evidence'. Try the given path first, then its
    parent when the leaf is 'tb', then the canonical sim roots. Returns the
    first directory that actually holds a .v/.sv, else None."""
    # vibe-ic#599: this list did not have `sim_full_stack`, which is where the
    # flow itself writes the full-stack testbench and — MEASURED over the
    # tracked corpus — where 29 of them are, against 11 under `sim/`. The
    # resolution now lives in `_path_layout` so `l12_tb_coverage_check`, which
    # had NO fallback at all, answers the same question the same way; two gates
    # with two independently incomplete views of one question is how step 4 got
    # credited without any measurement.
    got = _pl.resolve_tb_dir(Path("."), given)
    if got is not None:
        try:
            return str(got.relative_to(Path(".").resolve()))
        except ValueError:
            return str(got)
    # last resort: return the given path if it at least exists as a dir, so
    # the caller's missing-dir error message is accurate.
    return given if Path(given).is_dir() else None


def _resolve_summary(given: str) -> str:
    """ORGANIC #572 — fall back across the common summary locations when the
    default path is absent (mirrors read_summary's own two candidates but
    extends to the sim/ root and reports/)."""
    cands = [given, "phase2/stage1/sim/work/summary.txt",
             "phase2/stage1/sim/summary.txt", "reports/sim/summary.txt",
             "sim/work/summary.txt", "sim/summary.txt"]
    for c in cands:
        if Path(c).is_file():
            return c
    return given


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--l10", required=True, help="phase1/generated_docs/L10_TEST_CASES.json")
    p.add_argument("--tb-dir", default="phase2/stage1/sim/tb", help="directory containing testbench .v files")
    p.add_argument("--summary", default="phase2/stage1/sim/work/summary.txt", help="sim summary file")
    p.add_argument("--out", default="reports/gates/l10_tb_conformance.json")
    p.add_argument("--strict", action="store_true", help="fail on ANY case lacking evidence (default)")
    p.add_argument("--warn-only", action="store_true", help="print warnings but exit 0")
    p.add_argument(
        "--skip-analog", action="store_true",
        help="ORGANIC #773 — the analog / mixed-signal track is explicitly "
             "deferred; verification_intent (A/M-track) L10 cases with no "
             "digital-TB trace are credited as WAIVED-DEFERRED (rc=3 + "
             "PASS_WITH_WAIVERS) when a reviewable capability-gap anchor "
             "(sim/results.xml) is present, instead of hard-FAILing Step 4. "
             "§4.05: genuine digital cases with no evidence STILL FAIL.")
    p.add_argument(
        "--project", default=None,
        help="ORGANIC #773 — project root used to locate the reviewable "
             "analog-deferral anchor (phase2/stage1/sim/results.xml). "
             "Defaults to inferring from --l10's project tree.")
    p.add_argument(
        "--analog-anchor", default=None,
        help="ORGANIC #773 — explicit path to the reviewable capability-gap "
             "anchor (sim/results.xml). Overrides --project inference.")
    args = p.parse_args(argv)

    try:
        cases = load_l10(args.l10)
    except Exception as e:
        print(f"[l10-tb-conformance] cannot load L10: {e}", file=sys.stderr)
        return 2

    tb_dir = _resolve_tb_dir(args.tb_dir)
    if tb_dir is None:
        print(f"[l10-tb-conformance] tb dir missing: {args.tb_dir} "
              f"(and no fallback under sim/)", file=sys.stderr)
        return 2

    per_file, tb_blob = read_all_tb_text(tb_dir)
    summary = read_summary(_resolve_summary(args.summary))

    # #206 — VACUOUS-TB substance gate (shared with vacuous_testbench_check so
    # the two never disagree). A placeholder testbench prints a pass and never
    # instantiates the DUT; its `$display("[TB <id>] PASS_PLACEHOLDER")` puts the
    # case id into tb_blob, so the id-substring / opcode evidence below used to
    # credit it — a check that COUNTED cases present, not cases exercised. When
    # NOTHING under the sim tree drives the design, that "evidence" is theatre:
    # suppress the blob so genuine digital cases FAIL (no evidence) while the
    # existing anchored A/M waiver path is untouched (verification_intent cases
    # still waive; §4.05 — a vacuous DIGITAL TB can never be waived). A tree with
    # >=1 live driver keeps its full evidence corpus, so a trace-companion TB
    # sitting beside a real driver still credits its cases.
    vacuous_sim_tree = False
    vacuous_files: List[str] = []
    if per_file and _vtb is not None and not _vtb.any_source_drives_dut(
            per_file.values()):
        vacuous_sim_tree = True
        vacuous_files = sorted(per_file.keys())
        tb_blob = ""  # evidence suppressed — presence is not coverage (#206)

    # ORGANIC #773 — resolve the reviewable analog-deferral anchor. The
    # project root is the explicit --project, else inferred from the L10
    # path's project tree (…/phase1/generated_docs/L10*.json → project root).
    project_root: Optional[str] = args.project
    if project_root is None:
        l10p = Path(args.l10).resolve()
        # Walk up to the project root: the parent of phase1/ (if present),
        # else the L10 file's parent (best-effort; anchor resolution is
        # tolerant of a missing file).
        for parent in l10p.parents:
            if parent.name in ("generated_docs", "phase1"):
                continue
            if (parent / "phase1").is_dir() or (parent / "phase2").is_dir():
                project_root = str(parent)
                break
        if project_root is None:
            project_root = str(l10p.parent)
    # The A/M track owns a verification_intent case's oracle whether it was
    # DEFERRED or RUN; only the reviewable anchor differs. Resolving the
    # second case is #773 r3 — see analog_ran_anchor.
    analog_anchor = (
        analog_skip_anchor(project_root, args.analog_anchor)
        if args.skip_analog else analog_ran_anchor(project_root)
    )
    analog_anchor_kind = "deferred" if args.skip_analog else "ran"
    # ORGANIC #778 companion — auto-detect the CPU functional-oracle
    # capability gap from results.xml. No CLI flag needed: the gate reads
    # the runner's own artefact and coordinates with
    # cpu_functional_oracle_waiver_check.
    cpu_anchor = cpu_oracle_anchor(project_root)

    # ORGANIC #761 — read the PRODUCER's own scope over this same case list, so
    # the artefact and the stderr can name BOTH scopes. Annotation only: the
    # verdict below is computed exactly as before.
    prod_scope = producer_scope_report(cases)

    results, ok_count, fail_count = evaluate(
        cases, tb_blob, summary,
        skip_analog=args.skip_analog, analog_anchor=analog_anchor,
        analog_anchor_kind=analog_anchor_kind,
        cpu_oracle_anchor_desc=cpu_anchor, project_root=project_root,
        producer_scaffold_kinds=scaffold_kinds_of(prod_scope),
    )
    scope_gap = count_producer_scope_gap(results)
    waive_count = count_waived(results)
    checklist_gap_count = count_checklist_gaps(results)
    waiver_caps = sorted({
        r["capability_gap"] for r in results
        if r.get("status") == "waived" and r.get("capability_gap")
    })

    out = {
        "total": len(cases),
        "ok": ok_count,
        "fail": fail_count,
        "waived": waive_count,
        "checklist_gaps": checklist_gap_count,
        "capability_gap": waiver_caps[0] if len(waiver_caps) == 1 else (waiver_caps or None),
        "capability_gaps": waiver_caps or None,
        "analog_anchor": analog_anchor,
        "cpu_oracle_anchor": cpu_anchor,
        # ORGANIC #786 r5 — how the design's OWN L3 answered each
        # instruction-signal case's pointer (`resolve_case_oracle` histogram).
        # `bound` = the spec gives a reference output, so the case is failable;
        # `unbound` = it does not, which is the registered capability gap.
        # ANNOTATION ONLY — no verdict reads it; it exists so an all-waived
        # layer is visibly a property of the L-DOC, not of this gate.
        "cpu_oracle_binding_census": cpu_oracle_binding_census(
            cases, load_l3_opcodes(project_root)) or None,
        # ORGANIC #761 — the OTHER reader of this same L10 layer. `producer_scope`
        # is the TB producer's own record (case total, kind histogram, the kinds
        # its scaffold covers); `producer_scope_gap` counts the cases that ended
        # with NO TESTBENCH EVIDENCE (FAILed, or WAIVED for want of the CPU
        # instruction-set oracle — see `result_has_no_testbench`, which admits
        # that one waiver and no other) and that no producer in the flow was
        # scoped to write a testbench for.
        # A non-zero gap does NOT soften the verdict — it explains it.
        "producer_scope": prod_scope,
        "producer_scope_gap": scope_gap,
        # #206 — the substance verdict the gate judged on: whether the sim tree
        # actually drives the DUT, and (when it does not) the offending vacuous
        # testbench files. Emitted so this verdict can be cross-checked from the
        # gate's own output instead of trusted on its say-so.
        "sim_tree_drives_dut": (not vacuous_sim_tree) if per_file else None,
        "vacuous_sim_tree": vacuous_sim_tree,
        "vacuous_testbench_files": vacuous_files,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    if fail_count:
        # A genuine FAIL dominates — even if some cases were waived, an
        # un-waivable digital miss is still a hard FAIL (§4.05 NO-LEAK).
        #
        # ORGANIC #761 — when the failures are cases the TB producer was never
        # scoped to write for, say BOTH scopes here, at the point of the FAIL.
        # The verdict is unchanged (fail_count still dominates, rc still 1);
        # what changes is that the reader no longer has to pair this number with
        # a `SKIP  no functional_vector L10 cases` line further up the run to
        # find out that the two readers of one layer disagreed about its scope.
        if scope_gap:
            hist = (prod_scope or {}).get("kind_histogram") or {}
            scaffold = (prod_scope or {}).get("scaffold_kinds") or []
            # #786 x #761 — `scope_gap` no longer counts FAILures alone (a case
            # waived for want of an oracle still has no testbench), so it must
            # NOT be narrated against `fail_count`: with 8 failures and 4
            # out-of-scope waivers this sentence read "12 of the 8 failure(s)".
            # Name the split instead, so the number is always attributed to the
            # population it was actually counted over.
            gap_fail = sum(
                1 for r in results
                if r.get("status") == "fail"
                and r.get("producer_scaffold_scope") == "out")
            gap_waived = scope_gap - gap_fail
            _split = (f"{gap_fail} FAILing"
                      + (f" and {gap_waived} WAIVED-DEFERRED for want of an "
                         f"oracle" if gap_waived else ""))
            print(
                f"[l10-tb-conformance] SCOPE DISAGREEMENT — the L10 layer "
                f"carries {len(cases)} case(s) of kind(s) "
                f"{{{', '.join(f'{k} {v}' for k, v in hist.items())}}}; the TB "
                f"producer (testbench_gen) auto-emits a scaffold ONLY for "
                f"{{{', '.join(scaffold)}}}. This gate grades ALL {len(cases)}. "
                f"{scope_gap} case(s) — {_split} — are cases NO producer in "
                f"the flow was scoped to write a testbench for; no testbench "
                f"exists for them, and none was fabricated. (This run has "
                f"{fail_count} failure(s) in total.) Fix the scope, not the "
                f"gate: a design that ships no testbench for a declared case "
                f"is still marked down.",
                file=sys.stderr,
            )
        if vacuous_sim_tree:
            print(
                f"[l10-tb-conformance] VACUOUS sim tree — none of "
                f"{len(vacuous_files)} testbench(es) instantiate the DUT; "
                f"id-substring / opcode presence is NOT coverage (#206). "
                f"Files: {', '.join(vacuous_files)}",
                file=sys.stderr,
            )
        print(
            f"[l10-tb-conformance] {fail_count}/{len(cases)} cases lack evidence "
            f"(see {args.out}):",
            file=sys.stderr,
        )
        for r in results:
            if r.get("status") == "fail":
                print(f"  - {r['id']} ({r['category']})", file=sys.stderr)
        if args.warn_only:
            return 0
        return 1

    if waive_count or checklist_gap_count:
        # ORGANIC #773 — class/kind-aware A/M-track waiver, AND/OR
        # ORGANIC #808 — verification_checklist (DV-milestone) checklist gaps.
        # In both cases every genuine digital / functional case that REQUIRES a
        # TB trace had its evidence (fail_count == 0 here). The only un-credited
        # rows are verification_intent (A/M-track) cases under an anchored
        # --skip-analog and/or verification_checklist (DV-milestone) rows whose
        # carried status is blank/None/FAIL. Mirror #651/#773: rc=3 +
        # line-start PASS_WITH_WAIVERS sentinel so flow_compliance_check
        # promotes Step 4 to WAIVED-DEFERRED (Overall PASS_WITH_WAIVERS),
        # not a hard FAIL.
        bits = [f"{ok_count}/{len(cases)} cases satisfied"]
        analog_waived = sum(
            1 for r in results
            if r.get("status") == "waived"
            and r.get("capability_gap") == CAP_ANALOG_VERIFICATION_INTENT)
        cond_waived = sum(
            1 for r in results
            if r.get("status") == "waived"
            and r.get("capability_gap") == CAP_CONDITIONAL_FEATURE_UNDECLARED)
        cpu_waived = sum(
            1 for r in results
            if r.get("status") == "waived"
            and r.get("capability_gap") == CAP_CPU_FUNCTIONAL_ORACLE)
        if analog_waived:
            bits.append(
                f"{analog_waived}/{len(cases)} verification_intent A/M-track "
                f"case(s) WAIVED-DEFERRED ({CAP_ANALOG_VERIFICATION_INTENT}, "
                f"review_required; anchor: {analog_anchor})")
        if cond_waived:
            bits.append(
                f"{cond_waived}/{len(cases)} conditional-optional-feature "
                f"case(s) WAIVED-DEFERRED ({CAP_CONDITIONAL_FEATURE_UNDECLARED}"
                f", review_required — design's declaration.json does not "
                f"confirm selection)")
        if cpu_waived:
            bits.append(
                f"{cpu_waived}/{len(cases)} CPU instruction-set oracle "
                f"case(s) WAIVED-DEFERRED ({CAP_CPU_FUNCTIONAL_ORACLE}, "
                f"review_required; anchor: {cpu_anchor})")
        if checklist_gap_count:
            bits.append(
                f"{checklist_gap_count}/{len(cases)} verification_checklist "
                f"DV-milestone row(s) not satisfied (review_required; "
                f"ORGANIC #808 — process milestone, not TB-traceable)")
        print(
            "PASS_WITH_WAIVERS: l10_tb_conformance — " + "; ".join(bits)
            + f"  → {args.out}")
        return 3

    print(f"[l10-tb-conformance] PASS  {ok_count}/{len(cases)} cases covered  → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
