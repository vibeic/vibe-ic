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

WHY `--top` IS DERIVED AND NOT DEFAULTED TO THE FIRST `.subckt` (vibe-ic#693)
----------------------------------------------------------------------------
`subckt_ports(text, top=None)` returns the FIRST `.subckt` in the file. That
default is correct only for a single-subckt fixture. A Magic-extracted
netlist is emitted BOTTOM-UP: the first `.subckt` is always a leaf standard
cell, and the design top is last. MEASURED over the 13 extracted netlists in
the published corpus, 13/13:

    FIRST .subckt                        ports   design top          ports
    sky130_fd_sc_hd__conb_1                  6   user_project_wrapper  639
    sky130_fd_sc_hd__decap_8                 4   ibex_core             266
    sky130_fd_sc_hd__a21oi_1                 8   chip_top              187
    sky130_fd_sc_hd__tapvpwrvgnd_1           2   spm                    38

So a `--top`-less invocation guards a STANDARD CELL's pin list. Standard
cells always have pins, so the guard returns PASS unconditionally — a gate
structurally incapable of firing, which is the defect it exists to catch,
moved one level down. Its unit fixture (`.subckt spm_top` alone) hid this
because there first == top.

The top is therefore DERIVED STRUCTURALLY: the `.subckt` that no other
`.subckt` instantiates — the root of the instantiation DAG. Measured unique
and correct on 13/13. Ordering conventions ("it's the last one") are not
relied on. When the derivation is ambiguous (0 or >1 roots) the guard does
not guess: it checks EVERY root, so an ambiguous file cannot buy a pass.

CLI:
    python3 lvs_signoff_guard.py <project_dir> [--verdict-file <netgen.log>]
    python3 lvs_signoff_guard.py --spice <extracted.spice|glob> [--top <name>]
    python3 lvs_signoff_guard.py --spice <f> --verdict-file <netgen.log> [--strict]
Exit 0 = trustworthy (ported subckt). Exit 1 = portless extraction (untrustworthy
match). Exit 2 = NOT CHECKED (no extracted netlist to guard) — printed with a
`VACUOUS_PASS:` sentinel so the flow's verdict tier sees it rather than
crediting a silent pass.
"""
from __future__ import annotations

import argparse
import glob as _glob
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


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


_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)", re.IGNORECASE)
_ENDS_RE = re.compile(r"^\s*\.ends\b", re.IGNORECASE)
_INST_RE = re.compile(r"^\s*[Xx]\S*\s+(.*)$")


def defined_subckts(spice_text: str) -> List[str]:
    """Every `.subckt` name defined in the netlist, in file order."""
    return [m.group(1) for m in
            (_SUBCKT_RE.match(ln) for ln in _logical_lines(spice_text)) if m]


def derive_tops(spice_text: str) -> List[str]:
    """The STRUCTURAL roots: `.subckt`s that no other `.subckt` instantiates.

    A SPICE subcircuit call is `X<inst> <net>... <subckt-name> [p=v ...]`, so
    the reference is the last token that is not a `name=value` parameter. Any
    definition that never appears as such a reference is a root.

    Returns every root, in file order. Callers guard ALL of them: with one
    root that is the design top, and with several the file is ambiguous and
    guessing one would be exactly the silent choice this program exists to
    refuse. Empty list = no `.subckt` at all.
    """
    defined = defined_subckts(spice_text)
    referenced = set()
    for ln in _logical_lines(spice_text):
        if _SUBCKT_RE.match(ln) or _ENDS_RE.match(ln):
            continue
        m = _INST_RE.match(ln)
        if not m:
            continue
        toks = [t for t in m.group(1).split() if "=" not in t]
        if toks:
            referenced.add(toks[-1])
    return [d for d in defined if d not in referenced]


def resolve_tops(spice_text: str, top: Optional[str] = None) -> Tuple[List[str], str]:
    """Which `.subckt`(s) this guard must judge, and how that was decided.

    An explicit `--top` always wins. Otherwise the structural roots are used.
    NEVER falls back to "the first subckt": on a real hierarchical extraction
    that is a leaf standard cell (see the module docstring) and the guard
    would pass unconditionally.
    """
    if top is not None:
        return [top], f"explicit --top {top}"
    roots = derive_tops(spice_text)
    if len(roots) == 1:
        return roots, f"derived structurally: {roots[0]} is the only .subckt no other instantiates"
    if not roots:
        return [], "no .subckt is a structural root (every definition is instantiated — cyclic or empty netlist)"
    return roots, ("ambiguous: %d structural roots (%s) — ALL are guarded, "
                   "because picking one would be a silent choice"
                   % (len(roots), ", ".join(roots)))


# Phrases netgen emits for a genuine clean match (vs a vacuous/failed one).
# #524: the canonical "match uniquely" recognition is delegated to the SHARED
# classifier (lvs_verdict_tokens.MATCHED_RE) so the token can never drift;
# "the circuits match" stays a local extension (netgen summary-line variant).
#
# AUDITED (LVS wording-gate fix): this is a CLAIM DETECTOR, not a verdict
# producer — it decides whether to APPLY the portless-extraction guard, and a
# True only ever causes assert_lvs_trustworthy to RAISE. So the raw MATCHED_RE
# use here runs in the fail-safe direction (over-detecting a match claim
# strengthens the guard; it can never turn a failing LVS into a pass) and
# deliberately stays BROADER than lvs_verdict_tokens.classify().
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


# Where a run keeps the netlist netgen actually consumed, and the verdict it
# produced. Discovery-by-convention exists so the flow can invoke this with a
# project dir; an explicit --spice/--verdict-file always wins.
_SPICE_GLOBS = ("phase3/stage3/extracted/*.sp", "phase3/stage3/extracted/*.spice",
                "**/extracted/*.sp", "**/extracted/*.spice")
_VERDICT_RELS = ("reports/phase3/lvs.rpt", "phase3/reports/lvs.rpt",
                 "reports/phase3/lvs_signoff.rpt")


def discover_netlists(project: Path) -> List[Path]:
    """Extracted netlists under a project dir, nearest convention first."""
    out: List[Path] = []
    seen = set()
    for g in _SPICE_GLOBS:
        for fp in sorted(project.glob(g)):
            rp = fp.resolve()
            if fp.is_file() and rp not in seen:
                seen.add(rp)
                out.append(fp)
        if out:
            break
    return out


def discover_verdict(project: Path) -> Optional[Path]:
    for rel in _VERDICT_RELS:
        fp = project / rel
        if fp.is_file():
            return fp
    return None


def _expand(spec: str) -> List[Path]:
    """A --spice value: a file, or a glob. A glob is expanded HERE because the
    flow quotes its gate commands, so the shell never sees the pattern — the
    plan's `--spice='phase3/stage3/extracted/*.sp'` died on exactly this,
    with rc=2 (credited a vacuous pass) rather than a fire."""
    p = Path(spec)
    if p.is_file():
        return [p]
    hits = sorted(Path(h) for h in _glob.glob(spec, recursive=True))
    return [h for h in hits if h.is_file()]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("project_dir", nargs="?", default=None,
                   help="Project directory: discovers phase3/stage3/extracted/*.sp "
                        "and reports/phase3/lvs.rpt. Omit when using --spice.")
    p.add_argument("--spice", action="append", default=None,
                   help="Extracted layout SPICE netlist to guard. Accepts a glob "
                        "(expanded internally, not by the shell). Repeatable.")
    p.add_argument("--top", default=None,
                   help="Top subckt name. Default: DERIVED structurally (the "
                        ".subckt no other instantiates) — never 'the first "
                        "subckt', which on a real extraction is a standard cell.")
    p.add_argument("--verdict-file", type=Path, default=None,
                   help="Optional netgen verdict log; guard only trips if it claims a match.")
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 on a portless extraction even without a verdict file.")
    args = p.parse_args(argv)

    project = Path(args.project_dir) if args.project_dir else None
    if args.spice:
        files: List[Path] = []
        for spec in args.spice:
            hits = _expand(spec)
            if not hits:
                print(f"ERROR: no file matches: {spec}", file=sys.stderr)
                return 2
            files.extend(hits)
    elif project is not None:
        if not project.is_dir():
            print(f"ERROR: not a directory: {project}", file=sys.stderr)
            return 2
        files = discover_netlists(project)
    else:
        p.error("give a project_dir or --spice")
        return 2

    if not files:
        # NOT CHECKED, disclosed. Most published runs carry no extracted
        # netlist at all; a silent 0 here would certify an LVS nobody ran.
        print("VACUOUS_PASS: lvs_signoff_guard examined 0 extracted netlist(s) "
              f"— none found under {project} (looked for "
              f"{', '.join(_SPICE_GLOBS[:2])}). Nothing was verified.")
        return 2

    verdict_path = args.verdict_file
    if verdict_path is None and project is not None:
        verdict_path = discover_verdict(project)
    verdict = (verdict_path.read_text(errors="replace")
               if verdict_path and verdict_path.is_file()
               else (None if not args.strict else "circuits match uniquely"))

    failed = 0
    checked = 0
    for fp in files:
        text = fp.read_text(errors="replace")
        tops, how = resolve_tops(text, args.top)
        if not tops:
            print(f"LVS-GUARD FAIL: {fp}: {how}", file=sys.stderr)
            failed += 1
            continue
        for t in tops:
            checked += 1
            try:
                ports = assert_lvs_trustworthy(text, t, verdict)
            except PortlessExtractionError as e:
                print(f"LVS-GUARD FAIL: {fp} [.subckt {t}; {how}]: {e}",
                      file=sys.stderr)
                failed += 1
                continue
            print(f"LVS-GUARD PASS: {fp} [.subckt {t}; {how}] has "
                  f"{len(ports)} port(s) — verdict is anchorable.")
    if failed:
        print(f"LVS-GUARD: {failed} of {checked} guarded top(s) are PORTLESS.",
              file=sys.stderr)
        return 1
    print(f"LVS-GUARD PASS: {checked} top .subckt(s) across "
          f"{len(files)} netlist(s), verdict source: "
          f"{verdict_path if verdict_path else '(none — guard applied unconditionally)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
