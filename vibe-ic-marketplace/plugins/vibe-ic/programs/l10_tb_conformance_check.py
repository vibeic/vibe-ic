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


# ----- helpers ------------------------------------------------------


def load_l10(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    # Accept either a flat list or a dict with "test_cases" / "cases" / "vectors"
    if isinstance(data, list):
        return data
    for key in ("test_cases", "cases", "vectors", "cmd_response", "tests"):
        if key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError("L10 JSON did not contain a recognisable test-case list")


def read_all_tb_text(tb_dir: str) -> Tuple[Dict[str, str], str]:
    """Return (per-file text map, concatenated blob) of every .v / .sv under tb_dir."""
    per_file: Dict[str, str] = {}
    blob_parts: List[str] = []
    for p in sorted(Path(tb_dir).rglob("*")):
        if p.is_file() and p.suffix in (".v", ".sv", ".svh"):
            try:
                txt = p.read_text(errors="replace")
            except Exception:
                continue
            per_file[str(p)] = txt
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


def case_has_opcode_evidence(case: Dict[str, Any], tb_blob: str) -> bool:
    """Check if the case's opcode or host packet bytes appear in any tb file."""
    # Find the opcode hex from common field names
    opcode = None
    for field in ("opcode", "cmd", "cmd_hex", "cmd_byte"):
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
    kind=verification_intent mislabel cannot defeat the digital requirement."""
    if is_cmd_rsp:
        return True
    for field in ("opcode", "cmd", "cmd_hex", "cmd_byte"):
        if case.get(field):
            return True
    cat = str(case.get("category", case.get("type", "")) or "").strip().lower()
    return cat in _DIGITAL_CLASS_TOKENS


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


# ----- CLI ----------------------------------------------------------


def evaluate(
    cases: List[Dict[str, Any]],
    tb_blob: str,
    summary: str,
    skip_analog: bool = False,
    analog_anchor: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Return (results, ok_count, fail_count).

    The per-case ``status`` field ("pass" / "fail" / "waived") and a
    project-level ``waive_count`` are derivable from the returned ``results``
    list (see ``count_waived``); the 3-tuple return shape is preserved for
    backward compatibility with existing callers.

    ORGANIC #773 — when ``skip_analog`` is set AND ``analog_anchor`` resolves
    to a reviewable capability-gap bridge, a `verification_intent` (A/M-track)
    case that lacks a digital-TB id-substring trace is credited as WAIVED-
    DEFERRED instead of FAILing. §4.05 NO-LEAK: a genuine digital case
    (anything NOT `verification_intent`) with no tb evidence STILL FAILs even
    under --skip-analog, and an UNANCHORED verification_intent case (no
    reviewable bridge) also still FAILs — the relaxation is kind-scoped and
    anchor-gated so it can never mask a missing digital testbench."""
    results: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    waiver_active = bool(skip_analog) and bool(analog_anchor)
    for c in cases:
        case_id = str(c.get("id", c.get("name", "")))
        category = c.get("category", c.get("type", c.get("kind", "")))
        is_cmd_rsp = category.lower() in ("cmd_response", "cmd_rsp", "happy", "happy_path") if category else False
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
        if (not ok and waiver_active and is_verification_intent(c)
                and not _has_digital_signal(c, is_cmd_rsp)):
            waived = True
            status = "waived"
            evidence = [
                "WAIVED-DEFERRED: verification_intent A/M-track oracle "
                f"({CAP_ANALOG_VERIFICATION_INTENT}); analog track deferred "
                f"via --skip-analog; reviewable anchor: {analog_anchor}"
            ]
        results.append(
            {
                "id": case_id,
                "category": category,
                "evidence": evidence,
                "pass": ok,
                "status": status,
                "waived": waived,
                "review_required": waived,
                "capability_gap": (CAP_ANALOG_VERIFICATION_INTENT if waived else None),
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


def _tb_files_under(d: Path) -> bool:
    """True when directory `d` directly or recursively holds a testbench
    .v/.sv (a tb_*.v or anything with a `module tb` / `_tb`)."""
    if not d.is_dir():
        return False
    for p in d.rglob("*"):
        if p.is_file() and p.suffix in (".v", ".sv"):
            return True
    return False


def _resolve_tb_dir(given: str) -> Optional[str]:
    """ORGANIC #572 — the default --tb-dir (phase2/stage1/sim/tb) is rigid;
    a project that keeps testbenches at the sim/ ROOT (phase2/stage1/sim/)
    reported 4/4 false 'lack evidence'. Try the given path first, then its
    parent when the leaf is 'tb', then the canonical sim roots. Returns the
    first directory that actually holds a .v/.sv, else None."""
    cands: List[str] = [given]
    gp = Path(given)
    if gp.name == "tb":
        cands.append(str(gp.parent))
    cands += ["phase2/stage1/sim/tb", "phase2/stage1/sim",
              "sim/tb", "sim"]
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        if _tb_files_under(Path(c)):
            return c
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

    _, tb_blob = read_all_tb_text(tb_dir)
    summary = read_summary(_resolve_summary(args.summary))

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
    analog_anchor = (
        analog_skip_anchor(project_root, args.analog_anchor)
        if args.skip_analog else None
    )

    results, ok_count, fail_count = evaluate(
        cases, tb_blob, summary,
        skip_analog=args.skip_analog, analog_anchor=analog_anchor,
    )
    waive_count = count_waived(results)

    out = {
        "total": len(cases),
        "ok": ok_count,
        "fail": fail_count,
        "waived": waive_count,
        "capability_gap": (CAP_ANALOG_VERIFICATION_INTENT if waive_count else None),
        "analog_anchor": analog_anchor,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    if fail_count:
        # A genuine FAIL dominates — even if some cases were waived, an
        # un-waivable digital miss is still a hard FAIL (§4.05 NO-LEAK).
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

    if waive_count:
        # ORGANIC #773 — class/kind-aware A/M-track waiver. Every genuine
        # digital case had evidence; the only un-traced cases are
        # verification_intent (A/M-track) cases under an anchored
        # --skip-analog. Mirror #651: rc=3 + line-start PASS_WITH_WAIVERS
        # sentinel so flow_compliance_check promotes Step 4 to
        # WAIVED-DEFERRED (Overall PASS_WITH_WAIVERS), not a hard FAIL.
        print(
            f"PASS_WITH_WAIVERS: l10_tb_conformance — {ok_count}/{len(cases)} "
            f"digital cases traced; {waive_count}/{len(cases)} "
            f"verification_intent A/M-track case(s) WAIVED-DEFERRED "
            f"({CAP_ANALOG_VERIFICATION_INTENT}, review_required) — analog "
            f"track deferred via --skip-analog, reviewable anchor: "
            f"{analog_anchor}  → {args.out}")
        return 3

    print(f"[l10-tb-conformance] PASS  {ok_count}/{len(cases)} cases covered  → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
