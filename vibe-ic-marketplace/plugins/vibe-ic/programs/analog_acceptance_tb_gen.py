#!/usr/bin/env python3
"""analog_acceptance_tb_gen.py — PRODUCER of executable acceptance checks for
the analog `verification_intent` rows Phase 1 declares.

ORGANIC #2064. WHAT WAS MISSING, MEASURED (u_hawaii_adc, image 0.3.46):
Phase 1 harvests the design's own `## Verification intent` section into four
L10 rows of `kind: verification_intent`, and NOTHING in the flow can author an
acceptance for one. `testbench_gen`'s scaffold scope is the functional-vector
family; `full_stack_tb_gen` is connectivity-only; `professional_tb_gen` derives
a digital reference model. So Step 4 read "0 functional tests ran for 4
declared L10/L12 row(s)" — a denominator of four with a numerator no producer
in the tree could ever raise. Adding `verification_intent` to
`cpu_functional_oracle_waiver_check._NON_EXECUTABLE_TEST_KINDS` would have
passed Step 4 on an EMPTY denominator and was refused by ruling: the rows are
not process milestones, they are real acceptance statements about the analog
blocks, and the flow already MEASURES those blocks (A4's per-corner PVT sweep).

WHAT THIS PRODUCER DOES. For each `verification_intent` row it derives the
acceptance FROM THE DESIGN'S OWN INPUT and emits an EXECUTABLE check per
derived clause. The check reads the A4 corner-sweep record — the flow's own
measurement, never a golden/oracle artefact (§4.05) — and asserts the declared
bound at every EXECUTED corner.

GENERAL CORE, THIN ANALOG ADAPTER
=================================
The core knows no IC and no block kind. Everything design-specific is read
from two structures Phase 1 already publishes:

  * `L22.fields.verification_plan` — `l22_analog_verification_plan_emit`
    already joins `L5.analog_blocks[].spec.specs[]` (the per-block bound table)
    with the design's literal `Verification intent` bullets, attributes each
    bullet to a block by the design's OWN vocabulary, and normalises a stated
    PVT matrix into process and temperature axes. That module OWNS that
    derivation; this one IMPORTS its helpers rather than respelling them (the
    #761 two-private-scopes shape, refused again).
  * `phase3/analog/<block>/corner_results.json` — the A4 record, resolved
    through `_analog_a_check_common.resolve_block_artefact` so the phase-2 and
    phase-3 layouts both bind.

THREE CLAUSE SOURCES, ALL INPUT-DERIVED
---------------------------------------
  (A) NAMED QUANTITY. A quantity whose L5 spec name the row's own prose names
      (token match, using L22's own tokeniser). Bound = that spec's declared
      target/min/max. A named quantity for which L5 declares NO numeric bound
      is REFUSED BY NAME — never silently dropped, never passed.
  (B) CORNER COVERAGE. A row whose prose declares a PVT matrix (L22's own
      `_corner_matrix`) demands that every (process, temperature) it names was
      really executed in the A4 record.
  (C) BLOCK-SCOPED BOUNDS. A row L22 attributed to a block is an acceptance
      statement about that block: every L5-BOUNDED quantity of it that the A4
      record actually MEASURES must be inside its bound at every executed
      corner. Bounded quantities the record does not measure are DISCLOSED by
      name under `unmeasured_declared_bounds` and are NOT turned into
      testcases: the row does not name them, and demanding them would be
      inventing an acceptance the input never stated.

FOUR VERDICTS, KEPT APART
-------------------------
  PASS         the bound holds at every executed corner.
  FAIL         a measured value is outside the declared bound.
  NOT_MEASURED the acceptance is derivable and nothing measured it (no A4
               record, no executed corner, or the record carries no value for
               this quantity — e.g. ENOB until the SNDR measurement of #2062
               exists). NEVER a pass, and never collapsed into FAIL: "could
               not read it" is not "read it and it was wrong".
  REFUSED      no acceptance is derivable from the input for this row (or for
               a named quantity), stated with the reason and the row's name.

§4.05. Only the design INPUT is read for the acceptance; the A4 record is the
flow's own measurement. A row whose prose names the fabricated / golden
reference is REFUSED with §4.05 named and its artefact is never opened.

CHIP_AGNOSTIC: strict-logic
Block names, spec names, bounds, corner axes and evidence all come from the
design's own Phase-1 artefacts: no chip, vendor, node, SKU, PDK or part literal
appears in the LOGIC of this file. The module docstring above names the design
this producer was measured on, which is the provenance of every claim in it —
`source_chip_agnostic_check` reads the declaration on this line and discloses
the scope it binds; this program's own test file enforces it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _path_layout as _pl  # noqa: E402
import _analog_a_check_common as _aac  # noqa: E402
# ONE definition of "what a PVT matrix in a verification-intent bullet is" and
# ONE definition of "what a token of that prose is". Both live in the L22
# emitter, which is the producer of the plan this consumer reads; importing
# them is what keeps the two readers from drifting into two private scopes.
import l22_analog_verification_plan_emit as _l22  # noqa: E402

TOOL = "analog_acceptance_tb_gen"

#: The declared L10 `kind` vocabulary this producer authors an acceptance for.
#: chip-AGNOSTIC: a kind token, never a chip/vendor/SKU literal.
ACCEPTANCE_KINDS = frozenset({"verification_intent"})

#: Where the emitted checks live, and where their JUnit lands. The JUnit path
#: is the Step-4 professional-result slot `_sim_results_bridge` already reads;
#: `testbench_gen.run_unit_tbs` writes a sibling there under `l10_unit_tb`, so
#: this is the established multi-producer contract, not a new one.
CHECK_DIR_NAME = "tb_analog_acceptance"
RESULT_DIR_NAME = "analog_acceptance"
RECORD_REL = "reports/analog/analog_acceptance.json"

#: Verdict vocabulary. Kept apart on purpose — see the module docstring.
PASS = "PASS"
FAIL = "FAIL"
NOT_MEASURED = "NOT_MEASURED"
REFUSED = "REFUSED"

#: Exit codes of an emitted check script.
_EXIT = {PASS: 0, FAIL: 1, NOT_MEASURED: 3, REFUSED: 4}
_EXIT_VERDICT = {v: k for k, v in _EXIT.items()}

#: §4.05 — the vocabulary of an artefact this flow must NOT read as design
#: evidence. A row whose prose names one is refused before anything is opened.
_GOLDEN_TOKENS = ("golden", "fabricated", "oracle")

#: The A4 record's own name for a corner that a simulator really ran.
_EXECUTED_KEY = "simulator_run"

#: Keys under which the A4 record carries a per-corner measured value, in the
#: order they are probed. `<quantity>_v` is what `analog_real_corner_sweep`
#: writes; `value` is the generic fallback the A4 gate also reads.
def _corner_value(corner: dict, quantity: str) -> Optional[float]:
    for key in (f"{quantity}_v", quantity, f"{quantity}_value"):
        if key in corner:
            try:
                return float(corner[key])
            except (TypeError, ValueError):
                return None
    return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _fields(doc: Optional[dict]) -> dict:
    if not isinstance(doc, dict):
        return {}
    f = doc.get("fields")
    return f if isinstance(f, dict) else doc


def _norm(name: Any) -> str:
    """A spec name reduced to its comparison form (lowercase alphanumerics)."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _bound_of(spec: dict) -> Optional[dict]:
    """The DECLARED numeric bound of one L5 spec row, or None when the input
    states none. `target` alone is NOT a bound: a target with no tolerance
    cannot decide pass from fail, and inventing one would be inventing an
    acceptance."""
    lo, hi = spec.get("min"), spec.get("max")
    if lo is None and hi is None:
        return None
    out: Dict[str, Any] = {"unit": spec.get("unit")}
    if lo is not None:
        out["min"] = float(lo)
    if hi is not None:
        out["max"] = float(hi)
    if spec.get("target") is not None:
        out["target"] = float(spec["target"])
    out["declared_as"] = {"target_raw": spec.get("target_raw"),
                          "range_raw": spec.get("range_raw")}
    return out


