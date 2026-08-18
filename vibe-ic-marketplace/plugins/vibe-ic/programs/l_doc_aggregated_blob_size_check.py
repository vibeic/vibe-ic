#!/usr/bin/env python3
"""
l_doc_aggregated_blob_size_check.py — gate (Wave 31, v0.119.63).

Detects the LX_DUMP / `all_input_literals_aggregated` gaming
pattern. SEMANTIC_AUDIT_v0119.57 (docs/design/SEMANTIC_AUDIT_v0119.57.md)
showed every L doc carrying a 192,638-byte aggregated blob; the
literal-grep coverage hit 100% but the typed-field coverage was 13%.

For every L*.json in `<project>/generated_docs/` we sum the byte
size of fields whose name matches the blob-shape (``*_dump`` /
``*_blob`` / ``*_aggregated`` / ``raw_text`` / ``all_input_literals_*``
/ ``LX_DUMP``).  FAIL when:
  * any single such field exceeds 10 KB; OR
  * the sum across all blob-fields in one L doc exceeds 50 KB; OR
  * the sum across the whole `generated_docs/` set exceeds 200 KB.

Wave 31 — this gate is **non-waivable**.  The forbidden-waiver list
in `phase1_no_waivers_used_check` is extended to include the
prefix ``l_doc_aggregated_*``.

Usage
-----
    python3 l_doc_aggregated_blob_size_check.py <project_dir>

Returns 0 PASS, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import _path_layout as _pl


SINGLE_FIELD_LIMIT = 10 * 1024       # 10 KB
PER_DOC_LIMIT = 50 * 1024            # 50 KB
GLOBAL_LIMIT = 200 * 1024            # 200 KB


_BLOB_FIELD_NAMES = (
    "all_input_literals_aggregated",
    "raw_text",
    "evidence_text",
)
_BLOB_FIELD_SUFFIXES = ("_dump", "_blob", "_aggregated")
_BLOB_FIELD_PREFIXES = ("LX_DUMP", "all_input_literals_", "raw_", "RAW_")


def _is_blob_field(name: str) -> bool:
    if not isinstance(name, str):
        return False
    if name in _BLOB_FIELD_NAMES:
        return True
    for s in _BLOB_FIELD_SUFFIXES:
        if name.endswith(s) or name.endswith(s.upper()):
            return True
    for p in _BLOB_FIELD_PREFIXES:
        if name.startswith(p):
            return True
    return False


def _value_byte_size(value) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (list, dict)):
        try:
            return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except Exception:
            return 0
    if value is None:
        return 0
    return len(str(value).encode("utf-8"))


def _scan_doc(path: Path):
    """Return list of (field_name, size_bytes) for every blob-shape
    top-level field in the L*.json at `path`."""
    out = []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for k, v in data.items():
        if _is_blob_field(k):
            out.append((k, _value_byte_size(v)))
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: l_doc_aggregated_blob_size_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 2
    base = _pl.generated_docs_dir(project)
    if not base.is_dir():
        print("SKIP — no generated_docs/ in project")
        return 2
    l_files = sorted(base.glob("L*.json"))
    if not l_files:
        print("SKIP — no L*.json under generated_docs/")
        return 2

    fails: list[str] = []
    global_total = 0
    per_doc_summary: list[tuple[str, int, list]] = []
    for lp in l_files:
        fields = _scan_doc(lp)
        per_doc_total = sum(sz for _, sz in fields)
        per_doc_summary.append((lp.name, per_doc_total, fields))
        global_total += per_doc_total
        for fname, sz in fields:
            if sz > SINGLE_FIELD_LIMIT:
                fails.append(
                    f"{lp.name}: field `{fname}` is {sz} B "
                    f"(>{SINGLE_FIELD_LIMIT} B single-field limit). "
                    "Move data into typed structured fields.")
        if per_doc_total > PER_DOC_LIMIT:
            fails.append(
                f"{lp.name}: total blob-shape bytes = {per_doc_total} "
                f"(>{PER_DOC_LIMIT} B per-doc limit).")
    if global_total > GLOBAL_LIMIT:
        fails.append(
            f"global: blob-shape bytes across all L docs = "
            f"{global_total} (>{GLOBAL_LIMIT} B global limit). "
            "This is the canonical SEMANTIC_AUDIT gaming pattern.")

    if not fails:
        print(f"PASS — blob-field bytes within limits "
              f"(per-field ≤{SINGLE_FIELD_LIMIT}B, "
              f"per-doc ≤{PER_DOC_LIMIT}B, "
              f"global ≤{GLOBAL_LIMIT}B; "
              f"actual global={global_total}B)")
        return 0
    print(f"FAIL — Wave 31 (v0.119.63): blob-shape fields exceed "
          f"limits. Detected {len(fails)} violation(s):")
    for ln in fails:
        print(f"  - {ln}")
    print()
    print("Wave 31 — `all_input_literals_aggregated`, `*_dump`, "
          "`*_blob`, `*_aggregated`, `raw_text`, `LX_DUMP*` are "
          "raw-blob shapes that game extraction coverage. Promote "
          "the data into typed structured fields (opcodes / "
          "registers / fsm_states / timing_parameters / etc.). "
          "NO waiver allowed (forbidden prefix "
          "`l_doc_aggregated_*` in phase1_no_waivers_used_check).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
