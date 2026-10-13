#!/usr/bin/env python3
"""cpu_functional_oracle_waiver_check.py — legacy-named Step-4 functional
evidence requirement.

ENFORCEMENT: blocking. A completed connectivity simulation is useful
structural evidence, but it is not a functional oracle and cannot release
Step 4. The runner still records the connectivity result verbatim
(``CONNECTIVITY_PASS``, ``functional_verified=false`` and its transcript
pointer); this gate now reports that state as ``INCOMPLETE`` and exits 1.

Program-first routing is explicit: ``professional_tb_gen`` generates and runs
the self-checking oracle first. A class whose reference semantics are not
deterministically derivable is handed to the shipped ``testbench-gen`` expert
fallback to fill the reference hook and re-run it. Missing semantics are work
to close, never a class waiver. The filename is retained for compatibility
with shipped flow definitions and old reports; it no longer grants a waiver.

Verdicts / exit codes (chip-AGNOSTIC — project artifacts only):
  0 = N/A for this gate: sim/results.xml is a genuine functional PASS (an
      oracle / non-connectivity verdict). This gate makes no claim about it;
      the existing functional gates own it.  (Also 0 when no connectivity
      marker is present at all and the verdict is a plain functional PASS.)
  2 = VACUOUS: no sim/results.xml at all — nothing for this gate to assess
      (the absence is the standard missing-file FAIL the files_exist gate
      reports; this gate stays out of the way).
      OR NOT_MEASURED [EXTERNAL] (FX_P2): every case that could run ran and
      passed, and some declared case could not run because the design input
      supplies no stimulus for it (`testbench_gen.case_input_gap`). The JSON
      report says verdict NOT_MEASURED, reason_class EXTERNAL, and names each
      case and what is missing. Never a PASS, never a FAIL.
  1 = INCOMPLETE when a substantiated connectivity-only run exists without a
      real professional/oracle result; FAIL when the bridge evidence is forged
      or broken. Both are blocking and neither is a waiver.

Owner ruling R-0929-OWNER-SUB-ACCEPT moves exactly two kinds of row, and every
verdict above carries a bracketed disclosure when either did:
  (1) a declared case or instruction goal the core-ISA conformance suite ran on
      the SAME RTL with only the top's memory-size PARAMETER raised is CREDITED
      by it (`_l10_execution.isa_conformance_credit`, which re-checks the rule
      and names any refusal); the delivered-memory run is disclosed beside it;
  (2) a firmware row whose named image the design input lacks is NOT_MEASURED
      [input_absent] and EXCLUDED from the verdict, as FPGA steps 6/39 are
      (`testbench_gen.input_absent_exclusion`), and is listed under
      `not_measured_excluded` in the JSON report. It is never a pass and it
      does not block.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import _sim_results_bridge as _srb  # noqa: E402
import _l10_execution as _l10x  # R-0915-87(2): the ONE execution reader  # noqa: E402
import l10_coverage_goal_classify as _cgc  # R-0915-113(4)  # noqa: E402
import testbench_gen as _tbg  # who owns a case that did not run  # noqa: E402

# The capability-gap token retained on a connectivity-PASS evidence record.
# A chip-AGNOSTIC capability identifier, NOT a chip/vendor/SKU literal.
CAP_CPU_FUNCTIONAL_ORACLE = "cap:cpu_functional_oracle"
CONNECTIVITY_VERDICT = "CONNECTIVITY_PASS"


def _read_xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip() if m else "")


def _waiver_track_class_label(xml: str) -> str:
    """ORGANIC #779 — derive the human-readable '<track> no-oracle <ic_class>
    class' label from the STRUCTURED results.xml, instead of the hardcoded
    'generic_full_stack no-oracle CPU/SoC class' literal that MISLABELS non-CPU
    classes. After #745 made arith_oracle_tb_gen DEFER for serial-parallel
    multipliers, `digital_arithmetic_primitive` ICs route into this same #654
    gate — and the hardcoded 'CPU/SoC' string then mis-described them, even
    though every structured field (verdict / capability_gap /
    functional_verified / waiver_reason) was already correct. The helper name
    and legacy XML field are retained for artifact compatibility.

    The connectivity bridge writes <verification_track> directly (e.g.
    'generic_full_stack') and embeds the real ic_class in <waiver_reason> as a
    `class '<name>'` token (from _class_uses_aid_reference_tb). Reads a dedicated
    <ic_class> tag first if a future schema adds one; falls back to a generic
    label when a field is absent (older artifact). chip-AGNOSTIC — reads the
    class from structured output, never a chip/vendor/SKU literal."""
    track = _read_xml_field(xml, "verification_track") or "generic_full_stack"
    ic_class = _read_xml_field(xml, "ic_class")
    if not ic_class:
        m = re.search(r"\bclass\s+'([A-Za-z0-9_]+)'",
                      _read_xml_field(xml, "waiver_reason"))
        ic_class = m.group(1) if m else ""
    if ic_class:
        return f"{track} no-oracle {ic_class} class"
    return f"{track} no-oracle class"


# A PROCESS MILESTONE IS NOT AN EXECUTABLE TEST.
#
# MEASURED, opentitan_aes at v1.15.80: this gate reported "103 declared L10
# row(s), 0 functional tests ran" and blocked Step 4. All 103 rows carried
# `kind: "verification_checklist"`, harvested by Phase 1 from the vendor's DV
# CHECKLIST — rows named `spec_complete`, `csr_defined`, `clkrst_connected`,
# whose stimulus is the literal string "DV checklist item SPEC_COMPLETE — Done"
# and whose expected value is "DV checklist item satisfied (Done)".
#
# Nothing can drive those. There is no stimulus and no expected VALUE in any
# circuit sense; they record that a project reached a milestone. The unit-TB
# producer was RIGHT to place 0 of 103 in its scaffold scope — the defect was
# never that the tests do not run, it is that a project-management checklist
# was counted as a test-case population, so the gate demanded execution of 103
# things that can never be executed and reported a shortfall that was
# arithmetic, not evidence.
#
# They are still REPORTED, under their own key, so a reader sees what the input
# declared and why it is not in the executable denominator. This NARROWS a
# blocking denominator, so the controls below hide a real functional row inside
# a checklist-dominated L10 and prove it is still counted and still demanded.
#
# chip-AGNOSTIC: a declared `kind`, not a chip, vendor or document literal.
_NON_EXECUTABLE_TEST_KINDS = frozenset({"verification_checklist"})


# ORGANIC #2055 — NAME THE ROW KIND THE STEP COULD NOT RUN.
#
# MEASURED, u_hawaii_adc at v1.17.83 (lane czadc28, front door, image 0.3.46):
# this gate's blocking sentence read "0 functional tests ran for 4 declared
# L10/L12 row(s). Connectivity is not a functional oracle." Every one of those
# four rows was `kind: verification_intent` — analog acceptance prose harvested
# from the input's `## Verification intent` list — and the TB producer had
# already said so in its own SKIP ("0 in scope, 4 out of scope"). The sentence
# named neither fact, so three separate lanes read the wall as a defect in the
# RTL and re-authored a testbench that was never the missing piece.
#
# The numerator and the denominator are both kept exactly as they were; this
# adds the two facts a reader needs to act: WHAT KIND the declared rows are,
# and HOW MANY of them any producer in the flow is scoped to author. The
# producer's scope is IMPORTED from `testbench_gen`, which owns it, rather than
# respelled here — the #761 two-private-scopes shape, refused a third time.
#
# chip-AGNOSTIC: a declared `kind` vocabulary, never a chip/vendor/SKU literal.
def _row_kind_disclosure(project: Path) -> str:
    """`" [verification_intent 2]; 0 of 2 authorable ..."` for the blocking
    sentence, or `""` when the rows or the producer scope cannot be read.

    "Could not read it" is not "read it and it was empty": on any failure this
    returns the empty string and the sentence keeps exactly the wording it had
    before, rather than asserting a breakdown nobody measured.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import testbench_gen as _tb
    except Exception:
        return ""
    rows: list = []
    gd = _pl.generated_docs_dir(project)
    rows.extend(_declared_rows(
        gd / "L10_TEST_CASES.json", ("test_cases", "cases", "vectors")))
    rows.extend(_declared_rows(
        gd / "L12_BEHAVIORAL_SEQUENCES.json",
        ("sequences", "behavioral_sequences")))
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return ""
    # ORGANIC #2064 — THE SCAFFOLD SCOPE IS NOT THE FLOW'S SCOPE ANY MORE.
    #
    # This sentence ended "the rest carry no stimulus ANY PRODUCER IN THE FLOW
    # is scoped to drive", and computed that claim by summing over ONE
    # producer's `SCAFFOLD_KINDS`. That was true while `testbench_gen` was the
    # only producer, and false the moment `analog_acceptance_tb_gen` began
    # authoring an executable acceptance for `verification_intent` rows.
    # MEASURED on u_hawaii_adc with that producer on the tree: this sentence
    # printed "0 of 4" while the flow could author 2 of the 4.
    #
    # The union comes from `testbench_gen.flow_authorable`, the ONE accessor
    # both readers share — the #761 two-private-scopes shape, refused a fourth
    # time. `analog_acceptance` is ABSENT (not zero) from that dict when that
    # producer could not be asked, and the sentence says so rather than
    # reporting a 0 nobody measured.
    try:
        hist = _tb.kind_histogram(rows)
        scope = _tb.SCAFFOLD_KINDS
        flow = _tb.flow_authorable(project, rows)
        authorable = int(flow["authorable"])
    except Exception:
        return ""
    kinds = ", ".join(f"{k} {v}" for k, v in hist.items()) or "(none)"
    by = [f"{flow['scaffold']} inside the TB producer's scaffold scope "
          f"{{{', '.join(sorted(scope))}}}"]
    if "analog_acceptance" in flow:
        by.append(f"{flow['analog_acceptance']} by analog_acceptance_tb_gen")
    else:
        by.append("the analog-acceptance producer could NOT be asked, so its "
                  "share is unmeasured, not zero")
    left = flow.get("unauthorable_kinds") or {}
    return (f" [{kinds}]; {authorable} of {len(rows)} row(s) are authorable by "
            f"some producer in the flow (" + "; ".join(by) + ") — the "
            f"remaining {left or '(none)'} carry no stimulus any producer is "
            f"scoped to drive, so that part of the shortfall is NOT a "
            f"statement about the RTL")


