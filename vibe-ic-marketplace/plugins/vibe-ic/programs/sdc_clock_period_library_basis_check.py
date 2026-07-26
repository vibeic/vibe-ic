#!/usr/bin/env python3
"""The sign-off clock period must have a basis in the spec FOR THE LIBRARY THAT SIGNED OFF.

MEASURED DEFECT (spm x ihp-sg13g2, 8HD-8, plugin 1.5.85 and 1.6.4 alike)
------------------------------------------------------------------------
A design spec keyed its target clock period BY STANDARD-CELL LIBRARY::

    | Target clock period - SKY130 generic            | 10 ns (100 MHz)  |
    | Target clock period - SKY130 high-speed         |  8 ns (125 MHz)  |
    | Target clock period - GF180MCU                  | 24 ns (~41.7 MHz)|

The physical sign-off then ran against ``ihp-sg13g2`` -- a library with NO ROW
in that table. Phase 1 flattened the table by prose-scanning for a frequency
literal, kept the FIRST one, and recorded it WITHOUT the library it belongs to::

    L8_RTL_CONSTANTS.json:
      clock_mhz = 100.0
      clock_domains[0].evidence = {file: input/docs/L1_product_metadata.md,
                                   line: 35, matched_substring: "100 MHz"}
      # ...and line 35 is the *SKY130* row.

That 100 MHz became ``create_clock -period 10.0`` in the IHP SG13G2 sign-off
SDC, and STA reported "setup met, worst slack +6.11 ns". The number is real;
the CONSTRAINT it is measured against is another library's row.

Nothing in the flow disclosed this. The period is not a hardcoded default that
coincidentally matches -- it is provably the substituted PDK's row, carried
end to end. It is the PDK-substitution defect a second time, in the one place
where it silently converts into a timing PASS.

WHY THIS IS A PROGRAM AND NOT A JUDGMENT CALL (Bucket A)
--------------------------------------------------------
Exact input the program sees:
  1. ``create_clock ... -period P`` from the sign-off SDC.
  2. The PDK that phase 3 actually ran (``reports/orchestrator/phase3_one_shot.json``
     -> ``pdk``, or the ``# VIBEIC_SDC_PDK_PROVENANCE:`` stamp in the SDC).
  3. The design's own input docs, scanned for LIBRARY-KEYED period rows: a line
     that carries BOTH a period/frequency literal AND a std-cell-library or PDK
     family token.

Exact decision, no judgment required:
  * Fewer than 2 distinct families carry a period row -> the spec is not
    library-keyed. Nothing to enforce. SKIP.
  * The signed-off family HAS a row -> P must equal that row. Equal: PASS.
    Different: FAIL (a row exists for this library and the flow used another).
  * The signed-off family has NO row -> the spec cannot answer for this
    library. FAIL unless an artefact discloses the substitution (or a
    documented waiver covers it), naming both the signed-off library and the
    row P was actually taken from.

Every step is a file read plus token matching plus numeric equality. There is
no input from which a program could not reach this verdict.

EXIT CODES
----------
  0  PASS / PASS_WITH_DISCLOSURE / SKIP
  1  FAIL

rc == 2 is deliberately NOT used. flow_compliance_check converts rc == 2 into
a VACUOUS_PASS and counts it in the PASS numerator; a clock period with no
basis for the library that signed off must never land in that numerator.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROGRAM = "sdc_clock_period_library_basis_check"

# A period row is a doc line carrying a time period or a frequency.
_PERIOD_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ns\b", re.IGNORECASE)
_FREQ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MHz\b", re.IGNORECASE)

# Std-cell library / PDK family tokens. Deliberately a fixed vocabulary: a
# family token has to be recognisable to BOTH the doc scanner and the resolved
# PDK id, and inventing tokens from arbitrary text is exactly the judgment call
# this program must not make.
_FAMILY_TOKENS: tuple[str, ...] = (
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

# Disclosure convention, shared with the analog and digital PDK-substitution
# doctrine: a line that announces a substitution / a clock-basis note.
_DISCLOSE_RE = re.compile(
    r"pdk[_\s-]*substitution|pdk\s*note|clock[_\s-]*period[_\s-]*basis"
    r"|clock[_\s-]*period\s*note",
    re.IGNORECASE,
)

_SDC_CANDIDATES: tuple[str, ...] = (
    "phase3/stage3/pnr/constraint.sdc",
    "phase2/stage2/constraints/*.sdc",
    "phase3/**/*.sdc",
)

_DISCLOSURE_FILES: tuple[str, ...] = (
    "reports/final_summary.md",
    "reports/clock_period_basis.json",
    "reports/pdk_substitution.json",
    "reports/phase3/pdk_substitution.json",
    "RESULT.md",
)


# --------------------------------------------------------------------------
# tokenisation
# --------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase and strip separators so 'ihp-sg13g2' and 'IHP SG13G2' agree."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _families_in(text: str) -> set[str]:
    """Family tokens present in `text`, matched on the separator-free form."""
    flat = _norm(text)
    return {tok for tok in _FAMILY_TOKENS if tok in flat}


def _resolved_families(pdk: str) -> set[str]:
    """Family tokens for the PDK that actually signed off.

    'ihp-sg13g2' -> {'sg13g2', 'ihp'};  'sky130A' -> {'sky130'}.
    Falls back to the normalised id itself so an unregistered PDK still gets a
    token and cannot silently match nothing.
    """
    fams = _families_in(pdk)
    return fams or {_norm(pdk)}


# --------------------------------------------------------------------------
# input readers
# --------------------------------------------------------------------------

def _find_signoff_sdc(project: Path) -> Path | None:
    for pat in _SDC_CANDIDATES:
        if "*" in pat:
            for cand in sorted(project.glob(pat)):
                if cand.is_file() and _period_in_sdc(cand) is not None:
                    return cand
        else:
            cand = project / pat
            if cand.is_file() and _period_in_sdc(cand) is not None:
                return cand
    return None


def _period_in_sdc(sdc: Path) -> float | None:
    """The smallest `create_clock -period` in the file (the binding one)."""
    try:
        text = sdc.read_text(errors="replace")
    except OSError:
        return None
    best: float | None = None
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


def _resolved_pdk(project: Path, sdc: Path | None) -> str | None:
    p = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    try:
        d = json.loads(p.read_text(errors="replace"))
        pdk = str(d.get("pdk") or "").strip()
        if pdk:
            return pdk
    except (OSError, ValueError):
        pass
    # Fallback: the SDC stamps its own PDK provenance.
    if sdc is not None:
        try:
            for line in sdc.read_text(errors="replace").splitlines()[:8]:
                m = re.search(r"VIBEIC_SDC_PDK_PROVENANCE\s*:\s*(\S+)", line)
                if m:
                    return m.group(1).strip()
        except OSError:
            pass
    return None


def _library_keyed_period_rows(project: Path) -> list[dict[str, Any]]:
    """Every input-doc line that keys a period/frequency to a library family.

    Returns one record per (file, line) that carries BOTH a family token and a
    period or frequency literal. This is the spec's own per-library table, read
    from the design INPUT -- never from a previous run's output.
    """
    rows: list[dict[str, Any]] = []
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return rows
    for doc in sorted(docs_dir.rglob("*.md")):
        try:
            lines = doc.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            fams = _families_in(line)
            if not fams:
                continue
            period: float | None = None
            m = _PERIOD_RE.search(line)
            if m:
                period = float(m.group(1))
            else:
                mf = _FREQ_RE.search(line)
                if mf:
                    mhz = float(mf.group(1))
                    if mhz > 0:
                        period = round(1000.0 / mhz, 4)
            if period is None or period <= 0:
                continue
            rows.append({
                "file": str(doc.relative_to(project)),
                "line": idx,
                "text": line.strip(),
                "families": sorted(fams),
                "period_ns": period,
            })
    return rows


def _disclosure(project: Path, resolved: str, other: str) -> str | None:
    """A disclosure line naming BOTH the signed-off library and the row used."""
    want_a = _resolved_families(resolved)
    want_b = _families_in(other) or {_norm(other)}
    cands: list[Path] = [project / rel for rel in _DISCLOSURE_FILES]
    cands.extend(sorted(project.glob("reports/**/clock_period_basis*")))
    cands.extend(sorted(project.glob("reports/**/pdk_substitution*")))
    for path in cands:
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if not _DISCLOSE_RE.search(line):
                continue
            flat = _norm(line)
            if any(t in flat for t in want_a) and any(t in flat for t in want_b):
                try:
                    return str(path.relative_to(project))
                except ValueError:
                    return path.name
    return None


def _waived(project: Path) -> bool:
    """A documented CLOCK_PERIOD_BASIS / PDK_MISMATCH waiver."""
    p = project / "waivers.json"
    try:
        d = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return False
    blob = json.dumps(d).upper()
    return "CLOCK_PERIOD_BASIS" in blob or "PDK_MISMATCH" in blob


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

def check(project: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"program": PROGRAM, "project": str(project)}

    sdc = _find_signoff_sdc(project)
    if sdc is None:
        out.update(verdict="SKIP", reason="no sign-off SDC with a create_clock "
                                          "-period; nothing to check")
        return out
    period = _period_in_sdc(sdc)
    out["sdc"] = str(sdc.relative_to(project))
    out["signoff_period_ns"] = period

    pdk = _resolved_pdk(project, sdc)
    if not pdk:
        out.update(verdict="SKIP",
                   reason="phase 3 did not record a resolved PDK; nothing to "
                          "bind the period to")
        return out
    out["resolved_pdk"] = pdk
    fams = _resolved_families(pdk)
    out["resolved_pdk_families"] = sorted(fams)

    rows = _library_keyed_period_rows(project)
    out["library_keyed_rows"] = rows
    distinct = {f for r in rows for f in r["families"]}
    out["distinct_families_in_spec"] = sorted(distinct)

    if len(distinct) < 2:
        out.update(verdict="SKIP",
                   reason=("the design inputs do not key the clock period by "
                           "library (%d distinct family row(s) found); there "
                           "is no per-library basis to enforce"
                           % len(distinct)))
        return out

    own = [r for r in rows if fams & set(r["families"])]
    if own:
        match = [r for r in own if abs(r["period_ns"] - (period or -1)) < 1e-6]
        if match:
            out.update(verdict="PASS",
                       reason=("sign-off period %.4g ns is the spec row for "
                               "the library that signed off (%s:%d)"
                               % (period, match[0]["file"], match[0]["line"])),
                       basis_row=match[0])
            return out
        out.update(
            verdict="FAIL",
            reason=("CLOCK_PERIOD_WRONG_ROW: the spec DOES carry a period row "
                    "for the signed-off library %r (%s), but the sign-off SDC "
                    "%s constrains -period %.4g ns, which is not that row's "
                    "value. The flow used a different library's number."
                    % (pdk, "; ".join("%s:%d=%.4gns" % (r["file"], r["line"],
                                                        r["period_ns"])
                                      for r in own),
                       out["sdc"], period)),
            candidate_rows=own)
        return out

    # The signed-off library has NO row. The spec cannot answer for it.
    source_rows = [r for r in rows
                   if abs(r["period_ns"] - (period or -1)) < 1e-6]
    other = ", ".join(sorted({f for r in source_rows for f in r["families"]}))
    out["period_traced_to_rows"] = source_rows

    if _waived(project):
        out.update(verdict="PASS_WITH_DISCLOSURE",
                   reason="a documented CLOCK_PERIOD_BASIS / PDK_MISMATCH "
                          "waiver covers the missing spec row")
        return out
    disc = _disclosure(project, pdk, other or pdk)
    if disc:
        out.update(verdict="PASS_WITH_DISCLOSURE",
                   reason=("the substitution is disclosed in %s, naming both "
                           "the signed-off library and the row the period "
                           "came from" % disc),
                   disclosure=disc)
        return out

    traced = ""
    if source_rows:
        r0 = source_rows[0]
        traced = (" The period in force traces to %s:%d -- %r -- which is the "
                  "row for %s, NOT for %s."
                  % (r0["file"], r0["line"], r0["text"],
                     "/".join(r0["families"]), pdk))
    out.update(
        verdict="FAIL",
        reason=("CLOCK_PERIOD_LIBRARY_NOT_IN_SPEC_TABLE: the design inputs key "
                "the target clock period by standard-cell library (%s), but "
                "the library that actually signed off (%r) has NO row. The "
                "sign-off SDC %s nevertheless constrains -period %.4g ns and "
                "STA is graded against it, so every timing 'met' in this run "
                "is measured against a constraint with no basis in the spec "
                "for this library.%s No artefact discloses this."
                % (", ".join(sorted(distinct)), pdk, out["sdc"], period,
                   traced)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", nargs="?", default=".",
                    help="run/project directory")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    report = check(project)

    # House style: a single human-readable verdict line FIRST. The umbrella in
    # flow_compliance_check quotes a failing gate's first stdout line into the
    # report a human reads, so leading with indented JSON would render the
    # finding as a bare "{".
    print("%s: %s" % (report["verdict"], report["reason"]))
    for r in report.get("period_traced_to_rows", []) or []:
        print("  period %.4g ns traces to %s:%d — %s"
              % (r["period_ns"], r["file"], r["line"], r["text"]))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 1 if report.get("verdict") == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