# ── the plan (input side) ────────────────────────────────────────────────────
def load_plan(project: Path) -> Optional[dict]:
    """`L22.fields.verification_plan` when it carries the analog track, else
    None. None means "this design declares no analog verification plan", which
    is a byte-for-byte no-op for this producer — not an empty plan."""
    doc = _read_json(_pl.generated_docs_dir(project) / "L22_VERIFICATION_PLAN.json")
    plan = _fields(doc).get("verification_plan")
    if not isinstance(plan, dict):
        return None
    if not isinstance(plan.get("analog"), list) or not plan["analog"]:
        return None
    return plan


def load_intent_rows(project: Path) -> List[dict]:
    """The declared L10 rows this producer is scoped to, in declaration order."""
    import testbench_gen as _tbg
    try:
        cases = _tbg.load_l10_cases(project)
    except (OSError, ValueError):
        return []
    if not cases:
        return []
    return [c for c in cases if _tbg.case_kind(c) in ACCEPTANCE_KINDS]


def _plan_block_specs(block: dict) -> List[dict]:
    """The L5 spec rows of one block, in EITHER shape it is carried in.

    `l22_analog_verification_plan_emit` copies `L5.analog_blocks[].spec.specs[]`
    verbatim into the plan under the key `specifications`; the L5 document
    itself nests them under `spec.specs`. One accessor reads both, so a caller
    can never silently see zero specifications because it was handed the other
    shape — which is exactly what happened on the first run of this producer
    (`_l22._block_specs` on a PLAN row returns []).
    """
    rows = block.get("specifications")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return _l22._block_specs(block)


