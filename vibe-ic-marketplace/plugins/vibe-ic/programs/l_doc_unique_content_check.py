#!/usr/bin/env python3
"""
l_doc_unique_content_check.py — gate (Wave 31, v0.119.63).

Each L*.json doc must carry UNIQUE content. The 192,638-byte
aggregated blob shared across all 13 L docs in the v0.119.57
benchmark is a textbook gaming pattern (each L doc dumps the same
catch-all string).

Detection (chip-AGNOSTIC):
  * for each pair of L docs, compute the Jaccard similarity of
    their tokenised content (whitespace + punctuation tokens with
    a minimum length of 3 characters).
  * FAIL when ANY pair scores > 70% similarity.

Wave 31 — this gate is non-waivable.  The forbidden-waiver list in
`phase1_no_waivers_used_check` is extended to include the prefix
``l_doc_unique_*``.

Usage
-----
    python3 l_doc_unique_content_check.py <project_dir>

Returns 0 PASS, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path
import _path_layout as _pl


JACCARD_FAIL_THRESHOLD = 0.70
TOKEN_RX = re.compile(r"[A-Za-z0-9_]{3,}")


def _doc_tokens(path: Path) -> set[str]:
    """Tokenise the JSON content (string-serialised) and return the
    set of tokens of length ≥ 3."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        try:
            txt = path.read_text(errors="replace")
        except Exception:
            return set()
        return set(TOKEN_RX.findall(txt))
    txt = json.dumps(data, ensure_ascii=False)
    return set(TOKEN_RX.findall(txt))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: l_doc_unique_content_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 2
    base = _pl.generated_docs_dir(project)
    if not base.is_dir():
        print("SKIP — no generated_docs/")
        return 2
    l_files = sorted(base.glob("L*.json"))
    if len(l_files) < 2:
        print(f"SKIP — fewer than 2 L*.json under generated_docs/ "
              f"(found {len(l_files)}); pairwise comparison is N/A.")
        return 2

    cache: dict[str, set[str]] = {}
    for lp in l_files:
        cache[lp.name] = _doc_tokens(lp)

    fails: list[str] = []
    pair_count = 0
    for a, b in combinations(l_files, 2):
        pair_count += 1
        j = _jaccard(cache[a.name], cache[b.name])
        if j > JACCARD_FAIL_THRESHOLD:
            fails.append(f"{a.name} vs {b.name}: jaccard={j:.2f} "
                         f"(>{JACCARD_FAIL_THRESHOLD:.0%}; suggests "
                         f"shared blob).")

    if not fails:
        print(f"PASS — all {pair_count} L-doc pair(s) carry distinct "
              f"content (jaccard ≤ {JACCARD_FAIL_THRESHOLD:.0%}).")
        return 0
    print(f"FAIL — Wave 31 (v0.119.63): {len(fails)} L-doc pair(s) "
          f"share more than {JACCARD_FAIL_THRESHOLD:.0%} content. "
          f"This is the canonical 'shared aggregated blob' gaming "
          f"pattern.")
    for ln in fails:
        print(f"  - {ln}")
    print()
    print("Each L doc must carry its own typed structured content; "
          "do NOT dump the same all_input_literals_aggregated blob "
          "into every L*.json. NO waiver allowed (forbidden prefix "
          "`l_doc_unique_*`).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
