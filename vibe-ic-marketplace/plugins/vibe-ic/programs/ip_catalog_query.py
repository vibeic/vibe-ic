#!/usr/bin/env python3
"""
ip_catalog_query.py — IP catalog query + match + pull engine.

Plugin pipeline hooks:
  - design_one_shot_runner.step_rtl_gen → query catalog when rtl_gen=null
  - ic_class_profile.detect_ic_class → annotate profile with catalog hits
  - catalog-glue-author skill → consume CatalogMatch list to pull RTL

Manifest schema: ip-catalog/_schema/ip_manifest.schema.json
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _shape_refusal  # noqa: E402  (#991)


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
    # v0.2.102 — for #492. Synthesis-safety hints (param name ->
    # synth-safe value + reason) carried verbatim from the manifest's
    # `synth_safe_params`. catalog-glue-author applies these by default
    # when instantiating the IP for synthesis (sim-only generate blocks
    # with PLI/system tasks are the canonical case).
    synth_safe_params: List[Dict[str, Any]] = field(default_factory=list)
    # #187 (BENCHMARK INTEGRITY) — set when this catalog entry would hand back
    # the IC-under-test's OWN reference design (its top/name intersects the IC
    # identity) rather than a leaf COMPONENT IP. Such an entry is REFUSED by
    # query_catalog unless self-match is explicitly acknowledged; offering it
    # would leak the answer key through the front door (§4.05).
    self_match: bool = False
    self_match_reason: str = ""
    # #991 — every list field above that was PRESENT in the manifest and was
    # not a JSON array. Recorded on the match rather than dropped, because the
    # three coercions that built them (`x if isinstance(x, list) else []`) made
    # a manifest that declares a dependency indistinguishable from one that
    # declares none: MEASURED, a `depends_on` keyed BY DEPENDENCY NAME caused
    # the required IP to be silently absent from the offered set, with no
    # diagnostic anywhere. A match carrying any of these is REFUSED by
    # `query_catalog` — see `_shape_refusals_in`.
    shape_refusals: List[Dict[str, Any]] = field(default_factory=list)

    def to_audit_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def synth_param_overrides(self) -> Dict[str, Any]:
        """Return {param_name: synth_safe_value} the glue-author must pin
        by default at synthesis instantiation time. chip-AGNOSTIC: reads
        only the manifest-supplied list."""
        out: Dict[str, Any] = {}
        for entry in self.synth_safe_params:
            if not isinstance(entry, dict):
                continue
            name = entry.get("param")
            if not isinstance(name, str) or not name:
                continue
            if "synth_safe_value" in entry:
                out[name] = entry["synth_safe_value"]
        return out


# ---------------------------------------------------------------------------
# Catalog discovery
# ---------------------------------------------------------------------------
def find_catalog_dir() -> Optional[Path]:
    """Locate ip-catalog/ directory. Returns None if not found."""
    here = Path(__file__).resolve().parent
    # Walk up: programs/ -> vibe-ic/ -> ip-catalog/
    for ancestor in [here] + list(here.parents):
        candidate = ancestor / "ip-catalog"
        if candidate.is_dir() and (candidate / "_schema").is_dir():
            return candidate
    # Explicit override, then a walk-up sibling layout. The previous fallbacks
    # hardcoded this project's INTERNAL workspace directory name under `~` —
    # which was doubly wrong: it is not a sensible location on anyone else's
    # machine, and `Path("~/...")` is never expanded, so `.is_dir()` was always
    # False and the fallback could not fire at all.
    env = os.environ.get("VIBE_IC_IP_CATALOG_DIR")
    if env:
        cand = Path(env).expanduser()
        if cand.is_dir():
            return cand
    for ancestor in [here] + list(here.parents):
        cand = (ancestor / "opensource_repo" / "vibe-ic-marketplace"
                / "plugins" / "vibe-ic" / "ip-catalog")
        if cand.is_dir() and (cand / "_schema").is_dir():
            return cand
    return None


def load_manifests(catalog_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load every ip-catalog/*/*/manifest.yaml, returning list of dicts.

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
    """Minimal YAML parser sufficient for ip-catalog manifests.

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
    # v-orch 4a — per-layer text so matches_when predicates keyed on a
    # structured L2 field can fall back to a SCOPED keyword search over
    # only the relevant layer section (not the whole-doc _full_text).
    layer_text: Dict[str, str] = {}
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
        doc_json = json.dumps(data, ensure_ascii=False)
        full_text_parts.append(doc_json)
        # Key the section by the bare layer id (L1, L2, ...) so a
        # "L2.cpu_isa" predicate can scope to the L2 section regardless
        # of the doc suffix ("L2_FRS" → "L2").
        bare = layer_key.split("_", 1)[0]
        layer_text[bare] = layer_text.get(bare, "") + "\n" + doc_json

    # Also include input/docs/L*.md (the original spec text — sometimes
    # more verbose than the extracted JSON)
    docs_dir = project / "input" / "docs"
    if docs_dir.is_dir():
        for md_path in sorted(docs_dir.glob("L*.md")):
            try:
                md_txt = md_path.read_text()
            except Exception:
                continue
            full_text_parts.append(md_txt)
            bare = md_path.stem.split("_", 1)[0]
            layer_text[bare] = layer_text.get(bare, "") + "\n" + md_txt

    facts["_full_text"] = "\n".join(full_text_parts)
    facts["_layer_text"] = layer_text
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
# v-orch 4a — STRUCTURED L2 fields. When a matches_when predicate keys
# on one of these and the L2 doc does NOT expose it as a discrete flat
# key, fall back to a keyword search SCOPED to the relevant layer
# section only (not the whole-doc _full_text), and lower the confidence
# of substring-only hits so they rank below structured-field hits.
_STRUCTURED_L2_FIELDS = {
    "cpu_family", "cpu_isa", "cpu_arch", "cpu_extensions",
    "memory_topology", "submodule_required",
}
# Substring-only (scoped or full-text) confidence ceilings. Structured
# discrete-key hits keep the original high (0.9-1.0) scores.
_CONF_SCOPED_SUBSTR = 0.45    # keyword found in the SCOPED layer section
_CONF_FULLTEXT_SUBSTR = 0.3   # keyword found only in whole-doc fallback


def _structured_field_name(field_ref: str) -> Optional[str]:
    """Return the structured field name if `field_ref` keys on one of
    the discrete L2 fields (e.g. "L2.cpu_isa" -> "cpu_isa"), else None."""
    if "." not in field_ref:
        return None
    _, rest = field_ref.split(".", 1)
    rest = rest.strip().lower()
    return rest if rest in _STRUCTURED_L2_FIELDS else None


def _layer_id(field_ref: str) -> Optional[str]:
    """Return the bare layer id ("L2") from a field ref ("L2.cpu_isa")."""
    head = field_ref.split(".", 1)[0].strip()
    if re.fullmatch(r"L\d+R?", head):
        # Strip a trailing reverse-extract 'R' so "L2R" scopes to "L2".
        return re.sub(r"R$", "", head)
    return None