def _block_index(plan: dict) -> Dict[str, dict]:
    return {str(b.get("block")): b for b in plan.get("analog") or []
            if isinstance(b, dict) and b.get("block")}


def _row_text(row: dict, plan_row: Optional[dict]) -> str:
    """Everything the declaration says about this row, as one string."""
    parts = [row.get("stimulus"), row.get("description"), row.get("expected"),
             row.get("name")]
    if plan_row:
        parts += [plan_row.get("method"), plan_row.get("phase")]
    return " ".join(str(p) for p in parts if p)


def _plan_row_for(plan: dict, row_name: str) -> Tuple[Optional[dict], List[str]]:
    """(the L22 intent row with this phase, the blocks L22 attributed it to).

    An UNSCOPED row (L22 could not attribute it) returns every declared block:
    an acceptance nobody scoped applies to the whole analog track, and scoping
    it to nothing would silently drop it."""
    target = _norm(row_name)
    scoped: List[str] = []
    found: Optional[dict] = None
    for block in plan.get("analog") or []:
        if not isinstance(block, dict):
            continue
        for intent in block.get("verification_intent") or []:
            if isinstance(intent, dict) and _norm(intent.get("phase")) == target:
                found = intent
                scoped.append(str(block.get("block")))
    if scoped:
        return found, scoped
    for intent in plan.get("unscoped_intent") or []:
        if isinstance(intent, dict) and _norm(intent.get("phase")) == target:
            return intent, sorted(_block_index(plan))
    return None, sorted(_block_index(plan))


#: The phase the FLOW declares the A2-A4 frontend artefacts under. Taken from
#: `analog_a4_corner_sweep_check.DECLARED_PHASE` — the gate that owns the A4
#: record — so the producer and the gate resolve the SAME candidate paths.
_A4_DECLARED_PHASE = 2


def _record_rel(project: Path, block: str) -> Optional[str]:
    """The project-relative A4 record for `block`, or None when there is none.

    None is "there is no record", NOT "the record is empty": every caller must
    keep those apart, so no default path is handed back on a miss."""
    path, found = _aac.resolve_block_artefact(
        project, block, "corner_results.json", _A4_DECLARED_PHASE)
    if not found:
        return None
    try:
        return Path(path).resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


