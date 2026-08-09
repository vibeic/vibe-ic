#!/usr/bin/env python3
"""
pdk_capability_claim_disclosure.py — when a DESIGN DOCUMENT says the PDK cannot
do something the INSTALLED PDK demonstrably can, say so.

The defect
----------
A design-input constraint document may carry a disclosure of the form

    <target PDK> has no public ngspice corner lib
      -> corner sims use documented LEVEL=1 standin models

That sentence is not decoration. It is the documented justification for running
the analog corner sweep on an ideal analytic device model instead of the
foundry's own corner sections, and the flow HONOURS it:
`analog_corner_lib_realism_lint` downgrades an otherwise-FAILing LEVEL=1 deck to
an advisory WARNING the moment such a disclosure is present (its disclosure
token list literally contains "no public ngspice").

Documents go stale; installed PDKs get corner libraries added. When that
happens the disclosure keeps buying a WEAKER analysis than the environment can
actually support, and nothing in the flow notices — the document is never
compared against the PDK on disk. A disclosure that UNDERSTATES the environment
is as much a lie about the run as one that overstates it, and it is the harder
one to spot, because every gate downstream is happy.

What this does
--------------
1. Scans the DESIGN-OWNED document corpus (the same corpus
   `l19_pdk_floorplan_contract_check` scans for `pdk_target` traceability —
   imported, not re-listed, so the two cannot drift) for NEGATIVE claims about a
   PDK capability: a negation token governing a capability noun phrase, anchored
   to a PDK subject.
2. Probes the INSTALLED PDK for that same capability, via
   `analog_pdk_availability.resolve_pdk` + `probe_corner_capability` — the
   resolver the analog track already uses, so "installed" means the same thing
   here as it does to the deck emitter.
3. Reports every claim the installed PDK CONTRADICTS.

This program does NOT edit the document. A design-input document is the flow's
INPUT; rewriting it changes what the flow reads, which is a decision for a
human, not a side effect of a check.

DISCLOSURE-ONLY (the `route_congestion_trade_disclosure` precedent, §4.05): a
stale document is a documentation lag, not a design defect, and a blocking gate
would stop otherwise-sound runs over one. The content path always exits 0. The
only exit code this program owns is the I/O refusal.

ENFORCEMENT: advisory — this gate REPORTS a contradiction between a document
and an environment; per 4.05 it must not change the verdict tier. Advisory is
the intended wiring, not an accident, and not a gate that was quietly softened:
it never had a blocking form. Escalating it would mean stopping a run because a
sentence in an input document is out of date, which is a documentation problem
with a documentation fix.

chip-AGNOSTIC: negation grammar, capability noun phrases and generic PDK subject
tokens only. The one design-specific string it uses — the declared PDK target —
is read from the design's OWN L19, never written here. NDA hygiene: PATHS,
counts and corner-section role names only, never a PDK parameter value.

Exit codes:
    0  ran and reported (contradiction found or not)
    2  I/O error (project dir unreadable)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analog_pdk_availability as _apa  # noqa: E402
from analog_netlist_pdk_check import _declared_pdk_target  # noqa: E402
from l19_pdk_floorplan_contract_check import (  # noqa: E402
    _CORPUS_GLOBS, _CORPUS_MAX_BYTES, _CORPUS_MAX_FILES,
)

GATE = "pdk_capability_claim_disclosure"
REPORT_REL = "reports/pdk_capability_claim_contradictions.json"

# Text-ish corpus members only. `_CORPUS_GLOBS` includes a bare `**/*` arm, so
# the extension filter is what keeps a staged binary out of the scanner.
_TEXT_SUFFIXES = frozenset({
    ".md", ".txt", ".json", ".yaml", ".yml", ".cfg", ".tcl", ".sdc", ".rst",
    ".csv", ".ini", ".conf", "",
})

# ── the capabilities a document can deny and this program can verify ────────
# Each entry pairs a NOUN PHRASE (what the document is denying) with the probe
# key that answers whether the installed PDK actually provides it. A capability
# with no probe would be an opinion, not a check, so there are only two.
_CAPABILITIES = (
    {
        "id": "corner_lib",
        "noun": re.compile(
            r"(?i)corner[\s\-]*"
            r"(?:lib(?:rar(?:y|ies))?|libs?|models?|decks?|files?|sets?)"),
        "probe_key": "corner_lib_present",
        "what": "sectioned process-corner model library",
    },
    {
        "id": "mismatch_lib",
        "noun": re.compile(
            r"(?i)(?:mismatch|statistical|monte[\s\-]*carlo)[\s\-]*"
            r"(?:lib(?:rar(?:y|ies))?|libs?|models?|decks?|data)"),
        "probe_key": "mismatch_lib_present",
        "what": "statistical / mismatch model library",
    },
)

# Negation grammar. Whole words only — `nothing` must not be reached through
# `no`, and a hyphenated identifier must not be split into one.
_NEG_RE = re.compile(
    r"(?i)(?<![\w\-])"
    r"(?:no|not|none|never|without|lacks?|lacking|missing|absent|"
    r"unavailable|nonexistent|non-existent|unsupported)"
    r"(?![\w\-])")

# How far before the capability noun the negation may sit and still govern it.
_NEG_WINDOW = 64
# Clause breaks the negation may NOT reach across. `->` / an arrow is the exact
# shape of the real document ("has no X -> therefore we do Y"): the negation is
# on the LEFT and must not be read as governing anything on the right.
_CLAUSE_BREAK_RE = re.compile(r"->|→|⇒|[;:!?]|\.\s")

# A PDK-capability claim must be ABOUT a PDK. Any of these generic subject
# tokens in the line qualifies, as does the design's OWN declared target.
_SUBJECT_TOKENS = ("pdk", "foundry", "process", "technology", "node",
                   "ngspice", "spice", "simulator", "silicon")

# Markdown emphasis / code fencing is stripped so `**no public ngspice corner
# lib**` reads as prose. `_` is deliberately NOT stripped: it is a word
# character in every identifier a SPICE document names.
_MD_STRIP_RE = re.compile(r"[*`>#|]")


def _normalise(line: str) -> str:
    return _MD_STRIP_RE.sub(" ", line or "")


def _corpus_files(project: Path) -> List[Path]:
    """The design-owned document corpus, deduped and bounded exactly as the L19
    traceability scan bounds it."""
    seen: List[Path] = []
    known = set()
    for pat in _CORPUS_GLOBS:
        for p in sorted(project.glob(pat)):
            if len(seen) >= _CORPUS_MAX_FILES:
                return seen
            if not p.is_file() or p in known:
                continue
            if p.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if p.stat().st_size > _CORPUS_MAX_BYTES:
                    continue
            except OSError:
                continue
            known.add(p)
            seen.append(p)
    return seen


def _target_tokens(target: Optional[str]) -> List[str]:
    """Alphanumeric tokens of the design's declared PDK target, long enough to
    be a real anchor. Data-driven — no PDK literal lives in this source."""
    return [t for t in re.findall(r"[a-z0-9]+", (target or "").lower())
            if len(t) >= 3]


def _has_subject(low: str, tgt_tokens: List[str]) -> bool:
    return (any(tok in low for tok in _SUBJECT_TOKENS)
            or any(tok in low for tok in tgt_tokens))


def _negation_governs(line: str, noun_start: int) -> Optional[str]:
    """The negation token governing a capability noun at `noun_start`, or None.

    Governs means: inside the preceding window, and with no clause break
    between the two. Without the clause-break rule, the negation in
    "has no corner lib -> use standin models" would also be read as denying the
    standin models on the right of the arrow."""
    lo = max(0, noun_start - _NEG_WINDOW)
    window = line[lo:noun_start]
    last = None
    for m in _NEG_RE.finditer(window):
        last = m
    if last is None:
        return None
    if _CLAUSE_BREAK_RE.search(window[last.end():]):
        return None
    return last.group(0)


def find_claims(project: Path, target: Optional[str] = None,
                corpus: Optional[List[Path]] = None) -> List[Dict[str, Any]]:
    """Every NEGATIVE PDK-capability claim in the design-owned corpus.

    A claim is a line that (a) names a capability this program can verify,
    (b) has a negation governing that capability, and (c) is anchored to a PDK
    subject. All three are required: a line missing any one of them is not
    reported, because an over-eager claim scanner would put words in a
    document's mouth."""
    tgt_tokens = _target_tokens(target)
    out: List[Dict[str, Any]] = []
    for f in (corpus if corpus is not None else _corpus_files(project)):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(f.relative_to(project))
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = _normalise(raw)
            low = line.lower()
            if not _has_subject(low, tgt_tokens):
                continue
            for cap in _CAPABILITIES:
                m = cap["noun"].search(line)
                if not m:
                    continue
                neg = _negation_governs(line, m.start())
                if not neg:
                    continue
                out.append({
                    "file": rel,
                    "line": lineno,
                    "capability": cap["id"],
                    "capability_what": cap["what"],
                    "negation": neg,
                    "claim_text": raw.strip()[:300],
                })
    return out


