#!/usr/bin/env python3
"""l10_test_case_oracle_anchor_check.py — L10 CONSUMER-CONTRACT gate.

BLOCKS (exit 1).  Rationale for blocking, not advising: the readers of
L10 do not fail when a case is unusable — they *silently* degrade.
``testbench_gen._emit_case_tb`` — which the flow does run, at
``phase1_phase2_phase3.yaml`` step ``testbench_gen`` — appends the case to
``report['skipped']`` when the handle is not a legal Verilog identifier,
and when the case has no oracle it still emits a TB carrying
``ORACLE_NONE`` plus a ``SUBSTANCE_OK`` print.  ``phase2_scaffold_gen``
would copy the case text into ``compliance_vectors.txt`` verbatim — that
one is a CONTRACT ORACLE and no flow step runs it (#509), so it states
what a conforming phase 2 owes rather than what happens.  Either way
nothing downstream reports that the case was never actually checked, so
an unverifiable case credits itself in every coverage count it appears
in.  A gate that only advised would reproduce failure (b) of the
motivating defect — a FAIL that the flow walks straight past.

WHAT THIS GATE IS *NOT*
-----------------------
It is not a duplicate of ``l10_test_cases_cover_l3_constraints_check``.
That gate asks a cross-layer question — "does every L3 constraint have
some L10 case?" — and answers it with token presence: it
``json.dumps()``-es the whole case (including the ``evidence``
provenance string) and credits an opcode found ANYWHERE in that blob.
This gate asks the orthogonal, per-case question the TB generators
actually need answered:

    Is THIS case, on its own, drivable and falsifiable by the program
    that consumes it?

A case can satisfy the coverage gate and still be worthless here, and
that is exactly the "a token appeared somewhere" failure the L21 power
-intent defect was made of: the requirement must be present IN THE FIELD
THE CONSUMER READS, in actionable form.

THE CONTRACT (per executable case)
----------------------------------
1. HANDLE — ``name``/``id``/``case_id`` must exist, must match
   ``testbench_gen._LEGAL_ID_RE`` (a legal Verilog identifier, imported
   from the consumer itself rather than re-spelled here), and must be
   unique across the layer.  An illegal handle is dropped by the
   generator; a duplicated handle makes the second case overwrite the
   first one's TB file, so N declared cases silently become fewer TBs.

2. ORACLE ANCHOR — the case's expected-role text must contain something
   a testbench can compare against.  Exactly three families count:

     LITERAL     0x…, sized Verilog (8'hA5), a bare hex word
                 (``ba7816bf`` — NIST-style digests are legitimate
                 expected values), a multi-digit decimal, or a
                 number carrying a unit (``120 us``).
     RELATION    a comparison operator (= == != >= <= < > ≥ ≤ ≠)
                 linking operands — "readback == written value" is a
                 real oracle even with no literal in it.
     OBSERVABLE  a token that matches a name the DESIGN ITSELF declares
                 in its other machine-readable L-docs (signal / port /
                 register / field / state / opcode / constant names
                 harvested from L1-L27 at run time).

   Family OBSERVABLE is why this gate is chip-AGNOSTIC: the vocabulary
   of legal anchors is *derived from the design's own inputs* on every
   run.  No design name, PDK name, part number, or pin literal appears
   anywhere in this file.

3. DISTINCTNESS — expected text must be non-empty, must carry at least
   one alphanumeric character (a bare "✅" is not an oracle), and must
   not be byte-identical to the stimulus text (restating the stimulus is
   not a prediction).

SCOPE — WHICH CASES ARE "EXECUTABLE"
------------------------------------
Only cases whose own declared ``kind``/``category`` is not
documentation-shaped.  Kinds matching ``intent|checklist|doc|info|plan|
review|note|summary|observation|coverage_goal`` are counted and skipped
honestly, mirroring the ``category=info_only`` escape hatch that
``l12_sequence_implementation_check`` already honours.  This keeps the
gate from demanding a byte-level oracle from an entry that never claimed
to be one — and, unlike a waiver, it is the DESIGN's own declaration
that grants the exemption, so it cannot be used to launder a real
vector.

Usage:
    python3 l10_test_case_oracle_anchor_check.py <project_dir> [--json OUT]

Exit codes:
    0 = PASS
    1 = FAIL (blocking)
    2 = SKIP / input missing

Honors waiver ``l10_test_case_oracle_anchor_intentional`` (>=40 chars).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

WAIVER_KEY = "l10_test_case_oracle_anchor_intentional"
WAIVER_MIN = 40

_L10_GLOBS = (
    "phase1/generated_docs/L10_TEST_CASES.json",
    "phase1/generated_docs/L10*.json",
    "**/L10_TEST_CASES.json",
)

_CASE_ARRAY_KEYS = ("test_cases", "cases", "tests", "vectors")
_HANDLE_KEYS = ("name", "id", "case_id", "test_id")
_EXPECT_KEYS = ("expected", "expected_response", "expected_result",
                "expect", "expected_bytes", "response", "golden",
                "expected_value", "pass_criteria")
_STIMULUS_KEYS = ("stimulus", "input", "drive", "opcode_hex", "command",
                  "request", "inputs", "operands")
_KIND_KEYS = ("kind", "test_kind", "category", "type", "class")

# A case kind that is documentation-shaped implies no executable vector.
_DOC_KIND_RE = re.compile(
    r"intent|checklist|doc|info|plan|review|note|summary|observation|"
    r"coverage_goal|goal_only|descriptive",
    re.IGNORECASE,
)

# --- oracle anchor families -------------------------------------------------
# LITERAL: 0x-hex | sized Verilog | bare hex word (>=4, must contain a digit)
#          | multi-digit decimal | number+unit
_LIT_RE = re.compile(
    r"0x[0-9a-fA-F]+"
    r"|[0-9]+\s*'\s*[sS]?\s*[hbdoHBDO][0-9a-fA-FxXzZ?_]+"
    r"|\b(?=[0-9a-fA-F]{4,}\b)[a-fA-F]*[0-9][0-9a-fA-F]*\b"
    r"|\b\d{2,}\b"
    r"|\b\d+(?:\.\d+)?\s*(?:ns|us|ms|ps|s|sec|cycle|cycles|clk|clks|"
    r"MHz|kHz|Hz|V|mV|uV|A|mA|uA|nA|bit|bits|byte|bytes|LSB|dB)\b"
)
# RELATION: an explicit comparison. Requires an operand character on at
# least one side so a lone bullet dash never counts.
_REL_RE = re.compile(
    r"(?:[\w\)\]％%]\s*(?:==|!=|>=|<=|=>|=<|[=<>≥≤≠])\s*)"
    r"|(?:(?:==|!=|>=|<=|=>|=<|[=<>≥≤≠])\s*[\w\(\[])"
)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_ALNUM_RE = re.compile(r"[0-9A-Za-z一-鿿]")

# Keys under which other L-docs declare an OBSERVABLE name. Deliberately
# generic — these are schema role names, never design content.
_NAME_ROLE_KEYS = (
    "name", "signal", "signal_name", "net", "net_name", "port", "port_name",
    "pin", "pin_name", "field", "field_name", "register", "register_name",
    "reg", "bus", "interface", "id", "state", "state_name", "constant",
    "symbol", "mnemonic", "opcode_name", "parameter", "param", "output",
    "input", "terminal", "label", "key",
)
_NAME_LIST_KEYS = (
    "signals", "ports", "pins", "nets", "outputs", "inputs", "fields",
    "registers", "states", "constants", "parameters", "terminals",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.exists():
        return False, ""
    try:
        d = json.loads(p.read_text(errors="replace"))
        v = d.get(WAIVER_KEY)
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            return True, v.strip()
    except Exception:
        pass
    return False, ""


def _legal_id_re() -> "re.Pattern[str]":
    """Import the consumer's OWN identifier rule instead of re-spelling it.

    ``testbench_gen`` is the program that drops a case whose handle is not
    a legal Verilog identifier, so its regex is the contract. Falling back
    to a local copy only if the import is unavailable keeps the gate
    runnable standalone.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import testbench_gen  # noqa: WPS433
        pat = getattr(testbench_gen, "_LEGAL_ID_RE", None)
        if pat is not None and hasattr(pat, "match"):
            return pat
    except Exception:
        pass
    return re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _find_l10(project: Path) -> Optional[Path]:
    for pat in _L10_GLOBS:
        for hit in sorted(project.glob(pat)):
            if hit.is_file():
                return hit
    return None