# ── clause derivation (the CORE) ─────────────────────────────────────────────
def derive_clauses(project: Path) -> dict:
    """Derive one acceptance record for this project.

    Returns
      {"applicable": bool, "reason": str,
       "rows": [ {name, authorable, clauses:[...], refusals:[...]} ],
       "blocks": [...], "clauses": [...], "refusals": [...]}
    Nothing is written and nothing is executed here."""
    plan = load_plan(project)
    if plan is None:
        return {"applicable": False,
                "reason": ("no L22 analog verification plan "
                           "(fields.verification_plan.analog) — this design "
                           "declares no analog block; producer is a no-op"),
                "rows": [], "blocks": [], "clauses": [], "refusals": []}
    rows = load_intent_rows(project)
    if not rows:
        return {"applicable": False,
                "reason": (f"no L10 row of kind "
                           f"{'/'.join(sorted(ACCEPTANCE_KINDS))} — nothing "
                           f"for this producer to author"),
                "rows": [], "blocks": sorted(_block_index(plan)),
                "clauses": [], "refusals": []}

    blocks = _block_index(plan)
    out_rows: List[dict] = []
    all_clauses: List[dict] = []
    all_refusals: List[dict] = []

    for row in rows:
        row_name = str(row.get("name") or "")
        plan_row, scope = _plan_row_for(plan, row_name)
        text = _row_text(row, plan_row)
        evidence = [x for x in [row.get("evidence"),
                                (plan_row or {}).get("evidence")] if x]
        clauses: List[dict] = []
        refusals: List[dict] = []

        golden = [t for t in _GOLDEN_TOKENS if t in text.lower()]
        if golden:
            # §4.05: refused BEFORE anything is opened. The artefact this row
            # points at is the oracle/harness/golden and is never design
            # evidence; naming it is the whole refusal.
            refusals.append({
                "id": f"{row_name}__section_4_05",
                "row": row_name, "verdict": REFUSED,
                "reason_class": "SECTION_4_05_GOLDEN",
                "detail": (f"row names the golden/fabricated reference "
                           f"({', '.join(golden)}); §4.05 forbids reading the "
                           f"oracle/harness/golden as design evidence, so no "
                           f"acceptance is authored and the artefact is never "
                           f"opened"),
                "evidence": evidence})
            out_rows.append({"name": row_name, "authorable": False,
                             "scope": scope, "clauses": [],
                             "refusals": [r["id"] for r in refusals]})
            all_refusals.extend(refusals)
            continue

        tokens = _l22._tokens(text)

        # (A) NAMED QUANTITY — a quantity this row's own prose names.
        # Searched over EVERY declared block, not only the block L22 scoped
        # the row to: a row NAMES the quantity, and the name is the binding.
        # The measured case (see the module docstring) is a single bullet that
        # names TWO blocks: L22 attributes it to one of them by identity, and
        # the same sentence names the other block's headline quantity by name.
        # Scoping the search to the attributed block dropped that half of the
        # row on the floor.
        named: List[Tuple[str, dict]] = []
        for bname in sorted(blocks):
            block = blocks.get(bname) or {}
            for spec in _plan_block_specs(block):
                if not (_l22._tokens(spec.get("name")) & tokens):
                    continue
                named.append((bname, spec))
        for bname, spec in named:
            qn = _norm(spec.get("name"))
            bound = _bound_of(spec)
            if bound is None:
                refusals.append({
                    "id": f"{row_name}__{bname}__{qn}",
                    "row": row_name, "block": bname, "quantity": qn,
                    "l5_name": spec.get("name"), "verdict": REFUSED,
                    "reason_class": "NO_DECLARED_BOUND",
                    "detail": (f"this row names {spec.get('name')!r} and the "
                               f"input declares no numeric bound for it "
                               f"(target_raw={spec.get('target_raw')!r}, "
                               f"range_raw={spec.get('range_raw')!r}); an "
                               f"acceptance the input does not state is "
                               f"refused, never invented"),
                    "evidence": evidence})
                continue
            clauses.append(_value_clause(row_name, bname, spec, bound,
                                         evidence, "named_quantity"))

        # (B) CORNER COVERAGE — a PVT matrix this row's own prose declares.
        matrix = _l22._corner_matrix([{"method": text, "evidence": ""}])
        if matrix and matrix.get("process") and matrix.get("temperature_c"):
            for bname in scope:
                clauses.append({
                    "id": f"{row_name}__{bname}__corner_coverage",
                    "row": row_name, "block": bname,
                    "kind": "corner_coverage",
                    "corner_matrix": {"process": matrix["process"],
                                      "temperature_c": matrix["temperature_c"]},
                    "evidence": evidence,
                    "derivation": "corner_matrix",
                })

        # (C) BLOCK-SCOPED BOUNDS — a row L22 attributed TO A BLOCK is an
        # acceptance statement about that block, and the acceptance the input
        # states for a block is its L5 bound table. One clause per BOUNDED
        # quantity.
        #
        # DERIVED FROM THE INPUT ALONE, deliberately: an earlier revision
        # emitted a clause only for the quantities the A4 record already
        # measured, which made the clause SET a function of the measurement —
        # the same producer derived three clauses before A4 had run and four
        # after, and the five declared bounds nothing measured were named
        # nowhere. A bound the input states and nobody measured is exactly the
        # fact this producer exists to surface, so it gets its own clause and
        # its own NOT_MEASURED verdict.
        scoped_to_block = bool(plan_row) and any(
            isinstance(b, dict)
            and any(isinstance(i, dict)
                    and _norm(i.get("phase")) == _norm(row_name)
                    for i in b.get("verification_intent") or [])
            for b in plan.get("analog") or [])
        if scoped_to_block:
            have = {(c.get("block"), c.get("quantity")) for c in clauses}
            for bname in scope:
                for spec in _plan_block_specs(blocks.get(bname) or {}):
                    qn = _norm(spec.get("name"))
                    bound = _bound_of(spec)
                    if bound is None or (bname, qn) in have:
                        continue
                    clauses.append(_value_clause(
                        row_name, bname, spec, bound, evidence,
                        "block_scoped_bound"))

        if not clauses and not refusals:
            refusals.append({
                "id": f"{row_name}__no_acceptance",
                "row": row_name, "verdict": REFUSED,
                "reason_class": "NO_ACCEPTANCE_DERIVABLE",
                "detail": ("this row names no quantity the input bounds and "
                           "declares no PVT matrix; the input states no "
                           "acceptance for it"),
                "evidence": evidence})

        out_rows.append({"name": row_name, "authorable": bool(clauses),
                         "scope": scope, "clauses": [c["id"] for c in clauses],
                         "refusals": [r["id"] for r in refusals]})
        all_clauses.extend(clauses)
        all_refusals.extend(refusals)

    return {"applicable": True, "reason": "",
            "rows": out_rows, "blocks": sorted(blocks),
            "clauses": all_clauses, "refusals": all_refusals}