def probe_installed(project: Path, target: Optional[str],
                    pdks_root: str = _apa.DEFAULT_PDKS_ROOT,
                    container: Optional[str] = None,
                    lister=None, reader=None) -> Dict[str, Any]:
    """What the installed PDK actually provides, via the analog track's own
    resolver. `lister` / `reader` are injectable so this is testable without a
    container and so a rung-2 CONTAINER path can be read at all."""
    # An explicit NON-DEFAULT pdks root is a real host path (a test fixture or a
    # host-mounted PDK), and `resolve_pdk` already lists it locally in that
    # case. Handing the container down anyway would make the READER go through
    # `docker exec` for paths that only exist on the host — every lib
    # "unreadable", and an UNVERIFIED verdict about a PDK sitting right there.
    use_container = container if pdks_root == _apa.DEFAULT_PDKS_ROOT else None
    res = _apa.resolve_pdk(target, project=str(project), pdks_root=pdks_root,
                           container=use_container, lister=lister)
    cap = _apa.probe_corner_capability(res, reader=reader,
                                       container=use_container)
    return {
        "target": target,
        "resolved": {
            "available": res.get("available"),
            "probe_ok": res.get("probe_ok"),
            "source": res.get("source"),
            "rung": res.get("rung"),
            "matched_dir": res.get("matched_dir"),
            "pdk_root": res.get("pdk_root"),
            "reason": res.get("reason"),
        },
        "capability": cap,
    }


