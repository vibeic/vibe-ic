#!/usr/bin/env python3
"""l11_otp_content_consumer_contract_check.py — L11 CONSUMER-CONTRACT gate.

BLOCKS (exit 1).  Rationale: every one of L11's consumers degrades
silently rather than erroring.  ``aid_class_rtl_gen`` emits an OTP
regfile from whatever field map it finds and emits nothing when it finds
none; ``otp_image_check`` opens L11 by exact filename and treats a miss
as "no sibling hint"; ``tx_bit_timing_units_check`` reads L11 for
``clk_hz`` and falls through when the read returns empty.  None of them
says "I could not read L11".  An advisory gate here would leave the same
hole the L21 power-intent defect fell through: a layer that looks
captured, is never actually consumed, and surfaces as an opaque failure
several steps downstream.

TWO HALVES, BOTH DERIVED FROM MACHINE-READABLE INPUTS
-----------------------------------------------------
HALF A — RESOLUTION.  A layer is only complete if the consumer can open
it.  The repo declares the L11 filename in two machine-readable places
that DISAGREE:

    tools/phase1_engine/schema.py  LAYER_FILE_NAMES["L11"]
    programs/l_doc_taxonomy.py     L_DOCS_V2 -> LDocSpec(code="L11").full_name

Half A reads BOTH declarations at run time (never a hardcoded string),
resolves each against the run's ``generated_docs/`` directory, and fails
when a declared name does not resolve while a sibling ``L11_*.json``
does.  That state means: the layer WAS emitted, and every consumer that
opens it under the non-resolving declared name is doing a dead read that
returns None forever.  This is the generalised form of the motivating
defect — "the layer the consumer actually reads contained it 0 times" —
and it is detectable without knowing anything about the design.

HALF B — ACTIONABILITY.  When the resolved L11 declares an OTP image at
all (any of ``otp_present`` / ``otp_bytes`` / ``content_hex`` /
``otp_layout`` / ``depth``x``width_bits``), the consumers need it in a
form they can synthesise:

  B1. A byte-addressed field map: an array (or address-keyed object) of
      entries each carrying an address, a field name, and a width, so
      ``aid_class_rtl_gen`` can emit a regfile and
      ``otp_field_map_check`` can cross-check it.
  B2. The field map must SPAN the declared image: the highest addressed
      field must lie inside the image length derived from the doc's own
      ``otp_bytes`` / ``content_hex`` / ``depth``x``width_bits``.  A map
      that stops short leaves image bytes with no declared meaning, and
      a map that runs past the image describes storage that does not
      exist.  Both are derived purely from this document's own numbers.
  B3. Every declared lock bit must be synthesisable as write-path
      gating: a handle (name/bit/address) PLUS what it protects
      (affects/protects_range/locked_addresses/...) PLUS the value that
      arms it (trigger_value/arming_pattern/...).  A lock bit with only
      a name is a comment, not a gate.

Half B deliberately SKIPS when the design declares no OTP image — the
absence of OTP is a legitimate property of most designs, and demanding a
field map from them would be a false positive, not a finding.

CHIP-AGNOSTIC: no design name, PDK name, vendor part number, or pin /
signal literal appears in this file.  Every threshold is read out of the
document under test or out of the repo's own declaration modules.

Usage:
    python3 l11_otp_content_consumer_contract_check.py <project_dir> [--json OUT]

Exit codes:
    0 = PASS
    1 = FAIL (blocking)
    2 = SKIP / input missing

Honors waiver ``l11_otp_content_consumer_contract_intentional`` (>=40 chars).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

WAIVER_KEY = "l11_otp_content_consumer_contract_intentional"
WAIVER_MIN = 40

_LAYER = "L11"

_LOCK_ARRAY_KEYS = ("otp_lock_bits", "lock_bits", "otp_locks", "locks",
                    "lock_table", "write_lock_bits")
_LOCK_HANDLE_KEYS = ("name", "bit", "address", "addr", "id", "field")
_LOCK_AFFECTS_KEYS = ("affects", "protects_range", "locked_addresses",
                      "covers", "scope", "address_range",
                      "protected_addresses", "covered_addresses",
                      "protects", "locks_range")
_LOCK_TRIGGER_KEYS = ("trigger_value", "arming_pattern", "arming_value",
                      "lock_value", "set_value", "write_value",
                      "assert_value", "programmed_value")

_FIELDMAP_ARRAY_KEYS = ("field_map", "otp_field_map", "fields", "otp_fields",
                        "field_table", "otp_layout", "layout", "map")
_ADDR_KEYS = ("address", "addr", "byte_address", "offset", "byte_offset",
              "start_address", "start", "index")
_WIDTH_KEYS = ("width", "width_bits", "bits", "size_bits", "length_bits",
               "nbits", "bit_width")
_FIELDNAME_KEYS = ("name", "field", "field_name", "label", "id")

_OTP_DECLARED_KEYS = ("otp_present", "otp_bytes", "content_hex",
                      "otp_layout", "otp_image", "image_hex")

_HEXWORD_RE = re.compile(r"[0-9a-fA-F]")


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


def declared_layer_filenames(layer: str = _LAYER) -> Dict[str, str]:
    """Read the repo's OWN machine-readable declarations of this layer's file.

    Returns {declaration_site: filename}. Never hardcodes a filename — a
    site that cannot be imported is simply omitted, which keeps the gate
    runnable from a partial checkout.
    """
    out: Dict[str, str] = {}
    here = Path(__file__).resolve().parent
    root = here.parent  # plugins/vibe-ic
    for p in (str(here), str(root), str(root / "tools")):
        if p not in sys.path:
            sys.path.insert(0, p)

    # Site 1 — tools/phase1_engine/schema.py
    try:
        from phase1_engine import schema as _schema  # type: ignore
        v = getattr(_schema, "LAYER_FILE_NAMES", {}).get(layer)
        if isinstance(v, str) and v:
            out["phase1_engine.schema.LAYER_FILE_NAMES"] = v
    except Exception:
        pass

    # Site 2 — programs/l_doc_taxonomy.py
    try:
        import l_doc_taxonomy as _tax  # type: ignore
        for spec in getattr(_tax, "L_DOCS_V2", ()):  # noqa: WPS110
            if getattr(spec, "code", None) == layer:
                fn = getattr(spec, "full_name", "")
                if fn:
                    out["l_doc_taxonomy.L_DOCS_V2"] = (
                        fn if fn.endswith(".json") else fn + ".json")
                break
    except Exception:
        pass
    return out


def _int_of(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().replace("_", "")
        try:
            return int(s, 16) if s.lower().startswith("0x") else int(s)
        except ValueError:
            return None
    return None


def image_length_bytes(doc: dict) -> Optional[int]:
    """Derive the OTP image length from the DOCUMENT'S OWN numbers."""
    b = doc.get("otp_bytes")
    if isinstance(b, list) and b:
        return len(b)
    ch = doc.get("content_hex") or doc.get("image_hex")
    if isinstance(ch, str):
        digits = [c for c in ch if _HEXWORD_RE.fullmatch(c)]
        if len(digits) >= 2:
            return len(digits) // 2
    depth = _int_of(doc.get("depth"))
    width = _int_of(doc.get("width_bits"))
    if depth and width:
        return depth * ((width + 7) // 8)
    return None


def otp_is_declared(doc: dict) -> bool:
    for k in _OTP_DECLARED_KEYS:
        v = doc.get(k)
        if isinstance(v, bool) and v:
            return True
        if isinstance(v, (list, dict)) and v:
            return True
        if isinstance(v, str) and v.strip():
            return True
    return bool(_int_of(doc.get("depth")) and _int_of(doc.get("width_bits")))


def _collect_arrays(node, keys: Tuple[str, ...], out: List[dict],
                    depth: int = 0) -> None:
    """Collect dict entries from any array stored under one of `keys`."""
    if depth > 10:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).lower() in keys:
                if isinstance(v, list):
                    out.extend(x for x in v if isinstance(x, dict))
                elif isinstance(v, dict):
                    # address-keyed object form: {"0x00": {...}, ...}
                    for addr, entry in v.items():
                        if isinstance(entry, dict):
                            e = dict(entry)
                            e.setdefault("address", addr)
                            out.append(e)
            else:
                _collect_arrays(v, keys, out, depth + 1)
    elif isinstance(node, list):
        for it in node:
            _collect_arrays(it, keys, out, depth + 1)


