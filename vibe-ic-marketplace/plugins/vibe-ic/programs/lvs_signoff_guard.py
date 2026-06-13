#!/usr/bin/env python3
"""LVS sign-off guard — defensive check against a SILENT FALSE-POSITIVE LVS match.

Captured v0.2.1 (per the v0.1.99 session review §5). The single highest-risk finding of
the doc→GDS pilots was that `eda_lvs` can return a "match" that is VACUOUS: when the
Magic-extracted layout `.subckt <top>` has NO top-level ports (because the pin labels were
never promoted — see ORGANIC-20260531-magic-extraction-no-toplevel-ports), netgen has no
anchor to seed top-level pin matching, and a naive wrapper may still report matched=true.
A silent false-positive LVS is far more dangerous than an explicit fail: an explicit fail
blocks the flow and forces investigation; a silent match lets a wrong design flow downstream
toward tape-out.

This module turns that KNOWN tool limitation into a DETERMINISTIC, GENERAL, process-enforced
gate: parse the top `.subckt` of an extracted SPICE netlist; if it is PORTLESS, refuse to
trust any LVS "match" verdict and RAISE with an actionable message (run the canonical
`port makeall` extraction via magic_port_extract_emit, or DEF-seed via lvs_def_port_seed).

Chip-AGNOSTIC: pure SPICE structural parse, no design-specific names.

CLI:
    python3 lvs_signoff_guard.py --spice <extracted.spice> [--top <name>] [--strict]
    python3 lvs_signoff_guard.py --spice <extracted.spice> --verdict-file <netgen.log>
Exit 0 = trustworthy (ported subckt). Exit 1 = portless extraction (untrustworthy match).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional


class PortlessExtractionError(Exception):
    """Raised when the extracted top .subckt has no ports — an LVS match on it is vacuous."""


def _logical_lines(spice_text: str) -> List[str]:
    """Yield logical SPICE lines: strip `*` comments, splice `+` continuation lines.

    SPICE continues a line when the NEXT non-comment line begins with `+`. Comment lines
    (`*...`) and blank lines are dropped before splicing.
    """
    raw = []
    for line in spice_text.splitlines():
        s = line.rstrip("\n")
        stripped = s.lstrip()
        if not stripped or stripped.startswith("*"):
            continue
        raw.append(s)
    out: List[str] = []
    for s in raw:
        if s.lstrip().startswith("+") and out:
            out[-1] = out[-1].rstrip() + " " + s.lstrip()[1:].lstrip()
        else:
            out.append(s)
    return out


def subckt_ports(spice_text: str, top: Optional[str] = None) -> Optional[List[str]]:
    """Return the port list of the named `.subckt` (or the FIRST subckt if top is None).

    Returns the list of port tokens (possibly empty []), or None if no matching `.subckt`
    line exists at all. Case-insensitive on the `.subckt` keyword and the name match.
    A trailing `M=...`/`PARAMS:` tail (rare on subckt defs) is not treated as a port.
    """
    pat = re.compile(r"^\s*\.subckt\s+(\S+)\s*(.*)$", re.IGNORECASE)
    for line in _logical_lines(spice_text):
        m = pat.match(line)
        if not m:
            continue
        name, rest = m.group(1), m.group(2).strip()
        if top is not None and name.lower() != top.lower():
            continue
        if not rest:
            return []
        # ports are whitespace-separated tokens up to any `params:`/`<name>=<val>` tail
        toks = rest.split()
        ports: List[str] = []
        for t in toks:
            if t.lower() == "params:" or "=" in t:
                break
            ports.append(t)
        return ports
    return None


def has_top_level_ports(spice_text: str, top: Optional[str] = None) -> bool:
    """True iff the top `.subckt` exists AND declares >=1 port."""
    ports = subckt_ports(spice_text, top)
    return bool(ports)


# Phrases netgen emits for a genuine clean match (vs a vacuous/failed one).
# #524: the canonical "match uniquely" recognition is delegated to the SHARED
# classifier (lvs_verdict_tokens.MATCHED_RE) so the token can never drift;
# "the circuits match" stays a local extension (netgen summary-line variant).
_MATCH_PHRASES = (
    "the circuits match",
)


def verdict_claims_match(verdict_text: str) -> bool:
    try:
        import sys as _sys
        from pathlib import Path as _P
        _here = str(_P(__file__).resolve().parent)
        if _here not in _sys.path:
            _sys.path.insert(0, _here)
        import lvs_verdict_tokens as _lvt
        if _lvt.MATCHED_RE.search(verdict_text):
            return True
    except Exception:  # nosec — best-effort; local phrases below still apply
        pass
    low = verdict_text.lower()
    return any(p in low for p in _MATCH_PHRASES)


def assert_lvs_trustworthy(spice_text: str,
                           top: Optional[str] = None,
                           verdict_text: Optional[str] = None) -> List[str]:
    """RAISE PortlessExtractionError if a (claimed) LVS match would be vacuous.

    The defense: a netgen top-level "match" is only trustworthy if the extracted layout
    top `.subckt` actually has ports to anchor the comparison. If it is portless, ANY match
    claim is suspect (netgen had nothing to disambiguate against). Returns the port list on
    success. If `verdict_text` is given, only raises when the verdict ALSO claims a match
    (a portless extraction that already FAILED is honest and needs no extra guard).
    """
    ports = subckt_ports(spice_text, top)
    if ports is None:
        raise PortlessExtractionError(
            f"No top-level .subckt {'`'+top+'` ' if top else ''}found in the extracted "
            "netlist — cannot trust an LVS verdict against it."
        )
    if not ports:
        claims = verdict_text is None or verdict_claims_match(verdict_text)
        if claims:
            raise PortlessExtractionError(
                "Extracted top .subckt is PORTLESS — an LVS 'match' on it is VACUOUS "
                "(netgen has no top-level pins to anchor; a naive wrapper may report a "
                "SILENT FALSE-POSITIVE match). Refuse to sign off. Fix the extraction: run "
                "the canonical `port makeall` flow via magic_port_extract_emit.py "
                "(see ORGANIC-20260531-magic-extraction-no-toplevel-ports), or DEF-seed the "
                "ports via lvs_def_port_seed.py, then re-run LVS."
            )
    return ports


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--spice", required=True, type=Path,
                   help="Extracted layout SPICE netlist to guard.")
    p.add_argument("--top", default=None, help="Top subckt name (default: first subckt).")
    p.add_argument("--verdict-file", type=Path, default=None,
                   help="Optional netgen verdict log; guard only trips if it claims a match.")
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 on a portless extraction even without a verdict file.")
    args = p.parse_args(argv)

    if not args.spice.is_file():
        print(f"ERROR: not a file: {args.spice}", file=sys.stderr)
        return 2
    text = args.spice.read_text(errors="replace")
    verdict = args.verdict_file.read_text(errors="replace") if (
        args.verdict_file and args.verdict_file.is_file()) else (
        None if not args.strict else "circuits match uniquely")
    try:
        ports = assert_lvs_trustworthy(text, args.top, verdict)
    except PortlessExtractionError as e:
        print(f"LVS-GUARD FAIL: {e}", file=sys.stderr)
        return 1
    print(f"LVS-GUARD PASS: top .subckt has {len(ports)} port(s) — verdict is anchorable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