def _scoped_section_text(facts: Dict[str, Any], field_ref: str) -> str:
    """Text scoped to the layer named in `field_ref`. Falls back to the
    empty string when no per-layer text is captured."""
    lid = _layer_id(field_ref)
    layer_text = facts.get("_layer_text")
    if lid and isinstance(layer_text, dict):
        return str(layer_text.get(lid, ""))
    return ""


# Integer-only / extension-exclusion vocabulary (chip-AGNOSTIC). When a
# spec asserts an integer-only ISA or explicitly excludes an extension,
# an "ISA contains '<ext>'" rule must NOT fire on a stray substring.
_INTEGER_ONLY_MARKERS = (
    "integer-only", "integer only", "int-only", "int only",
    "no floating point", "no floating-point", "no fpu",
    "without fpu", "without floating point", "no float",
    "soft-float", "soft float",
)


# ---------------------------------------------------------------------------
# v1.0.51 — for #681. GENERIC optional/negation phrase-grammar (chip-AGNOSTIC).
# A free-text 'mentions' hit on a term that sits inside an OPTIONAL or an
# EXPLICIT-NEGATION / NOT-constrained window is NOT evidence the design
# actually uses that thing — it is a "you may add it but it is not required"
# or "we do NOT use it" mention. This mirrors (and generalises) the
# asymmetric suppression `_extension_optional_only` / `_extension_excluded`
# already apply to the cpu_extensions/cpu_isa `contains` branch, but here
# the vocabulary is term-agnostic so it is reusable by the 'mentions' rules.
# Bilingual (EN + zh-Hant) because real spec docs mix both. NO chip literal.
# Qualifiers that PRECEDE the term ("may add foo", "without foo",
# "must not use foo", "可自行加 foo"). Checked in a tight BACKWARD window.
_PRECEDING_QUALIFIER_MARKERS = (
    # optional (precede)
    "optional", "optionally", "may add", "may include", "may also add",
    "can add", "could add", "可自行加", "可自行", "選用", "可選",
    # negation (precede)
    "must not use", "must not", "does not use", "do not use", "don't use",
    "without", "excludes", "excluding", "no use of", "not in scope",
    "out of scope", "不使用", "未使用", "排除", "不採用", "不納入", "❌",
)
# Qualifiers that TRAIL the term as a TERMINAL existence assertion about
# the term itself ("foo (optional)", "foo is optional", "foo，但不強制").
# Matched in a tight FORWARD window within the term's own clause. NOTE: a
# bare adjacent "optionally" is NOT here — "foo optionally supports X" says
# foo does X optionally, NOT that foo itself is optional (that genuine case
# must still fire); only copula-bound trailing patterns suppress, see
# _TRAILING_GOVERNOR_RE below.
_TRAILING_QUALIFIER_MARKERS = (
    "(opt)", "(optional)",
)
# Reference / comparison markers that PRECEDE the term: a comparative or
# referential mention ("regarding X", "such as X", "compared to X", "對 X
# 級 protocol" — "regarding the X-level protocol") is NOT an assertion that
# the design USES X; it is a reference. Checked in a tight backward window.
_REFERENCE_QUALIFIER_MARKERS = (
    "regarding", "such as", "compared to", "compared with", "relative to",
    "as opposed to", "instead of", "rather than", "similar to", "like the",
    "對", "類似", "相較", "相對", "而非", "而不是",
)
# Tight bounded windows (chars) — small enough that a qualifier attached to
# a DIFFERENT occurrence cannot bleed onto a genuine one (further bounded by
# the term's clause).
_PRECEDE_WINDOW = 24
_TRAIL_WINDOW = 24
# Clause separators (hard punctuation) — used to bound a clause around the
# term so a qualifier/marker in a DIFFERENT clause cannot bleed onto a
# genuine one.
_CLAUSE_SEPARATORS = ".。!！?？;；,，、\n"
# Coordinating conjunctions are SOFT clause boundaries: "X is mandatory but
# an optional Y can be added" — the 'but'/'and'/'while'/... separates the X
# assertion from the Y qualifier even with no comma. They must NOT be used
# as a hard split (they can appear inside a single term clause), but they DO
# bound the term-anchored governor search so a qualifier on the far side of
# a conjunction never governs the term. v1.0.51-r2 — for #681 review leak.
_SOFT_BOUNDARY_RE = re.compile(
    r"\b(?:and|but|while|with|although|though|whereas|plus|yet|however|"
    r"as\s+well\s+as)\b")


def _term_anchored_governor(term_l: str, segment: str) -> bool:
    """v1.0.51-r2 — for #681 review. TERM-ANCHORED optional/negation
    governor. Return True ONLY when an optional/negation qualifier is
    grammatically bound to THE TERM (not merely co-present in the clause):

      preceding:  optional/optionally <term> ; an optional <term>
      trailing :  <term> is/are optional ; <term> is/are not
                  required|mandatory|used|supported|present ;
                  <term> may/might/can be added|omitted|included ;
                  <term> (optional)

    A naive ±N proximity window is INSUFFICIENT — it wrongly suppresses
    "the <term> optionally supports burst transfers" (verified by the
    reviewer). Hence the trailing form requires a COPULA ("is/are") or a
    modal-existence phrase between the term and the qualifier.

    chip-AGNOSTIC: pure grammar; no chip/IP literal.
    """
    t = re.escape(term_l)
    pats = (
        # preceding qualifier directly modifying the term
        rf"\boptional(?:ly)?\s+{t}\b",
        rf"\ban?\s+optional\s+{t}\b",
        # trailing copula-bound existence assertion about the term
        rf"\b{t}\b[^.;:,!?]{{0,30}}?\b(?:is|are|remains?|stays?)\s+optional\b",
        rf"\b{t}\b[^.;:,!?]{{0,30}}?\b(?:is|are)\s+not\s+"
        rf"(?:required|mandatory|used|supported|present|needed)\b",
        # modal existence ("<term> may be added/omitted")
        rf"\b{t}\b[^.;:,!?]{{0,20}}?\b(?:may|might|can|could)\s+be\s+"
        rf"(?:added|omitted|included|present|left\s+out|removed)\b",
        # parenthetical
        rf"\b{t}\b\s*\((?:opt|optional)\)",
    )
    return any(re.search(p, segment) for p in pats)