def _first_str(case: dict, keys: Tuple[str, ...]) -> str:
    """Concatenate every present value under `keys` into one text blob."""
    out: List[str] = []
    for k in keys:
        v = case.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, (list, tuple)):
            for it in v:
                if isinstance(it, (str, int, float)):
                    out.append(str(it))
        elif isinstance(v, (int, float)):
            out.append(str(v))
        elif isinstance(v, dict):
            out.append(json.dumps(v, ensure_ascii=False))
    return " ".join(out)


def harvest_observables(docs_dir: Path, exclude_stem_prefix: str = "L10") -> Set[str]:
    """Name vocabulary DERIVED from the design's own other L-docs.

    Walks every sibling ``L*.json`` and collects string values that sit
    under a name-role key and look like an identifier. This is the whole
    reason the gate needs no hardcoded design knowledge.
    """
    names: Set[str] = set()

    def take(v) -> None:
        if isinstance(v, str):
            s = v.strip()
            if _IDENT_RE.fullmatch(s) and len(s) >= 3:
                names.add(s.lower())

    def walk(node, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                lk = str(k).lower()
                if lk in _NAME_ROLE_KEYS:
                    take(v)
                if lk in _NAME_LIST_KEYS and isinstance(v, list):
                    for it in v[:500]:
                        take(it)
                walk(v, depth + 1)
        elif isinstance(node, list):
            for it in node[:500]:
                walk(it, depth + 1)

    if not docs_dir.is_dir():
        return names
    for p in sorted(docs_dir.glob("L*.json")):
        if p.stem.startswith(exclude_stem_prefix):
            continue
        try:
            walk(json.loads(p.read_text(errors="replace")))
        except Exception:
            continue
    return names


def classify_anchor(text: str, observables: Set[str]) -> Optional[str]:
    """Return the anchor family that makes `text` falsifiable, else None."""
    if not text:
        return None
    if _LIT_RE.search(text):
        return "literal"
    if _REL_RE.search(text):
        return "relation"
    for tok in _IDENT_RE.findall(text):
        if tok.lower() in observables:
            return f"observable:{tok}"
    return None


def _is_doc_kind(case: dict) -> bool:
    for k in _KIND_KEYS:
        v = case.get(k)
        if isinstance(v, str) and _DOC_KIND_RE.search(v):
            return True
    return False


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
def audit(l10_path: Path, docs_dir: Path) -> Dict:
    """Return a machine-readable report. Pure function — no I/O side effects."""
    report: Dict = {
        "program": "l10_test_case_oracle_anchor_check",
        "version": "1.0.0",
        "l10": str(l10_path),
        "summary": {
            "cases_total": 0,
            "cases_executable": 0,
            "cases_doc_kind_skipped": 0,
            "cases_anchored": 0,
            "observable_vocab_size": 0,
        },
        "findings": [],
    }
    try:
        data = json.loads(l10_path.read_text(errors="replace"))
    except Exception as exc:
        report["findings"].append({
            "severity": "ERROR", "category": "INVALID_JSON",
            "case": "", "message": f"cannot parse L10: {exc}",
        })
        return report

    cases: List[dict] = []
    for k in _CASE_ARRAY_KEYS:
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, list) and v:
            cases = [c for c in v if isinstance(c, dict)]
            break
    report["summary"]["cases_total"] = len(cases)
    if not cases:
        return report

    observables = harvest_observables(docs_dir)
    report["summary"]["observable_vocab_size"] = len(observables)
    legal_id = _legal_id_re()

    seen: Dict[str, int] = {}
    for idx, case in enumerate(cases):
        handle = ""
        for k in _HANDLE_KEYS:
            v = case.get(k)
            if isinstance(v, str) and v.strip():
                handle = v.strip()
                break
        label = handle or f"case[{idx}]"

        # --- 1. HANDLE -----------------------------------------------------
        if not handle:
            report["findings"].append({
                "severity": "ERROR", "category": "NO_HANDLE", "case": label,
                "message": ("case has no name/id — testbench_gen cannot name a "
                            "TB for it and l10_tb_conformance_check cannot "
                            "match a summary.txt PASS to it, so the case is "
                            "structurally unverifiable."),
            })
        elif not legal_id.match(handle):
            report["findings"].append({
                "severity": "ERROR", "category": "ILLEGAL_HANDLE", "case": label,
                "message": (f"handle {handle!r} is not a legal Verilog "
                            "identifier — testbench_gen SKIPS the case and "
                            "emits no TB, while the case still counts itself "
                            "in every L10 coverage total."),
            })
        else:
            if handle.lower() in seen:
                report["findings"].append({
                    "severity": "ERROR", "category": "DUPLICATE_HANDLE",
                    "case": label,
                    "message": (f"handle {handle!r} already used by case "
                                f"index {seen[handle.lower()]} — the second TB "
                                "overwrites the first, so two declared cases "
                                "become one executed one."),
                })
            else:
                seen[handle.lower()] = idx

        # --- scope ---------------------------------------------------------
        if _is_doc_kind(case):
            report["summary"]["cases_doc_kind_skipped"] += 1
            continue
        report["summary"]["cases_executable"] += 1

        expected = _first_str(case, _EXPECT_KEYS)
        stimulus = _first_str(case, _STIMULUS_KEYS)

        # --- 3. DISTINCTNESS ------------------------------------------------
        if not expected.strip():
            report["findings"].append({
                "severity": "ERROR", "category": "NO_EXPECTED", "case": label,
                "message": ("executable case declares no expected/"
                            "expected_response text — a TB built from it "
                            "cannot fail."),
            })
            continue
        if not _ALNUM_RE.search(expected):
            report["findings"].append({
                "severity": "ERROR", "category": "VACUOUS_EXPECTED",
                "case": label,
                "message": (f"expected text {expected[:40]!r} carries no "
                            "alphanumeric content — a checkmark or bullet is "
                            "not an oracle."),
            })
            continue
        if stimulus.strip() and expected.strip() == stimulus.strip():
            report["findings"].append({
                "severity": "ERROR", "category": "EXPECTED_RESTATES_STIMULUS",
                "case": label,
                "message": ("expected text is byte-identical to the stimulus "
                            "— restating the input is not a prediction, so the "
                            "comparison is trivially true."),
            })
            continue

        # --- 2. ORACLE ANCHOR ----------------------------------------------
        anchor = classify_anchor(expected, observables)
        if anchor is None:
            report["findings"].append({
                "severity": "ERROR", "category": "NO_ORACLE_ANCHOR",
                "case": label,
                "message": (
                    f"expected text {expected[:70]!r} contains no literal, no "
                    "comparison relation, and no name this design declares in "
                    f"its own L-docs ({len(observables)} observable names "
                    "harvested). testbench_gen will emit an ORACLE_NONE "
                    "testbench that prints SUBSTANCE_OK without checking the "
                    "case."),
            })
        else:
            report["summary"]["cases_anchored"] += 1

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Assert every executable L10 test case is drivable and "
                    "falsifiable by the programs that consume L10.")
    ap.add_argument("project", help="project directory")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="optional path for the machine-readable report")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"[SKIP] l10_test_case_oracle_anchor_check: not a directory: "
              f"{project}")
        return 2

    l10 = _find_l10(project)
    if l10 is None:
        print("[SKIP] l10_test_case_oracle_anchor_check: "
              "L10_TEST_CASES.json not found")
        return 2

    report = audit(l10, l10.parent)
    if args.json_out:
        outp = Path(args.json_out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    s = report["summary"]
    errs = [f for f in report["findings"] if f["severity"] == "ERROR"]
    report["summary"]["pass"] = not errs

    if s["cases_total"] == 0:
        print("[SKIP] l10_test_case_oracle_anchor_check: "
              "L10 declares no test_cases[]")
        return 2

    if errs:
        waived, text = _waived(project)
        head = (f"[FAIL] l10_test_case_oracle_anchor_check: "
                f"{len(errs)} unverifiable case(s) of "
                f"{s['cases_executable']} executable "
                f"({s['cases_doc_kind_skipped']} doc-kind skipped, "
                f"{s['observable_vocab_size']} observable names derived from "
                f"this design's own L-docs):")
        body = "\n".join(f"  - [{f['category']}] {f['case']}: {f['message']}"
                         for f in errs[:8])
        if waived:
            print(f"[PASS] l10_test_case_oracle_anchor_check: waived "
                  f"({WAIVER_KEY}; {len(errs)} finding(s) suppressed)")
            return 0
        print(head)
        print(body)
        if len(errs) > 8:
            print(f"  ... {len(errs) - 8} more")
        return 1

    print(f"[PASS] l10_test_case_oracle_anchor_check: "
          f"{s['cases_anchored']}/{s['cases_executable']} executable case(s) "
          f"carry an oracle anchor; {s['cases_doc_kind_skipped']} doc-kind "
          f"entr(ies) skipped by their own declared kind")
    return 0


if __name__ == "__main__":
    sys.exit(main())