def _row_kind_denominator(project: Path) -> dict:
    """The machine-readable half of `_row_kind_disclosure`.

    Returns ``{}`` — the keys ABSENT, not zeroed — when the rows or the
    producer scope could not be read, so a consumer can tell "nothing was
    declared" from "nothing could be measured"."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import testbench_gen as _tb
    except Exception:
        return {}
    gd = _pl.generated_docs_dir(project)
    rows = [r for r in (
        _declared_rows(gd / "L10_TEST_CASES.json",
                       ("test_cases", "cases", "vectors"))
        + _declared_rows(gd / "L12_BEHAVIORAL_SEQUENCES.json",
                         ("sequences", "behavioral_sequences")))
        if isinstance(r, dict)]
    try:
        flow = _tb.flow_authorable(project, rows)
        out = {
            "declared_row_kinds": _tb.kind_histogram(rows),
            "rows_inside_tb_producer_scaffold_scope": sum(
                1 for r in rows if _tb.case_kind(r) in _tb.SCAFFOLD_KINDS),
            "tb_producer_scaffold_scope": sorted(_tb.SCAFFOLD_KINDS),
            # ORGANIC #2064 — the FLOW's answer beside this one producer's.
            # The scaffold key above keeps meaning exactly what its name says.
            "rows_authorable_by_any_producer": int(flow["authorable"]),
            "rows_not_authorable_by_any_producer": flow.get(
                "unauthorable_kinds") or {},
        }
        if "analog_acceptance" in flow:
            out["rows_authorable_by_analog_acceptance"] = int(
                flow["analog_acceptance"])
        return out
    except Exception:
        return {}


def _split_executable(rows: list) -> "tuple[list, list]":
    """(executable, process_only) over declared test rows."""
    executable, process_only = [], []
    for row in rows:
        kind = (row.get("kind") or row.get("type") or "") if isinstance(
            row, dict) else ""
        (process_only if str(kind).strip().lower()
         in _NON_EXECUTABLE_TEST_KINDS else executable).append(row)
    return executable, process_only


# ── R-0915-102(1): a case the design DECLARED it does not have ─────────────
#
# MEASURED on subservient x gf180mcuD as a DIE, FRONT DOOR, run r48 (lane
# icsub2, host 8HD-4, tree 41d3b39b8): three of the ten declared L10 cases
# are stated CONDITIONALLY by the input's own verification-plan table --
# "(若 Plugin 選 M) Mul/Div 指令" and its Zicsr and C siblings -- and the
# design's own `plugin_output/declaration.json` records
# `isa_extensions: ["I", "Zifencei"]`. None of the three options is selected,
# so the gate was demanding execution of three cases the design had declared
# it does not have, and the blocking sentence read "only 1 of 10".
#
# THE BASIS IS DECLARED, NEVER SCANNED (R-0915-15 stands). This gate does not
# read the input's prose and does not decide what a sentence means. Phase 1's
# L10 emitter attaches `applies_when` at the point the prose already becomes a
# row; here two DECLARED documents are compared -- the case's own condition
# against the design's own selection -- and nothing else.
#
# FAIL-CLOSED IN BOTH DIRECTIONS, which is the whole point of a narrowing:
#   * no declaration, unreadable declaration, or no selection field  -> decide
#     NOTHING; every case stays in the denominator exactly as before;
#   * a case with no `applies_when`                                  -> stays;
#   * an option the design DID select                                -> stays,
#     and is still demanded.
# So the only rows this can remove are ones two declarations agree are absent.
#: Where the design records which optional features it selected.
_DECLARATION_REL = "plugin_output/declaration.json"
#: The selection fields a design may use. A declaration that carries none of
#: them decides nothing -- it is not an empty selection, it is no statement.
_SELECTION_FIELDS = ("isa_extensions", "extensions", "selected_options",
                     "options")


def design_selected_options(project: Path,
                            selection_issue: "Optional[dict]" = None
                            ) -> "Optional[frozenset]":
    """The options the DESIGN declares it has, lower-cased, or None.

    None means no consistent, well-formed selection can be established. An
    explicit [] is an empty selection; blank or non-string entries are not.
    Every supported selector, including a wrapped `fields` declaration, must
    agree after case/whitespace normalization. `selection_issue` receives the
    named reason for an undecidable declaration, without inventing a selection.
    """
    def undecided(reason_class: str, why: str) -> None:
        if selection_issue is not None:
            selection_issue.update(reason_class=reason_class, why=why)
        return None

    try:
        obj = json.loads((Path(project) / _DECLARATION_REL).read_text(
            errors="replace"))
    except (OSError, ValueError):
        return undecided("SELECTION_UNAVAILABLE",
                         f"no selection can be read from {_DECLARATION_REL}")
    if not isinstance(obj, dict):
        return undecided("MALFORMED_SELECTION", "declaration is not an object")
    scopes = [("", obj)]
    if isinstance(obj.get("fields"), dict):
        scopes.append(("fields.", obj["fields"]))
    selections = []
    for prefix, fields in scopes:
        for key in _SELECTION_FIELDS:
            if key not in fields:
                continue
            field = prefix + key
            value = fields[key]
            if not isinstance(value, list):
                return undecided("MALFORMED_SELECTION",
                                 f"{field} must be a list of nonblank strings")
            for index, entry in enumerate(value):
                if not isinstance(entry, str) or not entry.strip():
                    return undecided(
                        "MALFORMED_SELECTION",
                        f"{field}[{index}] must be a nonblank string")
            selections.append((field, frozenset(v.strip().lower() for v in value)))
    if not selections:
        return undecided("SELECTION_UNDECLARED",
                         f"no supported selection field in {_DECLARATION_REL}")
    first_field, selected = selections[0]
    for field, other in selections[1:]:
        if other != selected:
            return undecided(
                "CONFLICTING_SELECTION",
                f"{first_field}={sorted(selected)} conflicts with "
                f"{field}={sorted(other)}")
    return selected


#: The only option spellings the narrowing decides on: RISC-V base/extension
#: names that no other name in the set overlaps. A token outside it -- a
#: subset/superset extension such as Zmmul or Zca, a combined string such as
#: RV32IMC, G or rv32im_zicsr, free text such as "M (mul/div)", or an entry of
#: an unrelated generic options list -- is never decided by string equality,
#: so a case conditional on it stays DEMANDED (R-0929-UNSELECTED-FEATURES:
#: only an EXPLICIT unselected declaration makes a case N/A). Moved here from
#: professional_tb_check so every consumer makes ONE decision.
NARROWING_VOCABULARY = frozenset(
    {"i", "e", "m", "a", "f", "d", "q", "c", "v", "h", "zicsr", "zifencei"})

#: The emitter's sidecar recording, per declaration field, who chose it.
DECLARATION_PROVENANCE_REL = "plugin_output/declaration.provenance.json"


def split_design_declared_na(rows: list,
                             selected: "Optional[frozenset]",
                             not_narrowed: "Optional[list]" = None,
                             selection_issue: "Optional[dict]" = None
                             ) -> "tuple[list, list]":
    """(applicable, design_declared_na) over declared rows. FAIL-CLOSED.

    A row is design-declared N/A only when its `applies_when.option` AND every
    entry of the design's selection are spelled in `NARROWING_VOCABULARY` and
    the option is not selected. Anything else stays applicable (demanded); when
    `not_narrowed` is given, each row that would have been narrowed but could
    not be decided is appended to it with the reason (`row` = its index in
    `rows`)."""
    if selected is None:
        if not_narrowed is not None and selection_issue:
            for index, row in enumerate(rows):
                aw = row.get("applies_when") if isinstance(row, dict) else None
                opt = aw.get("option") if isinstance(aw, dict) else None
                if opt:
                    not_narrowed.append({
                        "case": row.get("name") or row.get("id"), "row": index,
                        "option": opt, **selection_issue,
                        "why": selection_issue["why"] + " -- the case is DEMANDED"})
        return list(rows), []
    undecodable = sorted(o for o in selected if o not in NARROWING_VOCABULARY)
    applicable, na = [], []
    for index, row in enumerate(rows):
        aw = row.get("applies_when") if isinstance(row, dict) else None
        opt = (aw or {}).get("option") if isinstance(aw, dict) else None
        tok = str(opt).strip().lower() if opt else ""
        if not tok or tok in selected:
            applicable.append(row)
            continue
        why = None
        if undecodable:
            why = (f"the declaration's selection is not parseable in the "
                   f"vocabulary {sorted(NARROWING_VOCABULARY)}: {undecodable}")
        elif tok not in NARROWING_VOCABULARY:
            why = (f"option token {opt!r} is not in the vocabulary "
                   f"{sorted(NARROWING_VOCABULARY)}")
        if why:
            applicable.append(row)
            if not_narrowed is not None:
                not_narrowed.append({
                    "case": row.get("name") or row.get("id"), "row": index,
                    "option": opt, "why": why + " -- the case is DEMANDED"})
        else:
            na.append(row)
    return applicable, na


def selection_basis_provenance(project: Path) -> Dict[str, Any]:
    """The provenance record of the declaration field the narrowing read.

    The shared reader validates all selectors first. Only a consistent
    selection has a basis; an undecidable declaration carries its named
    reason. The provenance record comes from the emitter's own sidecar."""
    project = Path(project)
    field = None
    issue: Dict[str, Any] = {}
    selected = design_selected_options(project, issue)
    try:
        obj = json.loads((project / _DECLARATION_REL).read_text(
            errors="replace"))
        fields = obj.get("fields") if isinstance(obj.get("fields"), dict) else obj
        if selected is not None:
            field = next((k for k in _SELECTION_FIELDS
                          if isinstance(fields.get(k), list)), None)
    except (OSError, ValueError, AttributeError):
        pass
    out: Dict[str, Any] = {"field": field,
                           "sidecar": DECLARATION_PROVENANCE_REL,
                           "provenance": None, "provenance_verified": None}
    if selected is None:
        out["selection_issue"] = issue
    try:
        side = json.loads((project / DECLARATION_PROVENANCE_REL).read_text(
            errors="replace"))
        rec = (side.get("fields") or {}).get(field) if field else None
    except (OSError, ValueError, AttributeError):
        out["why"] = "no readable provenance sidecar -- the basis is UNVERIFIED"
        return out
    if not isinstance(rec, dict):
        out["why"] = (f"the sidecar carries no record for {field!r} -- the "
                      f"basis is UNVERIFIED")
        return out
    out["provenance"] = rec.get("provenance")
    out["provenance_verified"] = rec.get("provenance_verified") is True
    if not out["provenance_verified"]:
        out["why"] = ("the sidecar does not verify who chose this selection "
                      "-- the basis is UNVERIFIED")
    return out