def _term_optional_or_negated(term: str, text: str) -> bool:
    """v1.0.51 — GENERIC suppression test for a free-text term.

    Return True when EVERY occurrence of `term` in `text` sits inside an
    OPTIONAL ('optional'/'可自行加'/'不強制'/'may add'/'(opt)'…) or an
    EXPLICIT-NEGATION / NOT-constrained ('must not use'/'without'/'不在…
    約束的事'/'❌'…) window — i.e. there is no genuine, unqualified mention
    of the term anywhere. A single unqualified occurrence anywhere defeats
    the suppression (mandatory/plain mention wins), so a real constrained
    spec section still fires.

    Direction-aware AND TERM-ANCHORED: a preceding qualifier ("may add foo",
    "without foo", "optional foo") is checked in a tight BACKWARD window; a
    trailing qualifier is COPULA-bound to the term ("foo is optional", "foo
    is not required") via _term_anchored_governor — never a bare clause-wide
    keyword. Both are bounded by hard clause separators AND coordinating
    conjunctions (soft boundaries), so a qualifier modifying a DIFFERENT
    noun ("foo is mandatory but an optional bar...") cannot leak onto the
    term. v1.0.51-r2 removed the unsound whole-clause governor branch that
    dropped genuine mandatory-term mentions (#681 review leak).

    chip-AGNOSTIC: pure bilingual phrase grammar; no chip/IP literal.
    """
    term_l = term.strip().lower()
    if not term_l or not text:
        return False
    blob = text.lower()
    found_any = False
    start = 0
    while True:
        idx = blob.find(term_l, start)
        if idx < 0:
            break
        found_any = True
        end = idx + len(term_l)

        # CLAUSE-bound the term on hard punctuation: a qualifier in a
        # DIFFERENT clause must not leak (e.g. "interconnect is optional; a
        # real crossbar fabric" — 'is optional' governs the interconnect
        # clause only).
        c_lo = idx
        while c_lo > 0 and blob[c_lo - 1] not in _CLAUSE_SEPARATORS:
            c_lo -= 1
        c_hi = end
        while c_hi < len(blob) and blob[c_hi] not in _CLAUSE_SEPARATORS:
            c_hi += 1

        # Further bound the term-anchored governor search by coordinating
        # conjunctions (soft boundaries) so "X is mandatory but an optional
        # Y" cannot let the Y-qualifier govern the X-term. The governor
        # segment is the largest conjunction-free span around the term.
        seg_lo = c_lo
        for mm in _SOFT_BOUNDARY_RE.finditer(blob, c_lo, idx):
            seg_lo = mm.end()  # last conjunction before the term
        seg_hi = c_hi
        mm = _SOFT_BOUNDARY_RE.search(blob, end, c_hi)
        if mm:
            seg_hi = mm.start()  # first conjunction after the term
        segment = blob[seg_lo:seg_hi]

        # Backward sub-window inside the segment (adjacent preceding marker).
        back = blob[max(seg_lo, idx - _PRECEDE_WINDOW):idx]
        # Forward sub-window inside the segment (adjacent trailing marker).
        fwd = blob[end:min(seg_hi, end + _TRAIL_WINDOW)]

        suppressed = (
            any(mk in back for mk in _PRECEDING_QUALIFIER_MARKERS)
            or any(mk in back for mk in _REFERENCE_QUALIFIER_MARKERS)
            or any(mk in fwd for mk in _TRAILING_QUALIFIER_MARKERS)
            # TERM-ANCHORED governor (copula-bound), conjunction-scoped.
            or _term_anchored_governor(term_l, segment)
            # bare 'no <term>' immediately preceding the occurrence
            or re.search(rf"\bno\s+{re.escape(term_l)}\b",
                         blob[max(0, idx - 6):end]) is not None
        )
        if not suppressed:
            # A genuine unqualified occurrence — the term IS real evidence.
            return False
        start = end
    # Only reach here when the term occurred at least once and EVERY
    # occurrence was inside an optional/negation window.
    return found_any


# Match a JSON-serialised metadata key whose value is EMPTY: "key": [],
# "key": {}, "key": "", "key": null. A bare key name with an empty value is
# NOT evidence the design mentions that thing (the field exists but carries
# nothing). chip-AGNOSTIC structural match on the serialised L*.json blob.
_RE_EMPTY_JSON_VALUE = re.compile(
    r'"([^"]+)"\s*:\s*(?:\[\s*\]|\{\s*\}|""|null)', re.IGNORECASE)


def _strip_empty_metadata_keys(text: str) -> str:
    """Return `text` with every JSON "<key>": <empty> pair removed, so a
    'mentions' substring search cannot be satisfied by a key NAME whose
    value is empty (e.g. `"interconnect_rules": []`). Non-JSON text and
    keys with non-empty values are left untouched.

    chip-AGNOSTIC: pure structural JSON-shape strip; no chip/IP literal."""
    if not text or '"' not in text:
        return text
    return _RE_EMPTY_JSON_VALUE.sub(" ", text)


def _extension_excluded(ext: str, field_str: str, scoped_text: str,
                        full_text: str) -> bool:
    """v-orch 4c — extension-negation guard. Return True when the spec
    indicates the given ISA extension is absent / excluded, so a
    "contains '<ext>'" rule must be suppressed even if the letter
    appears as a stray substring.

    Fires on:
      * an explicit integer-only / no-FPU marker (for the F/D float
        extensions), OR
      * a literal "no <ext>" / "without <ext>" / "excludes <ext>" /
        "<ext> not supported" phrase for any extension.

    chip-AGNOSTIC: pure phrase grammar; no chip-class literal.
    """
    ext_l = ext.strip().lower()
    if not ext_l:
        return False
    haystacks = [s.lower() for s in (field_str, scoped_text, full_text) if s]
    blob = "\n".join(haystacks)
    if not blob:
        return False
    # Float extensions: any generic integer-only / no-FPU marker excludes.
    if ext_l in ("f", "d", "q") and any(m in blob for m in _INTEGER_ONLY_MARKERS):
        return True
    # Generic explicit negation of THIS extension.
    neg_patterns = [
        rf"\bno\s+['\"]?{re.escape(ext_l)}['\"]?\b",
        rf"\bwithout\s+['\"]?{re.escape(ext_l)}['\"]?\b",
        rf"\bexcludes?\s+['\"]?{re.escape(ext_l)}['\"]?\b",
        rf"\bno\s+{re.escape(ext_l)}[\s-]*extension\b",
        rf"\b{re.escape(ext_l)}[\s-]*extension\s+(?:is\s+)?(?:not|excluded|unsupported|disabled)\b",
        rf"\b{re.escape(ext_l)}\s+not\s+supported\b",
    ]
    for pat in neg_patterns:
        if re.search(pat, blob):
            return True
    return False


# v0.2.102 — for #493 part 1. MANDATORY-vs-OPTIONAL extension guard.
# A "cpu_extensions / cpu_isa contains '<ext>'" rule must only fire when
# the extension is a REQUIRED part of the design's ISA — i.e. it appears
# in the base ISA string (the contiguous rvXX... token's extension
# letters) or in a required/mandatory extensions field. It must NOT fire
# when the extension is only an OPTIONAL mention (e.g. "F (optional)",
# "optionally supports the F extension", or listed under an
# optional-extensions field). This is how L2.cpu_extensions is honestly
# populated: the catalog manifest itself splits isa_extensions_mandatory
# vs isa_extensions_optional, so the matcher mirrors that split.
#
# Base-ISA detection mirrors phase1's canonical RISC-V base token:
#   rv(32|64|128)[base + extension letters], e.g. rv32imf, rv64gc.
# The post-base block must be parsed per the canonical RISC-V ISA-string
# grammar (see _parse_canonical_single_letters): a run of single-letter
# extensions terminates at the first z*/x* multi-letter token, and z*/x*
# tokens (zifencei, zfinx, zicsr, xcustom, ...) are whole tokens — a
# single-letter query like 'f' must NOT match the 'f' buried inside one.
# `_` is allowed as an explicit separator (rv64gc_zifencei), so the token
# regex permits underscores inside the captured block.
_RE_RV_BASE_TOKEN = re.compile(
    r"\brv(?:32|64|128)([a-z_]+)\b", re.IGNORECASE)

