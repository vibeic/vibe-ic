#!/usr/bin/env python3
"""A DIGITAL sign-off run on a PDK the spec never declared must SAY SO.

The plugin already enforces this doctrine for the ANALOG track: #496 /
`flow_compliance_check._pdk_substitution_disclosed()` refuses a run whose
analog decks substitute a different PDK for the L19-declared target unless the
substitution is honestly disclosed. That function scans `analog_dir` for
`*.sp` decks and returns None the moment there is no analog directory — so on
a PURE DIGITAL run the doctrine never applies and the substitution is silent.

MEASURED (spm x ihp-sg13g2, plugin v1.5.85, image vibeic-eda:0.2.29):

    L19_CONSTRAINTS_PDK.json  fields.pdk_target = "sky130"
    reports/orchestrator/phase3_one_shot.json  pdk = "ihp-sg13g2"

The whole backend -- PnR, CTS, DRC, LVS, STA, antenna, IR-drop -- ran against
IHP SG13G2 and every report says PASS, while the spec the reports are graded
against declares SKY130 (primary) / GF180MCU (secondary) and never mentions
IHP. Nothing in the run reconciled the two, and no artifact disclosed it.

The consequence is not cosmetic. The spec's per-library constraint table
(L9 9.1.2) keys the clock period BY LIBRARY -- sky130_fd_sc_hd 10 ns,
sky130_fd_sc_hs 8 ns, gf180mcu_* 24 ns -- and has NO ROW for the substituted
PDK. With no row to read, the period fell back to a hardcoded default
(`phase2_scaffold_gen.derive_clock_period_ns(..., default_ns=10.0)`, note
"default 100 MHz") and the run then reported timing MET against a constraint
with no basis in the spec for that library. A reader of the sign-off cannot
tell that from any artifact -- which is exactly the "silent wrong-PDK belief"
failure class the commercial-PDK fallback guard already refuses at the ASSET
layer. This check closes the same hole at the SPEC layer, for digital.

VERDICTS
  SKIP                    -- no concrete L19 target, or phase 3 did not run:
                             nothing to compare, never a silent pass.
  PASS                    -- the resolved PDK is the declared target.
  PASS_WITH_DISCLOSURE    -- substituted AND honestly disclosed (a
                             `pdk_substitution` marker naming BOTH PDKs, or a
                             documented PDK_MISMATCH waiver).
  FAIL                    -- substituted and NOT disclosed.

chip-AGNOSTIC and PDK-AGNOSTIC: token containment only, no PDK literals.
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

# Minimum token length that may carry a PDK identity. "ihp" (3) is a vendor
# prefix that collides too easily; "sky130" / "gf180mcu" / "sg13g2" do not.
_MIN_TOKEN = 4
_DISCLOSE_RE = re.compile(r"pdk[_\s-]*substitution|pdk\s*note", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _tokens(s: str) -> List[str]:
    """Identity-bearing tokens of a PDK name / target phrase.

    The whole normalised string plus each alphanumeric run long enough to be
    an identity (so `ihp-sg13g2` yields `ihpsg13g2` and `sg13g2`, and a prose
    target like `open-source(SKY130 primary, GF180MCU secondary)` yields
    `sky130` and `gf180mcu`).
    """
    out: List[str] = []
    whole = _norm(s)
    if len(whole) >= _MIN_TOKEN:
        out.append(whole)
    for part in re.split(r"[^A-Za-z0-9]+", s or ""):
        p = _norm(part)
        if len(p) >= _MIN_TOKEN and p not in out:
            out.append(p)
    return out


def _families_match(resolved: str, declared: str) -> bool:
    """True when the resolved PDK is plausibly the declared target.

    Containment is checked BOTH ways: a declared `sky130` matches a resolved
    `sky130A`, and a declared prose phrase naming `GF180MCU` matches a
    resolved `gf180mcuD`.
    """
    rtoks, dtoks = _tokens(resolved), _tokens(declared)
    for r in rtoks:
        for d in dtoks:
            if r in d or d in r:
                return True
    return False


def _resolved_pdk(project: Path) -> Optional[str]:
    """The PDK phase 3 actually signed off against (machine-readable)."""
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    try:
        pdk = json.loads(rep.read_text(errors="replace")).get("pdk")
    except (OSError, ValueError):
        return None
    return pdk.strip() if isinstance(pdk, str) and pdk.strip() else None


def _declared_target(project: Path) -> Optional[str]:
    """Reuse the analog track's L19 reader so both tracks agree on 'declared'."""
    try:
        import analog_netlist_pdk_check as _npc
        return _npc._declared_pdk_target(project)
    except Exception:
        l19 = (project / "phase1" / "generated_docs"
               / "L19_CONSTRAINTS_PDK.json")
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


