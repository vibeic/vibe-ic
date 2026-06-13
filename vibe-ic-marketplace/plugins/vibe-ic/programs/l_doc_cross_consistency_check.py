#!/usr/bin/env python3
"""l_doc_cross_consistency_check.py — D3 program-first capture of the
``phase1-output-verify`` skill's "Cross-doc consistency" checklist (item 3).

Background
==========
``skills/phase1-output-verify/SKILL.md`` asked the AI to perform, *by eye*,
a set of inter-document set-membership relations over the typed L*.json
layer documents emitted by ``phase1_one_shot_runner``. Two of those
relations are purely structural (set-membership over already-typed JSON
fields) and need no judgment — they are extracted here so the skill can
delegate instead of narrate.

Implemented relations (chip-AGNOSTIC, declarative)
==================================================
R_pin_table_subset_ports
    Every L1 ``pin_table[]`` pin name must appear in the L9 integration
    spec's port list (``ports`` / ``top_ports`` / ``top_level_ports`` /
    ``dtop_top_level.ports`` — first populated wins), modulo aliases
    declared on the L1 entry (``aliases`` / ``rtl_name`` / ``board_name``).
    The flow's chip-top wrapper is generated from L9, so an L1 pin that
    never lands in L9 silently disappears from the design.

R_otp_bytes_subset_layout
    Every address referenced by an L11 ``otp_bytes[]`` entry
    (``address`` / ``addr`` / ``offset`` / ``byte_offset``) must be a
    declared field/offset in the L4 ``otp_layout`` (its ``fields[]`` or
    ``read_map[]``/``write_map[]`` offsets, plus any field with an
    explicit ``offset``/``address``). An OTP image byte that targets an
    address the regmap never declares is an inconsistent burn map.

Escape valves (the established Phase-1 ``no_<field>_in_input`` convention)
=========================================================================
A relation is reported **N/A** (not FAIL) — never silently PASSed — when
the *target* side is legitimately empty AND the corresponding extractor
escape-valve flag is set, e.g. L9 ``ports`` empty with
``no_top_module_in_input``/``no_integration_in_input``, or L4
``otp_layout`` empty with ``no_otp_in_input``/``no_otp_layout_in_input``.
This mirrors how ``phase1_structured_field_substance_check.py`` honors the
same flags so the gate does not false-fire on CPU / analog / no-OTP ICs.

What is intentionally NOT here (kept as AI judgment in the skill)
================================================================
The skill's other two listed relations require structure the typed
corpus does not actually carry, so encoding them as a program would mean
inventing a threshold/field the spec never gives (forbidden):
  * "L3.opcodes hex set ⊂ L9.fsm_states transitions" — L3 opcodes are
    instruction encoding patterns, not bus command hex bytes, and L9
    carries no ``transitions`` sub-structure.
  * "L3.verdict_byte_offset == rig_topology.fingerprint_byte_index" —
    ``rig_topology.fingerprint_byte_index`` does not exist anywhere in
    the typed L docs.
Those stay in the skill prose as a judgment residual.

Usage
=====
    python3 l_doc_cross_consistency_check.py <project_dir|generated_docs_dir>
    python3 l_doc_cross_consistency_check.py <dir> --json [out.json]

Exit codes
==========
    0  PASS / N/A-only / VACUOUS_PASS (generated_docs absent)
    1  FAIL (a real cross-doc subset violation)
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# L-doc discovery + lenient load (corpus uses raw 0x.. hex literals)
# ---------------------------------------------------------------------------
def _lenient_load(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    text = path.read_text(errors="ignore")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(
                r'(?P<pfx>[:\[\,\s])0x([0-9a-fA-F]+)',
                lambda m: m.group("pfx") + str(int(m.group(2), 16)),
                text,
            ))
        except Exception:
            return None


def _find_gen_dir(target: Path) -> Optional[Path]:
    """Resolve the generated_docs directory from a project dir, a
    phase1 dir, or the generated_docs dir itself."""
    if (target / "L1_DATASHEET.json").is_file() or \
       any(target.glob("L1_*.json")):
        return target
    for cand in (
        target / "phase1" / "generated_docs",
        target / "generated_docs",
    ):
        if cand.is_dir():
            return cand
    return None


def _load_layer(gen_dir: Path, prefix: str) -> Optional[Dict[str, Any]]:
    """Load the first L<prefix>_*.json (or L<prefix>.json) under gen_dir."""
    exact = gen_dir / f"{prefix}.json"
    if exact.is_file():
        return _lenient_load(exact)
    for cand in sorted(gen_dir.glob(f"{prefix}_*.json")):
        obj = _lenient_load(cand)
        if isinstance(obj, dict):
            return obj
    return None


def _flag_set(doc: Optional[Dict[str, Any]], *flag_keys: str) -> bool:
    if not isinstance(doc, dict):
        return False
    return any(doc.get(k) is True for k in flag_keys)


# ---------------------------------------------------------------------------
# Field accessors
# ---------------------------------------------------------------------------
def _norm(s: Any) -> str:
    return str(s).strip().lower()


def _l1_pin_aliases(entry: Dict[str, Any]) -> List[str]:
    """All names an L1 pin can legitimately appear under in L9."""
    out: List[str] = []
    for k in ("name", "rtl_name", "board_name"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            out.append(_norm(v))
    al = entry.get("aliases")
    if isinstance(al, list):
        out.extend(_norm(a) for a in al if isinstance(a, str) and a.strip())
    return out


def _l1_pin_primary(entry: Dict[str, Any]) -> str:
    for k in ("name", "rtl_name", "board_name"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return _norm(v)
    return ""


def _l9_port_names(l9: Dict[str, Any]) -> Tuple[List[str], str]:
    """Return (port_names, source_key). First populated source wins."""
    # direct list-valued keys
    for key in ("ports", "top_ports", "top_level_ports", "top_module_pins"):
        v = l9.get(key)
        if isinstance(v, list) and v:
            names = [_norm(p.get("name") or p.get("rtl_name") or p.get("signal"))
                     for p in v if isinstance(p, dict)]
            names = [n for n in names if n]
            if names:
                return names, key
    # nested dtop_top_level.ports (may be list or grouped dict)
    dtop = l9.get("dtop_top_level")
    if isinstance(dtop, dict):
        v = dtop.get("ports")
        flat: List[Dict[str, Any]] = []
        if isinstance(v, list):
            flat = [p for p in v if isinstance(p, dict)]
        elif isinstance(v, dict):
            for grp in v.values():
                if isinstance(grp, list):
                    flat.extend(p for p in grp if isinstance(p, dict))
                elif isinstance(grp, dict):
                    flat.append(grp)
        names = [_norm(p.get("name") or p.get("rtl_name") or p.get("signal"))
                 for p in flat]
        names = [n for n in names if n]
        if names:
            return names, "dtop_top_level.ports"
    return [], ""


def _addr_of(entry: Dict[str, Any]) -> Optional[int]:
    """Coerce an OTP-byte / OTP-field address to an int, accepting
    int, '0x..' hex, or decimal-string forms."""
    for k in ("address", "addr", "offset", "byte_offset"):
        if k not in entry:
            continue
        v = entry[k]
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            s = v.strip()
            try:
                return int(s, 16) if s.lower().startswith("0x") else int(s, 10)
            except ValueError:
                continue
    return None


def _l11_otp_addrs(l11: Dict[str, Any]) -> List[int]:
    ob = l11.get("otp_bytes")
    out: List[int] = []
    if isinstance(ob, list):
        for e in ob:
            if isinstance(e, dict):
                a = _addr_of(e)
                if a is not None:
                    out.append(a)
    return out


def _l4_otp_declared_addrs(l4: Dict[str, Any]) -> Tuple[set, bool]:
    """Return (declared_addr_set, layout_present). An OTP layout is
    'present' if otp_layout exists and carries any fields/maps."""
    ol = l4.get("otp_layout")
    if not isinstance(ol, dict):
        return set(), False
    addrs: set = set()
    present = False
    for list_key in ("fields", "read_map", "write_map"):
        seq = ol.get(list_key)
        if isinstance(seq, list) and seq:
            present = True
            for e in seq:
                if isinstance(e, dict):
                    a = _addr_of(e)
                    if a is not None:
                        addrs.add(a)
    return addrs, present


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------
@dataclass
class RelationFinding:
    relation: str
    verdict: str          # PASS | FAIL | N/A
    detail: str = ""
    violations: Optional[List[Any]] = None


def _rel_pin_table_subset_ports(l1, l9) -> RelationFinding:
    rid = "R_pin_table_subset_ports"
    if not isinstance(l1, dict) or not isinstance(l9, dict):
        return RelationFinding(rid, "N/A", "L1 or L9 absent")
    pins = l1.get("pin_table")
    if not isinstance(pins, list) or not pins:
        if _flag_set(l1, "no_pin_table_in_input", "no_pinout_in_input"):
            return RelationFinding(rid, "N/A", "L1 pin_table legitimately empty (no_pin_table_in_input)")
        return RelationFinding(rid, "N/A", "L1 pin_table empty (no pins to relate)")
    port_names, src = _l9_port_names(l9)
    if not port_names:
        if _flag_set(l9, "no_top_module_in_input", "no_integration_in_input",
                     "no_ports_in_input"):
            return RelationFinding(rid, "N/A",
                                   "L9 port list legitimately empty (no_top_module_in_input)")
        # Target side empty WITHOUT an escape flag while L1 has pins =>
        # honest FAIL: the pins cannot land anywhere.
        return RelationFinding(rid, "FAIL",
                               f"L1 declares {len([p for p in pins if isinstance(p, dict)])} "
                               f"pins but L9 has no port list and no escape flag",
                               violations=[_l1_pin_primary(p) for p in pins
                                           if isinstance(p, dict)][:20])
    port_set = set(port_names)
    missing: List[str] = []
    for p in pins:
        if not isinstance(p, dict):
            continue
        aliases = _l1_pin_aliases(p)
        if not aliases:
            continue
        if not any(a in port_set for a in aliases):
            missing.append(_l1_pin_primary(p) or aliases[0])
    if missing:
        return RelationFinding(rid, "FAIL",
                               f"{len(missing)} L1 pin(s) absent from L9 ports[{src}]",
                               violations=sorted(set(missing))[:20])
    return RelationFinding(rid, "PASS",
                           f"all {len(pins)} L1 pins present in L9 ports[{src}]")


def _rel_otp_bytes_subset_layout(l11, l4) -> RelationFinding:
    rid = "R_otp_bytes_subset_layout"
    if not isinstance(l11, dict) or not isinstance(l4, dict):
        return RelationFinding(rid, "N/A", "L11 or L4 absent")
    otp_addrs = _l11_otp_addrs(l11)
    if not otp_addrs:
        if _flag_set(l11, "no_otp_in_input", "no_otp_bytes_in_input",
                     "no_calibration_in_input"):
            return RelationFinding(rid, "N/A",
                                   "L11 otp_bytes legitimately empty (no_otp_in_input)")
        return RelationFinding(rid, "N/A", "L11 otp_bytes empty (no addresses to relate)")
    declared, layout_present = _l4_otp_declared_addrs(l4)
    if not layout_present:
        if _flag_set(l4, "no_otp_in_input", "no_otp_layout_in_input"):
            return RelationFinding(rid, "N/A",
                                   "L4 otp_layout legitimately empty (no_otp_layout_in_input)")
        return RelationFinding(rid, "FAIL",
                               f"L11 references {len(otp_addrs)} OTP byte address(es) "
                               f"but L4 otp_layout declares none and has no escape flag",
                               violations=sorted(set(otp_addrs))[:20])
    undeclared = sorted({a for a in otp_addrs if a not in declared})
    if undeclared:
        return RelationFinding(rid, "FAIL",
                               f"{len(undeclared)} L11 OTP address(es) not declared in L4 otp_layout",
                               violations=undeclared[:20])
    return RelationFinding(rid, "PASS",
                           f"all {len(set(otp_addrs))} L11 OTP addresses declared in L4 otp_layout")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def check(target: Path) -> Tuple[str, List[RelationFinding], Dict[str, Any]]:
    gen_dir = _find_gen_dir(target)
    if gen_dir is None:
        return "VACUOUS_PASS", [], {"generated_docs": None}
    l1 = _load_layer(gen_dir, "L1")
    l4 = _load_layer(gen_dir, "L4")
    l9 = _load_layer(gen_dir, "L9")
    l11 = _load_layer(gen_dir, "L11")
    findings = [
        _rel_pin_table_subset_ports(l1, l9),
        _rel_otp_bytes_subset_layout(l11, l4),
    ]
    fails = [f for f in findings if f.verdict == "FAIL"]
    verdict = "FAIL" if fails else "PASS"
    summary = {
        "generated_docs": str(gen_dir),
        "relations_checked": len(findings),
        "pass": sum(1 for f in findings if f.verdict == "PASS"),
        "fail": len(fails),
        "na": sum(1 for f in findings if f.verdict == "N/A"),
    }
    return verdict, findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Cross-doc structural consistency over phase1 L*.json.")
    ap.add_argument("target", help="project dir, phase1 dir, or generated_docs dir")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="emit JSON report (to path, or stdout if no path)")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    verdict, findings, summary = check(target)
    report = {
        "gate": "l_doc_cross_consistency_check",
        "verdict": verdict,
        "summary": summary,
        "findings": [asdict(f) for f in findings],
    }

    if args.json is not None:
        blob = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json == "-":
            print(blob)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(blob + "\n", encoding="utf-8")
            print(f"{verdict}: l_doc_cross_consistency_check (report -> {out})")
    else:
        print(f"{verdict}: l_doc_cross_consistency_check — "
              f"pass={summary.get('pass', 0)} fail={summary.get('fail', 0)} "
              f"na={summary.get('na', 0)}")
        for f in findings:
            line = f"  [{f.verdict}] {f.relation}"
            if f.detail:
                line += f" — {f.detail}"
            print(line)
            if f.violations:
                print(f"      violations: {f.violations}")

    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
