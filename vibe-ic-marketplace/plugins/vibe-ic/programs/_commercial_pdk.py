#!/usr/bin/env python3
"""_commercial_pdk.py — private commercial-PDK identifier resolver + the single
runtime home of the NDA foundry tokens.

Two DISTINCT responsibilities live here, on purpose:

  1. FUNCTIONAL config (COMMERCIAL_PDK_ID + derived paths).
     The plugin optionally supports a proprietary (NDA) commercial foundry PDK.
     Its process SKU / codename is confidential and MUST NOT appear literally in
     tracked source (enforced by source_chip_agnostic_check.py). The identifier
     and its on-disk paths are resolved at RUNTIME from a PRIVATE, gitignored
     source — never hardcoded:

         - env var  VIBEIC_COMMERCIAL_PDK_ID          (just the SKU string)
         - env var  VIBEIC_PRIVATE_CONFIG -> a JSON file (full config dict)
         - ~/.config/vibeic/commercial_pdk.json       (default private config)

     When NONE is present (the public / default case) COMMERCIAL_PDK_ID is the
     empty string "", so every `pdk == COMMERCIAL_PDK_ID and COMMERCIAL_PDK_ID`
     branch is inert and public users get generic behaviour. When the owner
     provides the private config, the exact commercial-PDK path activates and
     functionality is preserved.

  2. NDA DETECTOR data (nda_tokens / nda_source_regex / nda_cell_prefixes).
     The anti-fabrication guards (source_chip_agnostic_check, backlog_sanitize_
     check, practical_notes_specificity_check, fpga_gate_level_attestation_check,
     commit_msg_nda_check, nda_diff_scan_check, nda_tracked_tree_scan) must
     RECOGNISE the NDA foundry tokens to catch a leak. The tokens come from the
     PRIVATE config ONLY — the same public-inert / private-active shape
     `project_codenames()` already uses below:

         - env var  VIBEIC_NDA_TOKENS -> a JSON object {role: literal}
         - key      'nda_tokens'      -> the same object, in the private config

     NOTHING TOKEN-DERIVED LIVES IN TRACKED SOURCE. Not the literal, not a
     base64 of it, and not a hash of it.

     THE HISTORY THIS REPLACES, AND WHY BOTH EARLIER SHAPES WERE WRONG.

     (a) The tokens used to live here base64-ENCODED, defended as "`git grep
         <SKU>` therefore finds NOTHING in tracked source". That goal was met
         and it was the wrong goal: a public `nda_tokens()` decoded all eight in
         one call, so every installer of this plugin recovered the whole set on
         one line. Our own plaintext sweeps returned zero BECAUSE the tokens
         were encoded — the sweep measured the encoding, not the exposure.
         ENCODING IS NOT PROTECTION.

     (b) The proposed successor was a salted SHA-256 commitment (`_NDA_DIGESTS`)
         with the salt in this file, plus a plaintext store under `tools/ci/`.
         MEASURED 2026-08-29 on one ordinary 32-core server, pure Python, no
         GPU and no wordlist: exhaustive [a-z0-9]^6 over the 6-character role
         recovers it in 97.6 s. A hand-written wordlist of publicly-known
         foundry and IP-vendor names (~1.2M candidates, seconds) recovers two
         further roles. These tokens are 6-17 characters drawn from a universe
         any search engine enumerates; a commitment over them under a PUBLISHED
         salt is a lock whose key ships beside it. HASHING A LOW-ENTROPY SECRET
         UNDER A PUBLISHED SALT IS NOT PROTECTION EITHER. And this repository is
         PUBLIC (`git ls-remote` succeeds with no credentials) and is itself the
         plugin marketplace source (`claude plugin marketplace add
         vibeic/vibe-ic`), so a plaintext store "outside plugins/" is not out of
         reach of an installer — it is in GitHub code search.

     The only shape left that is actually a shape: the detector holds no secret
     at all, and the secret reaches it at runtime from a private source. A host
     WITHOUT that config cannot answer the NDA question, and every builder here
     says so by raising `NoNdaLiterals` rather than returning a pattern that
     matches everything or nothing. A guard that loses its tokens must REFUSE,
     never report clean.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# (0) The PRIVATE config, loaded once. Both responsibilities below read it, so
# it is resolved before either — the NDA token store is private-sourced now,
# not tracked-source-sourced, which is what puts it after this loader.
# ---------------------------------------------------------------------------
def _load_private_config() -> dict:
    """Best-effort read of the OPTIONAL private commercial-PDK config JSON.
    Returns {} when absent (the public case). Never raises."""
    candidates: List[Path] = []
    env_path = os.environ.get("VIBEIC_PRIVATE_CONFIG")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path.home() / ".config" / "vibeic" / "commercial_pdk.json")
    for path in candidates:
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


_PRIVATE: dict = _load_private_config()



# ---------------------------------------------------------------------------
# (2) NDA detector tokens — resolved at RUNTIME from the PRIVATE config only.
# Keys name the ROLE of each token. A ROLE NAME IS NOT A SECRET (it says a
# foundry brand exists, not which one) and stays in tracked source so a report
# can name what it matched without echoing it. The VALUES live only on a
# configured host.
# ---------------------------------------------------------------------------
#: The canonical roles. A private config may supply any subset; a key outside
#: this tuple is ignored rather than silently trusted, so a typo in a private
#: config cannot quietly become a ninth token nobody's report can name.
NDA_ROLES: Tuple[str, ...] = (
    "foundry_product",
    "sku_full",
    "sku_prefix",
    "foundry_brand1",
    "foundry_brand2",
    "foundry_brand3",
    # IP-vendor family (a commercial OTP/hard-macro provider whose name +
    # a specific macro part number leaked in a landed test fixture, #247).
    # A vendor brand + part number is as much a disclosure as the foundry SKU.
    "ip_vendor",
    "ip_part",
)


def _nda_token_map() -> Dict[str, str]:
    """Role -> literal, from the PRIVATE config ONLY. `{}` in the public case.

    Sources, env first so a CI job can carry the set without a file on disk:
        - env  VIBEIC_NDA_TOKENS   a JSON object {role: literal}
        - key  'nda_tokens'        the same object in the private config
          (~/.config/vibeic/commercial_pdk.json or VIBEIC_PRIVATE_CONFIG)

    The env var is read on EVERY call, not cached at import: the landing
    verifier hands these to a gate subprocess through the environment, and a
    value captured at import time would be a different question than the one
    the caller is asking. Malformed JSON resolves to `{}` — which every builder
    below turns into a raise, never into a clean answer."""
    out: Dict[str, str] = {}
    raw = os.environ.get("VIBEIC_NDA_TOKENS")
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            for role, value in data.items():
                if role in NDA_ROLES and isinstance(value, str) and value.strip():
                    out[role] = value.strip()
    cfg = _PRIVATE.get("nda_tokens") if isinstance(_PRIVATE, dict) else None
    if isinstance(cfg, dict):
        for role, value in cfg.items():
            if (role in NDA_ROLES and isinstance(value, str)
                    and value.strip() and role not in out):
                out[role] = value.strip()
    return out


def nda_tokens() -> List[str]:
    """The NDA foundry / SKU / process / IP-vendor tokens the guards forbid in
    tracked source. EMPTY on an unconfigured host — and empty means "cannot
    answer", never "nothing to find". A caller that scans with this list must
    check `nda_literals_available()` first and report NOT_MEASURED when it is
    False; a scanner driven by an empty token list reports a confident, specific
    PASS over content it never actually looked for."""
    return list(_nda_token_map().values())


def nda_token_for(role: str) -> str:
    """The literal for ONE role, or "" when this host cannot resolve it.

    Ask by ROLE. Two tests used to pick their token by matching a hardcoded
    character prefix of the real value — `startswith("m18")`, `startswith("hp")`
    — which put the first characters of two NDA tokens into tracked test source
    while the store around them was carefully base64'd, and hard-coupled those
    tests to the one real token set. A role is not a secret; the value is."""
    return _nda_token_map().get(role, "")


def nda_literals_available() -> bool:
    """True when this host can answer the NDA question at all.

    The one call a guard makes BEFORE scanning. `nda_tokens()` returning `[]`
    and `nda_tokens()` returning eight tokens that all miss are the same value
    and opposite facts; this separates them so a guard can refuse instead of
    passing."""
    return bool(_nda_token_map())


class NoNdaLiterals(RuntimeError):
    """Raised instead of returning a pattern that matches EVERYTHING.

    These builders join the tokens into an alternation. With an EMPTY token set
    that is an alternation of nothing — `(?<![0-9a-zA-Z])()(?![0-9a-zA-Z])` —
    which matches the empty string at every position. MEASURED by driving the two
    real gates with an empty set:
        commit_msg_nda_check   FAIL: 4 NDA token occurrence(s) in 3 message(s)
        nda_diff_scan_check    FAIL: 1621 NDA token occurrence(s) in the diff
    Both messages are false, confident, and specific. This is the same defect as
    returning `("",)` from a prefix accessor: a detector that says YES to every
    subject.

    IT IS NO LONGER LATENT. It was latent while the token store was eight
    entries compiled into this file; the store is now the private config, so
    the empty set is the ORDINARY state of every public checkout and of every
    CI job that has not been given the tokens. Every caller must handle this
    raise, and `nda_literals_available()` is the cheap way to ask first."""


def _family(*roles: str) -> List[str]:
    """The present subset of `roles`, in the order given, or raise.

    A partial private config is a real state — an operator may hold the foundry
    brands and not the IP-vendor part. The builders answer with what they have
    rather than refusing outright, because a detector that matches six of eight
    tokens is strictly better than one that matches none. It refuses only when
    it has NOTHING, which is the case that would otherwise match everything."""
    toks = _nda_token_map()
    have = [toks[r] for r in roles if toks.get(r)]
    if not have:
        raise NoNdaLiterals(
            "no NDA literals; a pattern built from an empty token set "
            "matches EVERYTHING. A caller must report NOT_MEASURED.")
    return have


#: The hit boundaries. `(?<![0-9a-zA-Z]) … (?![0-9a-zA-Z])` rather than `\b`:
#: it rejects a hit that is merely a substring of a longer alphanumeric word
#: (a vendor name inside a conference URL) while still catching a token glued
#: to punctuation, the way a real mid-sentence leak is — and, unlike `\b`, it
#: behaves the same for a token that starts or ends with a non-word character.
_BOUND_L = r"(?<![0-9a-zA-Z])"
_BOUND_R = r"(?![0-9a-zA-Z])"


def nda_regex_family() -> List[str]:
    """EVERY token the store names, in `NDA_ROLES` order — the family the
    source / tracked-tree / prose detectors match on.

    IT USED TO BE THREE ROLES: `sku_full`, `foundry_product`, `sku_prefix`, the
    "process / foundry-product codename" subset. `nda_tokens()` named eight.
    The five it left out — `foundry_brand1..3`, `ip_vendor`, `ip_part` — are
    exactly the roles the store exists to keep out of tracked artefacts: a
    foundry BRAND is a commercial foundry NAME, and a vendor brand plus a part
    number is the disclosure #247 was filed for.

    MEASURED on this file's own parent commit, with the fictional fixture set,
    by planting one token per role into a tracked file of a throwaway git repo
    and running `nda_tracked_tree_scan.py`:

        index 0,1,2  ->  rc 1   (FAIL — the token was seen)
        index 3..7   ->  rc 0   (PASS — "no NDA token in any tracked path or
                                 content", over a tree that carried one)

    rc 0 there is not a weaker verdict, it is a FALSE one, printed in the
    confident, specific shape this repo removes everywhere else. A token the
    list names and the family cannot match leaves the constraint unenforced for
    that token while every gate reports clean.

    So the family IS the token list. `NDA_ROLES` order (not length order) makes
    the returned index stable and mappable back to a role by
    `nda_regex_family_roles()`, which is what lets a finding be reported as an
    INDEX without echoing what it matched."""
    return _family(*NDA_ROLES)


def nda_regex_family_roles() -> List[str]:
    """The ROLE of each entry of `nda_regex_family()`, index-aligned.

    A detector reports `pattern index 4`; this is how a reader turns that back
    into `foundry_brand2` without the literal ever being printed. Index-aligned
    by construction (both walk `NDA_ROLES` through `_family`), never by two
    lists that happen to agree today."""
    toks = _nda_token_map()
    have = [r for r in NDA_ROLES if toks.get(r)]
    if not have:
        raise NoNdaLiterals(
            "no NDA literals; a pattern built from an empty token set "
            "matches EVERYTHING. A caller must report NOT_MEASURED.")
    return have


def _token_alt(token: str) -> str:
    """One token as a regex ALTERNATIVE: escaped, separator-insensitive.

    `[\s_\-]*` and not `[\s_\-]+`: `nda_content_regex`'s docstring claims a
    multi-word brand's "spaced / unspaced / hyphenated / underscored spellings
    all hit", and with `+` the UNSPACED spelling was the one spelling that did
    not — measured, fictional two-word brand, `nospace` variant: no match from
    either builder. A concatenated brand name is the ordinary way a brand
    reaches a filename or an identifier, so it was the miss that mattered."""
    return r"[\s_\-]*".join(re.escape(part) for part in token.split())


def _b64_fragment(token: str, offset: int) -> str:
    """The base64 substring of `token` that is invariant when the token sits at
    byte `offset` (0, 1 or 2) within a base64 payload — "" when too short.

    Base64 encodes three bytes to four characters, so what a token looks like
    encoded depends on where it starts. Only the characters produced by 3-byte
    groups made ENTIRELY of token bytes are invariant: the first group mixes in
    whatever precedes the token (drop 4 characters when `offset` is non-zero)
    and the last group mixes in whatever follows (drop 4 always). The result is
    a fragment that appears verbatim however the token is embedded.

    Below 8 characters a fragment stops being a signature and starts matching
    ordinary base64 payloads, so it is refused rather than returned — which is
    a REAL BOUND, not a tuning choice: a token of 6 characters has no safe
    base64 signature at any offset, and one of 7 has one at offset 0 only.
    `nda_token_patterns` therefore covers the encoded form of the LONG tokens
    at every offset and the short ones at some or none. That residual is
    reported here rather than papered over with a shorter floor."""
    import base64
    enc = base64.b64encode(("\0" * offset + token).encode()).decode()
    core = enc[(4 if offset else 0):-4]
    return core if len(core) >= 8 else ""


def _b64_alts(token: str) -> List[str]:
    """Every invariant base64 fragment of `token`, over all three offsets.

    WHY A TRACKED-TREE SCANNER NEEDS THIS. The module docstring above records
    that this very repo once kept the token store base64-ENCODED and defended
    it with "`git grep <SKU>` therefore finds NOTHING in tracked source" —
    "Our own plaintext sweeps returned zero BECAUSE the tokens were encoded;
    the sweep measured the encoding, not the exposure." A plaintext-only tree
    scan has exactly that blind spot, and the blind spot is not hypothetical.

    MEASURED 2026-09-07, real store, both trees: 0 hits over the plugin tree
    (7948 blobs) and 1 over the sibling dataset tree — a tracked file still
    carrying that historical shape, from which every role decodes in one call,
    and which the plaintext scan of the same tree reports as a clean rc 0."""
    return sorted({f for f in (_b64_fragment(token, o) for o in (0, 1, 2)) if f})


def nda_token_patterns() -> List[str]:
    """Per-token pattern STRINGS, index-aligned with `nda_regex_family()`.

    For a detector that wants ONE pattern per token so it can report which
    index hit (`nda_tracked_tree_scan`). The single-alternation form is
    `nda_source_regex_str()`.

    These are patterns, not literals. `nda_tracked_tree_scan._patterns()` used
    to `re.compile()` the raw family LITERALS: unescaped, so any regex
    metacharacter in a token silently changed what the gate matched, and a
    literal `.` in a SKU quietly matched any character.

    Each entry also matches the token's BASE64 fragments (see `_b64_alts`),
    unanchored — an encoded token has no word boundary to anchor to, and a
    scanner that only sees plaintext measures the encoding rather than the
    exposure. This widening is deliberately NOT in `nda_source_regex_str()`:
    a commit message or a backlog document does not carry a base64 payload,
    and the prose rules built on that string must not start matching one."""
    out = []
    for t in nda_regex_family():
        alts = [_BOUND_L + _token_alt(t) + _BOUND_R]
        alts += [re.escape(b) for b in _b64_alts(t)]
        out.append("(?:" + "|".join(alts) + ")")
    return out


def nda_source_regex() -> "re.Pattern[str]":
    """Compiled, case-insensitive, boundary-anchored regex over EVERY NDA
    token — built at runtime from the private token store, so no literal token
    lives in this detector's source."""
    return re.compile(nda_source_regex_str(), re.IGNORECASE)


def nda_source_regex_str() -> str:
    """Same as `nda_source_regex()` but the raw pattern STRING, for detectors
    that keep a table of `(name, pattern, message)` tuples.

    Longest token first so an alternation prefers the full SKU over the SKU
    prefix that is a strict prefix of it — the reported span is then the whole
    leak, which is what `nda_mask_neighbourhood` masks."""
    alts = [_token_alt(t) for t in
            sorted(set(nda_regex_family()), key=len, reverse=True)]
    return _BOUND_L + "(" + "|".join(alts) + ")" + _BOUND_R


def nda_cell_prefixes() -> Tuple[str, ...]:
    """Std-cell name prefix(es) that identify the commercial PDK in a gate-level
    netlist (used by the attestation scanner)."""
    # () NOT ("",) — a prefix scanner doing `name.startswith(p)` matches EVERY
    # name against an empty prefix. Empty means "cannot answer"; the caller
    # must report NOT_MEASURED rather than scanning with nothing.
    pfx = _nda_token_map().get("sku_prefix", "")
    return (pfx,) if pfx else ()


def nda_content_regex() -> "re.Pattern[str]":
    """Broad, case-insensitive regex over EVERY NDA token — the foundry
    SKU/process family AND the foundry BRANDS AND the IP vendor/part — for
    scanning arbitrary CONTENT (a commit message, a diff's added lines, a
    filename).

    IT IS NOW THE SAME PATTERN AS `nda_source_regex()`, and this alias is kept
    so the two names still say which SURFACE a caller is scanning. It used to
    be genuinely wider, and that gap was the defect, not the design: the
    narrow side was the SOURCE and TRACKED-TREE scanners, i.e. the surface the
    "no foundry name in any repo artefact" constraint is actually about. Two
    families meant two answers to one question, and the guard whose answer was
    "clean" was the one guarding the repository.

    Shared by `commit_msg_nda_check` and `nda_diff_scan_check` so the message
    guard and the diff guard can never drift."""
    return nda_source_regex()


def nda_role_of(matched: str) -> str:
    """Reverse-map a matched substring to its NDA token ROLE, for MASKED
    reporting (`<NDA-TOKEN:role>`) so a guard never echoes the literal token.
    Case- and separator-insensitive so any spelling of a brand resolves."""
    def _norm(s: str) -> str:
        return re.sub(r"[\s_\-]+", " ", s).strip().lower()

    n = _norm(matched)
    for role, value in _nda_token_map().items():
        if _norm(value) == n:
            return role
    return "unknown"


def nda_mask_neighbourhood(text: str, start: int, end: int, role: str,
                           context: int = 32) -> str:
    """The neighbourhood of the hit at [start, end) with EVERY NDA token in it
    replaced by `<NDA-TOKEN:role>` — not only the one being reported.

    MASKING ONE TOKEN PER FINDING IS NOT MASKING. Both guards used to mask the
    hit they were reporting and print the window around it verbatim, so a
    subject carrying TWO different tokens produced two findings that each
    masked one and echoed the other. MEASURED 2026-08-29 against v1.12.49 with
    the REAL tokens, on a commit message naming both a SKU and a foundry brand:

        commit:<sha>:1  role=sku_full
            wire up <NDA-TOKEN:sku_full> for the <brand printed in full> flow
        commit:<sha>:1  role=foundry_brand1
            wire up <sku printed in full> for the <NDA-TOKEN:foundry_brand1> flow

    Between the two lines both literals appear in the clear, in the output of
    the guard whose stated contract is that the literal is never printed — and
    `commit_msg_nda_check`'s last output line is copied into the push-preflight
    receipt's `summary`, which is a permanent landing record.

    Shared here rather than written twice for the same reason `nda_content_regex`
    is: the message guard and the diff guard must not drift."""
    rx = nda_content_regex()
    parts: List[str] = []
    cursor = 0
    length = 0
    focus_start: Optional[int] = None
    focus_end: Optional[int] = None
    for m in rx.finditer(text):
        segment = text[cursor:m.start(1)]
        parts.append(segment)
        length += len(segment)
        label = f"<NDA-TOKEN:{nda_role_of(m.group(1))}>"
        if m.start(1) == start:
            focus_start, focus_end = length, length + len(label)
        parts.append(label)
        length += len(label)
        cursor = m.end(1)
    parts.append(text[cursor:])
    masked = "".join(parts)
    if focus_start is None:
        # The caller's span did not re-scan to a token. Withhold the window
        # rather than guess: an unanchored slice of a leaking subject is the
        # one thing this function must never return.
        return f"<NDA-TOKEN:{role}> (context withheld)"
    a = max(0, focus_start - context)
    b = min(len(masked), (focus_end or focus_start) + context)
    prefix = "\u2026" if a > 0 else ""
    suffix = "\u2026" if b < len(masked) else ""
    return f"{prefix}{masked[a:b]}{suffix}".strip()


# ---------------------------------------------------------------------------
# (1) Functional config — resolved from the private, gitignored source.
# ---------------------------------------------------------------------------
# The commercial-PDK process SKU. "" in the public/default case (all commercial
# branches inert -> generic behaviour); the exact SKU when the owner configures
# it via env var or private JSON.
COMMERCIAL_PDK_ID: str = (
    os.environ.get("VIBEIC_COMMERCIAL_PDK_ID")
    or (_PRIVATE.get("commercial_pdk_id") if isinstance(_PRIVATE, dict) else "")
    or ""
)


def is_configured() -> bool:
    """True when the owner has provided a commercial-PDK identifier."""
    return bool(COMMERCIAL_PDK_ID)


def project_codenames() -> Tuple[str, ...]:
    """Internal project codename(s) to SANITIZE — the REAL sensitive value(s),
    read from the PRIVATE config only:
        - env var  VIBEIC_PROJECT_CODENAMES   (comma-separated)
        - key      'project_codenames'        (a JSON list) in the private
          config dict (~/.config/vibeic/commercial_pdk.json or VIBEIC_PRIVATE_CONFIG)

    Empty in the public / default case, so the literal codename NEVER lives in
    tracked source (the public deny-list / checks carry only a FICTIONAL
    placeholder). On a configured host these values EXTEND the deny-token set
    and the codename rules, so the sanitizers still catch the true codename in a
    submission / in plugin source — they just no longer SHIP the literal. Same
    public-inert / private-active shape as COMMERCIAL_PDK_ID. chip-AGNOSTIC."""
    vals: List[str] = []
    env = os.environ.get("VIBEIC_PROJECT_CODENAMES", "")
    vals.extend(t.strip() for t in env.split(",") if t.strip())
    cfg = _PRIVATE.get("project_codenames") if isinstance(_PRIVATE, dict) else None
    if isinstance(cfg, list):
        vals.extend(str(t).strip() for t in cfg if str(t).strip())
    seen: set = set()
    out: List[str] = []
    for v in vals:
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return tuple(out)


def cell_model_container_path() -> str:
    """Container-absolute Verilog cell-model path for the commercial PDK, or ""
    when unconfigured. Explicit config `cell_model` wins; otherwise a default is
    derived from the SKU."""
    if _PRIVATE.get("cell_model"):
        return str(_PRIVATE["cell_model"])
    if COMMERCIAL_PDK_ID:
        return f"/pdk/verilog/{COMMERCIAL_PDK_ID}_neg.v"
    return ""


def dff_cells_seed() -> str:
    """Comma-separated flip-flop cell SEED for `fault cut --dff` on the
    commercial PDK. The real set is auto-detected from the netlist and unioned
    with this seed, so a generic std-cell seed is sufficient and safe."""
    seed = _PRIVATE.get("dff_cells")
    if seed:
        return str(seed)
    return "DFFHQD1,DFFHQD2,DFFHQD4,DFFSQD1,DFFRQD1,DFFSRQD1"


def commercial_pdk_config() -> Optional[dict]:
    """The fault-ATPG PDK_CONFIG entry for the commercial PDK, or None when no
    private config is present (public case)."""
    if not COMMERCIAL_PDK_ID:
        return None
    return {"cell_model": cell_model_container_path(),
            "dff_cells": dff_cells_seed()}


def ngspice_shim_name() -> str:
    """Filename of the commercial-PDK ngspice bridge shim, or "" when
    unconfigured (public case -> the SPICE-correlation driver self-skips)."""
    return str(_PRIVATE.get("ngspice_shim_name") or "")


def hspice_lib_globs() -> Tuple[str, ...]:
    """Glob pattern(s) for the foundry HSPICE `.lib` files, or () when
    unconfigured (public case -> the HSPICE-dir discovery finds nothing)."""
    g = _PRIVATE.get("hspice_lib_globs")
    if isinstance(g, (list, tuple)) and g:
        return tuple(str(x) for x in g)
    return ()