def _design_declared_na_disclosure(project: Path) -> dict:
    """What was narrowed away, by name, and on what declared basis."""
    issue: Dict[str, Any] = {}
    selected = design_selected_options(project, issue)
    rows, _p = _split_executable(_declared_rows(
        _pl.generated_docs_dir(project) / "L10_TEST_CASES.json",
        ("test_cases", "cases", "vectors")))
    _app, na = split_design_declared_na(rows, selected)
    if selected is None:
        return {"decided": False,
                **issue, "why": issue["why"] + " -- nothing narrowed"}
    return {
        "decided": True,
        "design_selected": sorted(selected),
        "declaration": _DECLARATION_REL,
        "cases": [{"case": r.get("name"),
                   "option": (r.get("applies_when") or {}).get("option"),
                   "stated": (r.get("applies_when") or {}).get("stated"),
                   "source": (r.get("applies_when") or {}).get("source")}
                  for r in na],
        "note": ("the case declares an option and the design declares it does "
                 "not have it; two declared documents agree the case does not "
                 "apply, so it is not demanded. It is not a waiver and not a "
                 "pass: nothing about it is claimed verified."),
    }


def _declared_rows(path: Path, keys: "tuple[str, ...]") -> list:
    """The declared list itself, without inventing one on bad input."""
    try:
        obj = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    fields = obj.get("fields") if isinstance(obj.get("fields"), dict) else obj
    for key in keys:
        value = fields.get(key)
        if isinstance(value, list):
            return value
    return []


def _list_denominator(path: Path, keys: "tuple[str, ...]") -> int:
    """Count the EXECUTABLE declared rows. See `_NON_EXECUTABLE_TEST_KINDS`."""
    executable, _process = _split_executable(_declared_rows(path, keys))
    return len(executable)


def _process_only_count(path: Path, keys: "tuple[str, ...]") -> int:
    """How many declared rows were excluded as process milestones."""
    _executable, process = _split_executable(_declared_rows(path, keys))
    return len(process)



# ── R-0915-87(2): a green ROW COUNT is not an EXECUTED ORACLE ───────────────
def _declared_l10_case_ids(project: Path) -> "list[str]":
    """Every declared EXECUTABLE L10 case id, in declaration order.

    THE SAME SCOPE THIS GATE ALREADY LANDED, APPLIED AT THE NEW DOOR. The
    executed-oracle guard (R-0915-87(2), 5fc0a5593) asked over EVERY declared
    row, and so re-opened the failure `_split_executable` above was written to
    close. MEASURED, opentitan_aes run_aes_h (e322992a6, 2026-09-18):

        only 8 of 111 declared L10 case(s) EXECUTED their own oracle ...
        Not executed: spec_complete [NOT_EXECUTED], csr_defined [NOT_EXECUTED],
        clkrst_connected [NOT_EXECUTED], ip_top, ip_instantiable,
        physical_macros_defined_80 (+97 more)

    L10 there declares 111 rows: 8 `known_answer_vector` (all 8 EXECUTED, all
    PASS) and 103 `verification_checklist` rows harvested from the vendor's DV
    CHECKLIST, whose stimulus is "DV checklist item SPEC_COMPLETE -- Done".
    Nothing can execute an oracle for a process milestone, so the guard
    demanded 103 things that can never happen, and every executable case had
    in fact run. Those rows are still declared and still REPORTED by
    `_evidence_summary` under their own key; they are only kept out of the
    executed-versus-declared comparison, exactly as the denominator path
    already keeps them out. A functional row hidden among checklist rows is
    still counted and still demanded -- the controls pin that.
    """
    gd = _pl.generated_docs_dir(project)
    out = []
    rows, _process_only = _split_executable(_declared_rows(
        gd / "L10_TEST_CASES.json", ("test_cases", "cases", "vectors")))
    # R-0915-102(1) — a case whose declared option the design did not
    # select is not in the executed-versus-declared comparison. It is
    # still DECLARED and still reported, under its own key.
    rows, _design_na = split_design_declared_na(
        rows, design_selected_options(project))
    # R-0915-113(4) — a COVERAGE GOAL is not a functional vector.
    #
    # MEASURED, sha256 x sky130A, FRONT DOOR, run23 on main 751bed176: this
    # gate read "only 6 of 11 declared L10 case(s) EXECUTED their own oracle"
    # and named `random_message_...`, `message_length`, `protocol` and
    # `mode_switch` among the five. All four declare `kind: coverage_goal`
    # and state an acceptance PERCENTAGE ("100% PASS") over a named SCOPE,
    # not a stimulus and an expected value. Nothing can execute an oracle for
    # an acceptance percentage, so the comparison demanded four things that
    # can never happen -- the same shape `_split_executable` already closed
    # for `verification_checklist` rows, one kind later.
    #
    # They are still DECLARED, still REPORTED, and NEVER marked executed.
    # They move to the population that HAS an instrument for them -- the
    # run's own coverage arm -- and `_coverage_goal_summary` gives each one a
    # verdict by the NUMBER, or NOT_MEASURED with its scope quoted by name.
    # NOT_MEASURED is not a pass and this gate still refuses on it, so no row
    # is satisfied by being un-instrumented.
    rows, _goals = _cgc.partition(rows)
    for row in rows:
        if isinstance(row, dict):
            name = row.get("name") or row.get("id") or row.get("case")
            if name:
                out.append(str(name))
    return out


