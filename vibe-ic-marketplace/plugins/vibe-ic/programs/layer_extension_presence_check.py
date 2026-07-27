#!/usr/bin/env python3
"""layer_extension_presence_check.py — v0.50 plugin gate

Phase 1 (doc-extraction) extended layers (v0.50 adds L10/L11/L12 beyond the legacy L1-L23).
Verifies extension layers are present + non-empty when class template
declares spec_floor entries for them.

Motivation: v0.50-pre HIGH <benchmark> pilot showed L1-L23 schema was too narrow
to hold every vendor-doc fact, so agents silently dropped:
  - full CMD→RSP test-vector matrix (fits neither L3 nor L8)
  - FPGA calibration tables (20230103-3 windows — neither L8 nor L8R had
    a slot)
  - multi-packet behavioural sequences (Engineer Mode unlock, CC_Reset
    700ms, TestMode HV entry — neither L3 nor L6 had a slot)
This resulted in RTL that passed every structural check yet failed the
<half-duplex-tester> real-hardware test because the dropped facts were load-bearing.

New layers:
  - L10_TEST_CASES.json         (cmd→rsp vectors + error paths)
  - L11_CALIBRATION.json        (platform-specific tuning tables)
  - L12_BEHAVIORAL_SEQUENCES.json (multi-step protocols)

Usage:
    python3 layer_extension_presence_check.py <generated_docs_dir>
        [--class-path <cable-side-id-ic|...>]
        [--class-kb <path>]
        [--json <out>]
        [--strict]

Exit codes:
    0 — all required extensions present + meet floors
    1 — one or more below floor
    2 — input error
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

import _spec_floor_keys as _sfk   # noqa: E402  (re #495 Stage 0)
import _class_template_resolve as _ctr   # noqa: E402  (re #495 Stage 3)

try:
    import yaml
except ImportError:
    yaml = None


def _load_yaml(path: Path):
    if yaml is None:
        raise RuntimeError("PyYAML required; pip install pyyaml")
    with path.open() as f:
        return yaml.safe_load(f)


def load_layer(docs_dir: Path, layer: str) -> dict | None:
    for f in docs_dir.glob(f"{layer}*.json"):
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return None


def count_l10_test_cases(l10: dict) -> tuple[int, int]:
    """Return (total, cmd_response_count)."""
    if not l10:
        return 0, 0
    cases = l10.get("test_cases") or []
    if not isinstance(cases, list):
        return 0, 0
    cmd_resp = [c for c in cases if isinstance(c, dict) and c.get("category") == "cmd_response"]
    return len(cases), len(cmd_resp)


def count_l11_tables(l11: dict) -> int:
    """Count L11 calibration tables.

    re #495 Stage 0 — the incumbent read was ``L11["tables"]``, a key that
    occurs in 0 of the 201 tracked doc-sets: the L11 emitter writes
    ``calibration_tables`` (the ``tables`` spelling belongs to L15, a
    different layer). ``tables`` is kept first so any doc that does carry it
    reads exactly as before."""
    if not l11:
        return 0
    _key, t = _sfk.first_nonempty(l11, _sfk.L11_CALIBRATION_TABLE_KEYS)
    if isinstance(t, (dict, list)):
        return len(t)
    return 0


def count_l12_sequences(l12: dict) -> tuple[int, list, list]:
    """Count L12 behavioural sequences, and collect their ids / categories.

    re #495 Stage 0 — the incumbent read was ``L12["sequences"]`` (written by
    a handful of protocol synths, 11/201); the mainline L12 emitter writes
    ``behavioral_sequences`` (22/201 populated), which was unread. ``kinds``
    is restricted to ``list`` so a dict-shaped ``sequences`` — which this
    counter cannot consume and returned 0 for — no longer shadows a
    list-shaped ``behavioral_sequences``."""
    if not l12:
        return 0, [], []
    _key, seqs = _sfk.first_nonempty(l12, _sfk.L12_SEQUENCE_KEYS, kinds=(list,))
    if not isinstance(seqs, list):
        return 0, [], []
    ids = []
    cats = []
    for s in seqs:
        if isinstance(s, dict):
            if "id" in s:       ids.append(str(s["id"]))
            if "category" in s: cats.append(str(s["category"]))
    return len(seqs), ids, cats


def load_class_template(class_path: str, class_kb: Path) -> dict:
    tdir = class_kb / "templates"
    if not tdir.exists():
        return None
    # re #495 Stage 3 — own template, else the nearest templated ANCESTOR in
    # the class tree, else the vacuous `any-ic`. The incumbent chain skipped
    # step 2 entirely, so every one of the 20 template-less nodes silently
    # dropped to a NO-floor template even when the tree named an ancestor that
    # has one (`hash-function` -> `crypto-engine`, `spi-peripheral` ->
    # `protocol-ic`). `any-ic` remains the terminal fallback so a class the
    # tree does not contain still cannot pick up a protocol-specific floor.
    r = _ctr.resolve(class_path, class_kb, neutral_chain=("any-ic",))
    return r["template"]


def check(docs_dir: Path, class_kb: Path, class_path: str) -> dict:
    tpl = load_class_template(class_path, class_kb)
    if tpl is None:
        # No template found — silent-skip with PASS (no floor to enforce).
        return {"pass": True, "verdict": "SKIP",
                "reason": f"no class template for '{class_path}' — "
                          f"gate silent-skips on generic / unregistered classes",
                "findings": [], "measured": {}}
    floor = (tpl or {}).get("spec_floor") or {}
    findings = []
    measured = {}

    # ---- L10 ----
    l10 = load_layer(docs_dir, "L10")
    n_all, n_cmd = count_l10_test_cases(l10)
    measured["L10_test_cases_total"]     = n_all
    measured["L10_cmd_response_count"]   = n_cmd
    if floor.get("L10_test_cases_min") is not None and n_all < floor["L10_test_cases_min"]:
        findings.append({
            "severity": "FAIL",
            "rule": "L10_test_cases_min",
            "floor": floor["L10_test_cases_min"], "actual": n_all,
            "message": f"L10_TEST_CASES.json has {n_all} cases, floor {floor['L10_test_cases_min']}",
        })
    if floor.get("L10_cmd_response_min") is not None and n_cmd < floor["L10_cmd_response_min"]:
        findings.append({
            "severity": "FAIL",
            "rule": "L10_cmd_response_min",
            "floor": floor["L10_cmd_response_min"], "actual": n_cmd,
            "message": f"L10 cmd_response cases {n_cmd} below floor {floor['L10_cmd_response_min']}",
        })

    # ---- L11 ----
    l11 = load_layer(docs_dir, "L11")
    n_tables = count_l11_tables(l11)
    measured["L11_calibration_tables"] = n_tables
    if floor.get("L11_calibration_tables_min") is not None and n_tables < floor["L11_calibration_tables_min"]:
        findings.append({
            "severity": "FAIL",
            "rule": "L11_calibration_tables_min",
            "floor": floor["L11_calibration_tables_min"], "actual": n_tables,
            "message": f"L11_CALIBRATION.json has {n_tables} tables, floor {floor['L11_calibration_tables_min']}",
        })

    # ---- L12 ----
    l12 = load_layer(docs_dir, "L12")
    n_seq, seq_ids, seq_cats = count_l12_sequences(l12)
    measured["L12_sequences"] = n_seq
    measured["L12_sequence_ids"] = seq_ids
    measured["L12_sequence_categories"] = seq_cats
    if floor.get("L12_sequences_min") is not None and n_seq < floor["L12_sequences_min"]:
        findings.append({
            "severity": "FAIL",
            "rule": "L12_sequences_min",
            "floor": floor["L12_sequences_min"], "actual": n_seq,
            "message": f"L12_BEHAVIORAL_SEQUENCES.json has {n_seq} sequences, floor {floor['L12_sequences_min']}",
        })
    # Generic check: required CATEGORIES (not vendor-specific ids)
    req_cats = floor.get("L12_required_sequence_categories") or []
    missing_cat = [r for r in req_cats if r not in seq_cats]
    if missing_cat:
        findings.append({
            "severity": "FAIL",
            "rule": "L12_required_sequence_categories",
            "floor": req_cats, "actual": seq_cats,
            "message": f"L12 missing required sequence categories: {missing_cat}",
        })
    # Legacy: required ids (kept for back-compat; not vendor-specific in new templates)
    req_ids = floor.get("L12_required_sequence_ids") or []
    missing_seq = [r for r in req_ids if r not in seq_ids]
    if missing_seq:
        findings.append({
            "severity": "FAIL",
            "rule": "L12_required_sequence_ids",
            "floor": req_ids, "actual": seq_ids,
            "message": f"L12 missing required sequences: {missing_seq}",
        })

    return {
        "class_path": class_path,
        "measured": measured,
        "findings": findings,
        "pass": len(findings) == 0,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n",1)[0])
    ap.add_argument("docs_dir")
    ap.add_argument("--class-path", default=None,
                    help="Override class. When omitted, read L1_DATASHEET.json's "
                         "class_path field; final fallback 'any-ic'.")
    ap.add_argument("--class-kb", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    docs = Path(args.docs_dir)
    if not docs.exists():
        print(f"ERROR: docs_dir {docs} not found", file=sys.stderr)
        return 2

    if args.class_kb:
        class_kb = Path(args.class_kb)
    else:
        here = Path(__file__).resolve().parent
        class_kb = here.parent / "agents" / "class_kb"

    # Resolve class_path from L1 if not explicitly given
    class_path = args.class_path
    if not class_path:
        l1 = docs / "L1_DATASHEET.json"
        if l1.exists():
            try:
                text = l1.read_text()
                import re as _re
                # lenient: tolerate 0xNN literals
                text_fixed = _re.sub(
                    r'(?P<p>[:\[\,\s])0x([0-9a-fA-F]+)',
                    lambda m: m.group("p") + str(int(m.group(2), 16)), text)
                l1_data = json.loads(text_fixed)
                cp = l1_data.get("class_path", "")
                if isinstance(cp, str) and cp.strip():
                    # Extract leaf class name from "any-ic > digital-ic > crypto-engine"
                    class_path = cp.split(">")[-1].strip().lower()
            except Exception:
                pass
        if not class_path:
            class_path = "any-ic"

    result = check(docs, class_kb, class_path)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
