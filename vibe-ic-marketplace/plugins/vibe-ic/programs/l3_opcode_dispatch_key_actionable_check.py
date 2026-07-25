#!/usr/bin/env python3
"""l3_opcode_dispatch_key_actionable_check.py — L3 consumer-contract gate.

VERDICT SEMANTICS: **BLOCKS** (exit 1 on FAIL).
------------------------------------------------------------------
Why blocking and not advisory: the consumer keys its dispatcher and
its byte-exact oracle BY HEX, and drops or overwrites entries silently.
In `programs/design_one_shot_runner.py` the table is built as

    for op in (l3.get("opcodes") or []):
        h = op.get("hex")
        if isinstance(h, str) and h.startswith("0x") and h.upper() != "0X__TODO__":
            opcodes_hex.append(h)
    ...
    l3_by_hex[h.lower()] = op

so an opcode whose hex is null/prose/`__TODO__` is NEVER appended — no
case arm is emitted for it and the DUT is silent on that command — and
two opcodes sharing a hex silently OVERWRITE each other in
`l3_by_hex`, so the loser's `response_payload_template` never reaches
`oracle_vector_gen` / `cmd_protocol_byte_exact_check`. Neither event
raises anything. An advisory verdict would reproduce the documented
failure where a layer gate said FAIL and the flow continued anyway.
So: FAIL => rc 1.

The principle it embodies
------------------------------------------------------------------
A layer is complete when the requirement is present IN THE LAYER THAT
CONSUMES IT, IN AN ACTIONABLE FORM — not when a token appears
somewhere.

This is the same defect as the one `l3_opcode_name_coverage_check`
closed, one field over. That gate was written because
`len(L3.opcodes) == 18` with 9 `OPCODE_NAME_UNKNOWN` names made the
dispatcher emit a default-only table and the DUT went silent; it FAILs
at placeholder-NAME ratio > 0. But the dispatcher does not key on
`name` — it keys on `hex`. An opcode with a perfect real name and
`hex: null` passes name coverage and is then dropped by the consumer
exactly as a placeholder-named one was.

Not a duplicate of the neighbouring gates (grepped before writing):
  * `l3_opcode_name_coverage_check` — NAME placeholders only; never
    reads `hex` except to print it in the failure list.
  * `opcode_field_width_consistency_check` — bounds a hex against a
    declared field width and reconciles L3<->L15 mnemonics; it states
    "only hex-bearing, name-matched rows are compared", i.e. a
    hex-less row is silently skipped, which is precisely the hole here.
  * `l3_opcode_response_template_check`, `..._argument_constraints_check`,
    `..._pre_wake_allowed_typed_check` — typed sub-field depth on other
    fields, and unreachable from the phase1 loop.
None of them fails on a missing hex, and none checks hex uniqueness.

Three limbs, all derived from L3 itself + the consumer's keying rule
------------------------------------------------------------------
  1. DISPATCH KEY PRESENT — every opcode entry must carry a `hex`
     that parses to a non-negative integer. `__TODO__`, null, prose
     and non-hex strings are unactionable: the consumer's
     `startswith("0x")` filter drops them.
  2. DISPATCH KEY UNIQUE — normalised hex values must be distinct.
     A collision makes `l3_by_hex[h] = op` overwrite, so at most one
     of the colliding entries survives into the oracle.
  3. ORACLE LOOKUP KEY UNIQUE — mnemonics must be distinct, since the
     L3<->L15 reconciliation in `opcode_field_width_consistency_check`
     indexes `out[name.strip().lower()] = ...` and a repeated mnemonic
     silently resolves to whichever row came last.

Chip-AGNOSTIC: no design name, PDK name, vendor part number, opcode
value or mnemonic literal appears in this file. Every value examined
comes from the design's own L3 document.

Verdicts
------------------------------------------------------------------
  PASS         every opcode carries a unique, parseable dispatch key
  VACUOUS_PASS L3.opcodes empty/absent (non-protocol IP — the
               `no_opcodes_in_input: true` case)
  FAIL         any unparseable hex, hex collision, or mnemonic collision
  rc 2         L3 absent / unparseable / project dir absent

Waiver: `waivers.json` key `l3_opcode_dispatch_key_intentional`
(>= 40 chars) downgrades FAIL to PASS_WITH_WAIVER.

Usage:
    python3 l3_opcode_dispatch_key_actionable_check.py <project_dir> [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402

GATE = "l3_opcode_dispatch_key_actionable_check"
WAIVER_KEY = "l3_opcode_dispatch_key_intentional"
WAIVER_MIN_LEN = 40

# The consumer accepts only `0x...`; accept the same plus a bare hex or
# decimal literal so the gate reports "unparseable" only when the value
# genuinely yields no integer.
_HEX_0X = re.compile(r"^\s*0[xX][0-9a-fA-F]+\s*$")
_HEX_BARE = re.compile(r"^\s*[0-9a-fA-F]+[hH]?\s*$")
# Sentinels the emitters use for "not extracted".
_SENTINELS = frozenset({"__TODO__", "0X__TODO__", "TODO", "TBD", "TBA",
                        "UNKNOWN", "NONE", "N/A", "",
                        "<HALLUCINATION_SCRUBBED>"})
# Fields that may carry the dispatch key, in the consumer's order.
_HEX_KEYS = ("hex", "opcode_hex", "opcode", "code", "value")


def _hex_value(entry: Dict[str, Any]) -> Optional[int]:
    """Integer the dispatcher would compare against, or None."""
    for key in _HEX_KEYS:
        if key not in entry:
            continue
        raw = entry[key]
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            return raw
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if s.upper() in _SENTINELS:
            continue
        if _HEX_0X.match(s):
            return int(s, 16)
        if _HEX_BARE.match(s):
            try:
                return int(s.rstrip("hH"), 16)
            except ValueError:
                continue
    return None


def _raw_key(entry: Dict[str, Any]) -> Any:
    for key in _HEX_KEYS:
        if key in entry:
            return entry[key]
    return None


def _mnemonic(entry: Dict[str, Any]) -> Optional[str]:
    n = entry.get("name")
    if isinstance(n, str) and n.strip():
        return n.strip().lower()
    return None


def _waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.is_file():
        return False
    try:
        v = json.loads(p.read_text()).get(WAIVER_KEY, "")
    except Exception:
        return False
    return isinstance(v, str) and len(v.strip()) >= WAIVER_MIN_LEN


def evaluate(project: Path) -> Dict[str, Any]:
    l3_path = _pl.generated_docs_dir(project) / "L3_CMD_PROTOCOL.json"
    if not l3_path.is_file():
        return {"gate": GATE, "verdict": "SILENT_SKIP", "rc": 2,
                "reason": f"{l3_path.name} not found (phase1 hasn't run?)"}
    try:
        l3 = json.loads(l3_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"gate": GATE, "verdict": "ERROR", "rc": 2,
                "reason": f"cannot parse {l3_path.name}: {exc}"}

    opcodes = l3.get("opcodes")
    if not isinstance(opcodes, list) or not opcodes:
        return {"gate": GATE, "verdict": "VACUOUS_PASS", "rc": 0,
                "reason": "L3.opcodes empty/absent — no command protocol in "
                          "input (structurally correct for non-protocol IPs).",
                "total": 0, "violations": []}

    violations: List[Dict[str, Any]] = []
    by_hex: Dict[int, List[str]] = defaultdict(list)
    by_name: Dict[str, List[str]] = defaultdict(list)

    for idx, entry in enumerate(opcodes):
        if not isinstance(entry, dict):
            violations.append({
                "kind": "opcode_entry_not_an_object", "index": idx,
                "detail": f"L3.opcodes[{idx}] is {type(entry).__name__}, not "
                          f"an object — the dispatcher loop skips it."})
            continue
        label = _mnemonic(entry) or f"opcodes[{idx}]"
        val = _hex_value(entry)
        if val is None:
            violations.append({
                "kind": "dispatch_key_unparseable", "index": idx,
                "opcode": entry.get("name"), "hex": _raw_key(entry),
                "detail": (
                    f"opcode `{label}` carries hex={_raw_key(entry)!r}, which "
                    f"yields no integer. design_one_shot_runner only appends "
                    f"entries whose hex is a `0x..` string, so this opcode "
                    f"gets NO dispatcher case arm and the DUT stays silent "
                    f"on it."),
            })
        else:
            by_hex[val].append(label)
        mn = _mnemonic(entry)
        if mn:
            by_name[mn].append(f"opcodes[{idx}]")

    for val, labels in sorted(by_hex.items()):
        if len(labels) > 1:
            violations.append({
                "kind": "dispatch_key_collision", "hex": hex(val),
                "opcodes": labels,
                "detail": (
                    f"{len(labels)} opcodes share dispatch key {hex(val)} "
                    f"({', '.join(labels)}). The consumer builds "
                    f"`l3_by_hex[h] = op`, so all but the last are "
                    f"overwritten and their response templates never reach "
                    f"the byte-exact oracle."),
            })

    for mn, where in sorted(by_name.items()):
        if len(where) > 1:
            violations.append({
                "kind": "mnemonic_collision", "opcode": mn,
                "entries": where,
                "detail": (
                    f"mnemonic `{mn}` appears {len(where)} times "
                    f"({', '.join(where)}). The L3<->L15 reconciliation "
                    f"indexes by lowercased mnemonic, so a repeated name "
                    f"silently resolves to whichever row came last."),
            })

    report: Dict[str, Any] = {
        "gate": GATE,
        "total": len(opcodes),
        "distinct_dispatch_keys": len(by_hex),
        "violations": violations,
    }
    if not violations:
        report.update(verdict="PASS", rc=0, reason=(
            f"all {len(opcodes)} opcode(s) carry a unique, parseable "
            f"dispatch key and a unique mnemonic."))
        return report
    if _waived(project):
        report.update(verdict="PASS_WITH_WAIVER", rc=0, reason=(
            f"{len(violations)} dispatch-key violation(s) waived via "
            f"waivers.json:{WAIVER_KEY}."))
        return report
    report.update(verdict="FAIL", rc=1, reason=(
        f"{len(violations)} dispatch-key violation(s) across "
        f"{len(opcodes)} opcode(s) — the emitted dispatcher would silently "
        f"drop or overwrite command(s)."))
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=GATE, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = evaluate(project)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    rc = int(report.get("rc", 2))
    line = f"{report['verdict']}: {report['reason']}"
    if rc == 1:
        print(f"FAIL: {report['reason']}", file=sys.stderr)
        for v in report.get("violations", [])[:8]:
            print(f"  - {v['detail']}", file=sys.stderr)
    elif rc == 2:
        print(line, file=sys.stderr)
    else:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
