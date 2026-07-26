#!/usr/bin/env python3
"""Write a machine-readable PDK-substitution disclosure into reports/pdk_substitution.json.

CONTEXT
-------
Two gates (`digital_pdk_substitution_disclosure_check` and
`sdc_clock_period_library_basis_check`) enforce that a digital sign-off which
ran against a PDK the spec never declared must disclose that substitution.  The
gates are READERS: they verify the disclosure exists.  But nothing in the
digital flow ever WRITES the disclosure — so the doctrine is
unenforceable-by-construction on a pure-digital run: the gate demands a file
that no tool produces, forcing a human to hand-edit a report.  This program
closes that gap: it MEASURES both PDKs and WRITES the disclosure, making the
honesty doctrine machine-enforceable.

HONESTY CONTRACT (tests must enforce every clause)
--------------------------------------------------
1. NO-OP when families match: if the resolved PDK family is the same as the
   declared target there is NO substitution.  The program must write NOTHING
   and exit 0.  It must be impossible for this program to manufacture a
   disclosure when no substitution occurred.

2. Never write from constants: every family name written into the disclosure
   must come from a MEASURED value (the L19 JSON or the orchestrator JSON).
   If either PDK cannot be determined the program must NOT write a disclosure
   — it must exit 1 and say why.  Silence is correct; a vague disclosure is
   not.

3. Undetermined period basis → explicit UNDETERMINED field: if the
   substitution is measurable but the period basis cannot be traced, the
   emitter must still write the substitution disclosure AND must explicitly
   record `"clock_period_basis": "UNDETERMINED"` rather than omitting the
   field (an omitted field reads as "fine").

EXIT CODES
----------
  0  nothing-to-disclose (families match) OR disclosure written successfully
  1  cannot measure a required input (skip-with-reason): declared PDK unknown,
     resolved PDK unknown, or write failure

rc == 2 is deliberately NOT used.  `flow_compliance_check` converts rc == 2
into a VACUOUS_PASS that it counts in the PASS numerator; a genuine measurement
failure must never land there.  (Mirrors the convention documented in
`sdc_clock_period_library_basis_check`.)

OUTPUT
------
When a substitution is detected and both PDKs are measurable the program writes
`reports/pdk_substitution.json` containing at minimum::

    {
      "program": "pdk_substitution_disclosure_emit",
      "pdk_substitution": "resolved:<RESOLVED_PDK> declared:<DECLARED_PDK>",
      "declared_pdk_target": "<DECLARED>",
      "resolved_pdk": "<RESOLVED>",
      "clock_period_basis": "<SOURCE_FAMILY>" | "UNDETERMINED"
    }

The `pdk_substitution` line is designed to satisfy the regex checked by
`digital_pdk_substitution_disclosure_check._DISCLOSE_RE` and to carry enough
tokens of BOTH families for `_disclosure()` to find a match.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROGRAMS_DIR = Path(__file__).resolve().parent
if str(PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAMS_DIR))

PROGRAM = "pdk_substitution_disclosure_emit"

# ------------------------------------------------------------------
# token helpers — mirrors the logic in digital_pdk_substitution_disclosure_check
# ------------------------------------------------------------------

_MIN_TOKEN = 4
_DISCLOSE_RE = re.compile(r"pdk[_\s-]*substitution|pdk\s*note", re.IGNORECASE)

# Vocabulary of recognised standard-cell-library / PDK family tokens,
# mirrored from sdc_clock_period_library_basis_check._FAMILY_TOKENS.
_FAMILY_TOKENS: tuple = (
    "sky130",
    "gf180mcu",
    "gf180",
    "sg13g2",
    "ihp",
    "nangate45",
    "nangate",
    "asap7",
    "freepdk45",
    "tsmc",
    "globalfoundries",
)

_PERIOD_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ns\b", re.IGNORECASE)
_FREQ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MHz\b", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _tokens(s: str) -> List[str]:
    """Identity-bearing tokens of a PDK name / target phrase."""
    out: List[str] = []
    whole = _norm(s)
    if len(whole) >= _MIN_TOKEN:
        out.append(whole)
    for part in re.split(r"[^A-Za-z0-9]+", s or ""):
        p = _norm(part)
        if len(p) >= _MIN_TOKEN and p not in out:
            out.append(p)
    return out


def _families_in(text: str) -> set:
    """Family tokens present in `text`, matched on the separator-free form."""
    flat = _norm(text)
    return {tok for tok in _FAMILY_TOKENS if tok in flat}


def _families_match(resolved: str, declared: str) -> bool:
    """True when the resolved PDK is plausibly the declared target.

    Containment is checked BOTH ways (matches the gate's own predicate).
    """
    rtoks, dtoks = _tokens(resolved), _tokens(declared)
    for r in rtoks:
        for d in dtoks:
            if r in d or d in r:
                return True
    return False


# ------------------------------------------------------------------
# input readers
# ------------------------------------------------------------------

def _declared_target(project: Path) -> Optional[str]:
    """Read the declared PDK target from L19_CONSTRAINTS_PDK.json.

    Tries `analog_netlist_pdk_check._declared_pdk_target` first so both
    tracks agree on 'declared', then falls back to direct JSON parsing —
    exactly the same two-step pattern used by
    `digital_pdk_substitution_disclosure_check`.
    """
    try:
        import analog_netlist_pdk_check as _npc
        return _npc._declared_pdk_target(project)
    except Exception:
        pass
    l19 = project / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
    try:
        d = json.loads(l19.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    v = (d.get("fields") or {}).get("pdk_target")
    if not isinstance(v, str) or not v.strip():
        return None
    if v.strip().lower().startswith(("n/a", "na ", "none", "tbd")):
        return None
    return v.strip()


def _resolved_pdk(project: Path) -> Optional[str]:
    """The PDK phase 3 actually signed off against.

    Primary: reports/orchestrator/phase3_one_shot.json -> ["pdk"].
    Fallback: a '# VIBEIC_SDC_PDK_PROVENANCE: <pdk>' stamp in the
    sign-off SDC (mirrors sdc_clock_period_library_basis_check).
    """
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    try:
        pdk = json.loads(rep.read_text(errors="replace")).get("pdk")
        if isinstance(pdk, str) and pdk.strip():
            return pdk.strip()
    except (OSError, ValueError):
        pass
    # Fallback: look in the sign-off SDC
    for rel in ("phase3/stage3/pnr/constraint.sdc",):
        sdc = project / rel
        if not sdc.is_file():
            continue
        try:
            for line in sdc.read_text(errors="replace").splitlines()[:8]:
                m = re.search(r"VIBEIC_SDC_PDK_PROVENANCE\s*:\s*(\S+)", line)
                if m:
                    return m.group(1).strip()
        except OSError:
            pass
    return None


def _signoff_period(project: Path) -> Optional[float]:
    """The sign-off clock period in ns from phase3/stage3/pnr/constraint.sdc."""
    sdc = project / "phase3" / "stage3" / "pnr" / "constraint.sdc"
    if not sdc.is_file():
        return None
    try:
        text = sdc.read_text(errors="replace")
    except OSError:
        return None
    best: Optional[float] = None
    for line in text.splitlines():
        if "create_clock" not in line:
            continue
        m = re.search(r"-period\s+([0-9.]+)", line)
        if not m:
            continue
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if v > 0 and (best is None or v < best):
            best = v
    return best


def _period_basis(project: Path, period: Optional[float]) -> str:
    """Identify which spec-table family the sign-off period came from.

    Scans input/docs/*.md for lines that carry both a family token and a
    period/frequency literal, then looks for a row whose numeric value
    matches `period`.  Returns the family name(s) if found, or
    "UNDETERMINED" if not.
    """
    if period is None:
        return "UNDETERMINED"
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return "UNDETERMINED"
    source_families: List[str] = []
    for doc in sorted(docs_dir.rglob("*.md")):
        try:
            lines = doc.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            fams = _families_in(line)
            if not fams:
                continue
            row_period: Optional[float] = None
            m = _PERIOD_RE.search(line)
            if m:
                row_period = float(m.group(1))
            else:
                mf = _FREQ_RE.search(line)
                if mf:
                    mhz = float(mf.group(1))
                    if mhz > 0:
                        row_period = round(1000.0 / mhz, 4)
            if row_period is None:
                continue
            if abs(row_period - period) < 1e-6:
                for f in sorted(fams):
                    if f not in source_families:
                        source_families.append(f)
    if source_families:
        return "/".join(sorted(source_families))
    return "UNDETERMINED"


# ------------------------------------------------------------------
# core emitter
# ------------------------------------------------------------------

def emit(project: Path) -> Dict[str, Any]:
    """Measure the substitution and write the disclosure.

    Returns a dict describing what was done (for logging / JSON output).
    Never raises — all errors are captured in the returned dict.
    """
    out: Dict[str, Any] = {
        "program": PROGRAM,
        "project": str(project),
        "action": None,
    }

    declared = _declared_target(project)
    out["declared_pdk_target"] = declared
    if not declared:
        out["action"] = "SKIP"
        out["reason"] = (
            "L19.fields.pdk_target declares no concrete PDK target — "
            "nothing to measure; not writing disclosure"
        )
        return out

    resolved = _resolved_pdk(project)
    out["resolved_pdk"] = resolved
    if not resolved:
        out["action"] = "SKIP"
        out["reason"] = (
            "resolved PDK unknown (no reports/orchestrator/phase3_one_shot.json "
            "'pdk' field and no VIBEIC_SDC_PDK_PROVENANCE stamp) — "
            "cannot write an honest disclosure"
        )
        return out

    if _families_match(resolved, declared):
        out["action"] = "NO_OP"
        out["reason"] = (
            f"resolved PDK {resolved!r} matches the declared target "
            f"{declared!r} — no substitution occurred; nothing to disclose"
        )
        return out

    # Substitution confirmed — measure the period basis before writing.
    period = _signoff_period(project)
    out["signoff_period_ns"] = period
    basis = _period_basis(project, period)
    out["clock_period_basis"] = basis

    # Build the disclosure record.  The `pdk_substitution` string is designed
    # so that the gate's token-containment check finds both families in it:
    #   resolved tokens in "resolved:<RESOLVED>"
    #   declared tokens in "declared:<DECLARED>"
    disclosure_record: Dict[str, Any] = {
        "program": PROGRAM,
        "pdk_substitution": f"resolved:{resolved} declared:{declared}",
        "declared_pdk_target": declared,
        "resolved_pdk": resolved,
        "clock_period_basis": basis,
    }

    dest = project / "reports" / "pdk_substitution.json"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(disclosure_record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        out["action"] = "ERROR"
        out["reason"] = f"could not write {dest}: {exc}"
        return out

    out["action"] = "WROTE_DISCLOSURE"
    out["disclosure_path"] = str(dest.relative_to(project))
    out["disclosure"] = disclosure_record
    out["reason"] = (
        f"PDK substitution detected: resolved={resolved!r} "
        f"declared={declared!r}; disclosure written to "
        f"reports/pdk_substitution.json"
    )
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Measure the declared and resolved PDK and write a "
            "machine-readable substitution disclosure so the disclosure "
            "gates (`digital_pdk_substitution_disclosure_check`, "
            "`sdc_clock_period_library_basis_check`) can find it without "
            "human hand-editing."
        )
    )
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the report to this path")
    args = ap.parse_args(argv)

    project = args.project.resolve()
    rep = emit(project)

    text = json.dumps(rep, indent=2, ensure_ascii=False)
    print(text)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")

    action = rep.get("action")
    if action in ("SKIP", "ERROR"):
        return 1
    # NO_OP (no substitution) and WROTE_DISCLOSURE both exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