def _l10_rows_by_name(project: Path) -> dict:
    """Every declared L10 row keyed by its name, for asking WHY one did not run."""
    out: dict = {}
    for row in _declared_rows(_pl.generated_docs_dir(project)
                              / "L10_TEST_CASES.json",
                              ("test_cases", "cases", "vectors")):
        if isinstance(row, dict):
            name = row.get("name") or row.get("id") or row.get("case")
            if name:
                out[str(name)] = row
    return out


def _input_gap(project: Path, row: "dict | None",
               ic_class: "str | None") -> "dict | None":
    """`testbench_gen.case_input_gap`, never raising: an unanswerable question
    keeps the case where it was (blocking), it never moves it out."""
    if not isinstance(row, dict):
        return None
    try:
        return _tbg.case_input_gap(project, row, ic_class)
    except Exception:                                        # noqa: BLE001
        return None


def _oracles_that_actually_ran(project: Path) -> dict:
    """Which declared L10 cases EXECUTED their oracle, by name.

    THE FALSE GREEN THIS CLOSES. MEASURED on the subservient tapeout run r27
    (lane icsub2, 2026-09-16), this gate returned

        PASS: the record's functional_verified=true is SUBSTANTIATED by
        .../l10_unit_tb/results.xml: tests=10 passed=10 failures=0 errors=0

    while NINE of those ten cases never executed an oracle at all. The nine
    testbenches exist and are green, but each is the SUBSTANCE FLOOR the
    generator writes when no oracle is derivable: it asserts only that no
    output stays X/Z after reset, and says so in machine-readable form with
    `VIBEIC_TB_ORACLE: NONE (substance floor only)`. Ten scaffolds that check
    almost nothing produce ten green JUnit rows, and a row count reads them as
    ten verified functions. The single real oracle was
    `reset_n_cycle_instruction` (reset-to-first-bus-activity latency). A CPU
    whose instruction set was never exercised stood one gate away from a
    published PASS.

    So the JUnit predicate stops being SUFFICIENT. It stays NECESSARY — a
    failing, vacuous or unresolvable transcript is refused exactly where it
    always was — and this adds the question the transcript cannot answer: did
    the declared case's own oracle RUN?

    ASKED THROUGH THE READER THAT ALREADY OWNS IT. `_l10_execution` is the same
    module `professional_tb_check` and `l10_tb_conformance_check` consult, and
    it is fail-closed by construction: a missing record, an unreadable one, a
    schema mismatch, a case absent from the record, or a row whose verdict is
    not backed by `sim_executed=true` are each NOT_EXECUTED, never a silent
    pass. A second reader here would be a second answer waiting to disagree
    with theirs.
    """
    declared = _declared_l10_case_ids(project)
    l10 = _pl.generated_docs_dir(project) / "L10_TEST_CASES.json"
    record = _l10x.load_record(project, l10)
    executed: list = []
    not_executed: list = []
    # FX_P2 — a case that did NOT run because the design INPUT supplies no
    # stimulus for it is not this flow's failure and not the design's: it is
    # NOT_MEASURED, named, with what is missing. Decided by
    # `testbench_gen.case_input_gap` (delivery + the producer's own oracle
    # families), never here. A case that RAN keeps its verdict (a FAIL stays
    # a FAIL), and one this flow could have run stays blocking.
    input_not_supplied: list = []
    # R-0929-OWNER-SUB-ACCEPT (1) — a case this record left NOT_EXECUTED that
    # the core-ISA conformance suite ran on the SAME RTL at a test value of
    # the top's memory-size PARAMETER is credited by that suite, and the
    # credit is disclosed (`_l10x.isa_conformance_credit` re-checks every
    # condition of the rule and names the one that fails). A FAIL is never
    # asked: a case that ran and failed stays a FAIL.
    isa_credited: list = []
    isa_refused: list = []
    # R-0929-OWNER-SUB-ACCEPT (2) — a firmware row whose named image the input
    # lacks is NOT_MEASURED [input_absent] and EXCLUDED from this verdict, the
    # F10 mechanism steps 6/39 use (`testbench_gen.input_absent_exclusion`).
    # It stays listed in `input_not_supplied`, flagged, and is published
    # under `not_measured_excluded`; it never blocks and is never a pass.
    excluded: list = []
    rows = _l10_rows_by_name(project) if declared else {}
    ic_class = _tbg._detect_ic_class(project) if declared else None
    for case_id in declared:
        state, why = _l10x.case_state(case_id, record)
        if state == _l10x.PASS:
            executed.append(case_id)
            continue
        if state == _l10x.NOT_EXECUTED:
            credit, refusal = _l10x.isa_conformance_credit(
                project, case_id, rows.get(case_id))
            if credit is not None:
                isa_credited.append(credit)
                continue
            if refusal:
                isa_refused.append({"case": case_id, "why": refusal})
        gap = (_input_gap(project, rows.get(case_id), ic_class)
               if state == _l10x.NOT_EXECUTED else None)
        if gap is not None:
            entry = {"case": case_id, "state": state,
                     "why": gap["reason"],
                     "missing_from_input": gap["missing_from_input"]}
            excl = (_tbg.input_absent_exclusion(
                project, rows.get(case_id), ic_class)
                if gap.get("missing_images") else None)
            if excl is not None:
                entry["excluded_from_verdict"] = excl["excluded_from_verdict"]
                excluded.append(excl)
            input_not_supplied.append(entry)
        else:
            row = rows.get(case_id) if isinstance(rows.get(case_id), dict) \
                else {}
            aw = row.get("applies_when")
            opt = aw.get("option") if isinstance(aw, dict) else None
            if opt and state == _l10x.NOT_EXECUTED:
                # R-0915-102 left it in the denominator because the design
                # has declared no selection yet (a declaration that excludes
                # it removes it before this loop, as NOT_APPLICABLE citing
                # that declaration). Say so: it is not the input's gap.
                why = (f"{why}; applies only if the design selects option "
                       f"{opt!r}, and {_DECLARATION_REL} declares no "
                       f"selection at this point")
            not_executed.append({"case": case_id, "state": state, "why": why})
    return {
        "declared": declared,
        "declared_count": len(declared),
        "executed": executed,
        "executed_count": len(executed),
        "not_executed": not_executed,
        "not_executed_count": len(not_executed),
        "input_not_supplied": input_not_supplied,
        "input_not_supplied_count": len(input_not_supplied),
        "not_measured_excluded": excluded,
        "isa_conformance_credited": isa_credited,
        "isa_conformance_refused": isa_refused,
        "record_available": bool(record.get("available")),
        "record_reason": record.get("reason"),
        "asked_through": "_l10_execution.case_state",
    }



#: Where the run's coverage arm publishes the numbers a goal is measured
#: against. Read-only, and absent is NOT_MEASURED, never a pass.
_COVERAGE_TOTALS_RELS = (
    "reports/phase2/coverage/coverage_verilator.json",
    "reports/phase2/coverage/coverage_actual.json",
)


#: Instruments that publish their OWN dimensions, each in its own receipt.
#: R-0915-131: a dimension belongs to exactly one instrument, so a second arm
#: can never overwrite the first arm's numbers -- the totals are FUSED, and a
#: receipt that publishes nothing contributes nothing rather than blanking
#: what another arm measured.
_COVERAGE_DIMENSION_RECEIPT_RELS = (
    "reports/phase2/coverage/instruction_coverage.json",
)