def _value_clause(row_name: str, bname: str, spec: dict,
                  bound: dict, evidence: list, derivation: str) -> dict:
    qn = _norm(spec.get("name"))
    return {
        "id": f"{row_name}__{bname}__{qn}",
        "row": row_name, "block": bname, "kind": "value_bound",
        "quantity": qn, "l5_name": spec.get("name"), "bound": bound,
        "evidence": evidence, "derivation": derivation,
    }


# ── clause EVALUATION (what an emitted check runs) ───────────────────────────
def evaluate_clause(project: Path, clause: dict) -> Tuple[str, str]:
    """(verdict, detail) for one clause against the A4 record it names."""
    # RESOLVED AT CHECK TIME, NOT BAKED INTO THE CLAUSE.
    #
    # MEASURED on the front door: Step 4 runs BEFORE the A-track, so the
    # emission that Step 4 reads happens while no A4 record exists. An earlier
    # revision froze the record PATH into the emitted check, so the post-A4
    # re-evaluation re-ran nine checks that still pointed at nothing and
    # reported nine NOT_MEASURED over a record that was sitting right there.
    # The clause is an INPUT artefact; where the measurement lives is resolved
    # when the check runs.
    rel = _record_rel(project, str(clause.get("block") or ""))
    if not rel:
        return NOT_MEASURED, (
            f"no A4 corner-sweep record for block {clause.get('block')!r} "
            f"(phase3/analog/<block>/corner_results.json); flow step A4 has "
            f"not produced one, so this acceptance is UNMEASURED — it is not "
            f"a pass and it is not a failure")
    path = project / rel
    data = _read_json(path)
    if data is None:
        return NOT_MEASURED, (
            f"could not read the A4 record {rel} as JSON — NOT_MEASURED; "
            f"no value is assumed")
    corners = [c for c in (data.get("corners") or []) if isinstance(c, dict)]
    executed = [c for c in corners if c.get(_EXECUTED_KEY)]
    if clause.get("kind") == "corner_coverage":
        return _eval_corner_coverage(clause, rel, corners, executed)
    return _eval_value_bound(clause, rel, data, executed)


