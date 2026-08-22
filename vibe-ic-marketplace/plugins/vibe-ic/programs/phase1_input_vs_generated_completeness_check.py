#!/usr/bin/env python3
"""
phase1_input_vs_generated_completeness_check.py — Phase 1 coverage gate
========================================================================

Per-prompt completeness audit: for each Phase 1 input prompt (canonical
``input/prompt.md`` or benchmark fallback ``README.md``), harvest every
distinct chip-AGNOSTIC design token using the same regex families as
``phase1_doc_input_completeness_check``, then verify each
token appears somewhere in the union of every Phase 1 output haystack:

    <project>/generated_docs/L*.json   (machine-readable, fed to Phase 2)
    <project>/human_docs/L*.md         (human view, v0.60+)
    <project>/facts.yaml               (fact graph — pre-render source)
    <project>/PROVENANCE.md            (per-fact audit trail)

A token is "captured" when it appears as a substring in any output text.

Why this gate exists
--------------------
Phase 1 is an **interpretation** step (NL prompt → fact graph → L1-L23
render). Existing Phase 1 gates measure structural completeness (all 10
core L docs present, K4 consistency, K5 quality) but none verifies that
**facts the user stated in the prompt actually survived the pipeline**.
A vendor model number mentioned in the prompt that the NL ingester
ignored is silently dropped — no gate catches it.

This gate adds per-prompt accountability:

  * For the input prompt, compute
    ``captured_pct = captured_tokens / distinct_tokens``.
  * PASS if pct >= 0.80 (Phase 1 is interpretation — some prompt
    tokens legitimately get rephrased, normalised, or pushed into
    K3 defaults instead of verbatim copy).
  * WARN if 0.50 <= pct < 0.80.
  * FAIL if pct < 0.50.
  * SKIP if distinct_tokens < 10 (low-information prompt).

Threshold is intentionally more lenient than phase1's 100% (which
audits regex-canonical vendor docs); Phase 1 prompts are free-text
and contain narrative tokens that have no L*.json home.

Usage
-----
    python3 phase1_input_vs_generated_completeness_check.py <project_dir>

Optional flags:
    --prompt <path>      Override prompt discovery (default: auto)
    --fail-threshold N   Override FAIL threshold (default: 0.50)
    --warn-threshold N   Override WARN threshold (default: 0.80)

Exit codes: 0 PASS / WARN / SKIP, 1 FAIL, 2 input error.
Writes report to ``reports/phase1_input_vs_generated_completeness.json``
and a companion Markdown next to it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Canonical path resolution + AI deep-review sidecar credit. Bootstrap
# the programs/ dir onto sys.path so these resolve whether this file is
# run as a script or imported as a module by a test harness. We REUSE
# the sibling gate's sidecar mechanism (`_load_ai_patches_sidecar` /
# `_resolve_sidecar_path`) rather than re-implement it, so both Phase-1
# completeness gates honour the durable AI-recovery channel identically.
_PROGRAMS_DIR = Path(__file__).resolve().parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

import _path_layout as _pl  # noqa: E402
import phase1_doc_input_completeness_check as _doc_input  # noqa: E402

# ─── Chip-AGNOSTIC design-token regex families (mirror phase1) ────────
# Same families as phase1_doc_input_completeness_check so the
# two gates agree on what counts as a design token.
_REGEX_FAMILIES = (
    re.compile(r"@0x[0-9A-Fa-f]+"),
    re.compile(r"(?<![0-9A-Fa-f])0x[0-9A-Fa-f]+"),
    re.compile(r"[A-Z][A-Z0-9_]*\[\d+\]"),
    re.compile(
        r"(?<![A-Za-z0-9])"
        r"\d+\.?\d*[ \t\r]*(?:us|ms|ns|MHz|Hz|kHz|mV|kΩ|Ω|pF|nF|μF|nm|V)"
        r"\b"),
    # Iter-1 darkriscv fix: negative lookbehind on `-` rejects gcc
    # preprocessor flags like `-DBUILD`, `-DHARVARD`, `-D__RISCV__`
    # harvested from make/gcc/ld fenced build-log code blocks. The
    # `-D` glues onto the following all-caps macro name and was
    # being counted as a design identifier; it is a build-tool
    # diagnostic, not an IC fact. Chip-AGNOSTIC: every IC's README
    # may quote build logs.
    re.compile(r"(?<!-)\b[A-Z][A-Z0-9_]{2,}\b"),
)

_STOPLIST = frozenset({
    "JSON", "TRUE", "FALSE", "NULL", "TODO", "FIXME", "NOTE",
    "TBD", "TBA", "RTL", "PASS", "FAIL", "WARN", "INFO",
    # Iter-1 darkriscv: tool log-level prefixes harvested from
    # simulator / build-tool console output. Chip-AGNOSTIC:
    # almost any IC's README quotes a sim/build log somewhere.
    "WARNING", "ERROR", "DEBUG", "TRACE",
    "MIN", "MAX", "AVG", "STD",
    "THE", "AND", "WITH", "FOR", "MUST", "SHALL", "WILL", "FROM",
    "INTO", "THIS", "THAT", "WHEN", "WHERE", "WHILE", "BETWEEN",
    "OVER", "UNDER", "EACH", "ANY", "ALL", "BOTH", "SUCH",
    "BASED", "USED", "USE", "USES", "NEW", "OLD", "ONLY",
    "ONE", "TWO", "THREE", "BIT", "BYTE", "WORD",
    "TYPE", "NAME", "PIN", "PINS", "PORT", "PORTS",
    # Phase-1-prompt narrative noise (markdown headers, license terms)
    "API", "GPU", "CPU", "URL", "GIT", "MIT", "BSD", "GPL",
    "HTTP", "HTTPS", "README", "LICENSE", "FAQ", "GNU",
    "ISO", "IEC", "IEEE", "TM",
    # v1.6.306 — for #205 ORGANIC. Toolchain / debugger / build-system
    # acronyms that show up in every "how to build / how to debug"
    # section of every open-source RTL README. Chip-AGNOSTIC: no IC
    # has GCC / GDB / OPENOCD / WORKSPACE / BSP / SDK as a substantive
    # design fact at any L-layer. Cross-IC evidence: 4+ ICs leak these
    # into the gate denominator at v1.6.305.
    "GCC", "GDB", "OPENOCD", "RISCOF", "LLVM", "CMAKE", "MAKE",
    "NEWLIB", "BINUTILS", "OBJDUMP", "OBJCOPY",
    "WORKSPACE", "BSP", "SDK", "CDT", "JDK", "JAVA", "SBT",
    "VERILATOR_ROOT", "VERILATOR",
})

_TOKEN_REJECT_RES = (
    re.compile(r"\d+\.\s+[A-Za-zμµΩ]+"),
    # Iter-6 picorv32: ISA-reference opcode encoding bitmaps use
    # repeated `X` as a "don't-care" / variable-bits placeholder
    # (e.g. `0000000 ----- 000XX --- XXXXX 0001011`). The bare-word
    # regex matches `XXXXX` as an identifier; it carries no design
    # semantic. Chip-AGNOSTIC: every IC quoting any ISA opcode
    # reference (RISC-V, ARM, custom encoded). Reject runs of 3+ Xs.
    re.compile(r"^X{3,}$"),
)

_BINARY_CTX_WINDOW = 30
_BINARY_CTX_THRESHOLD = 0.30
_WS_RUN_RE = re.compile(r"[ \t]+")

# URL-context false-positive filter. Iter-0 cv32e40p run harvested
# `CONTRIBUTING` (from a github URL `/CONTRIBUTING.md`), `TVLSI` and
# `PATMOS` (from DOI URLs `doi.org/10.1109/TVLSI...`). These are
# URL-path components, not design facts; counting them inflates the
# denominator and forces spurious WARN/FAIL verdicts on every IC
# whose README cites publications or links to repo files.
_URL_CTX_WINDOW = 60
# v1.6.306 — for #205 ORGANIC sub-gap A. The `\.md[)\]]` alternation
# required the trailing `)` or `]` bracket to be in the same chunk,
# but `_URL_CHUNK_BOUNDARY` strips those brackets before the regex
# sees them — so `[contribute](CONTRIBUTING.md)` chunked to
# `CONTRIBUTING.md` (no bracket) and bypassed the URL filter. Replace
# with `\.md\b` to match `.md` as a token-end and pick up the
# bracket-stripped chunk too. Same for `.rst` / `.txt` docs that LLM
# READMEs commonly link as intra-repo files.
_URL_MARKER_RE = re.compile(
    r"(https?://|www\.|\.org/|\.com/|\.md\b|\.rst\b|\.txt\b"
    r"|doi\.org|github\.com|\]\(/|\.io/)",
    re.IGNORECASE)

# v1.6.306 — for #205 ORGANIC sub-gap A. Markdown-link target slug
# detector. Matches the bracket-stripped chunk shape directly
# (`CONTRIBUTING.md`, `CHANGELOG.rst`, `CREDITS.txt`) so the slug
# is rejected even when the URL chunk boundary peeled off `(` `)`.
# Chip-AGNOSTIC.
_MARKDOWN_LINK_SLUG_RE = re.compile(
    r"^[A-Z][A-Za-z0-9_.\-]*\.(?:md|rst|txt|adoc)$",
    re.IGNORECASE,
)

# Markdown reference-section heading detector. Anything from
# `## References` (or Bibliography / Citations / See also / Further
# reading) up to the next `##+` heading is dropped from the prompt
# before token harvesting — academic-citation venue acronyms
# (VLSI, PATMOS, TVLSI) are not facts about the IC itself.
_REF_HEADING_RE = re.compile(
    r"^#{1,6}\s+(references|bibliography|citations|see\s+also|"
    r"further\s+reading|acknowledg(?:e)?ments?|related\s+work)\s*$",
    re.IGNORECASE | re.MULTILINE)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)

# Defaults — overridable via CLI.
_DEFAULT_FAIL_PCT = 0.50
_DEFAULT_WARN_PCT = 0.80
_MIN_TOKENS = 10
_MAX_FILE_CHARS = 600_000

# Reference-doc auto-detection — same heuristic as phase1.
_AUTO_REFERENCE_DOC_GLOBS = (
    "DE0*", "DE1*", "DE2*", "DE10*", "DE10-Lite*", "DE10-Nano*",
    "DE0-Nano*", "de0-*", "de1-*", "de2-*", "de10-*",
    "ug-m10-*", "ug-cyclone*", "ug-stratix*", "ug-arria*",
    "EO[0-9]*", "EM[0-9]*", "EE[0-9]*",
    "bq[0-9]*",
)


def _normalize_token(tok: str) -> str:
    return _WS_RUN_RE.sub(" ", tok).strip()


def _is_design_token(tok: str) -> bool:
    for rx in _TOKEN_REJECT_RES:
        if rx.fullmatch(tok):
            return False
    return True


_WORD_STRUCTURAL_CHARS = frozenset(
    chr(o) for o in (0x07, 0x09, 0x0A, 0x0B, 0x0C, 0x0D))
_CONTROL_CHARS_FILTER = frozenset(
    chr(o) for o in range(0x20)
    if chr(o) not in _WORD_STRUCTURAL_CHARS
) | {chr(0x7F)}


def _looks_like_utf16_le_leak(window: str) -> bool:
    if "\x00" not in window:
        return False
    L = len(window)
    for i in range(0, L - 5):
        a, na, b, nb, c, nc = window[i:i + 6]
        if (na == "\x00" and nb == "\x00" and nc == "\x00"
                and a != "\x00" and b != "\x00" and c != "\x00"):
            return True
    return False


def _is_binary_context(text: str, span_start: int, span_end: int) -> bool:
    a = max(0, span_start - _BINARY_CTX_WINDOW)
    b = min(len(text), span_end + _BINARY_CTX_WINDOW)
    window = text[a:span_start] + text[span_end:b]
    if not window:
        return False
    if _looks_like_utf16_le_leak(window):
        return False
    ctrl_hits = sum(1 for ch in window if ch in _CONTROL_CHARS_FILTER)
    if ctrl_hits >= 2:
        return True
    bad = 0
    for ch in window:
        o = ord(ch)
        if ch in _WORD_STRUCTURAL_CHARS:
            continue
        if 0x20 <= o <= 0x7E:
            continue
        if 0x4E00 <= o <= 0x9FFF:
            continue
        if 0x3000 <= o <= 0x33FF:
            continue
        bad += 1
    return (bad / len(window)) >= _BINARY_CTX_THRESHOLD


_URL_CHUNK_BOUNDARY = frozenset(" \t\n\r()[]{}|<>\"")


def _is_url_context(text: str, span_start: int, span_end: int) -> bool:
    """Reject matches whose contiguous non-whitespace chunk contains
    a URL marker. The chunk is the longest run around the token
    bounded by whitespace / markdown delimiters. This is stricter
    than a fixed radius — `CORE` in `CORE-V family is at the` is
    NOT flagged even if a nearby line has a URL, but `CONTRIBUTING`
    in `https://.../CONTRIBUTING.md` IS flagged because the entire
    URL is one chunk."""
    left = span_start
    while left > 0 and text[left - 1] not in _URL_CHUNK_BOUNDARY:
        left -= 1
    right = span_end
    while right < len(text) and text[right] not in _URL_CHUNK_BOUNDARY:
        right += 1
    chunk = text[left:right]
    if _URL_MARKER_RE.search(chunk):
        return True
    # v1.6.306 — for #205 ORGANIC sub-gap A. Reject markdown-link
    # slugs (`CONTRIBUTING.md`, `CHANGELOG.rst`, `CREDITS.txt`) that
    # bypassed the URL marker because `_URL_CHUNK_BOUNDARY` peeled
    # off the trailing `)`/`]` brackets before the regex saw them.
    if _MARKDOWN_LINK_SLUG_RE.match(chunk):
        return True
    return False


def _strip_reference_sections(text: str) -> str:
    """Drop any markdown section whose heading is References /
    Bibliography / Citations / See also / Further reading /
    Acknowledgements / Related work. Returns the prompt text with
    those sections removed entirely. Chip-AGNOSTIC: matches the
    heading text alone, no chip-specific knowledge."""
    if not text or "#" not in text:
        return text
    # Collect (start, end) byte ranges of each reference section.
    # A reference section runs from its heading start to the start
    # of the next `##+` heading (or EOF).
    ref_heading_matches = list(_REF_HEADING_RE.finditer(text))
    if not ref_heading_matches:
        return text
    all_headings = [m.start() for m in _ANY_HEADING_RE.finditer(text)]
    all_headings.append(len(text))
    drop_ranges = []
    for ref in ref_heading_matches:
        start = ref.start()
        # Find next heading strictly after `start`.
        next_heading = next((h for h in all_headings if h > start),
                            len(text))
        drop_ranges.append((start, next_heading))
    # Splice the text, skipping the drop ranges.
    out = []
    cursor = 0
    for s, e in drop_ranges:
        if cursor < s:
            out.append(text[cursor:s])
        cursor = e
    if cursor < len(text):
        out.append(text[cursor:])
    return "".join(out)


def _harvest_tokens(text: str):
    # Step 1 — strip reference / bibliography / citation sections.
    # Academic-venue acronyms (VLSI, PATMOS, TVLSI) in those
    # sections are not facts about the IC under design.
    text = _strip_reference_sections(text)
    seen_clean: set = set()
    seen_dirty: set = set()
    for rx in _REGEX_FAMILIES:
        for m in rx.finditer(text):
            tok = m.group(0)
            tok = tok.strip() if isinstance(tok, str) else ""
            if (not tok or "\n" in tok or "\r" in tok or "\t" in tok
                    or tok.upper() in _STOPLIST):
                continue
            normalised = _normalize_token(tok)
            if not _is_design_token(normalised):
                seen_dirty.add(normalised)
                continue
            if _is_binary_context(text, m.start(), m.end()):
                seen_dirty.add(normalised)
                continue
            # Step 2 — URL-context filter. Tokens harvested from
            # inside markdown links / DOI / repo URLs are slugs,
            # not design facts.
            if _is_url_context(text, m.start(), m.end()):
                seen_dirty.add(normalised)
                continue
            seen_clean.add(normalised)
    seen_dirty -= seen_clean
    return seen_clean, seen_dirty


def _is_reference_doc(name: str) -> bool:
    import fnmatch
    for g in _AUTO_REFERENCE_DOC_GLOBS:
        if fnmatch.fnmatch(name, g):
            return True
    return False


def _discover_prompt(project: Path) -> tuple[Path | None, str]:
    """Find the Phase 1 input prompt for this project.

    Priority order (highest first):
      1. <project>/input/prompt.md       — canonical Phase 1 input
      2. <project>/input/prompt.txt
      3. <project>/prompt.md
      4. <project>/README.md             — benchmark fallback
      5. <project>/input/docs/*.md       — pre-extracted spec doc
    """
    candidates = [
        project / "input" / "prompt.md",
        project / "input" / "prompt.txt",
        project / "prompt.md",
        project / "README.md",
    ]
    for c in candidates:
        if c.is_file():
            return c, c.relative_to(project).as_posix()
    docs_dir = project / "input" / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.glob("*.md")):
            return p, p.relative_to(project).as_posix()
        for p in sorted(docs_dir.glob("*.txt")):
            return p, p.relative_to(project).as_posix()
    return None, ""


def _load_generated_haystacks(project: Path):
    """Concatenate every Phase 1 output text. The haystack covers
    generated_docs/L*.json, human_docs/L*.md, facts.yaml,
    PROVENANCE.md, AND the AI deep-review sidecar
    (phase1/ai_deep_review_patches.json). Each piece is loaded into a
    dict so per-layer attribution stays possible.

    Path resolution goes through ``_pl.generated_docs_dir`` /
    ``_pl.human_docs_dir`` (canonical ``<project>/phase1/...``) so this
    gate behaves identically to its sibling
    ``phase1_doc_input_completeness_check`` when invoked with the
    project ROOT. The old hard-coded ``<project>/generated_docs`` path
    produced a spurious "no Phase 1 output" SKIP because the canonical
    layout nests Phase-1 artefacts under ``phase1/``.

    Sidecar credit: the AI deep-review sidecar is the durable home of
    AI-recovered cells (``phase1_one_shot_runner`` rewrites
    generated_docs/L*.json from scratch each run, so inline AI patches
    do NOT survive regeneration). We credit ONLY the RECOVERED
    ``value``/``field`` of each patch (via
    ``_load_sidecar_recovered_values``), NEVER the patch's
    ``source_quote`` provenance — a source_quote is a verbatim copy of
    prompt text, so crediting it would auto-pass every quoted design
    token and blanket-pass a genuinely incomplete generated doc set
    (§4.05 no-leak: the sidecar credits RECOVERY, not the quote). A
    prompt token is creditable iff it literally appears in the L doc OR
    in a recovered sidecar VALUE.
    """
    out: dict = {}
    gen = _pl.generated_docs_dir(project)
    sidecar = _load_sidecar_recovered_values(project)
    seen_layers: set = set()
    if gen.is_dir():
        for p in sorted(gen.glob("L*.json")):
            try:
                raw = p.read_text(errors="replace")
            except Exception:
                continue
            layer = p.stem
            seen_layers.add(layer)
            sidecar_text = sidecar.get(layer, "")
            combined = raw + ("\n" + sidecar_text if sidecar_text else "")
            out[layer + ".json"] = _make_blob(combined)
    human = _pl.human_docs_dir(project)
    if human.is_dir():
        for p in sorted(human.glob("L*.md")):
            try:
                raw = p.read_text(errors="replace")
            except Exception:
                continue
            out[p.stem + ".md"] = _make_blob(raw)
    facts = project / "facts.yaml"
    if facts.is_file():
        try:
            out["facts.yaml"] = _make_blob(facts.read_text(errors="replace"))
        except Exception:
            pass
    prov = project / "PROVENANCE.md"
    if prov.is_file():
        try:
            out["PROVENANCE.md"] = _make_blob(prov.read_text(errors="replace"))
        except Exception:
            pass
    # Sidecar layers with no matching generated_docs/L*.json — uncommon
    # but legitimate (patches pre-staged before phase1 ran). Surface
    # them under a sidecar-tagged key so their tokens still count — but
    # ONLY when Phase 1 has actually produced a generated_docs dir.
    # With ZERO generated docs the gate must SKIP ("run phase1 first"),
    # exactly as the sibling guards before its sidecar loop; injecting
    # sidecar-only layers here would otherwise turn a no-output project
    # into a spurious verdict. §4.05.
    if gen.is_dir():
        for layer, sidecar_text in sidecar.items():
            if layer in seen_layers or not sidecar_text:
                continue
            out[layer + ".sidecar"] = _make_blob(sidecar_text)
    return out


def _load_sidecar_recovered_values(project: Path) -> dict:
    """Return {layer: text} crediting ONLY the AI-RECOVERED ``value``/``field``
    of each ai_deep_review_patch entry — NEVER the ``source_quote`` (or any
    prompt-echoing provenance field).

    §4.05 no-leak: a patch's ``source_quote`` is a verbatim copy of prompt text;
    appending it to the completeness haystack would auto-credit every design
    token the agent quoted as provenance, so a generated doc set that captured
    NONE of the prompt facts would still be credited 100% complete. Crediting
    only the recovered cell value (the fact that actually landed) keeps the
    sidecar a genuine AI-recovery channel without blanket-passing.
    """
    side = _doc_input._resolve_sidecar_path(project)
    if side is None:
        return {}
    try:
        data = json.loads(side.read_text(errors="replace"))
    except Exception:
        return {}
    patches = data.get("patches") or {}
    if not isinstance(patches, dict):
        return {}
    out: dict = {}
    for layer, lst in patches.items():
        if not isinstance(lst, list):
            continue
        vals: list = []
        for entry in lst:
            if not isinstance(entry, dict):
                continue
            # credit ONLY the recovered cell: the value(s) it fills and the
            # field name it targets. Everything else (source_quote, quote,
            # evidence, rationale, provenance) is excluded.
            for key in ("value", "values", "field"):
                v = entry.get(key)
                if v is None:
                    continue
                if isinstance(v, (list, tuple)):
                    vals.extend(str(x) for x in v)
                elif isinstance(v, dict):
                    vals.extend(str(x) for x in v.values())
                else:
                    vals.append(str(v))
        if vals:
            out[layer] = " ".join(vals)
    return out


_V1_6_305_RE_TRAILING_ZERO_UNIT = re.compile(
    # v1.6.305 — for #204 round-3 inverse regression. Strip the
    # trailing `.0` before any engineering-unit suffix so that
    # source-spelled `"100 MHz"` and rendered `"100.0 MHz"` both
    # collapse to the same canonical form `"100 MHz"` before
    # substring match. Mirror unit-token set covers Hz scaling
    # tier + common SI prefixes used in datasheets.
    r"(\d+)\.0(\s*)(MHz|GHz|kHz|Hz|ns|us|ms|ps|s|V|mV|uV|kV|"
    r"mA|uA|nA|A|W|mW|uW|kW|B|KB|MB|GB|TB|"
    r"mhz|ghz|khz|hz)\b",
    re.IGNORECASE,
)


def _v1_6_305_strip_dot_zero_unit(text: str) -> str:
    """v1.6.305 — for #204 round-3. Strip the trailing `.0` from
    integer-valued engineering-unit literals so source and rendered
    forms match symmetrically. Both `"100 MHz"` and `"100.0 MHz"`
    collapse to `"100 MHz"`.

    Chip-AGNOSTIC.
    """
    return _V1_6_305_RE_TRAILING_ZERO_UNIT.sub(r"\1\2\3", text)


def _make_blob(raw: str) -> dict:
    norm = _WS_RUN_RE.sub(" ", raw)
    no_space = norm.replace(" ", "")
    # v1.6.305 — for #204 round-3. Build `.0`-collapsed variants
    # so that source-token / rendered-output asymmetries on
    # integer-valued engineering quantities (e.g. `"100 MHz"` vs
    # `"100.0 MHz"`) match symmetrically. Both forms collapse to
    # the bare-int variant `"100 MHz"` before substring match.
    raw_dz = _v1_6_305_strip_dot_zero_unit(raw)
    norm_dz = _v1_6_305_strip_dot_zero_unit(norm)
    no_space_dz = norm_dz.replace(" ", "")
    return {
        "raw": raw,
        "norm": norm,
        "no_space": no_space,
        # Iter-2 ibex fix G3: pre-lowercase haystacks so short
        # all-caps acronyms (PMP, FPGA, JTAG, ALU, MMU, IRQ, DMA,
        # PHY) can match schema-convention lowercase field names
        # (pmp_regions, fpga_chip) without paying per-call lower()
        # cost.
        "raw_lc": raw.lower(),
        "no_space_lc": no_space.lower(),
        # v1.6.305 — `.0`-collapsed variants for #204 round-3.
        "raw_dz": raw_dz,
        "norm_dz": norm_dz,
        "no_space_dz": no_space_dz,
    }


def _is_captured(tok: str, layer_blobs) -> list:
    """Return list of haystack names that contain the token (under
    raw / single-space / no-space normalisation).

    Iter-2 G3: short all-caps acronyms (3-6 chars, pure alpha) ALSO
    matched case-insensitively against `raw_lc` / `no_space_lc`.
    Schema convention is lowercase snake_case field names; prompts
    use the uppercase acronym; the mechanical case mismatch was
    producing 40 percent of misses on acronym-heavy READMEs.
    Limited to short pure-alpha tokens so we do not collapse
    distinct identifiers like ABC123 (could legitimately differ
    from abc123 in another field)."""
    if not tok:
        return []
    tok_ns = tok.replace(" ", "")
    # v1.6.302 — for #203 ORGANIC. Widen case-insensitive eligibility
    # to admit (a) alphanumeric ALL-CAPS acronyms (`ICE40`, `RS485`,
    # `XC3S100E`, `RV32IM`, etc. — `isalpha` previously dropped them)
    # and (b) 7+ char ALL-CAPS architecture / protocol vocabulary
    # (`HARVARD`, `THREADING`, `PIPELINE`, ... — `len <= 6` clamp
    # previously dropped them). Token must start with a letter and
    # consist only of letters + digits; upper bound at 16 chars
    # excludes paragraph fragments.
    case_insensitive = (
        3 <= len(tok) <= 16
        and tok.isupper()
        and tok[0].isalpha()
        and all(ch.isalnum() for ch in tok)
    )
    tok_lc = tok.lower() if case_insensitive else None
    tok_ns_lc = tok_ns.lower() if case_insensitive else None
    # v1.6.305 — for #204 round-3. Apply the same `.0`-collapse
    # normalisation to the token so source-`"100 MHz"` matches
    # rendered-`"100.0 MHz"` (and vice versa). Both collapse to
    # `"100 MHz"` before substring match.
    tok_dz = _v1_6_305_strip_dot_zero_unit(tok)
    tok_ns_dz = tok_dz.replace(" ", "")
    hits: list = []
    for layer, blob in layer_blobs.items():
        if ((tok in blob["raw"]) or
                (tok in blob["norm"]) or
                (tok_ns in blob["no_space"])):
            hits.append(layer)
            continue
        # v1.6.305 — `.0`-collapsed match. Symmetric: both source
        # token and haystack are normalised to bare-int form. This
        # closes the inverse asymmetry from v1.6.303/v1.6.304 where
        # source `"X MHz"` would miss rendered `"X.0 MHz"`, OR
        # source `"X.0 MHz"` would miss rendered `"X MHz"`.
        # `.get()` fallback supports older test fixtures that
        # pre-date the `*_dz` blob fields.
        if ((tok_dz in blob.get("raw_dz", "")) or
                (tok_dz in blob.get("norm_dz", "")) or
                (tok_ns_dz in blob.get("no_space_dz", ""))):
            hits.append(layer)
            continue
        if case_insensitive and (
                tok_lc in blob["raw_lc"]
                or tok_ns_lc in blob["no_space_lc"]):
            hits.append(layer)
    return hits


def _verdict_from_pct(pct: float, fail_pct: float,
                      warn_pct: float) -> str:
    if pct >= warn_pct:
        return "PASS"
    if pct >= fail_pct:
        return "WARN"
    return "FAIL"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="phase1_input_vs_generated_completeness_check",
        description="Per-prompt completeness gate: harvested tokens "
                    "from the Phase 1 input prompt must land in the "
                    "union of generated_docs / human_docs / facts.yaml.",
    )
    parser.add_argument("project_dir",
                        help="Path to project directory.")
    parser.add_argument("--prompt", default=None,
                        help="Override prompt discovery with a "
                             "specific file path.")
    parser.add_argument("--fail-threshold", type=float,
                        default=_DEFAULT_FAIL_PCT,
                        help=f"FAIL below this fraction "
                             f"(default {_DEFAULT_FAIL_PCT}).")
    parser.add_argument("--warn-threshold", type=float,
                        default=_DEFAULT_WARN_PCT,
                        help=f"WARN below this fraction, PASS above "
                             f"(default {_DEFAULT_WARN_PCT}).")
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_usage()
        return 2
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 2

    if args.prompt:
        prompt_path = Path(args.prompt).resolve()
        if not prompt_path.is_file():
            print(f"FAIL — --prompt file not found: {prompt_path}")
            return 2
        prompt_name = prompt_path.name
    else:
        prompt_path, prompt_name = _discover_prompt(project)
        if prompt_path is None:
            print("SKIP — no Phase 1 input prompt discoverable "
                  "(looked for input/prompt.md, README.md, "
                  "input/docs/*.md).")
            return 0

    try:
        prompt_text = prompt_path.read_text(errors="replace")[:_MAX_FILE_CHARS]
    except Exception as e:
        print(f"FAIL — could not read prompt {prompt_path}: {e}")
        return 2

    layer_blobs = _load_generated_haystacks(project)
    if not layer_blobs:
        print("SKIP — no Phase 1 output found "
              "(generated_docs/L*.json, human_docs/L*.md, "
              "facts.yaml all absent). Run /vibe-ic-phase1 first.")
        return 0

    is_ref = _is_reference_doc(prompt_path.name)
    design_toks, garble_toks = _harvest_tokens(prompt_text)
    n = len(design_toks)
    n_garble = len(garble_toks)

    # Per-token attribution runs regardless of token count — even
    # a low-signal prompt deserves to show what landed where. The
    # verdict alone changes based on _MIN_TOKENS.
    captured_layers: dict = {}
    captured_cnt = 0
    missing: list = []
    for tok in design_toks:
        hits = _is_captured(tok, layer_blobs)
        if hits:
            captured_cnt += 1
            captured_layers[tok] = hits
        else:
            missing.append(tok)
    per_layer_hits: dict = {layer: 0 for layer in layer_blobs}
    for tok, layers in captured_layers.items():
        for layer in layers:
            per_layer_hits[layer] += 1
    pct = captured_cnt / n if n else 1.0
    missing_sample = sorted(missing, key=lambda x: (-len(x), x))[:50]

    if n < _MIN_TOKENS:
        verdict = "SKIP_LOW_TOKENS"
        report = {
            "gate": "phase1_input_vs_generated_completeness_check",
            "verdict": verdict,
            "fail_threshold": args.fail_threshold,
            "warn_threshold": args.warn_threshold,
            "prompt": prompt_name,
            "is_reference_doc": is_ref,
            "distinct_tokens": n,
            "garble_tokens": n_garble,
            "captured": captured_cnt,
            "missing": len(missing),
            "captured_pct": round(pct, 4),
            "haystack_layers": sorted(layer_blobs.keys()),
            "per_layer_hits": {k: per_layer_hits[k]
                               for k in sorted(per_layer_hits.keys())},
            "missing_sample": missing_sample,
        }
        _write_reports(project, report, prompt_name, missing_sample)
        print(f"SKIP_LOW_TOKENS — prompt has only {n} design tokens "
              f"(min {_MIN_TOKENS}); not enough signal to audit. "
              f"(For reference: captured {captured_cnt}/{n} = "
              f"{pct:.1%}.)")
        return 0

    verdict = _verdict_from_pct(pct, args.fail_threshold,
                                args.warn_threshold)
    if is_ref:
        verdict = "SKIP_REFERENCE"

    report = {
        "gate": "phase1_input_vs_generated_completeness_check",
        "verdict": verdict,
        "fail_threshold": args.fail_threshold,
        "warn_threshold": args.warn_threshold,
        "prompt": prompt_name,
        "is_reference_doc": is_ref,
        "distinct_tokens": n,
        "garble_tokens": n_garble,
        "raw_total": n + n_garble,
        "captured": captured_cnt,
        "missing": len(missing),
        "captured_pct": round(pct, 4),
        "haystack_layers": sorted(layer_blobs.keys()),
        "per_layer_hits": {k: per_layer_hits[k]
                           for k in sorted(per_layer_hits.keys())},
        "missing_sample": missing_sample,
    }
    _write_reports(project, report, prompt_name, missing_sample)

    if verdict == "FAIL":
        print(f"FAIL — prompt {prompt_name}: captured "
              f"{captured_cnt}/{n} = {pct:.1%} "
              f"(below {args.fail_threshold:.0%}).")
        print(f"  missing sample: "
              f"{', '.join(missing_sample[:8])}")
        return 1
    if verdict == "WARN":
        print(f"WARN — prompt {prompt_name}: captured "
              f"{captured_cnt}/{n} = {pct:.1%} "
              f"(below {args.warn_threshold:.0%} but above "
              f"{args.fail_threshold:.0%}).")
        print(f"  missing sample: "
              f"{', '.join(missing_sample[:8])}")
        return 0
    if verdict.startswith("SKIP"):
        print(f"{verdict} — prompt {prompt_name} ({n} tokens).")
        return 0
    print(f"PASS — prompt {prompt_name}: captured "
          f"{captured_cnt}/{n} = {pct:.1%} "
          f"(>= {args.warn_threshold:.0%}).")
    return 0


def _write_reports(project: Path, report: dict, prompt_name: str,
                   missing_sample: list) -> None:
    reports_dir = project / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_out = reports_dir / "phase1_input_vs_generated_completeness.json"
    md_out = reports_dir / "phase1_input_vs_generated_completeness.md"
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    md_lines = [
        "# Phase 1 — input prompt → Phase 1 output completeness",
        "",
        f"**Verdict**: {report['verdict']}",
        f"**Prompt**: `{prompt_name}`",
        f"**Reference doc**: {report['is_reference_doc']}",
        f"**Captured pct**: {report.get('captured_pct', 1.0):.1%}",
        f"  - distinct tokens: {report['distinct_tokens']}",
        f"  - garble / artefact: {report.get('garble_tokens', 0)}",
        f"  - captured: {report.get('captured', 0)}",
        f"  - missing: {report.get('missing', 0)}",
        "",
        f"**Thresholds**: FAIL < {report['fail_threshold']:.0%}, "
        f"WARN < {report['warn_threshold']:.0%}, PASS otherwise.",
        "",
        "## Haystack layers searched",
        "",
    ]
    for layer in report.get("haystack_layers", []):
        hits = report.get("per_layer_hits", {}).get(layer, 0)
        md_lines.append(f"- `{layer}`: {hits} token hit(s)")
    md_lines.extend([
        "",
        "## Missing tokens (sample, longest first)",
        "",
    ])
    if missing_sample:
        for t in missing_sample[:50]:
            md_lines.append(f"- `{t}`")
    else:
        md_lines.append("(none — every harvested token was captured)")
    md_lines.append("")
    md_lines.append(
        "Cell = chip-AGNOSTIC design token (numeric+unit, hex "
        "constant, all-caps identifier, indexed signal). Harvest "
        "matches `phase1_doc_input_completeness_check`. "
        "Phase 1 threshold is intentionally lower than Phase 1 (doc-extraction) "
        "(interpretation vs extraction) — see file header.")
    md_out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