def _waived(project: Path) -> bool:
    try:
        import analog_netlist_pdk_check as _npc
        return bool(_npc._pdk_mismatch_waived(project))
    except Exception:
        return False


def _disclosure(project: Path, resolved: str,
                declared: str) -> Optional[str]:
    """An honest disclosure names BOTH the substitute and the declared target.

    Mirrors the analog form: a `pdk_substitution` / `PDK NOTE` line whose text
    carries both identities, so `pdk_substitution: none` cannot game it.
    """
    cands: List[Path] = []
    for rel in ("reports/final_summary.md", "reports/pdk_substitution.json",
                "reports/phase3/pdk_substitution.json", "RESULT.md"):
        p = project / rel
        if p.is_file():
            cands.append(p)
    rdir = project / "reports"
    if rdir.is_dir():
        cands.extend(sorted(rdir.rglob("pdk_substitution*")))
    rtoks, dtoks = _tokens(resolved), _tokens(declared)
    for p in cands:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if not _DISCLOSE_RE.search(line):
                continue
            n = _norm(line)
            if any(t in n for t in rtoks) and any(t in n for t in dtoks):
                return str(p.relative_to(project))
    return None


def _clock_evidence(project: Path) -> Dict[str, Any]:
    """The sign-off clock period + where it came from (context, not a verdict).

    When the resolved PDK is a substitution, the spec's per-library period
    table has no row for it, so this records WHAT constraint the run actually
    signed off against.
    """
    ev: Dict[str, Any] = {"sdc": None, "create_clock": None}
    for rel in ("phase3/stage3/pnr/constraint.sdc",
                "phase2/stage2/constraints"):
        p = project / rel
        sdcs = ([p] if p.is_file()
                else sorted(p.glob("*.sdc")) if p.is_dir() else [])
        for s in sdcs:
            try:
                for line in s.read_text(errors="replace").splitlines():
                    if "create_clock" in line:
                        ev["sdc"] = str(s.relative_to(project))
                        ev["create_clock"] = line.strip()
                        return ev
            except OSError:
                continue
    return ev


def check(project: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "program": "digital_pdk_substitution_disclosure_check",
        "project": str(project),
    }
    declared = _declared_target(project)
    resolved = _resolved_pdk(project)
    out["declared_pdk_target"] = declared
    out["resolved_pdk"] = resolved

    if not declared:
        out["verdict"] = "SKIP"
        out["reason"] = ("L19.fields.pdk_target declares no concrete PDK "
                         "target — nothing to compare against")
        return out
    if not resolved:
        out["verdict"] = "SKIP"
        out["reason"] = ("no reports/orchestrator/phase3_one_shot.json 'pdk' "
                         "field — phase 3 did not run a physical sign-off")
        return out

    if _families_match(resolved, declared):
        out["verdict"] = "PASS"
        out["reason"] = (f"resolved PDK {resolved!r} matches the declared "
                         f"target {declared!r}")
        return out

    out["clock_evidence"] = _clock_evidence(project)
    if _waived(project):
        out["verdict"] = "PASS_WITH_DISCLOSURE"
        out["disclosure"] = "waivers.json PDK_MISMATCH waiver"
        out["reason"] = (f"{resolved!r} substituted for declared {declared!r} "
                         f"— documented PDK_MISMATCH waiver")
        return out
    where = _disclosure(project, resolved, declared)
    if where:
        out["verdict"] = "PASS_WITH_DISCLOSURE"
        out["disclosure"] = where
        out["reason"] = (f"{resolved!r} substituted for declared {declared!r} "
                         f"— disclosed in {where}")
        return out

    out["verdict"] = "FAIL"
    out["reason"] = (
        f"UNDISCLOSED PDK SUBSTITUTION: the physical sign-off ran against "
        f"{resolved!r}, but the spec (L19.fields.pdk_target) declares "
        f"{declared!r}. Every DRC/LVS/STA/antenna/IR-drop report in this run "
        f"is therefore graded against a PDK the specification never targets, "
        f"and no artifact says so. The spec's per-library constraint tables "
        f"have no row for {resolved!r}, so any constraint used here "
        f"(e.g. {out['clock_evidence'].get('create_clock') or 'the clock period'}) "
        f"has no basis in the spec for this library. Disclose the "
        f"substitution (a `pdk_substitution` line naming BOTH PDKs) or record "
        f"a PDK_MISMATCH waiver with a rationale.")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="A digital sign-off on a PDK the spec never declared must "
                    "disclose the substitution (digital counterpart of the "
                    "#496 analog PDK-substitution doctrine).")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, help="write the JSON report here")
    args = ap.parse_args(argv)

    rep = check(args.project.resolve())
    text = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if rep["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