def _eval_value_bound(clause: dict, rel: str, data: dict,
                      executed: List[dict]) -> Tuple[str, str]:
    q = str(clause.get("quantity"))
    bound = clause.get("bound") or {}
    lo, hi = bound.get("min"), bound.get("max")
    seen: List[Tuple[str, float]] = []
    for corner in executed:
        v = _corner_value(corner, q)
        if v is not None:
            seen.append((str(corner.get("name")), v))
    if not seen:
        for entry in data.get("spec_results") or []:
            if isinstance(entry, dict) and _norm(entry.get("name")) == q \
                    and entry.get("value") is not None:
                try:
                    seen.append(("spec_results", float(entry["value"])))
                except (TypeError, ValueError):
                    pass
    if not seen:
        return NOT_MEASURED, (
            f"{rel} carries no measured value for {clause.get('l5_name')!r} "
            f"at any executed corner (the input bounds it "
            f"{_bound_text(bound)}); UNMEASURED, never a pass")
    bad = [(n, v) for n, v in seen
           if (lo is not None and v < lo) or (hi is not None and v > hi)]
    if bad:
        return FAIL, (
            f"{clause.get('l5_name')} outside the declared bound "
            f"{_bound_text(bound)} at {len(bad)} of {len(seen)} executed "
            f"corner(s): "
            + "; ".join(f"{n}={v!r}" for n, v in bad[:6])
            + f" [{rel}]")
    return PASS, (
        f"{clause.get('l5_name')} inside the declared bound "
        f"{_bound_text(bound)} at all {len(seen)} executed corner(s): "
        + ", ".join(f"{n}={v!r}" for n, v in seen[:12])
        + f" [{rel}]")


def _eval_corner_coverage(clause: dict, rel: str, corners: List[dict],
                          executed: List[dict]) -> Tuple[str, str]:
    matrix = clause.get("corner_matrix") or {}
    want = [(p, t) for p in matrix.get("process") or []
            for t in matrix.get("temperature_c") or []]
    if not executed:
        return NOT_MEASURED, (
            f"{rel} records {len(corners)} corner(s) and none with "
            f"{_EXECUTED_KEY}=true; the declared "
            f"{len(want)}-corner matrix is UNMEASURED, never a pass")
    missing = [(p, t) for p, t in want
               if not _corner_present(executed, p, t)]
    if missing:
        return FAIL, (
            f"{len(missing)} of {len(want)} declared corner(s) were not "
            f"executed: "
            + ", ".join(f"{p}@{t}C" for p, t in missing[:9])
            + f" ({len(executed)} corner(s) executed in {rel})")
    return PASS, (
        f"all {len(want)} declared corner(s) "
        f"({'/'.join(matrix.get('process') or [])} x "
        f"{'/'.join(str(t) for t in matrix.get('temperature_c') or [])} C) "
        f"were executed; {len(executed)} executed corner(s) in {rel}")


def _corner_present(executed: List[dict], process: str, temp: Any) -> bool:
    p = _norm(process)
    for corner in executed:
        try:
            if float(corner.get("temp_c")) != float(temp):
                continue
        except (TypeError, ValueError):
            continue
        haystack = f"{corner.get('process') or ''}_{corner.get('name') or ''}"
        if p in {_norm(tok) for tok in re.split(r"[^A-Za-z0-9]+", haystack)}:
            return True
    return False


def _bound_text(bound: dict) -> str:
    lo, hi, unit = bound.get("min"), bound.get("max"), bound.get("unit") or ""
    if lo is not None and hi is not None:
        body = f"[{lo}, {hi}]"
    elif lo is not None:
        body = f">= {lo}"
    else:
        body = f"<= {hi}"
    return f"{body} {unit}".strip()


# ── emission ────────────────────────────────────────────────────────────────
_CHECK_TEMPLATE = '''#!/usr/bin/env python3
"""GENERATED by {tool} (ORGANIC #2064) — DO NOT EDIT.

Executable acceptance check for L10 verification-intent row
  {row!r}
derived from the design's own input ({derivation}); it reads the A4
corner-sweep record and asserts the declared bound. Re-generated every run.

CLAUSE (the authored acceptance, verbatim):
{clause_pretty}
"""
import json
import sys
from pathlib import Path

PROGRAMS_DIR = Path({programs!r})
PROJECT = Path(__file__).resolve().parents[{up}]
CLAUSE = json.loads({clause_json!r})

sys.path.insert(0, str(PROGRAMS_DIR))
import analog_acceptance_tb_gen as _acc

verdict, detail = _acc.evaluate_clause(PROJECT, CLAUSE)
print("ANALOG_ACCEPTANCE {id} %s: %s" % (verdict, detail))
sys.exit(_acc._EXIT[verdict])
'''


def check_dir(project: Path) -> Path:
    return _pl.sim_dir(project) / CHECK_DIR_NAME