def audit(project: Path, pdks_root: str = _apa.DEFAULT_PDKS_ROOT,
          container: Optional[str] = None, target: Optional[str] = None,
          lister=None, reader=None) -> Dict[str, Any]:
    """Compare every negative capability claim against the installed PDK.

    Verdicts (none of which change any caller's verdict tier):
      SKIP          — no design-owned document corpus to read
      NO_CLAIM      — corpus read, no negative capability claim in it
      UNVERIFIED    — claims found, installed PDK not probeable here
      CONSISTENT    — every claim agrees with the installed PDK
      CONTRADICTION — at least one claim is contradicted by the installed PDK
    """
    declared = target or _declared_pdk_target(project)
    corpus = _corpus_files(project)
    if not corpus:
        return {"gate": GATE, "verdict": "SKIP", "pdk_target": declared,
                "reason": "no design-owned document corpus",
                "corpus_files": 0, "claims": [], "contradictions": [],
                "installed": None, "note": _NOTE}

    claims = find_claims(project, declared, corpus=corpus)
    if not claims:
        return {"gate": GATE, "verdict": "NO_CLAIM", "pdk_target": declared,
                "reason": "no negative PDK-capability claim in the corpus",
                "corpus_files": len(corpus), "claims": [],
                "contradictions": [], "installed": None, "note": _NOTE}

    installed = probe_installed(project, declared, pdks_root=pdks_root,
                                container=container, lister=lister,
                                reader=reader)
    cap = installed["capability"]
    probed = bool(cap.get("probed"))

    contradictions: List[Dict[str, Any]] = []
    for c in claims:
        key = next(k["probe_key"] for k in _CAPABILITIES
                   if k["id"] == c["capability"])
        if not probed:
            c["status"] = "UNVERIFIED"
            c["installed_provides"] = None
            continue
        provides = bool(cap.get(key))
        c["installed_provides"] = provides
        if provides:
            c["status"] = "CONTRADICTED"
            contradictions.append(c)
        else:
            c["status"] = "CONSISTENT"

    if contradictions:
        verdict = "CONTRADICTION"
        reason = (f"{len(contradictions)} document claim(s) deny a PDK "
                  f"capability the installed PDK provides")
    elif not probed:
        verdict = "UNVERIFIED"
        reason = cap.get("reason") or "installed PDK not probeable here"
    else:
        verdict = "CONSISTENT"
        reason = "every claim agrees with the installed PDK"

    return {
        "gate": GATE,
        "verdict": verdict,
        "reason": reason,
        "pdk_target": declared,
        "corpus_files": len(corpus),
        "claims": claims,
        "contradictions": contradictions,
        "installed": installed,
        "note": _NOTE,
    }