def _get_any(d: dict, keys: Tuple[str, ...]):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
def audit(docs_dir: Path,
          declared: Optional[Dict[str, str]] = None) -> Dict:
    """Pure audit over a generated_docs directory. Returns a report dict."""
    if declared is None:
        declared = declared_layer_filenames()

    report: Dict = {
        "program": "l11_otp_content_consumer_contract_check",
        "version": "1.0.0",
        "docs_dir": str(docs_dir),
        "summary": {
            "declared_names": dict(declared),
            "siblings_present": [],
            "resolved_as": "",
            "otp_declared": False,
            "image_length_bytes": None,
            "field_map_entries": 0,
            "lock_bits": 0,
        },
        "findings": [],
    }

    if not docs_dir.is_dir():
        report["findings"].append({
            "severity": "INFO", "category": "NO_DOCS_DIR", "entity": "",
            "message": f"generated_docs directory absent: {docs_dir}",
        })
        return report

    siblings = sorted(p.name for p in docs_dir.glob(f"{_LAYER}_*.json"))
    report["summary"]["siblings_present"] = siblings
    if not siblings:
        report["findings"].append({
            "severity": "INFO", "category": "NO_L11", "entity": "",
            "message": f"no {_LAYER}_*.json emitted — nothing to check",
        })
        return report

    # --- HALF A: resolution ------------------------------------------------
    resolved: Optional[Path] = None
    for site, fname in sorted(declared.items()):
        cand = docs_dir / fname
        if cand.is_file():
            if resolved is None:
                resolved = cand
                report["summary"]["resolved_as"] = fname
        else:
            report["findings"].append({
                "severity": "ERROR", "category": "DEAD_CONSUMER_READ",
                "entity": site,
                "message": (
                    f"{site} declares {_LAYER} as {fname!r}, which does not "
                    f"exist in this run, while {siblings} WAS emitted. Every "
                    f"consumer that opens {_LAYER} under the declared name "
                    "gets None and silently no-ops — the requirement is "
                    "present, but not in the layer the consumer reads."),
            })
    if resolved is None:
        # No declared name resolved: fall back to the emitted sibling so
        # HALF B still runs and reports actionable content problems.
        resolved = docs_dir / siblings[0]
        report["summary"]["resolved_as"] = siblings[0]

    # --- HALF B: actionability --------------------------------------------
    try:
        doc = json.loads(resolved.read_text(errors="replace"))
    except Exception as exc:
        report["findings"].append({
            "severity": "ERROR", "category": "INVALID_JSON",
            "entity": resolved.name,
            "message": f"cannot parse {resolved.name}: {exc}",
        })
        return report
    if not isinstance(doc, dict):
        report["findings"].append({
            "severity": "ERROR", "category": "INVALID_JSON",
            "entity": resolved.name,
            "message": f"{resolved.name} is not a JSON object",
        })
        return report

    locks: List[dict] = []
    _collect_arrays(doc, _LOCK_ARRAY_KEYS, locks)
    report["summary"]["lock_bits"] = len(locks)

    declared_otp = otp_is_declared(doc)
    report["summary"]["otp_declared"] = declared_otp

    if declared_otp:
        n_bytes = image_length_bytes(doc)
        report["summary"]["image_length_bytes"] = n_bytes

        fields: List[dict] = []
        _collect_arrays(doc, _FIELDMAP_ARRAY_KEYS, fields)
        # Only entries that actually look like a field map row.
        rows = [f for f in fields
                if _get_any(f, _ADDR_KEYS) is not None
                or _get_any(f, _FIELDNAME_KEYS) is not None]
        report["summary"]["field_map_entries"] = len(rows)

        if not rows:
            report["findings"].append({
                "severity": "ERROR", "category": "NO_FIELD_MAP",
                "entity": resolved.name,
                "message": (
                    "the document declares an OTP image but carries no "
                    "byte-addressed field map (address -> field -> width -> "
                    "default). aid_class_rtl_gen has nothing to emit a "
                    "regfile from and otp_field_map_check has nothing to "
                    "cross-check, so the image ships as opaque bytes."),
            })
        else:
            max_addr = -1
            for i, row in enumerate(rows):
                lbl = str(_get_any(row, _FIELDNAME_KEYS) or f"field[{i}]")
                a = _int_of(_get_any(row, _ADDR_KEYS))
                w = _int_of(_get_any(row, _WIDTH_KEYS))
                miss = []
                if a is None:
                    miss.append("address")
                if _get_any(row, _FIELDNAME_KEYS) is None:
                    miss.append("name")
                if w is None:
                    miss.append("width")
                if miss:
                    report["findings"].append({
                        "severity": "ERROR", "category": "UNTYPED_FIELD",
                        "entity": lbl,
                        "message": (f"field map row lacks {', '.join(miss)} — "
                                    "an entry without all three cannot be "
                                    "turned into a regfile slice."),
                    })
                if a is not None:
                    span = a + max(1, ((w or 8) + 7) // 8) - 1
                    max_addr = max(max_addr, span)

            # B2 — the map must span the image the doc itself declares.
            if n_bytes is not None and max_addr >= 0:
                if max_addr >= n_bytes:
                    report["findings"].append({
                        "severity": "ERROR", "category": "FIELD_MAP_OVERRUNS_IMAGE",
                        "entity": resolved.name,
                        "message": (
                            f"highest mapped byte {max_addr} lies outside the "
                            f"{n_bytes}-byte image this same document declares "
                            "— the map describes storage that does not exist."),
                    })
                elif max_addr + 1 < n_bytes:
                    report["findings"].append({
                        "severity": "ERROR", "category": "FIELD_MAP_UNDERRUNS_IMAGE",
                        "entity": resolved.name,
                        "message": (
                            f"field map covers bytes 0..{max_addr} but the "
                            f"image this document declares is {n_bytes} bytes "
                            f"— {n_bytes - max_addr - 1} image byte(s) have no "
                            "declared meaning, so their value is unverifiable "
                            "against any layer."),
                    })

    # B3 — lock bits must be synthesisable as write-path gating.
    for i, e in enumerate(locks):
        lbl = str(_get_any(e, _LOCK_HANDLE_KEYS) or f"lock[{i}]")
        miss = []
        if _get_any(e, _LOCK_HANDLE_KEYS) is None:
            miss.append("name/bit/address")
        if _get_any(e, _LOCK_AFFECTS_KEYS) is None:
            miss.append("affects/protects_range/locked_addresses")
        if _get_any(e, _LOCK_TRIGGER_KEYS) is None:
            miss.append("trigger_value/arming_pattern")
        if miss:
            report["findings"].append({
                "severity": "ERROR", "category": "UNSYNTHESISABLE_LOCK_BIT",
                "entity": lbl,
                "message": (f"lock bit lacks {', '.join(miss)} — the write-path "
                            "gating it describes cannot be generated, so the "
                            "lock exists in prose only."),
            })

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _docs_dir(project: Path) -> Path:
    cand = project / "phase1" / "generated_docs"
    if cand.is_dir():
        return cand
    if project.name == "generated_docs":
        return project
    hits = sorted(project.glob("**/generated_docs"))
    return hits[0] if hits else cand


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Assert L11 resolves for its consumers and, when it "
                    "declares an OTP image, carries it in synthesisable form.")
    ap.add_argument("project", help="project directory")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"[SKIP] l11_otp_content_consumer_contract_check: "
              f"not a directory: {project}")
        return 2

    docs = _docs_dir(project)
    report = audit(docs)
    errs = [f for f in report["findings"] if f["severity"] == "ERROR"]
    report["summary"]["pass"] = not errs

    if args.json_out:
        outp = Path(args.json_out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    if any(f["category"] in ("NO_DOCS_DIR", "NO_L11")
           for f in report["findings"]):
        print("[SKIP] l11_otp_content_consumer_contract_check: "
              "no L11 document in this run")
        return 2

    s = report["summary"]
    if errs:
        waived, _ = _waived(project)
        if waived:
            print(f"[PASS] l11_otp_content_consumer_contract_check: waived "
                  f"({WAIVER_KEY}; {len(errs)} finding(s) suppressed)")
            return 0
        print(f"[FAIL] l11_otp_content_consumer_contract_check: "
              f"{len(errs)} finding(s) (resolved={s['resolved_as']!r}, "
              f"otp_declared={s['otp_declared']}, "
              f"field_map_entries={s['field_map_entries']}, "
              f"lock_bits={s['lock_bits']}):")
        for f in errs[:8]:
            print(f"  - [{f['category']}] {f['entity']}: {f['message']}")
        if len(errs) > 8:
            print(f"  ... {len(errs) - 8} more")
        return 1

    print(f"[PASS] l11_otp_content_consumer_contract_check: "
          f"L11 resolves as {s['resolved_as']!r} for every declaration site; "
          f"otp_declared={s['otp_declared']}, "
          f"field_map_entries={s['field_map_entries']}, "
          f"lock_bits={s['lock_bits']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