# Required-extension field markers (chip-AGNOSTIC field-name vocabulary).
_REQUIRED_EXT_FIELD_MARKERS = (
    "isa_extensions_mandatory", "extensions_mandatory",
    "mandatory_extensions", "required_extensions",
    "extensions_required", "required extensions",
    "mandatory extensions",
)


# Canonical RISC-V single-letter extension ordering (spec §"ISA Extension
# Naming"). A genuine ISA-string extension run is ALWAYS in this order, each
# letter at most once. A token like 'mfast' (from a product name 'RV32MFast')
# is m→f→a — F precedes A, violating canonical order — so it is NOT an ISA
# extension run and must yield zero single-letter extensions (ORGANIC #552).
_CANON_EXT_ORDER = "iemafdgqlcbkjtpvnh"
_CANON_EXT_RANK = {ch: i for i, ch in enumerate(_CANON_EXT_ORDER)}


def _is_canonical_ext_run(run: str) -> bool:
    """True when `run` is a strictly canonical-ordered RISC-V single-letter
    extension run (every char a valid single-letter extension, in increasing
    canonical rank, no repeats). Empty run is canonical (no extensions)."""
    if not run:
        return True
    last = -1
    for ch in run:
        r = _CANON_EXT_RANK.get(ch)
        if r is None or r <= last:
            return False
        last = r
    return True


def _parse_canonical_single_letters(block: str) -> str:
    """Parse the post-base letter block of a RISC-V ISA string and return
    ONLY the canonical single-letter extensions (i/e/m/a/f/d/g/q/c/...).

    Per the RISC-V ISA-string grammar, after the base width the string is
        <single-letter extensions> ( z<multi> | x<multi> | s<multi> )*
    where the single-letter run terminates at the FIRST z/x/s token that
    starts a multi-letter extension, and multi-letter extensions are whole
    tokens (zifencei, zfinx, zicsr, zba, xcustom, ...). Tokens may also be
    separated by '_'. So the 'f' inside 'zifencei' / 'zfinx' is part of a
    multi-letter token and must NOT be reported as a single-letter 'f'.

    Returns the concatenated single-letter extensions (lower-case). The
    multi-letter tail is intentionally dropped here — single-letter
    membership is decided from the returned run, multi-letter tokens are
    matched whole by _multi_letter_tokens().
    """
    out = []
    for seg in block.lower().split("_"):
        # The first segment carries the implicit single-letter run; any
        # later underscore-separated segment is a whole z*/x*/s* token.
        if not seg:
            continue
        if seg[0] in ("z", "x", "s"):
            # Whole multi-letter token segment — contributes no single
            # letters. (A bare single 's' is ambiguous but z/x/s as the
            # first char of an underscore-delimited segment is canonical
            # multi-letter; stop scanning this segment.)
            continue
        run = []
        for ch in seg:
            if ch in ("z", "x"):
                # Start of a multi-letter token inside an implicit run —
                # the single-letter run ends here.
                break
            run.append(ch)
        run_s = "".join(run)
        # ORGANIC #552 — only accept a run that is a strictly canonical
        # RISC-V single-letter extension sequence. A non-canonical run
        # (e.g. 'mfast' from the product name 'RV32MFast') is NOT an ISA
        # extension block and contributes nothing — this stops a stray
        # single-letter query ('F') from matching a buried product-name
        # letter.
        if _is_canonical_ext_run(run_s):
            out.append(run_s)
    return "".join(out)


def _multi_letter_tokens(block: str) -> List[str]:
    """Return whole z*/x*/s* multi-letter extension tokens from a post-base
    block, e.g. 'rv32izifencei_zfinx' → ['zifencei', 'zfinx']. A
    single-letter query never matches inside these; only a full-token query
    (e.g. 'zfinx') matches one."""
    toks: List[str] = []
    for seg in block.lower().split("_"):
        if not seg:
            continue
        if seg[0] in ("z", "x", "s"):
            toks.append(seg)
            continue
        # implicit run that may transition into a z*/x* token without '_'
        i = 0
        while i < len(seg):
            if seg[i] in ("z", "x"):
                toks.append(seg[i:])
                break
            i += 1
    return toks


def _ext_in_base_isa(ext: str, blob: str) -> bool:
    """True when `ext` is a MANDATORY extension inside a base rvXX... ISA
    token, parsed per the canonical RISC-V ISA-string grammar.

      * A single-letter query (e.g. 'f', 'g') matches ONLY a canonical
        single-letter extension in the base run — never the 'f' buried in
        a multi-letter token like 'zifencei' or 'zfinx'.
      * A multi-letter query (e.g. 'zfinx', 'zicsr', 'zifencei') matches
        ONLY a whole z*/x* token (split on '_' or implicit boundary).
    """
    ext_l = ext.strip().lower()
    if not ext_l:
        return False
    for m in _RE_RV_BASE_TOKEN.finditer(blob):
        block = m.group(1).lower()
        if len(ext_l) == 1:
            if ext_l in _parse_canonical_single_letters(block):
                return True
        else:
            if ext_l in _multi_letter_tokens(block):
                return True
    return False


# A standalone single-letter ISA-extension token: the letter must be
# bounded by non-alphabetic delimiters on BOTH sides (start/end, comma,
# space, slash, ...). This is what stops a single-letter query 'F' from
# matching the 'f' buried inside a multi-letter alphabetic run such as the
# RISC-V token 'zifencei'/'zfinx' or the English word 'floating'. Digits
# are allowed neighbours so 'rv32f'-style fragments are not falsely barred,
# but the rvXX base token is handled separately by _ext_in_base_isa.
def _single_letter_ext_token_present(ext: str, blob: str) -> bool:
    ext_l = ext.strip().lower()
    if len(ext_l) != 1 or not ext_l.isalpha():
        return False
    # bounded by anything that is NOT an ASCII letter on both sides
    return re.search(rf"(?<![a-z]){re.escape(ext_l)}(?![a-z])",
                     blob.lower()) is not None


def _ext_field_contains(ext: str, field_str: str, scoped_text: str,
                        full_text: str) -> bool:
    """Token-aware membership test for a single ISA-extension query against
    a cpu_extensions / cpu_isa field.

    A single-letter query (e.g. 'F') is present only when it is EITHER a
    canonical single-letter extension inside an rvXX... ISA token, OR a
    standalone list/word token (delimited by non-letters). It is NEVER
    counted when it is merely a letter buried inside a multi-letter
    alphabetic run (the 'f' inside 'zifencei'/'zfinx'/'floating'). A
    multi-letter query (e.g. 'zfinx') matches a whole z*/x* token or a
    plain substring as before.

    chip-AGNOSTIC: pure RISC-V ISA-string grammar; no chip literal.
    """
    ext_l = ext.strip().lower()
    if not ext_l:
        return False
    haystacks = [s for s in (field_str, scoped_text, full_text) if s]
    blob = "\n".join(haystacks)
    if not blob:
        return False
    if len(ext_l) == 1:
        # Canonical single-letter inside an rvXX token, OR a standalone
        # delimited token — but not buried in a multi-letter run.
        return (_ext_in_base_isa(ext_l, blob)
                or _single_letter_ext_token_present(ext_l, blob))
    # Multi-letter query: whole z*/x* token or plain substring.
    if _ext_in_base_isa(ext_l, blob):
        return True
    return ext_l in blob.lower()