def _totals_of(project: Path, rels) -> "tuple[dict, str]":
    """The first readable `totals` among `rels`, with the one that supplied it."""
    for rel in rels:
        f = Path(project) / rel
        if not f.is_file():
            continue
        try:
            doc = json.loads(f.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        totals = doc.get("totals") if isinstance(doc, dict) else None
        if isinstance(totals, dict) and totals:
            return totals, rel
    return {}, ""


def _coverage_totals(project: Path) -> "tuple[dict, str]":
    """`(totals, source)` FUSED over the run's coverage instruments.

    The verilator arm owns line/toggle/branch; a per-dimension instrument owns
    its own (R-0915-131). Fusing rather than first-wins is what lets a second
    instrument ADD a dimension without either arm having to know about the
    other -- and an arm that published nothing simply adds nothing, so an
    absent instrument is never a blank over a measured dimension."""
    fused: dict = {}
    sources: "list[str]" = []
    base, base_src = _totals_of(project, _COVERAGE_TOTALS_RELS)
    if base:
        fused.update(base)
        sources.append(base_src)
    for rel in _COVERAGE_DIMENSION_RECEIPT_RELS:
        extra, extra_src = _totals_of(project, (rel,))
        if not extra:
            continue
        # A per-dimension receipt may only ADD its own dimension(s); it never
        # restates one another arm already measured.
        for dim, row in extra.items():
            if dim not in fused:
                fused[dim] = row
        sources.append(extra_src)
    if fused:
        return fused, " + ".join(sources)
    return {}, ("the run published no coverage totals under "
                + " or ".join(_COVERAGE_TOTALS_RELS
                              + _COVERAGE_DIMENSION_RECEIPT_RELS))


def _dimension_receipt(project: Path, dimension: str) -> "tuple[dict | None, str]":
    """`(receipt, why_not)`: the per-dimension instrument's receipt for
    `dimension`, when one of `_COVERAGE_DIMENSION_RECEIPT_RELS` owns it and it
    was written by THIS run (no older than the L10 execution record the run's
    testbenches just wrote). None with the reason otherwise."""
    record = _l10x.resolve_record(project)
    for rel in _COVERAGE_DIMENSION_RECEIPT_RELS:
        f = Path(project) / rel
        if not f.is_file():
            continue
        try:
            doc = json.loads(f.read_text(errors="replace"))
        except (OSError, ValueError):
            return None, f"{rel} is unreadable"
        if not isinstance(doc, dict) or doc.get("dimension") != dimension:
            continue
        try:
            if record is not None and f.stat().st_mtime < \
                    record.stat().st_mtime:
                return None, (f"{rel} is older than this run's L10 execution "
                              f"record: the instrument did not run here")
        except OSError:
            return None, f"{rel} could not be dated"
        return doc, ""
    return None, (f"no instrument receipt for the {dimension!r} dimension "
                  f"(looked in {', '.join(_COVERAGE_DIMENSION_RECEIPT_RELS)})")


def _delivered_programs(project: Path) -> "list[str]":
    """Every declared L10 case (vector or goal) for which the design input
    DELIVERS a testbench or a named program image."""
    out: list = []
    for name, row in _l10_rows_by_name(project).items():
        stim = str(row.get("stimulus") or "")
        if (_tbg.delivered_case_oracle(project, name) is not None
                or _tbg.delivered_case_program(project, stim) is not None):
            out.append(name)
    return out


def _goal_input_gap(project: Path, goal: "dict | None",
                    dimension: str) -> "dict | None":
    """The coverage goal's input gap, on POSITIVE EVIDENCE only, else None.

    A goal's number is absent because no program the input delivers could
    feed it only when ALL of these hold:
      * the dimension is owned by a per-dimension instrument whose receipt
        this run wrote (a line/toggle/branch goal has no such receipt: its
        absent total is the verilator arm's, and stays a refusal);
      * that receipt says the instrument applied, and found NO tally at all --
        no contribution and no refusal, so no transcript of any case, passing
        or not, carried the dimension's line;
      * the design input delivers no testbench or program for ANY declared
        case, so no executed program existed to report one;
      * the goal itself is not claimed by this flow (`case_input_gap`'s own
        delivery and in-flow-testbench tests).
    Anything else -- the instrument did not run, ran before this run's
    testbenches, timed out, or saw a tally it refused -- keeps the goal a
    refusal (FAIL), because the flow could have measured it."""
    if not isinstance(goal, dict):
        return None
    name = str(goal.get("name") or goal.get("id") or "")
    if not name:
        return None
    receipt, _why = _dimension_receipt(project, dimension)
    if receipt is None:
        return None
    if receipt.get("applicable") is not True or receipt.get("totals"):
        return None
    if receipt.get("contributions") or receipt.get("refusals"):
        return None
    if not isinstance(receipt.get("contributions"), list) or \
            not isinstance(receipt.get("refusals"), list):
        return None
    if _delivered_programs(project):
        return None
    try:
        if (_tbg.delivered_case_oracle(project, name) is not None
                or _tbg._in_flow_testbench(project, name) is not None):
            return None
    except Exception:                                        # noqa: BLE001
        return None
    stimulus = str(goal.get("stimulus") or "").strip()
    if not stimulus:
        return None
    rel = next((r for r in _COVERAGE_DIMENSION_RECEIPT_RELS), "")
    return {
        "case": name,
        "missing_from_input": [
            f"a program or testbench for {name!r} whose run reports the "
            f"{dimension!r} tally"],
        "stimulus": stimulus,
        "reason": (f"coverage goal {name!r} cannot be measured: its "
                   f"{dimension!r} instrument ran in this run ({rel}) and "
                   f"found no tally in any case's transcript, and the design "
                   f"input delivers no testbench or program for any declared "
                   f"case -- it states the goal only as {stimulus[:120]!r}. "
                   f"Supplying the program is the design input's; this flow "
                   f"may not author it (§4.05)."),
    }


def _credit_isa_goals(project: Path, summary: dict) -> None:
    """R-0929-OWNER-SUB-ACCEPT (1) for the GOAL population, in place.

    A goal over the INSTRUCTION dimension that this run left without a number
    (NOT_MEASURED, no achieved percentage) takes the number the core-ISA
    conformance suite measured on the same RTL at the test parameter value:
    instructions whose every primary program passed, over the declared
    instruction total. It is then judged against its OWN stated percentage
    exactly as a measured figure is (PASS when met, FAIL when not), and the
    row carries the credit and its sentence. A goal this run DID measure keeps
    its number: the credit only fills an absence. A refused credit is named on
    the row, which keeps its verdict."""
    rows = summary.get("rows") or []
    touched = False
    for r in rows:
        if (r.get("verdict") != _cgc.NOT_MEASURED
                or r.get("achieved_pct") is not None
                or r.get("dimension") != "instruction"):
            continue
        credit, refusal = _l10x.isa_conformance_credit(
            project, str(r.get("case") or ""))
        if credit is None:
            if refusal:
                r["isa_conformance_refused"] = refusal
            continue
        # The ONE goal judgment the L10 table applies too.
        verdict, achieved, why = _l10x.isa_goal_verdict(
            r.get("stated_pct"), r.get("dimension"), credit)
        if verdict is None:
            r["isa_conformance_refused"] = why
            continue
        r.update(
            achieved_pct=achieved,
            achieved_source=credit["sentence"],
            instrument=_l10x.ISA_CREDIT_KIND,
            verdict=_cgc.PASS if verdict == _l10x.PASS else _cgc.FAIL,
            why=f"case {r.get('case')!r}: {why}, by {credit['sentence']}",
            isa_conformance_credit=credit)
        touched = True
    if touched:
        summary["passed_count"] = sum(
            1 for r in rows if r["verdict"] == _cgc.PASS)
        summary["failed_count"] = sum(
            1 for r in rows if r["verdict"] == _cgc.FAIL)
        summary["not_measured_count"] = sum(
            1 for r in rows if r["verdict"] == _cgc.NOT_MEASURED)


def _coverage_goal_summary(project: Path) -> dict:
    """The COVERAGE-GOAL population and its OWN denominator.

    R-0915-113(4). Separate from the executed-versus-declared comparison and
    measured by a separate instrument, so the Step-4 record reads as two
    populations rather than one mixed number."""
    gd = _pl.generated_docs_dir(project)
    l10 = gd / "L10_TEST_CASES.json"
    rows, _process_only = _split_executable(_declared_rows(
        l10, ("test_cases", "cases", "vectors")))
    rows, _design_na = split_design_declared_na(
        rows, design_selected_options(project))
    _vectors, goals = _cgc.partition(rows)
    totals, source = _coverage_totals(project)
    # The execution record arms the scenario pass-rate instrument (a goal
    # measured by the L10 cases bound to it that ran their own oracle).
    summary = _cgc.measure_goals(goals, totals, rows,
                                 _l10x.load_record(project, l10))
    import professional_tb_gen as professional
    for goal, measured in zip(goals, summary['rows']):
        actual = professional.random_pair_goal_measurement(project, goal)
        if actual is not None:
            measured.update(actual)
            measured.update(achieved_pct=actual.get('achieved_pct'),
                            achieved_source=actual.get('achieved_source'),
                            instrument='arithmetic_random_pairs')
    for state, key in ((_cgc.PASS, 'passed_count'), (_cgc.FAIL, 'failed_count'),
                       (_cgc.NOT_MEASURED, 'not_measured_count')):
        summary[key] = sum(row['verdict'] == state for row in summary['rows'])
    summary["totals_source"] = source
    _credit_isa_goals(project, summary)
    # FX_P2 — a goal whose dimension IS instrumented, but which no executed
    # program could feed because the design input delivers none, is the
    # input's gap: NOT_MEASURED by name, not a refusal. A goal the flow cannot
    # bind, and one measured short of its percentage, are unchanged. Decided
    # on the INSTRUMENT'S OWN RECEIPT (`_goal_input_gap`), never on the bare
    # absence of a number -- an instrument that never ran, timed out or
    # crashed leaves the same absence, and that is this flow's refusal.
    by_name = {str(g.get("name") or g.get("id") or ""): g for g in goals
               if isinstance(g, dict)}
    kept, gaps = [], []
    for r in summary.get("rows") or []:
        gap = None
        if (r.get("verdict") == _cgc.NOT_MEASURED and r.get("dimension")
                and r.get("achieved_pct") is None):
            gap = _goal_input_gap(project, by_name.get(r.get("case")),
                                  str(r.get("dimension")))
        if gap is not None:
            gaps.append(dict(r, why=gap["reason"],
                             missing_from_input=gap["missing_from_input"]))
        else:
            kept.append(r)
    if gaps:
        summary["rows"] = kept
        summary["declared_count"] = len(kept)
        summary["not_measured_count"] = sum(
            1 for r in kept if r["verdict"] == _cgc.NOT_MEASURED)
    summary["input_not_supplied"] = gaps
    return summary


def _oracle_execution_refusal(project: Path, transcript: str) -> "str | None":
    """The refusal a row-count PASS owes, or None when the oracles did run.

    ONE GUARD, EVERY PASS ROUTE THAT RESTS ON A TRANSCRIPT. There are two —
    the substantiated-claim route and the professional-TB slot route — and on
    r27 BOTH would have passed off the same ten green rows. A predicate applied
    at one of two doors is not a predicate.
    """
    ran = _oracles_that_actually_ran(project)
    goals = _coverage_goal_summary(project)
    goal_refusal = _cgc.coverage_goal_refusal(goals)
    if ran["declared_count"] == 0:
        # R-0915-113(4) — the vector denominator being empty says nothing
        # about the GOAL population. A design that declares only coverage
        # goals still owes their verdict; returning None here would let an
        # unmeasured goal ride out on the absence of vectors.
        if goal_refusal:
            return (f"{transcript}: this design declares no functional "
                    f"vector, and {goal_refusal}")
        # NARROW ON PURPOSE. A design that declares no L10 case asks a
        # different question, and this guard does not answer it: the gate's own
        # denominator path already reports "0 functional tests ran for N
        # declared row(s)". Refusing here as well was scope I added and the
        # ruling did not ask for, and it turned four landed fixtures red for a
        # fact none of them is about. The comparison this guard owns is
        # EXECUTED-versus-DECLARED, and over an empty declaration there is
        # nothing to compare.
        return None
    if not ran["not_executed_count"]:
        # The vectors all ran. A declared coverage goal that did NOT meet its
        # stated percentage -- or that this run had no instrument for -- is
        # still not verified, and saying nothing here would let the goal
        # population be satisfied by the vector population's success.
        return (f"{transcript} is a passing transcript and every declared "
                f"functional vector executed its own oracle, but "
                f"{goal_refusal}") if goal_refusal else None
    # The per-case ``why`` is the consumer-facing explanation for a
    # NOT_EXECUTED conditional row.  Do not reduce this published refusal to
    # just its state: in particular, R-0915-102's undecided option selection
    # is neither an input gap nor a silent exemption.  The gate JSON carries
    # this message, so rendering the reason here keeps the booking explainable
    # at the record a downstream reader actually receives.
    named = ", ".join(f"{r['case']} [{r['state']}]: {r['why']}"
                      for r in ran["not_executed"][:6])
    more = ran["not_executed_count"] - 6
    return (
        f"{transcript} is a passing transcript, but only "
        f"{ran['executed_count']} of {ran['declared_count']} declared L10 "
        f"case(s) EXECUTED their own oracle. A green row count over "
        f"substance-floor scaffolds is not functional verification. Not "
        f"executed: {named}" + (f" (+{more} more)" if more > 0 else "")
        + f". Asked through {ran['asked_through']}"
        + ("" if ran["record_available"]
           else f"; execution record unavailable ({ran['record_reason']})")
        + (f". Separately, {goal_refusal}" if goal_refusal else "")
        + (f". Not counted above: {_input_gap_sentence(ran['input_not_supplied'])}"
           if ran.get("input_not_supplied") else "")
    )


#: FX_P2 — the gate's one NOT_MEASURED outcome. The flow's reason taxonomy
#: calls "something outside the run must supply it" EXTERNAL, which a step
#: reads as `NOT_MEASURED(input_absent)` (`verdict._GATE_REASON_TO_STEP_REASON`).
INPUT_GAP_REASON_CLASS = "EXTERNAL"
NOT_MEASURED_PREFIX = "NOT_MEASURED [EXTERNAL]:"


def _input_gaps(project: Path, *, include_excluded: bool = False) -> list:
    """Every declared case and goal that did not run because the design input
    supplies no stimulus for it — each with its reason and what is missing.

    A firmware row EXCLUDED from the verdict (R-0929-OWNER-SUB-ACCEPT (2)) is
    not a blocking gap and is left out unless `include_excluded` asks for the
    whole list (the published record, where it is flagged)."""
    ran = _oracles_that_actually_ran(project)
    goals = _coverage_goal_summary(project)
    gaps = (list(ran.get("input_not_supplied") or [])
            + list(goals.get("input_not_supplied") or []))
    if include_excluded:
        return gaps
    return [g for g in gaps if not g.get("excluded_from_verdict")]


def _acceptance_disclosure(project: Path) -> str:
    """The sentence every verdict of this gate carries when either owner rule
    of R-0929-OWNER-SUB-ACCEPT moved a row: what the core-ISA conformance
    suite was credited with (parameter, delivered vs test value, suites,
    programs and instructions, and the delivered-memory run), and which rows
    are NOT_MEASURED and excluded. Empty when neither applied."""
    ran = _oracles_that_actually_ran(project)
    goals = _coverage_goal_summary(project)
    credits = list(ran.get("isa_conformance_credited") or []) + [
        r["isa_conformance_credit"] for r in goals.get("rows") or []
        if r.get("isa_conformance_credit")]
    bits = []
    if credits:
        bits.append(f"{len(credits)} declared case(s)/goal(s) CREDITED by "
                    + "; ".join(f"{c['case']}: {c['sentence']}"
                                for c in credits))
    excl = list(ran.get("not_measured_excluded") or [])
    if excl:
        bits.append(f"{len(excl)} declared case(s) NOT_MEASURED "
                    f"[input_absent] and EXCLUDED from the verdict (never a "
                    f"pass, not blocking): "
                    + "; ".join(e["excluded_from_verdict"] for e in excl))
    return (" [" + " | ".join(bits) + "]") if bits else ""


def _input_gap_sentence(gaps: list) -> str:
    named = "; ".join(g["why"] for g in gaps[:4])
    more = len(gaps) - 4
    return (f"{len(gaps)} declared L10 case(s)/goal(s) could not run because "
            f"the design input does not supply their stimulus: {named}"
            + (f" (+{more} more)" if more > 0 else ""))


def _not_measured_on_input(project: Path, passed_because: str
                           ) -> "tuple[int, str] | None":
    """(2, NOT_MEASURED …) when every case that COULD run ran and passed but
    some declared case could not run for want of input; None otherwise."""
    gaps = _input_gaps(project)
    if not gaps:
        return None
    return 2, (f"{NOT_MEASURED_PREFIX} {passed_because}; but "
               f"{_input_gap_sentence(gaps)}. Not a FAIL (nothing ran and "
               f"failed) and not a PASS (those cases are unverified)."
               + _acceptance_disclosure(project))


def _acceptance_record(project: Path) -> dict:
    """Machine-readable half of `_acceptance_disclosure`."""
    ran = _oracles_that_actually_ran(project)
    goals = _coverage_goal_summary(project)
    return {
        "not_measured_excluded": [
            {"case": e["case"], "status": e["status"],
             "reason_class": e["reason_class"],
             "missing_from_input": e["missing_from_input"],
             "reason": e["excluded_from_verdict"]}
            for e in ran.get("not_measured_excluded") or []],
        "isa_conformance_credit": {
            "credited": list(ran.get("isa_conformance_credited") or []) + [
                r["isa_conformance_credit"] for r in goals.get("rows") or []
                if r.get("isa_conformance_credit")],
            "refused": list(ran.get("isa_conformance_refused") or []) + [
                {"case": r.get("case"), "why": r["isa_conformance_refused"]}
                for r in goals.get("rows") or []
                if r.get("isa_conformance_refused")],
        },
    }


def _evidence_summary(project: Path) -> dict:
    """Machine-readable Step-4 denominator and coverage disclosure.

    These fields do not replace the dedicated L10/L12 and Verilator gates.
    They put the numbers beside this gate's functional verdict so a reader can
    see, in one record, whether the run checked anything and whether coverage
    was actually measured.

    R-0915-113(4) adds the SECOND population: declared coverage goals, with
    their own denominator, under `coverage_goals`. A reader must be able to
    tell "6 of 7 vectors executed" from "0 of 4 goals measured" without
    subtracting one number from another.
    """
    gd = _pl.generated_docs_dir(project)
    l10 = _list_denominator(
        gd / "L10_TEST_CASES.json", ("test_cases", "cases", "vectors"))
    l12 = _list_denominator(
        gd / "L12_BEHAVIORAL_SEQUENCES.json",
        ("sequences", "behavioral_sequences"))
    # #2073 — ONE reader of the professional slot, and it is the UNION. This
    # loop already summed every sibling suite; what it could not see is a suite
    # that produced NO transcript, which is now disclosed by name below.
    union = _srb.professional_tb_union(project)

    sim_results = _pl.sim_dir(project) / "results.xml"
    xml = ""
    try:
        if sim_results.is_file():
            xml = sim_results.read_text(errors="replace")
    except OSError:
        xml = ""
    try:
        vectors_total = int(_read_xml_field(xml, "vectors_total") or 0)
        vectors_passed = int(_read_xml_field(xml, "vectors_passed") or 0)
    except ValueError:
        vectors_total = vectors_passed = 0

    functional = {
        "source": None,
        "tests_run": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_skipped": 0,
        # #2073 — a sibling suite that produced no parsable JUnit is NOT
        # measured, and a denominator that omits it reads as though the suite
        # did not exist. Named here so the record carries the whole population.
        "not_measured": list(union["not_measured"]),
    }
    if union["rel_paths"]:
        functional.update({
            "source": ";".join(union["rel_paths"]),
            "tests_run": union["tests"],
            "tests_passed": union["passed"],
            "tests_failed": union["failures"] + union["errors"],
            "tests_skipped": union["skipped"],
        })
    elif vectors_total > 0:
        functional.update({
            "source": str(sim_results.relative_to(project)),
            "tests_run": vectors_total,
            "tests_passed": vectors_passed,
            "tests_failed": max(vectors_total - vectors_passed, 0),
        })

    coverage_path = _pl.report_path(project, "coverage/coverage_verilator.json")
    try:
        coverage_source = str(coverage_path.relative_to(project))
    except ValueError:
        coverage_source = str(coverage_path)
    coverage = {"measured": False, "source": coverage_source}
    try:
        cov = json.loads(coverage_path.read_text(errors="replace"))
        totals = cov.get("totals") if isinstance(cov, dict) else None
        if isinstance(totals, dict) and totals:
            coverage.update(measured=True, totals=totals)
    except (OSError, ValueError):
        pass

    return {
        "declared_denominator": {
            "l10_test_cases": l10,
            "l10_process_only_rows_excluded": _process_only_count(
                gd / "L10_TEST_CASES.json", ("test_cases", "cases", "vectors")),
            "l10_process_only_note": (
                "rows whose declared kind is a process milestone "
                f"({', '.join(sorted(_NON_EXECUTABLE_TEST_KINDS))}) are "
                "reported but not demanded: they carry no stimulus a "
                "testbench can drive"),
            "l12_behavioral_sequences": l12,
            "total_declared_rows": l10 + l12,
            # R-0915-102(1) — still DECLARED, still reported, not
            # demanded: the case states an option and the design's own
            # declaration does not select it. Named one by one, with the
            # clause each came from, so a reader can check the pairing
            # rather than take the narrowing on trust.
            "l10_design_declared_na": _design_declared_na_disclosure(
                project),
            # ORGANIC #2055 — the same two facts the blocking sentence now
            # carries, in machine-readable form. Absent (not zero) when the
            # rows or the producer scope could not be read.
            **_row_kind_denominator(project),
        },
        "functional_test_denominator": functional,
        # R-0915-113(4) — the SECOND population, with its OWN denominator.
        # A reader must be able to tell "6 of 7 vectors executed" from "0 of
        # 4 goals measured" without subtracting one number from another.
        "coverage_goals": _coverage_goal_summary(project),
        # R-0929-OWNER-SUB-ACCEPT — beside the verdict, never inside it: the
        # rows (2) took OUT (F10's key and entry shape) and what (1) CREDITED,
        # with every refusal named. Empty lists when neither rule applied.
        **_acceptance_record(project),
        "coverage": coverage,
        "program_first": "professional_tb_gen",
        "expert_fallback": "testbench-gen",
    }


def _evaluate(project: Path) -> "tuple[int, str]":
    """Return (exit_code, message)."""
    sim_dir = _pl.sim_dir(project)
    results = sim_dir / "results.xml"
    if not results.is_file():
        return 2, ("VACUOUS_PASS: no phase2/stage1/sim/results.xml — "
                   "cpu_functional_oracle_waiver_check has nothing to assess.")
    try:
        xml = results.read_text(errors="replace")
    except OSError as exc:
        return 1, f"FAIL: could not read sim/results.xml: {exc}"

    verdict = _read_xml_field(xml, "verdict").upper().replace("_", "-")
    cap = _read_xml_field(xml, "capability_gap")
    func_verified = _read_xml_field(xml, "functional_verified").lower()

    is_connectivity = (
        verdict == CONNECTIVITY_VERDICT.replace("_", "-")
        or cap == CAP_CPU_FUNCTIONAL_ORACLE)
    if not is_connectivity:
        refusal = _cgc.coverage_goal_refusal(_coverage_goal_summary(project))
        if refusal:
            return 1, 'INCOMPLETE: functional smoke PASS does not satisfy declared coverage goals: ' + refusal
        # A genuine functional PASS (oracle bridge) or any non-connectivity
        # verdict — not this gate's concern. The functional gates own it.
        return 0, ("PASS: sim/results.xml is not a cpu-functional-oracle "
                   "connectivity record (functional verdict owned by the "
                   "functional gates); cpu_functional_oracle_waiver_check N/A.")

    # It claims a connectivity-PASS capability-gap record. Substantiate it:
    #   (1) the capability-gap marker must be the cpu-functional-oracle one,
    #   (2) functional_verified must NOT be asserted true (a connectivity
    #       record that ALSO claims functional verification is a forgery),
    #   (3) the <evidence> pointer must dereference to a non-empty transcript
    #       that actually reached FULL_STACK_TB_DONE.
    if cap != CAP_CPU_FUNCTIONAL_ORACLE:
        return 1, (f"FAIL: connectivity verdict but capability_gap is "
                   f"{cap!r}, not {CAP_CPU_FUNCTIONAL_ORACLE!r} — "
                   f"unrecognised capability record.")
    if func_verified == "true":
        # A record may CLAIM functional verification only if it can SHOW it.
        # Before this, the claim alone was a forgery by construction, which was
        # right while no record could carry evidence — and wrong once one
        # could. `step_reference_tb`'s bridge now writes
        # `functional_verified=true` ONLY beside a `<functional_evidence>`
        # pointer to the professional cocotb transcript that closed the very
        # deferral this record's waiver_reason names, and that transcript is
        # judged by the SAME predicate the PASS branch below already applies:
        # a real JUnit document, tests > 0, failures == errors == 0.
        #
        # An unsubstantiated claim is still a forgery and still FAILs, with the
        # reason naming which half was missing — so a hand-edited flag, a
        # dangling pointer, a non-JUnit file, a vacuous zero-test result and a
        # failing one are each refused, exactly as before.
        claimed = _read_xml_field(xml, "functional_evidence")
        shown = _srb.substantiated_functional_evidence(project, claimed)
        if not shown:
            return 1, (
                "FAIL: connectivity-PASS record asserts "
                "functional_verified=true "
                + (f"and points at {claimed!r}, which does not resolve to a "
                   f"real passing JUnit transcript under this project"
                   if claimed else
                   "and carries no <functional_evidence> pointer")
                + " — a claim that cannot be shown is a forged waiver.")
        # R-0915-87(2) — the transcript proves a suite ran and did not fail;
        # it cannot prove WHAT it checked. On r27 this very transcript read
        # tests=10 passed=10 over NINE substance-floor scaffolds.
        _refusal = _oracle_execution_refusal(project, shown["rel_path"])
        if _refusal:
            return 1, (
                "FAIL: connectivity-PASS record asserts "
                f"functional_verified=true and {_refusal}."
                + _acceptance_disclosure(project))
        _nm_input = _not_measured_on_input(
            project, f"every case that could run executed and passed "
                     f"({shown['rel_path']})")
        if _nm_input:
            return _nm_input
        _disc = _acceptance_disclosure(project)
        return 0, (
            "PASS: the record's functional_verified=true is SUBSTANTIATED by "
            f"{shown['rel_path']}: tests={shown['tests']} "
            f"passed={shown['passed']} failures={shown['failures']} "
            f"errors={shown['errors']}, AND every declared L10 case executed "
            "its own oracle"
            + (" or is accounted for in the bracket below" if _disc else "")
            + ". The connectivity binding and the "
            "functional oracle are both recorded, and the "
            f"{CAP_CPU_FUNCTIONAL_ORACLE} marker is retained for the "
            "per-case oracle gap it actually names." + _disc)
    evidence = _read_xml_field(xml, "evidence")
    if not evidence:
        return 1, ("FAIL: connectivity-PASS record carries no <evidence> "
                   "pointer — unreviewable evidence is not credited.")
    ev_path = (project / evidence)
    if not ev_path.is_file() or ev_path.stat().st_size == 0:
        return 1, (f"FAIL: connectivity-PASS record <evidence> pointer "
                   f"{evidence!r} does not dereference to a non-empty "
                   f"transcript — connectivity evidence broken.")
    try:
        ev_txt = ev_path.read_text(errors="replace")
    except OSError as exc:
        return 1, f"FAIL: could not read evidence transcript: {exc}"
    if "FULL_STACK_TB_DONE" not in ev_txt:
        return 1, ("FAIL: connectivity-PASS record evidence transcript did "
                   "not reach FULL_STACK_TB_DONE — connectivity binding to "
                   "rtl/ was NOT actually demonstrated.")

    # A real functional PASS closes the connectivity-only incomplete state.
    # The bridge above honestly says functional verification was not performed
    # because the AID reference TB cannot bind this interface family. For a
    # class whose oracle is derivable, professional_tb_gen may have already
    # closed functional verification with a real cocotb streaming-scoreboard
    # against the real rtl/ and failures=0. When that real PASS is present,
    # step aside (rc=0). This remains chip-AGNOSTIC and anti-fabrication-safe:
    # a missing, failing, or vacuous professional result returns None and the
    # blocking INCOMPLETE verdict below remains in force.
    union = _srb.professional_tb_union(project)
    pro = _srb.find_professional_tb_pass(project)
    if pro:
        _nm = _srb.union_disclosure(union)
        # R-0915-87(2) — the same guard, at the same height. This route reads
        # the professional suite's own transcript, which on r27 is the file
        # with the ten green rows.
        _refusal = _oracle_execution_refusal(project, ";".join(pro["rel_paths"]))
        if _refusal:
            return 1, (
                "INCOMPLETE: the professional-TB result slot cannot supersede "
                f"the {CAP_CPU_FUNCTIONAL_ORACLE} capability record — "
                f"{_refusal}. No waiver is granted and Step 4 is NOT a "
                "functional PASS." + _acceptance_disclosure(project))
        _nm_input = _not_measured_on_input(
            project, f"every case that could run executed and passed "
                     f"({';'.join(pro['rel_paths'])})")
        if _nm_input:
            return _nm_input
        return 0, (
            "PASS: functional verification ACHIEVED by the professional-TB "
            "result slot (producer: "
            + (", ".join(pro.get("suite_names") or []) or "unnamed suite")
            + f") — {';'.join(pro['rel_paths'])}: tests="
            f"{pro['tests']} passed={pro['passed']} failures={pro['failures']} "
            f"errors={pro['errors']} over {len(pro['rel_paths'])} sibling "
            f"suite(s). The connectivity-PASS capability record "
            f"({CAP_CPU_FUNCTIONAL_ORACLE}) is "
            "SUPERSEDED by this real functional PASS; Step 4 is a genuine "
            "functional simulation PASS, not WAIVED-DEFERRED."
            + (f" [{_nm}]" if _nm else "")
            + _acceptance_disclosure(project))

    denom = _evidence_summary(project)["declared_denominator"]
    # A functional transcript that EXISTS and did not pass is not the same fact
    # as no transcript at all, and this sentence used to report both as
    # "0 functional tests ran". Name the executed population when there is one:
    # the reader must be able to tell "nobody ran the testbenches" from "the
    # testbenches ran and the design failed them".
    # #2073 — NAME EVERY FAILURE, over the union. This used to report
    # `sorted(...)[0]` — the first transcript with tests > 0 — as "the"
    # transcript that did not pass. With sibling suites that is a coin toss:
    # when the PASSING suite sorts first the sentence named a green transcript
    # and said it did NOT pass, which is a lie about the file it cites.
    _nm = _srb.union_disclosure(union)
    if union["tests"] > 0:
        return 1, (
            f"INCOMPLETE: {_waiver_track_class_label(xml)} — connectivity-only "
            f"evidence reached FULL_STACK_TB_DONE (evidence: {evidence}), and "
            f"a functional transcript EXISTS but did NOT pass, over the "
            f"union of {len(union['rel_paths'])} sibling suite(s): "
            f"tests={union['tests']} passed={union['passed']} "
            f"failures={union['failures']} errors={union['errors']} "
            f"(errors = testbenches that never ran) for "
            f"{denom['total_declared_rows']} declared L10/L12 row(s)"
            f"{_row_kind_disclosure(project)}"
            + (f"; failing: {'; '.join(union['failing'])}"
               if union["failing"] else "")
            + (f"; {_nm}" if _nm else "")
            + ". No waiver is granted.")
    return 1, (
        f"INCOMPLETE: {_waiver_track_class_label(xml)} — connectivity-only "
        f"evidence reached FULL_STACK_TB_DONE (evidence: {evidence}), but 0 "
        f"functional tests ran for {denom['total_declared_rows']} declared "
        f"L10/L12 row(s){_row_kind_disclosure(project)}. Connectivity is not "
        "a functional oracle. Run the "
        "program-first professional_tb_gen route, then fill unsupported "
        "design-specific reference semantics with the testbench-gen expert "
        "fallback and re-run Step 4. No waiver is granted."
        + (f" [{_nm}]" if _nm else ""))


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Blocking Step-4 functional-evidence requirement for "
                    "connectivity-only results (ORGANIC #654/#1975).")
    ap.add_argument("project", nargs="?", default=".",
                    help="project root (default: .)")
    ap.add_argument("--json", default=None,
                    help="optional path to write the JSON verdict report")
    ns = ap.parse_args(argv)
    project = Path(ns.project).resolve()

    code, msg = _evaluate(project)
    print(msg)
    if ns.json:
        verdict = ({0: "PASS", 2: "VACUOUS_PASS"}.get(code)
                   or ("INCOMPLETE" if msg.startswith("INCOMPLETE:")
                       else "FAIL"))
        extra: dict = {}
        if code == 2 and msg.startswith(NOT_MEASURED_PREFIX):
            verdict = "NOT_MEASURED"
            extra = {"reason_class": INPUT_GAP_REASON_CLASS,
                     "input_not_supplied": _input_gaps(
                         project, include_excluded=True)}
        out = {"verdict": verdict, "exit_code": code, "message": msg,
               **extra,
               "capability_gap": CAP_CPU_FUNCTIONAL_ORACLE,
               "gate": "cpu_functional_oracle_waiver_check",
               "enforcement": "BLOCKING",
               **_evidence_summary(project)}
        try:
            jp = Path(ns.json)
            jp.parent.mkdir(parents=True, exist_ok=True)
            jp.write_text(json.dumps(out, indent=2))
        except OSError:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