_NOTE = (
    "DISCLOSURE ONLY (§4.05) — the verdict tier is unchanged. A contradiction "
    "means a design-input document understates the installed PDK, so an "
    "analysis weaker than the environment supports (e.g. a LEVEL=1 standin "
    "corner sweep) is being justified by a stale sentence. The document is "
    "design INPUT: a human decides whether to refresh it, not this check.")


def write_report(project: Path, rep: Dict[str, Any]) -> Path:
    out = project / REPORT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Disclose design-document claims about PDK capability "
                     "that the installed PDK contradicts."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None, help="also write the report here")
    # The flow wires this gate as a bare command with no container flag, so the
    # DEFAULT is what decides whether it can measure anything at all. Falling
    # back to None would make every real run report UNVERIFIED — a gate that
    # cannot be wrong because it never looks. The chain is the analog track's
    # own (`analog_one_shot_runner` reads VIBEIC_ANALOG_CONTAINER, default
    # `vibeic-eda`), widened to the two container variables the rest of the
    # plugin sets. When the named container is absent, the probe reports
    # UNVERIFIED honestly rather than guessing.
    ap.add_argument("--container",
                    default=(os.environ.get("EDA_CONTAINER")
                             or os.environ.get("VIBEIC_ANALOG_CONTAINER")
                             or os.environ.get("VIBEIC_EDA_CONTAINER")
                             or "vibeic-eda"),
                    help="EDA container to probe the installed PDK inside")
    ap.add_argument("--pdks-root", default=_apa.DEFAULT_PDKS_ROOT)
    ap.add_argument("--target", default=None,
                    help="override the L19-declared PDK target")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"IO_ERROR: no such project dir: {project}", file=sys.stderr)
        return 2

    rep = audit(project.resolve(), pdks_root=args.pdks_root,
                container=args.container, target=args.target)
    write_report(project, rep)
    if args.json:
        jp = Path(args.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")

    print(f"[{rep['verdict']}] {GATE}: {rep['reason']}")
    for c in rep["claims"]:
        print(f"  [{c.get('status', 'UNSCANNED')}] {c['file']}:{c['line']} "
              f"denies {c['capability']} ({c['capability_what']}) "
              f"via '{c['negation']}'")
        print(f"      claim: {c['claim_text']}")
    if rep["contradictions"]:
        cap = rep["installed"]["capability"]
        print(f"*** the installed PDK DOES provide it: "
              f"{len(cap['libs_with_full_corner_set'])} model lib(s) bracket "
              f"the process grid; roles={cap['corner_roles_covered']}; "
              f"sections={cap['example_corner_sections']}")
        print("    the document understates the environment — a weaker "
              "analysis is being justified by a stale sentence. "
              "DISCLOSURE ONLY; no verdict tier changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