def _ext_in_required_field(ext: str, blob: str) -> bool:
    """True when `ext` appears on the same line as a required/mandatory
    extensions field marker."""
    ext_l = ext.strip().lower()
    if not ext_l:
        return False
    for line in blob.splitlines():
        ll = line.lower()
        if any(mk in ll for mk in _REQUIRED_EXT_FIELD_MARKERS):
            # ext present as a word / list token on this required line.
            if re.search(rf"(?<![a-z0-9]){re.escape(ext_l)}(?![a-z0-9])",
                         ll):
                return True
    return False


def _extension_optional_only(ext: str, field_str: str, scoped_text: str,
                             full_text: str) -> bool:
    """v0.2.102 — for #493 part 1. Return True when the spec mentions the
    extension ONLY as an OPTIONAL extension (so a "contains '<ext>'" rule
    must be suppressed). Honest distinction:

      * NOT optional-only (→ rule may fire) when the extension is in the
        base ISA string (rvXX...<ext>...) OR in a required/mandatory
        extensions field. These are MANDATORY mentions.
      * optional-only (→ suppress) when an explicit optional qualifier
        ("optional", "optionally", "(opt)", listed under an
        optional-extensions field) sits next to the extension AND there
        is no mandatory mention to override it.

    chip-AGNOSTIC: pure phrase / field-name grammar; no chip literal.
    """
    ext_l = ext.strip().lower()
    if not ext_l:
        return False
    haystacks = [s.lower() for s in (field_str, scoped_text, full_text) if s]
    blob = "\n".join(haystacks)
    if not blob:
        return False
    # Mandatory wins: base-ISA membership or required-field membership
    # means the extension is NOT optional-only.
    if _ext_in_base_isa(ext_l, blob) or _ext_in_required_field(ext_l, blob):
        return False
    # Optional-extensions field marker carrying this extension.
    opt_field_markers = (
        "isa_extensions_optional", "extensions_optional",
        "optional_extensions", "extensions_optional",
        "optional extensions",
    )
    for line in blob.splitlines():
        ll = line.lower()
        if any(mk in ll for mk in opt_field_markers):
            if re.search(rf"(?<![a-z0-9]){re.escape(ext_l)}(?![a-z0-9])",
                         ll):
                return True
    # Optional qualifier within a small window around the extension token.
    # e.g. "F (optional)", "optional F extension", "optionally adds F".
    for m in re.finditer(
            rf"(?<![a-z0-9]){re.escape(ext_l)}(?![a-z0-9])", blob):
        lo = max(0, m.start() - 40)
        hi = min(len(blob), m.end() + 40)
        window = blob[lo:hi]
        if re.search(r"\boption(?:al|ally)?\b", window) or \
                re.search(r"\(opt(?:ional)?\)", window):
            return True
    return False


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
        # v-orch 4a — structured-field fallback. When the discrete key is
        # absent, prefer a SCOPED keyword search over the layer section
        # only; lower the confidence below structured hits.
        scoped = _scoped_section_text(facts, field_ref)
        if _structured_field_name(field_ref) and scoped:
            if value.lower() in scoped.lower():
                return (True, _CONF_SCOPED_SUBSTR)
            return (False, 0.0)
        # Generic fallback: substring search in full_text (lowered).
        if value.lower() in full_text.lower():
            return (True, _CONF_FULLTEXT_SUBSTR)
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
        structured = _structured_field_name(field_ref)
        scoped = _scoped_section_text(facts, field_ref)
        # v-orch 4c — extension-negation guard. For cpu_extensions /
        # cpu_isa "contains '<ext>'" rules, suppress when the spec is
        # integer-only or explicitly excludes that extension.
        ext_field = structured in ("cpu_extensions", "cpu_isa")
        for v in values:
            if ext_field and _extension_excluded(
                    v, field_str, scoped, full_text):
                continue
            # v0.2.102 — for #493 part 1. MANDATORY-vs-OPTIONAL guard:
            # suppress when the extension is only an OPTIONAL mention
            # (base ISA / required-field membership overrides this).
            if ext_field and _extension_optional_only(
                    v, field_str, scoped, full_text):
                continue
            # v0.3.2 — for #493 ROUND-2. ISA-extension membership must be
            # token-aware: a single-letter query ('F') must NOT match the
            # 'f' buried inside a multi-letter ISA token ('zifencei',
            # 'zfinx') in the field / scoped section / full text. The raw
            # substring `in` checks below over-fire on packed ISA strings.
            if ext_field:
                # Discrete structured key present → high-confidence hit
                # only when the ext is a genuine token in that field.
                if field_str and _ext_field_contains(v, field_str, "", ""):
                    return (True, 0.9)
                # Structured field with no discrete key → SCOPED fallback.
                if _ext_field_contains(v, "", scoped, ""):
                    return (True, _CONF_SCOPED_SUBSTR)
                # Whole-doc fallback (token-aware over the full text).
                if _ext_field_contains(v, "", "", full_text):
                    return (True, _CONF_FULLTEXT_SUBSTR)
                continue
            # Discrete structured key present → high-confidence hit.
            if v.lower() in field_str:
                return (True, 0.9)
            # Structured field with no discrete key → SCOPED fallback.
            if structured:
                if scoped and v.lower() in scoped.lower():
                    return (True, _CONF_SCOPED_SUBSTR)
                continue
            # Generic field → whole-doc substring fallback (lowered).
            if v.lower() in full_text.lower():
                return (True, _CONF_FULLTEXT_SUBSTR)
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

    # "X mentions 'Y'" or "X mentions 'Y' or 'Z' or ..." — alias for
    # free-text search. The multi-alternative form ("'X' or 'Y' or 'Z'",
    # alternatives joined by lowercase `or` inside one clause) is a
    # DISJUNCTION: a record mentioning ANY alternative is a hit. This
    # mirrors the sibling "contains 'X' or 'Y'" handler (which re.findall's
    # all quoted values and ORs them) — without this, the multi-alternative
    # 'mentions' form fell through to the AND-all free-text fallback below
    # and silently dropped legitimately-matching records (ORGANIC #666,
    # field-agent round-4 v1.0.42). Single quoted value + EOL kept its
    # original semantics as the 1-alternative special case.
    #
    # v1.0.51 — for #681. Three asymmetric guards (chip-AGNOSTIC) the raw
    # whole-doc substring search above lacked:
    #   (1) SCOPE the search to the LAYER named in the rule ("L8 mentions
    #       'interconnect'" must look in the L8 section, not L18 metadata)
    #       — use _scoped_section_text; fall back to whole-doc only when no
    #       per-layer text is captured (e.g. unit-test fixtures with only
    #       `_full_text`), so existing behaviour is preserved.
    #   (2) EMPTY-metadata-key non-evidence: a key NAME whose value is empty
    #       (`"interconnect_rules": []`) must not satisfy a mention.
    #   (3) OPTIONAL / EXPLICIT-NEGATION suppression: a term that occurs only
    #       inside an optional ('可自行加…但不強制', 'may add', '(opt)') or a
    #       NOT-constrained / negated ('must NOT use', '不在…約束的事', '❌')
    #       window is not real evidence of use — same asymmetry the ext_field
    #       'contains' branch already applies via _extension_optional_only /
    #       _extension_excluded.
    m = re.match(r"^(L\d+R?(?:\.[a-zA-Z0-9_\[\]]+)?)\s+mentions\s+(.+)$", p)
    if m:
        field_ref = m.group(1)
        values = re.findall(r"['\"]([^'\"]+)['\"]", m.group(2))
        if values:
            # (1) Scope to the declared layer; fall back to whole-doc only
            # when no per-layer text map exists for this layer.
            scoped = _scoped_section_text(facts, field_ref)
            search_src = scoped if scoped else full_text
            # (2) Drop empty-value metadata key NAMES so they are not
            # mistaken for evidence.
            search_src = _strip_empty_metadata_keys(search_src)
            ft = search_src.lower()
            for value in values:
                v_l = value.lower()
                if v_l not in ft:
                    continue
                # (3) Suppress when this term occurs ONLY inside an
                # optional / explicit-negation window (no genuine mention).
                if _term_optional_or_negated(value, search_src):
                    continue
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
# SoC-top detection (chip-AGNOSTIC heuristic)
# ---------------------------------------------------------------------------
# v-orch 4b — a manifest is treated as a SoC-top / integration-top IP
# (preferred over leaf-core IPs when both match) when it declares a top
# module. Detection (in priority order):
#   1. explicit manifest key `top_module` / `is_soc_top: true`
#      (forward-compatible — schema may add it).
#   2. `implements.architecture` mentions soc / integration / chip-top.
#   3. an rtl_file whose stem ends in `_top` / `_soc` or contains `soc`.
_RE_SOC_TOP_RTL = re.compile(
    r"(?:_top|_soc|chip_top|soc_top)\.(?:s?v|vhd|vhdl)$",
    re.IGNORECASE,
)


