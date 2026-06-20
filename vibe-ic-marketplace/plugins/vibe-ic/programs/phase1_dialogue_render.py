#!/usr/bin/env python3
"""phase1_dialogue_render.py — render a Phase-1 DIALOGUE artifact into a
freestyle design-description DOCUMENT for the unified DOC->JSON track.

Architecture (owner directive 2026-06-20): Phase 1 has ONE backend — the
DOC->JSON doc-extraction track (`phase1_doc_one_shot_runner`, the 17-skill
raw-corpus -> L1-L24 ingester). EVERY front-end first becomes a *document*:

  - a concrete vendor doc under input/docs/      -> already a document
  - a free-text input/phase1_prompt.md           -> already a document
  - a dialogue artifact (input/phase1_structured.yaml, the PM/IC-Expert
    convergence fact-tree, OR a raw transcript)  -> THIS renderer turns it
    into a freestyle markdown document

Treating the dialogue as a freestyle document lets the SAME deterministic
DOC->JSON program (plus the IC-Expert AI track + convergence) consume it, so
the emitted L1-L24 JSON is homogeneous regardless of input source.

The rendered markdown deliberately uses the STRUCTURAL forms the doc-track
extractors anchor on — a port/signal table for list-of-record subtrees
(pinout, registers, parameters), bullet `key: value` lines otherwise — so the
re-extraction recovers the same facts.

chip-AGNOSTIC: layer codes + generic shape detection only; no chip-specific
strings.

Usage:
    phase1_dialogue_render.py <src.yaml|.md|.txt> [--out <doc.md>]
    # reads a dialogue artifact, writes a freestyle design-description doc
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Optional: pull disambiguated layer titles from the engine schema when
# importable; otherwise fall back to a bare "L<N>" heading. Never hard-fail
# on the import (the renderer must run from an installed cache too).
try:  # pragma: no cover - import-environment dependent
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent /
                           "tools"))
    from phase1_engine.schema import LAYER_TITLES as _LAYER_TITLES  # type: ignore
except Exception:  # noqa: BLE001
    _LAYER_TITLES = {}

# L1..L27 — superset of the engine's ALL_LAYER_CODES so a richer dialogue
# tree renders fully. Rendering an absent layer is a no-op.
_LAYER_CODES = [f"L{i}" for i in range(1, 28)] + ["L8R"]


def _is_record_list(val: Any) -> bool:
    """A list whose items are all dicts — render as a markdown table so the
    doc-track table/port extractors re-anchor on it."""
    return (isinstance(val, list) and len(val) > 0
            and all(isinstance(x, dict) for x in val))


def _cell(v: Any) -> str:
    """Sanitize a markdown TABLE cell so a one-row record always yields exactly
    len(cols) cells. An unescaped `|` adds phantom columns and a newline splits
    the row into a phantom line — both corrupt the very port/register tables the
    doc-extraction track re-anchors on (Step-2.7 §4.05). Escape `|`; collapse
    any CR/newline to a space."""
    return str(v).replace("\\", "\\\\").replace("|", "\\|").replace(
        "\r", " ").replace("\n", " ").strip()


def _table(rows: List[Dict[str, Any]]) -> List[str]:
    # union of keys, stable first-seen order
    cols: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    if not cols:
        return []
    out = ["| " + " | ".join(_cell(c) for c in cols) + " |",
           "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        out.append("| " + " | ".join(
            _cell(r.get(c, "")) for c in cols) + " |")
    return out


def _bullets(tree: Any, prefix: str = "") -> List[str]:
    """Flatten a scalar/dict tree to `- a.b.c: value` bullets."""
    out: List[str] = []
    if isinstance(tree, dict):
        for k, v in tree.items():
            sub = f"{prefix}{k}"
            if isinstance(v, dict):
                out.extend(_bullets(v, sub + "."))
            elif _is_record_list(v):
                out.append(f"- {sub}:")
                out.extend("  " + ln for ln in _table(v))
            elif isinstance(v, list):
                out.append(f"- {sub}: " +
                           ", ".join(str(x) for x in v))
            else:
                out.append(f"- {sub}: {v}")
    elif _is_record_list(tree):
        out.extend(_table(tree))
    elif isinstance(tree, list):
        out.append("- " + ", ".join(str(x) for x in tree))
    else:
        out.append(f"- {tree}")
    return out


def _render_layer(code: str, tree: Any) -> List[str]:
    title = _LAYER_TITLES.get(code, "")
    head = f"## {code}" + (f" — {title}" if title else "")
    body = _bullets(tree)
    if not body:
        return []
    return [head, ""] + body + [""]


def _looks_structured(doc: Any) -> bool:
    return isinstance(doc, dict) and any(
        c in doc for c in _LAYER_CODES)


def render_dialogue(src: Path) -> Tuple[str, str]:
    """Return (markdown_document, kind). kind in {'structured','transcript'}.

    A YAML/JSON fact-tree with L<N> keys -> structured render. Anything else
    (a raw transcript / free prose) is ALREADY a freestyle document and is
    passed through verbatim (kind='transcript')."""
    text = src.read_text(errors="replace")
    doc: Any = None
    if src.suffix.lower() in (".yaml", ".yml", ".json"):
        try:
            import yaml  # local import; optional dep
            doc = yaml.safe_load(text)
        except Exception:  # noqa: BLE001
            doc = None
    if _looks_structured(doc):
        ic = doc.get("ic_name") or doc.get("L1", {}).get("ic_name") \
            if isinstance(doc, dict) else None
        cls = doc.get("class_path") if isinstance(doc, dict) else None
        lines: List[str] = []
        lines.append(f"# Design Description — {ic or 'UNNAMED_CHIP'}")
        lines.append("")
        lines.append("Rendered from a Phase-1 dialogue convergence "
                     "artifact for the unified DOC->JSON track.")
        lines.append("")
        if cls:
            lines.append(f"IC class: {cls}")
            lines.append("")
        for code in _LAYER_CODES:
            tree = doc.get(code) if isinstance(doc, dict) else None
            if isinstance(tree, (dict, list)) and tree:
                lines.extend(_render_layer(code, tree))
        return "\n".join(lines).rstrip() + "\n", "structured"
    # transcript / free prose — already a freestyle document
    return text, "transcript"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path, help="dialogue artifact "
                    "(phase1_structured.yaml | transcript .md/.txt)")
    ap.add_argument("--out", type=Path, default=None,
                    help="write the rendered document here "
                    "(default: stdout)")
    args = ap.parse_args(argv)
    if not args.src.is_file():
        print(f"ERROR: not a file: {args.src}", file=sys.stderr)
        return 2
    md, kind = render_dialogue(args.src)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md)
        print(f"[dialogue-render] kind={kind} bytes={len(md)} "
              f"-> {args.out}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