def result_dir(project: Path) -> Path:
    import testbench_gen as _tbg
    return _tbg.sim_professional_dir(project) / RESULT_DIR_NAME


def emit_acceptance_checks(project: Path,
                           report: "dict | None" = None) -> int:
    """Emit one executable check per derived clause. Returns the number of
    check files written, or a negative sentinel — nothing is written on either:
      -1  this design declares no analog verification plan / no intent row
      -2  the plan exists but NO clause is derivable (every row refused). The
          refusals are still recorded; an empty check directory must never read
          as "there was nothing to check"."""
    if report is None:
        report = {}
    derived = derive_clauses(project)
    report.update(derived)
    if not derived["applicable"]:
        return -1
    out = check_dir(project)
    # Clear EVERY prior emission before any refusal path, so a re-run with a
    # narrower derivation can never leave yesterday's check behind to be run
    # and counted again.
    if out.is_dir():
        for stale in out.glob("*.py"):
            stale.unlink()
    if not derived["clauses"]:
        return -2
    out.mkdir(parents=True, exist_ok=True)
    up = len(out.relative_to(project).parts)
    for clause in derived["clauses"]:
        text = _CHECK_TEMPLATE.format(
            tool=TOOL, row=clause["row"], id=clause["id"],
            derivation=clause.get("derivation"),
            clause_pretty=json.dumps(clause, indent=2, ensure_ascii=False),
            clause_json=json.dumps(clause, ensure_ascii=False),
            programs=str(_HERE), up=up)
        (out / f"{clause['id']}.py").write_text(text, encoding="utf-8")
    report["check_dir"] = str(out)
    return len(derived["clauses"])