def _is_soc_top(manifest: Dict[str, Any]) -> bool:
    """Return True when the manifest declares a top / integration module."""
    if manifest.get("is_soc_top") is True:
        return True
    tm = manifest.get("top_module")
    if isinstance(tm, str) and tm.strip():
        return True
    impl = manifest.get("implements")
    if isinstance(impl, dict):
        arch = str(impl.get("architecture", "")).lower()
        if any(k in arch for k in ("soc", "integration", "chip-top",
                                   "chip_top")):
            return True
    rtl = manifest.get("rtl_files")
    if isinstance(rtl, list):
        for f in rtl:
            if isinstance(f, str) and _RE_SOC_TOP_RTL.search(f):
                return True
    return False


#: The manifest fields this module reads as lists. Each one, when present in
#: another shape, was silently emptied — and each empty has a different and
#: entirely silent consequence downstream:
#:   rtl_files          `ip_catalog_pull` copies nothing AND `find_local_mirror`
#:                      stops testing candidate dirs for RTL (its `if
#:                      rtl_files:` guard), so it can bind the wrong mirror.
#:   depends_on         the transitive auto-include loop in `query_catalog`
#:                      never runs, so a required IP is simply not offered.
#:   synth_safe_params  `synth_param_overrides()` returns `{}`, so the glue
#:                      author instantiates the IP with none of the pins the
#:                      manifest says synthesis needs.
_MANIFEST_LIST_FIELDS = ("rtl_files", "depends_on", "synth_safe_params")


