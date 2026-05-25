#!/usr/bin/env python3
"""
ip_catalog_query.py — IP catalog query + match + pull engine.

Plugin pipeline hooks:
  - phase2_one_shot_runner.step_rtl_gen → query catalog when rtl_gen=null
  - ic_class_profile.detect_ic_class → annotate profile with catalog hits
  - catalog-glue-author skill → consume CatalogMatch list to pull RTL

Manifest schema: ip_catalog/_schema/ip_manifest.schema.json
Match grammar: see _evaluate_match_rule() docstring.

License: only permissive (ISC/MIT/BSD/Apache-2.0/CC0/CERN-OHL-P/W).
Reject GPL/AGPL/SSPL/CC-BY-SA-NC.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# License whitelist / blacklist (chip-AGNOSTIC, enforced at manifest load)
# ---------------------------------------------------------------------------
PERMISSIVE_LICENSES = {
    "ISC", "MIT", "BSD-2-Clause", "BSD-3-Clause",
    "Apache-2.0", "CC0-1.0", "Public-Domain", "Unlicense",
    "CERN-OHL-P-2.0", "CERN-OHL-W-2.0",
    # v1.6.586 — Usselmann custom permissive (OpenCores legacy IPs by
    # Rudolf Usselmann). "May be used and distributed without restriction
    # provided that this copyright statement is not removed." Functionally
    # equivalent to BSD-2-Clause + warranty disclaimer. Not in SPDX list
    # but legally permissive.
    "Usselmann-Permissive",
    # v1.6.587 — MPL-2.0 is file-scope copyleft (file-level only), and is
    # widely considered permissive enough for IP catalogs that bundle
    # IP without modification. Plugin still records use; license
    # propagation is per-file, not whole-design.
    "MPL-2.0",
}

FORBIDDEN_LICENSES = {
    "GPL", "GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later",
    "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
    "AGPL", "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later",
    "AGPL-2.0", "SSPL-1.0",
    "CC-BY-SA", "CC-BY-SA-4.0", "CC-BY-NC", "CC-BY-NC-4.0",
    "LGPL", "LGPL-2.1", "LGPL-3.0",  # weak copyleft still propagates to dynamic links
    "CERN-OHL-S-2.0",  # strongly-reciprocal CERN-OHL — restrictive copyleft
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass
class CatalogMatch:
    ip_name: str
    category: str          # cpu / crypto / memory / peripheral / interconnect
    version: str
    license: str
    canonical_url: str
    canonical_commit: str
    matched_pattern: str   # the matches_when entry that fired
    confidence: float      # 0.0-1.0 — for ranking when multiple matches
    manifest_path: str
    rtl_files: List[str] = field(default_factory=list)
    integration_notes: str = ""
    depends_on: List[str] = field(default_factory=list)

    def to_audit_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Catalog discovery
# ---------------------------------------------------------------------------
def find_catalog_dir() -> Optional[Path]:
    """Locate ip_catalog/ directory. Returns None if not found."""
    here = Path(__file__).resolve().parent
    # Walk up: programs/ -> vibe-ic/ -> ip_catalog/
    for ancestor in [here] + list(here.parents):
        candidate = ancestor / "ip_catalog"
        if candidate.is_dir() and (candidate / "_schema").is_dir():
            return candidate
    # Hard fallbacks
    for fallback in [
        Path("~/AI_IC_design/opensource_repo/vibe-ic-marketplace/plugins/vibe-ic/ip_catalog"),
        Path("~/AI_IC_design/vibe-ic-marketplace/plugins/vibe-ic/ip_catalog"),
    ]:
        if fallback.is_dir():
            return fallback
    return None


def load_manifests(catalog_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load every ip_catalog/*/*/manifest.yaml, returning list of dicts.

    Each dict gets `_manifest_path` and `_category` fields injected for
    downstream use. Silently skips manifests that fail to parse, fail
    license check, or violate other invariants.
    """
    if catalog_dir is None:
        catalog_dir = find_catalog_dir()
    if catalog_dir is None:
        return []

    manifests = []
    for manifest_path in catalog_dir.rglob("manifest.yaml"):
        try:
            text = manifest_path.read_text()
            # Lightweight YAML parse — avoid pyyaml dep when possible
            data = _parse_simple_yaml(text)
        except Exception as e:
            print(f"warn: failed to parse {manifest_path}: {e}", file=sys.stderr)
            continue

        # License enforcement — REJECT non-permissive
        lic = data.get("license", "")
        if lic in FORBIDDEN_LICENSES:
            print(f"reject: {manifest_path} declares forbidden license {lic}",
                  file=sys.stderr)
            continue
        if lic not in PERMISSIVE_LICENSES:
            print(f"warn: {manifest_path} declares unknown license {lic!r} — "
                  f"loading but flagging as risky", file=sys.stderr)

        data["_manifest_path"] = str(manifest_path)
        data["_category"] = manifest_path.parent.parent.name
        manifests.append(data)

    return manifests


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Minimal YAML parser sufficient for ip_catalog manifests.

    Supports: scalars, top-level lists, nested dicts via indentation,
    list-of-dicts, multi-line `>` block-scalars (folded), inline `{}` dicts.
    Does NOT support flow-style sequences, anchors, tags, or complex YAML.
    For full YAML, install pyyaml; this avoids the dependency for the
    common case.
    """
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        pass
    # Fallback minimal parser — sufficient for our schemas
    out: Dict[str, Any] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln or ln.lstrip().startswith("#"):
            i += 1
            continue
        # Top-level key
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$", ln)
        if m:
            key, rest = m.group(1), m.group(2).strip()
            if rest in ("", ">", ">-", "|", "|-"):
                # Multi-line scalar or nested block — gather indented lines
                block_lines = []
                i += 1
                while i < len(lines):
                    next_ln = lines[i]
                    if next_ln.strip() == "" or next_ln.startswith(" ") or next_ln.startswith("\t"):
                        block_lines.append(next_ln.lstrip())
                        i += 1
                    else:
                        break
                if rest in (">", ">-"):
                    out[key] = " ".join(s.strip() for s in block_lines if s.strip())
                elif rest in ("|", "|-"):
                    out[key] = "\n".join(block_lines)
                else:
                    # Try parse as nested dict/list
                    nested_text = "\n".join(block_lines)
                    out[key] = _try_parse_nested(nested_text)
            else:
                out[key] = _coerce_scalar(rest)
                i += 1
        else:
            i += 1
    return out


def _try_parse_nested(text: str) -> Any:
    """Try to parse nested YAML — dict, list, or fallback string."""
    lines = [ln for ln in text.split("\n") if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return None
    # If first non-empty line starts with "- ", treat as list
    if lines[0].lstrip().startswith("- "):
        items = []
        cur_item_lines: List[str] = []
        for ln in lines:
            stripped = ln.lstrip()
            if stripped.startswith("- "):
                if cur_item_lines:
                    items.append(_parse_list_item("\n".join(cur_item_lines)))
                cur_item_lines = [stripped[2:]]
            else:
                cur_item_lines.append(stripped)
        if cur_item_lines:
            items.append(_parse_list_item("\n".join(cur_item_lines)))
        return items
    # Else treat as nested dict
    nested = {}
    for ln in lines:
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$", ln.strip())
        if m:
            nested[m.group(1)] = _coerce_scalar(m.group(2).strip())
    return nested


def _parse_list_item(item_text: str) -> Any:
    """Parse a single list item, possibly inline dict {a: 1, b: 2}."""
    item_text = item_text.strip()
    if item_text.startswith("{") and item_text.endswith("}"):
        # Inline dict
        inner = item_text[1:-1]
        d = {}
        for part in _split_inline_dict(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                d[k.strip()] = _coerce_scalar(v.strip())
        return d
    # If multi-line, parse as dict
    if "\n" in item_text:
        d = {}
        for ln in item_text.split("\n"):
            m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$", ln.strip())
            if m:
                d[m.group(1)] = _coerce_scalar(m.group(2).strip())
        return d
    return _coerce_scalar(item_text)


def _split_inline_dict(text: str) -> List[str]:
    """Split 'a: 1, b: 2' respecting nested brackets and quotes."""
    parts: List[str] = []
    depth = 0
    in_quote = False
    cur = ""
    for ch in text:
        if ch in "\"'" and not in_quote:
            in_quote = ch
        elif ch == in_quote:
            in_quote = False
        elif not in_quote and ch in "[{(":
            depth += 1
        elif not in_quote and ch in "]})":
            depth -= 1
        elif not in_quote and ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def _coerce_scalar(s: str) -> Any:
    """Coerce scalar string to int/float/bool/None where appropriate."""
    s = s.strip()
    if s in ("null", "~", ""):
        return None
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    if s in ("true", "True", "yes"):
        return True
    if s in ("false", "False", "no"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    # Lists with [a, b, c]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_coerce_scalar(x) for x in _split_inline_dict(inner)]
    return s


# ---------------------------------------------------------------------------
# Fact extraction from project's phase1 output
# ---------------------------------------------------------------------------
def load_project_facts(project: Path) -> Dict[str, Any]:
    """Read project's phase1/generated_docs/L*.json into flat facts dict.

    Returns dict like:
      {"L1_DATASHEET.product_family": "...", "L2_FRS.cpu_arch": "...", ...}
    Plus a string concatenation of all doc text under key "_full_text"
    for substring matching against matches_when patterns.
    """
    facts: Dict[str, Any] = {}
    full_text_parts: List[str] = []
    gen_dir = project / "phase1" / "generated_docs"
    if not gen_dir.is_dir():
        return facts

    for json_path in sorted(gen_dir.glob("L*.json")):
        try:
            data = json.loads(json_path.read_text())
        except Exception:
            continue
        layer_key = json_path.stem  # e.g. "L1_DATASHEET"
        _flatten_into(facts, layer_key, data)
        full_text_parts.append(json.dumps(data, ensure_ascii=False))

    # Also include input/docs/L*.md (the original spec text — sometimes
    # more verbose than the extracted JSON)
    docs_dir = project / "input" / "docs"
    if docs_dir.is_dir():
        for md_path in sorted(docs_dir.glob("L*.md")):
            try:
                full_text_parts.append(md_path.read_text())
            except Exception:
                pass

    facts["_full_text"] = "\n".join(full_text_parts)
    return facts


def _flatten_into(out: Dict[str, Any], prefix: str, obj: Any, depth: int = 0) -> None:
    """Flatten nested dict/list into dotted keys, capped at depth 4."""
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f"{prefix}.{k}"
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[new_prefix] = v
            else:
                _flatten_into(out, new_prefix, v, depth + 1)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, (str, int, float, bool)) or item is None:
                out[f"{prefix}[{i}]"] = item
            else:
                _flatten_into(out, f"{prefix}[{i}]", item, depth + 1)


# ---------------------------------------------------------------------------
# Match pattern evaluation
# ---------------------------------------------------------------------------
def _evaluate_match_rule(pattern: str, facts: Dict[str, Any]) -> Tuple[bool, float]:
    """Evaluate a single matches_when prose pattern against facts.

    Grammar (heuristic, chip-AGNOSTIC):

        <pattern> := <term> [ ('AND' | 'OR') <term> ]*
        <term>    := <field-ref> <op> <value>
                   | <value> 'in' <field-ref>
                   | <free-text>
        <op>      := 'starts with' | 'contains' | '==' | 'matches' |
                     'less than' | 'greater than' | 'in'
        <field-ref> := 'L1' | 'L2' | ... | 'L1.xxx' | 'L2.cpu_arch' | etc.

    Returns (matched, confidence). Confidence is heuristic:
      1.0 if all sub-conditions pass with strong evidence
      0.5 if free-text fallback matches
      0.0 if no match
    """
    # Normalize
    p = pattern.strip()
    full_text = str(facts.get("_full_text", ""))

    # Top-level AND / OR split (case-sensitive — manifest convention)
    # Split AND first (lowest precedence in our heuristic)
    and_parts = re.split(r"\s+AND\s+", p)
    if len(and_parts) > 1:
        scores = [_evaluate_match_rule(part, facts) for part in and_parts]
        if all(s[0] for s in scores):
            return (True, min(s[1] for s in scores))
        return (False, 0.0)

    or_parts = re.split(r"\s+OR\s+", p)
    if len(or_parts) > 1:
        scores = [_evaluate_match_rule(part, facts) for part in or_parts]
        if any(s[0] for s in scores):
            return (True, max(s[1] for s in scores))
        return (False, 0.0)

    # Single term — look for op keywords
    # "X starts with 'Y'"
    m = re.match(r"^(L\d+R?(?:\.[a-zA-Z0-9_\[\]]+)?)\s+starts\s+with\s+['\"]([^'\"]+)['\"]\s*$", p)
    if m:
        field_ref, value = m.group(1), m.group(2)
        field_val = _resolve_field(facts, field_ref)
        if field_val is not None and str(field_val).lower().startswith(value.lower()):
            return (True, 0.9)
        # Fallback: substring search in full_text
        if value.lower() in full_text.lower():
            return (True, 0.5)
        return (False, 0.0)

    # "X contains 'Y'" or "X contains 'Y' or 'Z'"
    m = re.match(r"^(L\d+R?(?:\.[a-zA-Z0-9_\[\]]+)?)\s+contains\s+(.+)$", p)
    if m:
        field_ref = m.group(1)
        values_str = m.group(2)
        # Extract all quoted values
        values = re.findall(r"['\"]([^'\"]+)['\"]", values_str)
        if not values:
            return (False, 0.0)
        field_val = _resolve_field(facts, field_ref)
        field_str = str(field_val).lower() if field_val is not None else ""
        for v in values:
            if v.lower() in field_str:
                return (True, 0.9)
            if v.lower() in full_text.lower():
                return (True, 0.6)
        return (False, 0.0)

    # "X == 'Y'"
    m = re.match(r"^(L\d+R?(?:\.[a-zA-Z0-9_\[\]]+)?)\s*==\s*['\"]([^'\"]+)['\"]\s*$", p)
    if m:
        field_ref, value = m.group(1), m.group(2)
        field_val = _resolve_field(facts, field_ref)
        if field_val is not None and str(field_val).lower() == value.lower():
            return (True, 1.0)
        return (False, 0.0)

    # "X in [a, b, c]" or "X in [n1, n2]"
    m = re.match(r"^(L\d+R?(?:\.[a-zA-Z0-9_\[\]]+)?)\s+in\s+\[([^\]]+)\]\s*$", p)
    if m:
        field_ref = m.group(1)
        values_str = m.group(2)
        values = [v.strip().strip("'\"") for v in values_str.split(",")]
        field_val = _resolve_field(facts, field_ref)
        if field_val is not None:
            field_str = str(field_val).lower()
            for v in values:
                try:
                    if float(field_val) == float(v):
                        return (True, 1.0)
                except (ValueError, TypeError):
                    pass
                if v.lower() == field_str:
                    return (True, 1.0)
        return (False, 0.0)

    # "X less than N" / "X > N"
    m = re.match(r"^(L\d+R?(?:\.[a-zA-Z0-9_\[\]]+)?)\s+(less\s+than|greater\s+than)\s+([\d.]+)\s*$", p)
    if m:
        field_ref, op, value = m.group(1), m.group(2), float(m.group(3))
        field_val = _resolve_field(facts, field_ref)
        try:
            fv = float(field_val) if field_val is not None else None
        except (ValueError, TypeError):
            return (False, 0.0)
        if fv is None:
            return (False, 0.0)
        if op == "less than" and fv < value:
            return (True, 1.0)
        if op == "greater than" and fv > value:
            return (True, 1.0)
        return (False, 0.0)

    # "X mentions 'Y'" — alias for free-text search
    m = re.match(r"^(L\d+R?(?:\.[a-zA-Z0-9_\[\]]+)?)\s+mentions\s+['\"]([^'\"]+)['\"]\s*$", p)
    if m:
        value = m.group(2)
        if value.lower() in full_text.lower():
            return (True, 0.7)
        return (False, 0.0)

    # Free-text fallback: check if ALL quoted phrases appear in full_text
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", p)
    if quoted:
        ft = full_text.lower()
        if all(q.lower() in ft for q in quoted):
            return (True, 0.4)

    return (False, 0.0)


def _resolve_field(facts: Dict[str, Any], field_ref: str) -> Any:
    """Resolve 'L2.cpu_arch' into facts dict value.

    Tries exact match first, then fuzzy on:
      - L<n>.<field>     → look up L<n>_<*>.<field>
      - L<n>             → search any key starting with L<n>_
    """
    # Exact match
    if field_ref in facts:
        return facts[field_ref]

    # Try L2.foo → look for L2_*.foo
    if "." in field_ref:
        layer_part, rest = field_ref.split(".", 1)
        # Search any L<n>_*.<rest>
        for k, v in facts.items():
            if k.startswith(layer_part + "_") and k.endswith("." + rest):
                return v
            # Match dotted field path inside flat-keyed facts
            if k.startswith(layer_part + "_") and rest.lower() in k.lower():
                return v
    else:
        # Just "L2" — return any L2_* key's value (rare path)
        for k, v in facts.items():
            if k.startswith(field_ref + "_") or k.startswith(field_ref + "."):
                return v

    return None


# ---------------------------------------------------------------------------
# Public API: query catalog
# ---------------------------------------------------------------------------
def query_catalog(project: Path,
                  catalog_dir: Optional[Path] = None,
                  min_confidence: float = 0.4) -> List[CatalogMatch]:
    """Top-level API. Returns ranked list of catalog matches for project."""
    manifests = load_manifests(catalog_dir)
    if not manifests:
        return []

    facts = load_project_facts(project)
    matches: List[CatalogMatch] = []

    for m in manifests:
        ip_name = m.get("ip_name", "<unknown>")
        license_ = m.get("license", "<unknown>")
        patterns = m.get("matches_when", [])
        if not isinstance(patterns, list):
            continue

        best_pattern = ""
        best_confidence = 0.0
        for pattern in patterns:
            if not isinstance(pattern, str):
                continue
            matched, conf = _evaluate_match_rule(pattern, facts)
            if matched and conf > best_confidence:
                best_confidence = conf
                best_pattern = pattern

        if best_confidence >= min_confidence:
            matches.append(CatalogMatch(
                ip_name=ip_name,
                category=m.get("_category", ""),
                version=str(m.get("ip_version", "")),
                license=license_,
                canonical_url=m.get("canonical_url", ""),
                canonical_commit=m.get("canonical_commit", ""),
                matched_pattern=best_pattern,
                confidence=best_confidence,
                manifest_path=m.get("_manifest_path", ""),
                rtl_files=m.get("rtl_files", []) if isinstance(m.get("rtl_files"), list) else [],
                integration_notes=str(m.get("integration_notes", "")),
                depends_on=m.get("depends_on", []) if isinstance(m.get("depends_on"), list) else [],
            ))

    # Rank by confidence descending
    matches.sort(key=lambda x: x.confidence, reverse=True)
    return matches


def check_license_compatibility(license_id: str) -> Tuple[bool, str]:
    """Returns (is_permissive, rationale)."""
    if license_id in PERMISSIVE_LICENSES:
        return (True, f"{license_id} is on permissive whitelist")
    if license_id in FORBIDDEN_LICENSES:
        return (False, f"{license_id} is GPL-family or restrictive copyleft — "
                f"would taint user design. REJECTED.")
    return (False, f"Unknown license {license_id!r} — not on whitelist. "
            f"Add to PERMISSIVE_LICENSES in ip_catalog_query.py if appropriate.")


# ---------------------------------------------------------------------------
# CLI for ad-hoc query
# ---------------------------------------------------------------------------
def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Query ip_catalog against a Plugin project")
    ap.add_argument("project", help="Project root (containing phase1/generated_docs/)")
    ap.add_argument("--catalog-dir", default=None,
                    help="Override ip_catalog/ location")
    ap.add_argument("--min-confidence", type=float, default=0.4,
                    help="Minimum confidence to include in results (default 0.4)")
    ap.add_argument("--list-only", action="store_true",
                    help="List all manifests (no project query)")
    ap.add_argument("--json", action="store_true",
                    help="Output JSON")
    args = ap.parse_args(argv)

    if args.list_only:
        manifests = load_manifests(Path(args.catalog_dir) if args.catalog_dir else None)
        print(f"=== {len(manifests)} catalog manifests ===")
        for m in manifests:
            print(f"  {m.get('_category', '?'):12s} / {m.get('ip_name', '?'):20s}  "
                  f"v{m.get('ip_version', '?'):8s}  [{m.get('license', '?')}]")
        return 0

    project = Path(args.project)
    if not project.is_dir():
        print(f"ERROR: project dir not found: {project}", file=sys.stderr)
        return 2

    matches = query_catalog(
        project,
        Path(args.catalog_dir) if args.catalog_dir else None,
        min_confidence=args.min_confidence,
    )

    if args.json:
        print(json.dumps([m.to_audit_dict() for m in matches], indent=2))
        return 0

    if not matches:
        print(f"=== ip_catalog query: 0 matches for {project.name} ===")
        return 0

    print(f"=== ip_catalog query: {len(matches)} matches for {project.name} ===")
    for m in matches:
        print(f"  [{m.confidence:.2f}] {m.category}/{m.ip_name} v{m.version}  "
              f"({m.license})")
        print(f"       matched: {m.matched_pattern}")
        if m.depends_on:
            print(f"       depends_on: {', '.join(m.depends_on)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