# ── execution ───────────────────────────────────────────────────────────────
def run_acceptance_checks(project: Path, report: "dict | None" = None,
                          timeout: int = 120) -> int:
    """EXECUTE every emitted check and write the Step-4 JUnit + the record.

    Returns the number of checks that executed, or a negative sentinel:
      -1  nothing to run and no refusal to report (no analog plan / no rows)
      -2  no check was emitted but refusals exist — the JUnit IS written, with
          one `<error>` testcase per refusal, because a refused acceptance is
          not a pass and must not vanish from the denominator."""
    if report is None:
        report = {}
    derived = derive_clauses(project)
    report.update(derived)
    if not derived["applicable"]:
        return -1
    out = check_dir(project)
    cases: List[dict] = []
    executed = 0
    for clause in derived["clauses"]:
        script = out / f"{clause['id']}.py"
        t0 = time.time()
        if not script.is_file():
            cases.append({"name": clause["id"], "verdict": NOT_MEASURED,
                          "detail": (f"the emitted check {script} is absent; "
                                     f"nothing was executed for this clause"),
                          "time": 0.0})
            continue
        proc = subprocess.run([sys.executable, str(script)],
                              capture_output=True, text=True,
                              timeout=timeout, cwd=str(project))
        transcript = (proc.stdout or "") + (proc.stderr or "")
        verdict = _EXIT_VERDICT.get(proc.returncode)
        if verdict is None:
            # The check itself did not complete. That is NOT a design verdict.
            verdict = NOT_MEASURED
            detail = (f"check exited {proc.returncode}, which is not one of "
                      f"this producer's verdict codes; nothing is known about "
                      f"the acceptance: {transcript.strip()[:400]}")
        else:
            detail = transcript.strip().split(": ", 1)[-1][:800]
            executed += 1
        cases.append({"name": clause["id"], "verdict": verdict,
                      "detail": detail, "time": time.time() - t0,
                      "block": clause.get("block"), "row": clause["row"],
                      "clause_kind": clause.get("kind"),
                      "record": _record_rel(project,
                                            str(clause.get("block") or ""))})
    for refusal in derived["refusals"]:
        cases.append({"name": refusal["id"], "verdict": REFUSED,
                      "detail": (f"{refusal['reason_class']}: "
                                 f"{refusal['detail']}"),
                      "time": 0.0, "row": refusal["row"]})

    report["cases"] = cases
    report["passed"] = sum(1 for c in cases if c["verdict"] == PASS)
    report["failed"] = sum(1 for c in cases if c["verdict"] == FAIL)
    report["not_measured"] = sum(1 for c in cases
                                 if c["verdict"] == NOT_MEASURED)
    report["refused"] = sum(1 for c in cases if c["verdict"] == REFUSED)
    report["executed"] = executed
    report["rows_total"] = len(derived["rows"])
    report["rows_authorable"] = sum(1 for r in derived["rows"]
                                    if r["authorable"])
    if not cases:
        report["reason"] = ("the plan is applicable but produced neither a "
                            "clause nor a refusal — nothing written")
        return -1
    res_dir = result_dir(project)
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / "results.xml").write_text(_junit(cases), encoding="utf-8")
    report["results_xml"] = str(res_dir / "results.xml")
    rec = project / RECORD_REL
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({
        "gate": TOOL, "producer": TOOL,
        "rows_total": report["rows_total"],
        "rows_authorable": report["rows_authorable"],
        "clauses": derived["clauses"], "refusals": derived["refusals"],
        "rows": derived["rows"], "cases": cases,
        "results_xml": str(res_dir / "results.xml"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    report["record"] = str(rec)
    return executed if derived["clauses"] else -2


def _xml_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _junit(cases: List[dict]) -> str:
    """One `<testcase>` per clause AND per refusal.

    A NOT_MEASURED or REFUSED case is an `<error>`: the acceptance could not be
    executed. It is never `<skipped>` — a skip is subtracted from the passed
    count by every JUnit reader, which would let an acceptance nobody could run
    read as a suite with nothing wrong in it."""
    body = []
    failures = errors = 0
    for c in cases:
        name = _xml_escape(c["name"])
        line = (f'  <testcase classname="{RESULT_DIR_NAME}" name="{name}" '
                f'time="{c.get("time", 0.0):.3f}"')
        if c["verdict"] == PASS:
            body.append(line + "/>")
            continue
        detail = _xml_escape(c.get("detail") or "")
        if c["verdict"] == FAIL:
            failures += 1
            body.append(line + ">")
            body.append(f'    <failure message="{detail[:400]}">{detail}'
                        f'</failure>')
        else:
            errors += 1
            body.append(line + ">")
            body.append(f'    <error type="{c["verdict"]}" '
                        f'message="{detail[:400]}">{detail}</error>')
        body.append("  </testcase>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>\n'
            f'<testsuite name="{RESULT_DIR_NAME}" tests="{len(cases)}" '
            f'failures="{failures}" errors="{errors}" skipped="0">\n'
            + "\n".join(body) + "\n</testsuite>\n</testsuites>\n")


# ── the Step-4 denominator accessor ─────────────────────────────────────────
def authorable_row_names(project: Path) -> "set | None":
    """The L10 row names this producer can author an acceptance for.

    `None` — not an empty set — when the plan or the rows could not be read:
    "could not measure it" must not be handed to a caller as "there are none"."""
    try:
        derived = derive_clauses(project)
    except Exception:
        return None
    if not derived["applicable"]:
        return set()
    return {r["name"] for r in derived["rows"] if r["authorable"]}


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--run", action="store_true",
                    help="EXECUTE the emitted checks and write the Step-4 "
                         "JUnit instead of emitting")
    ap.add_argument("--json", default=None,
                    help="write the producer's own report here")
    ns = ap.parse_args(argv)
    project = ns.project.resolve()
    report: dict = {}
    if ns.run:
        n = run_acceptance_checks(project, report)
        print(f"{TOOL}: rows={report.get('rows_total', 0)} "
              f"authorable={report.get('rows_authorable', 0)} "
              f"executed={n} pass={report.get('passed', 0)} "
              f"fail={report.get('failed', 0)} "
              f"not_measured={report.get('not_measured', 0)} "
              f"refused={report.get('refused', 0)}"
              + (f" — {report['reason']}" if report.get("reason") else ""))
    else:
        n = emit_acceptance_checks(project, report)
        print(f"{TOOL}: emitted {max(n, 0)} check(s); "
              f"rows={len(report.get('rows') or [])} "
              f"clauses={len(report.get('clauses') or [])} "
              f"refusals={len(report.get('refusals') or [])}"
              + (f" — {report.get('reason')}" if report.get("reason") else ""))
    if ns.json:
        p = Path(ns.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                default=str), encoding="utf-8")
    # A producer never decides the run's verdict: emission/execution succeeded
    # or it reported why. The BLOCKING verdict is Step 4's, taken from the
    # JUnit this producer wrote.
    return 0


if __name__ == "__main__":
    sys.exit(main())