def _shape_refusals_in(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every list field PRESENT in this manifest in a shape this module cannot
    read, each NAMING what arrived. Empty list = nothing to refuse; a field
    that is absent, or is a declared `[]`, is not a refusal."""
    out: List[Dict[str, Any]] = []
    for key in _MANIFEST_LIST_FIELDS:
        _, mismatch = _shape_refusal.read_list_from(m, key)
        if mismatch is not None:
            out.append(mismatch)
    return out


def _manifest_to_match(m: Dict[str, Any], pattern: str,
                       confidence: float) -> CatalogMatch:
    """Build a CatalogMatch from a manifest dict + firing pattern.

    #991 — the three list fields keep their empty-on-unreadable behaviour so
    every existing reader is unchanged, but the refusal is now RECORDED on the
    match instead of discarded. `query_catalog` reads it and refuses the entry;
    a direct caller of this function that ignores `shape_refusals` behaves
    exactly as before rather than silently gaining a new failure mode.
    """
    return CatalogMatch(
        ip_name=m.get("ip_name", "<unknown>"),
        category=m.get("_category", ""),
        version=str(m.get("ip_version", "")),
        license=m.get("license", "<unknown>"),
        canonical_url=m.get("canonical_url", ""),
        canonical_commit=m.get("canonical_commit", ""),
        matched_pattern=pattern,
        confidence=confidence,
        manifest_path=m.get("_manifest_path", ""),
        rtl_files=m.get("rtl_files", []) if isinstance(m.get("rtl_files"), list) else [],
        integration_notes=str(m.get("integration_notes", "")),
        depends_on=m.get("depends_on", []) if isinstance(m.get("depends_on"), list) else [],
        synth_safe_params=(
            m.get("synth_safe_params", [])
            if isinstance(m.get("synth_safe_params"), list) else []
        ),
        shape_refusals=_shape_refusals_in(m),
    )


def _refuse_unreadable_shape(mt: CatalogMatch) -> Optional[str]:
    """The stderr sentence for a manifest whose list fields cannot be read, or
    `None` when there is nothing to refuse.

    REFUSED, not repaired and not offered-with-a-warning, for the same reason
    the #187 self-match guard refuses rather than flags: what follows a match
    is an automatic pull, and an IP pulled without the files, dependencies or
    synthesis pins its own manifest declares fails several steps later with an
    error that names none of this. The remedy is one edit to the manifest, and
    `ip_catalog_validate.py` already states the same requirement — it is simply
    not wired to run before a query.
    """
    if not mt.shape_refusals:
        return None
    parts = "; ".join(_shape_refusal.sentence(r) for r in mt.shape_refusals)
    return (f"manifest {mt.manifest_path or mt.ip_name} declares "
            f"{[r['field'] for r in mt.shape_refusals]} in a shape this "
            f"module cannot read, so this IP is NOT offered: {parts}")


# ---------------------------------------------------------------------------
# Public API: query catalog
# ---------------------------------------------------------------------------
# v-orch 4b — SoC-top preference bias. When a SoC-top IP and a leaf-core
# IP both match, the integration top should rank first so it gets pulled
# without manual help. Applied as a small additive bias at sort time so
# it never promotes a non-matching IP, only re-orders matched ones.
_SOC_TOP_RANK_BIAS = 0.05


# ---------------------------------------------------------------------------
# #187 (BENCHMARK INTEGRITY) — SELF-MATCH GUARD
# ---------------------------------------------------------------------------
# A catalog entry whose upstream repo / module set IS the IC-under-test's own
# reference design must never be offered as a pull candidate: doing so hands the
# generation the answer key through the front door (§4.05 forbids reading the
# oracle; the catalog can hand it over just the same). The guard keys on the
# IC's TOP-LEVEL identity (its ic-name / L1 part identity / top_module) — a
# legitimate COMPONENT IP supplies only a LEAF and its tokens never intersect
# the IC's own top. chip-AGNOSTIC: pure name/repo normalization, no chip literal.

# Generic tokens that are NOT design-identifying (the runner's auto wrapper name,
# family words) — dropped from BOTH the IC identity and the entry token set so a
# shared generic word can never trigger a false self-match.
_GENERIC_IDENT_STOP = frozenset({
    "chip_top", "chip", "top", "soc", "soc_top", "top_level", "toplevel",
    "core", "design", "ip", "rtl", "wrapper", "dut", "module", "tb",
    "src", "hdl", "verilog"})

# L1/L3/L9 fields that carry a SPECIFIC design name (never a family/category).
_IC_IDENT_KEYS = frozenset({
    "part_number", "part_name", "part", "product_name", "design_name",
    "ip_name", "chip_name", "module_name", "top_module", "top", "top_level"})


def _norm_ident(x: Any) -> str:
    """Normalize a name / path / URL to a bare identity token: basename, `.git`
    and HDL extension stripped, lowercased."""
    if not isinstance(x, str):
        return ""
    s = x.strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if not s:
        return ""
    base = s.replace("\\", "/").rstrip("/").split("/")[-1]
    low = base.lower()
    for suf in (".git", ".sv", ".svh", ".vhdl", ".vhd", ".sva", ".v"):
        if low.endswith(suf):
            base = base[: -len(suf)]
            break
    return base.strip().lower()


def _ic_identity_tokens(project: Path, facts: Dict[str, Any],
                        ic_name: Optional[str] = None) -> set:
    """The TOP-LEVEL identity tokens of the IC UNDER TEST (#187) — the run's
    ic-name, the project dir name, and the SPECIFIC design-name fields of L1/L3/L9
    — normalized, with generic tokens dropped. chip-AGNOSTIC."""
    toks: set = set()

    def _add(x: Any) -> None:
        t = _norm_ident(x)
        if t and t not in _GENERIC_IDENT_STOP:
            toks.add(t)

    _add(ic_name)
    _add(project.name)
    for k, v in (facts or {}).items():
        if isinstance(k, str) and isinstance(v, str) \
                and k.rsplit(".", 1)[-1].lower() in _IC_IDENT_KEYS:
            _add(v)
    return toks


def _entry_identity_tokens(mt: CatalogMatch,
                           manifest: Dict[str, Any]) -> set:
    """The module / repo identity tokens a catalog entry SUPPLIES (#187): its
    ip_name, declared top_module, the basenames of its rtl_files, and its
    upstream (canonical_url) repo basename — normalized, generic tokens dropped."""
    toks: set = set()

    def _add(x: Any) -> None:
        t = _norm_ident(x)
        if t and t not in _GENERIC_IDENT_STOP:
            toks.add(t)

    _add(mt.ip_name)
    _add(mt.canonical_url)
    if isinstance(manifest, dict):
        _add(manifest.get("top_module"))
        _add(manifest.get("upstream") or manifest.get("upstream_repo"))
    for f in (mt.rtl_files or []):
        _add(f)
    return toks


#: A `reference/` or `reference_<name>/` path in an input doc's source list is
#: this flow's written convention for "the tree this design ORIGINATES from".
#: RB2-02 (#2063).
_ORIGIN_REF_RE = re.compile(r'\breference[_\-/]([A-Za-z0-9][A-Za-z0-9_\-]*)')

#: Non-identifying words that follow `reference/` in a doc path and name a FILE,
#: not an origin repo. Dropped so a `reference/README.md` citation can never
#: refuse a catalog entry that happens to be called `readme`.
_ORIGIN_FILE_STOP = frozenset({
    "readme", "doc", "docs", "license", "notice", "makefile", "index",
    "images", "img", "fig", "figures", "test", "tests", "sim", "build"})


def _declared_origin_idents(facts: Dict[str, Any]) -> set:
    """The repo identities the INPUT DOCS state this design ORIGINATES from.

    RB2-02 (#2063). Read ONLY from the input-derived text (`_full_text`, which
    `load_project_facts` builds from `phase1/generated_docs/L*.json` and
    `input/docs/L*.md`) — §4.05: the design INPUT, never an oracle.

    THE GRAMMAR, and why it is this one. A doc's source list cites the tree the
    design comes from by a `reference/...` or `reference_<name>/...` path — the
    convention this flow's own Phase-1 docs already use (`reference_serv/doc/
    interface.rst`, `reference/subservient.core`). That prefix is what
    distinguishes an ORIGIN from a component the docs merely recommend reusing:
    a doc that says "drive it with an off-the-shelf UART" names an IP, a doc
    that cites `reference_x/` says where this design came from. Only the origin
    form is collected, so this guard can never refuse a legitimate component IP
    the input happens to mention.
    """
    text = str((facts or {}).get("_full_text") or "")
    if not text:
        return set()
    out: set = set()
    for m in _ORIGIN_REF_RE.finditer(text):
        t = _norm_ident(m.group(1))
        if not t or t in _GENERIC_IDENT_STOP or t in _ORIGIN_FILE_STOP:
            continue
        out.add(t)
    return out


def declared_reuse_idents(project: Path) -> set:
    """The identity tokens the INPUT DOCS name as REUSED IP. RB2-01 (#2063).

    Read from the input-derived text only (§4.05). A catalog MATCH is a
    heuristic guess made from L1-L23 predicates; the input docs naming an IP is
    the design's own statement that this IP is part of it. The runner uses the
    difference to decide whether a catalog match may override the class
    registry's declared `fallback_skill` — see
    `design_one_shot_runner.step_rtl_gen`.

    Deliberately a MEMBERSHIP test over the docs' own words, not a scoring
    heuristic: the question here is only "did the input mention this IP at
    all", and an IP the input never mentions cannot be its declared reuse.
    """
    facts = load_project_facts(project)
    text = str((facts or {}).get("_full_text") or "").lower()
    if not text:
        return set()
    toks = set(re.findall(r"[a-z0-9][a-z0-9_\-]*", text))
    return {t for t in toks if t not in _GENERIC_IDENT_STOP}


def _origin_match_reason(mt: CatalogMatch, manifest: Dict[str, Any],
                         origin_idents: set) -> str:
    """Non-empty reason when the entry's UPSTREAM REPO is the design's own
    stated origin. RB2-02 (#2063).

    MEASURED on the subservient cell (lane rbsub2, 2026-09-06): the token-only
    guard refused `shared_sram_rf` (it shares a name token with the IC) and let
    `serv` through — whose `canonical_url` is the very upstream that cell's own
    L2/L8 cite as `reference_serv`. The token arm cannot see that, because an
    origin's repo name need not share a single character with the design's
    name; here it is a strict SUBSTRING of it and still did not intersect as a
    token. Pulling a design's own origin repo through the catalog hands the
    generation the answer key exactly as a self-match does, so it is refused on
    its own axis — the repo identity — and the token arm stays as the FIRST
    refusal, never the only one.
    """
    if not origin_idents:
        return ""
    ids = {_norm_ident(mt.canonical_url)}
    if isinstance(manifest, dict):
        ids.add(_norm_ident(manifest.get("upstream")
                            or manifest.get("upstream_repo")))
    ids.discard("")
    inter = sorted(ids & origin_idents)
    if not inter:
        return ""
    return ("catalog entry's upstream repo IS the design origin the INPUT docs "
            f"state (repo identity: {', '.join(inter)}) — offering it would "
            "hand back the design's own origin; REFUSED (RB2-02 #2063 "
            "benchmark integrity)")


def _self_match_reason(mt: CatalogMatch, manifest: Dict[str, Any],
                       ic_ident: set, origin_idents: set | None = None) -> str:
    """Non-empty reason when the catalog entry would hand back the IC's OWN
    design — either because its top/name identity intersects the IC identity
    (#187), or because its upstream repo is the origin the input docs state
    (RB2-02 #2063). "" for a legitimate leaf COMPONENT IP."""
    inter = sorted(_entry_identity_tokens(mt, manifest) & ic_ident) if ic_ident else []
    if inter:
        return ("catalog entry supplies the IC-under-test's OWN design (shared "
                f"top/identity token(s): {', '.join(inter)}) — offering it would "
                "hand back the reference design; REFUSED (#187 benchmark integrity)")
    return _origin_match_reason(mt, manifest, origin_idents or set())


def query_catalog(project: Path,
                  catalog_dir: Optional[Path] = None,
                  min_confidence: float = 0.4,
                  ic_name: Optional[str] = None,
                  allow_self_match: bool = False) -> List[CatalogMatch]:
    """Top-level API. Returns ranked list of catalog matches for project.

    #187 — a catalog entry that would hand back the IC-under-test's OWN reference
    design (its top/name intersects the IC identity — see `_self_match_reason`)
    is REFUSED by default (never returned), so the flow can never pull the answer
    key. Pass `allow_self_match=True` to instead RETURN such entries flagged
    (`self_match=True`, with a reason) for an explicit-acknowledgement caller."""
    manifests = load_manifests(catalog_dir)
    if not manifests:
        return []

    facts = load_project_facts(project)
    ic_ident = _ic_identity_tokens(project, facts, ic_name)
    origin_idents = _declared_origin_idents(facts)   # RB2-02 (#2063)
    by_name: Dict[str, Dict[str, Any]] = {
        m.get("ip_name", ""): m for m in manifests if m.get("ip_name")
    }
    matches: List[CatalogMatch] = []
    matched_names: set = set()
    soc_top_names: set = set()

    for m in manifests:
        ip_name = m.get("ip_name", "<unknown>")
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
            mt = _manifest_to_match(m, best_pattern, best_confidence)
            _shape_reason = _refuse_unreadable_shape(mt)
            if _shape_reason:
                print(f"ip_catalog_query: REFUSED unreadable manifest shape "
                      f"{ip_name!r} — {_shape_reason}", file=sys.stderr)
                continue
            reason = _self_match_reason(mt, m, ic_ident, origin_idents)
            if reason:
                mt.self_match = True
                mt.self_match_reason = reason
                print(f"ip_catalog_query: REFUSED self-match {ip_name!r} — "
                      f"{reason}", file=sys.stderr)
                if not allow_self_match:
                    continue          # never offer the IC's own design
            matches.append(mt)
            matched_names.add(ip_name)
            if _is_soc_top(m):
                soc_top_names.add(ip_name)

    # v-orch 4b — auto-include depends_on IPs (transitive). A matched IP's
    # declared dependencies are required for integration, so pull them in
    # even if they did not independently match a predicate. Carry a
    # confidence just at the threshold so they survive filtering but rank
    # below organically-matched IPs.
    pending = [d for mt in matches for d in mt.depends_on]
    while pending:
        dep = pending.pop()
        if not isinstance(dep, str) or dep in matched_names:
            continue
        dm = by_name.get(dep)
        if dm is None:
            continue
        matched_names.add(dep)
        dep_match = _manifest_to_match(
            dm, "depends_on(auto-included)", max(min_confidence, 0.4))
        # #991 — and so does the shape refusal. A dependency pulled in
        # automatically gets no human read at all, so an unreadable manifest
        # here is if anything less likely to be noticed than one that matched.
        _dep_shape = _refuse_unreadable_shape(dep_match)
        if _dep_shape:
            print(f"ip_catalog_query: REFUSED unreadable manifest shape for "
                  f"dependency {dep!r} — {_dep_shape}", file=sys.stderr)
            continue
        # #187 — the self-match guard applies to auto-included dependencies too:
        # a dependency that is itself the IC's own design is refused.
        _dep_reason = _self_match_reason(dep_match, dm, ic_ident,
                                         origin_idents)
        if _dep_reason:
            dep_match.self_match = True
            dep_match.self_match_reason = _dep_reason
            print(f"ip_catalog_query: REFUSED self-match dependency {dep!r} — "
                  f"{_dep_reason}", file=sys.stderr)
            if not allow_self_match:
                continue
        matches.append(dep_match)
        if _is_soc_top(dm):
            soc_top_names.add(dep)
        pending.extend(d for d in dep_match.depends_on
                       if isinstance(d, str) and d not in matched_names)

    # Rank by confidence descending, with a SoC-top bias so the
    # integration top precedes leaf cores at equal/near confidence.
    def _rank_key(mt: CatalogMatch) -> float:
        bias = _SOC_TOP_RANK_BIAS if mt.ip_name in soc_top_names else 0.0
        return mt.confidence + bias

    matches.sort(key=_rank_key, reverse=True)
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
    ap = argparse.ArgumentParser(description="Query ip-catalog against a Plugin project")
    ap.add_argument("project", help="Project root (containing phase1/generated_docs/)")
    ap.add_argument("--catalog-dir", default=None,
                    help="Override ip-catalog/ location")
    ap.add_argument("--min-confidence", type=float, default=0.4,
                    help="Minimum confidence to include in results (default 0.4)")
    ap.add_argument("--ic-name", default=None,
                    help="IC-under-test name (strengthens the #187 self-match "
                         "guard; L1/L3/L9 identity is used when omitted)")
    ap.add_argument("--allow-self-match", action="store_true",
                    help="Return (flagged) instead of refusing a catalog entry "
                         "that supplies the IC's OWN design (#187 — requires "
                         "explicit acknowledgement)")
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
        ic_name=args.ic_name,
        allow_self_match=args.allow_self_match,
    )

    if args.json:
        print(json.dumps([m.to_audit_dict() for m in matches], indent=2))
        return 0

    if not matches:
        print(f"=== ip-catalog query: 0 matches for {project.name} ===")
        return 0

    print(f"=== ip-catalog query: {len(matches)} matches for {project.name} ===")
    for m in matches:
        print(f"  [{m.confidence:.2f}] {m.category}/{m.ip_name} v{m.version}  "
              f"({m.license})")
        print(f"       matched: {m.matched_pattern}")
        if m.depends_on:
            print(f"       depends_on: {', '.join(m.depends_on)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
