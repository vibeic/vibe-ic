#!/usr/bin/env python3
"""
foundry_handoff_package_check.py — gate (v1.6.13 Wave 88, integerised
in v1.6.14 Wave 90, renumbered Step 34 → 35 in v1.6.15 Wave 91).

Step 35 — foundry-handoff kit completeness

Behaviour
---------
* SKIP (rc=2) — required artefacts missing AND step not waived.
* WAIVED (rc=0) — `waivers.json` declares step waived (evidence + ticket).
* PASS (rc=0) — required files present; gate-specific predicate is a
  stub in v1.6.13 (PASS-on-presence).
* FAIL (rc=1) — files present but predicate fails (not used in v1.6.13).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Default rationale when SKIP: Foundry-handoff kit assembler not shipped.

Usage
-----
    python3 foundry_handoff_package_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return (json.loads(p.read_text()).get("waived_steps") or [])
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


_GATE_NAME = 'foundry_handoff_package_check'
_GATE_LABEL = 'foundry_handoff'
_REQUIRED_FILES = ['phase3/stage4/foundry_handoff/mask_spec.json', 'phase3/stage4/foundry_handoff/wat_plan.json']
_WAIVER_RATIONALE = 'Foundry-handoff kit assembler not shipped.'

# v1.6.162 (#60 P2-7) — explicit chip-GDS requirement. Field agent
# observed Step 35 PASS on a project whose only foundry-handoff GDS
# was `scribe_line_layout.gds` (a foundry-supplied dummy frame),
# while the chip itself never produced a real GDS (Step 33
# tapeout_signoff_check FAILed). Step 35 must require a chip-named
# GDS file under `phase3/stage4/gds/` (or `gds/`) whose basename
# matches `L1.ic_name`. chip-AGNOSTIC: the L1.ic_name is read from
# L1_DATASHEET.json, not pattern-matched against chip-class string.
_SCRIBE_LINE_GDS_HINTS = (
    "scribe_line",
    "scribeline",
    "scribe-line",
    "frame",
)


def _read_l1_ic_name(project):
    """Read L1.ic_name from the phase1-emitted L1_DATASHEET.json.
    Returns None if unavailable (project hasn't run phase1 or L1
    schema lacks the field)."""
    for cand in (
        project / "phase1" / "generated_docs" / "L1_DATASHEET.json",
        project / "generated_docs" / "L1_DATASHEET.json",
    ):
        if not cand.is_file():
            continue
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            return None
        ic = data.get("ic_name")
        if isinstance(ic, str) and ic.strip():
            return ic.strip()
    return None


def _read_l9_top_module(project):
    """v1.6.174 (#72 P0-3) — read L9.top_module so chip-GDS lookup
    can ALSO match the RTL top-module name. Real PnR runners write
    GDS under the top-module identifier (e.g. `chip_top_asic.gds`)
    rather than L1.ic_name; without this fallback the v1.6.162 gate
    FAILed with `FOUNDRY_HANDOFF_CHIP_GDS_MISSING` despite a valid
    chip GDS being present.
    Returns the top-module string or None when unavailable."""
    for cand in (
        project / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json",
        project / "generated_docs" / "L9_INTEGRATION_SPEC.json",
    ):
        if not cand.is_file():
            continue
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            return None
        tm = data.get("top_module")
        if isinstance(tm, str) and tm.strip():
            return tm.strip()
    return None


_DEF_DESIGN_RE = re.compile(r"^\s*DESIGN\s+([A-Za-z_]\w*)\s*;")
# Anchored to statement position (line start, after optional whitespace) so a
# `link_design` mentioned in TCL *comment prose* ("... link_design followed by
# a read_def ...") is never mistaken for the actual command.
_LINK_DESIGN_RE = re.compile(r"^\s*link_design\s+([A-Za-z_]\w*)", re.M)


def _read_pnr_physical_top(project):
    """Resolve the ACTUAL physical top module the backend placed, routed and
    streamed the chip GDS from — independent of L1.ic_name / L9.top_module.

    Why this is needed (field: caravel step-35 GDS naming): L1.ic_name and L9.top_module both record
    the DESIGN-INTENT / project name, which can legitimately differ from the
    synthesizable RTL top. The runner resolves the real top structurally (the
    RTL instantiation-graph root — `_resolve_asic_top_structural`) and names
    every backend artefact (netlist / DEF / GDS) after it. Standard caravel is
    the canonical case: ic_name=`caravel_user_project` but the hardened top is
    `user_project_wrapper`, so the deliverable is `user_project_wrapper.gds`.
    Deriving the expected GDS basename from L-doc values alone therefore FAILs
    a correctly-named chip GDS with FOUNDRY_HANDOFF_CHIP_GDS_MISSING.

    chip-AGNOSTIC: reads only physical backend outputs, no chip literals —
      (a) the `DESIGN <name> ;` record of a DEF (the top cell of the physical
          database the GDS is streamed from; a universal, tool-agnostic DEF
          keyword). Only the DEF header is scanned (DESIGN is emitted early),
          never the multi-MB body;
      (b) `link_design <name>` in the PnR script (corroboration / fallback for
          flows that leave a script but no DEF).

    Returns an ordered, de-duplicated list of candidate physical-top names
    (possibly empty). A non-empty, non-scribe GDS whose basename matches one
    of these is a real chip deliverable — an EXACT identity match against the
    routed database's top cell, so this widens recognition WITHOUT weakening
    the gate: a genuinely missing chip GDS still matches nothing and FAILs."""
    names: list = []

    def _add(n):
        if isinstance(n, str):
            n = n.strip()
            if n and n not in names:
                names.append(n)

    # (a) DEF DESIGN line — prefer the final routed / signoff / pnr / eco DEF
    # (the physical database the chip GDS is streamed from). Scan only the DEF
    # header (first lines): DESIGN is emitted right after VERSION/UNITS.
    def _def_rank(p):
        s = str(p).lower()
        return 0 if any(k in s for k in ("routed", "signoff", "/pnr/",
                                         "/eco/")) else 1
    defs = sorted(project.glob("phase3/**/*.def"), key=_def_rank)
    for dpath in defs[:64]:
        try:
            with dpath.open(errors="replace") as fh:
                for _i, line in enumerate(fh):
                    if _i > 200:
                        break
                    m = _DEF_DESIGN_RE.match(line)
                    if m:
                        _add(m.group(1))
                        break
        except OSError:
            continue

    # (b) link_design <top> in the PnR TCL (fallback / corroboration).
    for tcl in sorted(project.glob("phase3/**/*.tcl"))[:64]:
        try:
            txt = tcl.read_text(errors="replace")[:200000]
        except OSError:
            continue
        for m in _LINK_DESIGN_RE.finditer(txt):
            _add(m.group(1))

    return names


def _chip_basename_variants(ic_name, top_module=None, extra_tops=None):
    """v1.6.174 (#72 P0-3) — full chip-named GDS basename set.
    Covers: `<id>`, `<id>_top`, `<id>_asic`, `<id>_chip`,
    `chip_<id>` for both `ic_name` AND `top_module`, PLUS
    `<top>_asic` / `chip_<top>_asic` / `<id>_top_asic` style
    combinations seen in real PnR output (e.g. OpenROAD writes
    `chip_top_asic.gds` for `top_module=chip_top`).

    v1.6.189 (#76 P1) — when L9.top_module is null, also include
    the runner's canonical `chip_top` family so the PnR output
    `chip_top_asic.gds` is recognised even before the L9 generator
    populates top_module. chip-AGNOSTIC: `chip_top` is the
    universal default emitted by aid_class_rtl_gen for every chip,
    not a chip-class literal.

    chip-AGNOSTIC: built from L1.ic_name + L9.top_module values
    read from generated_docs, never chip-class string literals."""
    seeds = set()
    for s in (ic_name, top_module, *(extra_tops or [])):
        if s and isinstance(s, str) and s.strip():
            seeds.add(s.strip())
    # v1.6.189 (#76 P1) — always include the canonical runner
    # default so null-L9.top_module projects still match the PnR
    # output filename family.
    seeds.add("chip_top")
    variants = set()
    suffixes = ("", "_top", "_asic", "_chip",
                "_top_asic", "_chip_asic", "_signoff")
    prefixes = ("", "chip_")
    for seed in seeds:
        lo = seed.lower()
        for pre in prefixes:
            for suf in suffixes:
                variants.add(f"{pre}{lo}{suf}")
    # Strip any empty / pure prefix-suffix combos.
    variants.discard("")
    variants.discard("chip_")
    return variants


def _find_chip_gds(project, ic_name):
    """Return (chip_gds_path, scribe_only).
    v1.6.174 (#72 P0-3) — also reads L9.top_module so GDS files
    named after the RTL top (e.g. `chip_top_asic.gds`) are
    recognised. Without this fallback the gate FAILed despite a
    valid chip GDS being present.
    chip-AGNOSTIC: all candidate names are derived from L-doc
    values (L1.ic_name + L9.top_module), never hardcoded chip
    literals.
    """
    if not ic_name:
        return None, False, []
    top_module = _read_l9_top_module(project)
    # field (caravel step-35 GDS naming) — the ACTUAL physical top the backend hardened (may differ from
    # both L1.ic_name and L9.top_module; e.g. caravel → `user_project_wrapper`).
    physical_tops = _read_pnr_physical_top(project)
    roots = [
        project / "phase3/stage4/foundry_handoff/gds",
        project / "phase3/stage4/gds",
        project / "gds",
    ]
    all_gds = []
    for root in roots:
        if root.is_dir():
            all_gds.extend(sorted(root.glob("*.gds")))
    if not all_gds:
        return None, False, physical_tops
    chip_basenames = _chip_basename_variants(ic_name, top_module, physical_tops)
    seed_prefixes = [s.lower() for s in ([ic_name, top_module] + physical_tops)
                     if s and isinstance(s, str)]
    chip_gds = None
    real_files = []
    scribe_files = []
    for f in all_gds:
        stem = f.stem.lower()
        if any(hint in stem for hint in _SCRIBE_LINE_GDS_HINTS):
            scribe_files.append(f)
            continue
        real_files.append(f)
        # field (caravel step-35 GDS naming) — a real chip GDS must be NON-EMPTY. A 0-byte GDS is a
        # broken/placeholder deliverable and must never be accepted as the
        # chip GDS (the gate then FAILs as CHIP_GDS_MISSING, honestly). This
        # keeps the widened top-name matching from ever passing vacuously.
        try:
            if f.stat().st_size <= 0:
                continue
        except OSError:
            continue
        if stem in chip_basenames:
            chip_gds = chip_gds or f
            continue
        # Fallback: prefix-match on ic_name / top_module / physical top.
        for seed in seed_prefixes:
            if stem.startswith(seed):
                chip_gds = chip_gds or f
                break
    scribe_only = bool(scribe_files) and not real_files
    return chip_gds, scribe_only, physical_tops


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    found = [p for p in _REQUIRED_FILES if list(project.glob(p))]
    missing = [p for p in _REQUIRED_FILES if p not in found]

    # v1.6.162 (#60 P2-7) — chip-GDS gate.
    ic_name = _read_l1_ic_name(project)
    chip_gds, scribe_only, physical_tops = _find_chip_gds(project, ic_name)
    chip_gds_finding = None
    if ic_name and chip_gds is None:
        if scribe_only:
            chip_gds_finding = {
                "severity": "ERROR",
                "rule": "FOUNDRY_HANDOFF_SCRIBE_ONLY",
                "message": (
                    f"only scribe-line / frame GDS present under "
                    f"foundry-handoff GDS dirs; no chip GDS matching "
                    f"L1.ic_name={ic_name!r} found. Step 33 "
                    f"tapeout_signoff_check should have already FAILed; "
                    f"this gate must NOT PASS on a scribe-only manifest."
                ),
            }
        else:
            chip_gds_finding = {
                "severity": "ERROR",
                "rule": "FOUNDRY_HANDOFF_CHIP_GDS_MISSING",
                "message": (
                    f"no non-empty chip GDS matching L1.ic_name={ic_name!r}, "
                    f"L9.top_module, or the physical PnR top "
                    f"{physical_tops or '(none resolved)'} "
                    f"under phase3/stage4/foundry_handoff/gds/ or "
                    f"phase3/stage4/gds/ or gds/. Step 35 PASS "
                    f"requires the chip-named GDS deliverable."
                ),
            }

    # ORGANIC-20260606 #433(d) — 0-byte member hard-fail: an empty file
    # inside the handoff pack is a broken deliverable (one audited campaign
    # shipped a 0-byte chip_top.magic_merged.gds). Scan every member; any
    # 0-byte file FAILs packaging by NAME — never waivable into a PASS.
    zero_members = []
    for hd in sorted(project.glob("phase3/stage4/foundry_handoff/**/*")):
        if hd.is_file() and hd.stat().st_size == 0:
            zero_members.append(str(hd.relative_to(project)))
    if zero_members:
        verdict, rc = "FAIL", 1
        findings = [{
            "severity": "ERROR",
            "rule": "FOUNDRY_HANDOFF_ZERO_BYTE_MEMBER",
            "message": (
                f"0-byte member file(s) in the handoff pack — an empty "
                f"deliverable must hard-fail packaging (#433d): "
                f"{zero_members[:6]}"),
        }]
        report = {"program": _GATE_NAME, "verdict": verdict,
                  "findings": findings,
                  "zero_byte_members": zero_members}
        out = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out)
        print(out)
        return rc

    # ORGANIC-20260606 #437(b) — pack-substance scan: a handoff whose
    # members self-report placeholder content is not a deliverable. FAIL
    # by name on: TODO/TBD markers in pack text members, cell_count < 0,
    # pdk == "unknown" in pack JSON members. (0-byte members already
    # hard-fail above.)
    #
    # ORGANIC-20260606 #449 — TODO semantics split: design-derivable
    # TODO/TBD residue stays ERROR (an unfilled field the generator
    # should have derived), while the structured PENDING_FOUNDRY_*
    # namespace marks fields the FOUNDRY supplies before tapeout —
    # honest open items, surfaced as a NAMED INFO finding (and listed
    # in the report for the tapeout checklist), never an ERROR. The
    # generator's own legit output must pass its own gate.
    substance_findings = []
    pending_foundry_fields = []
    for hf in sorted(project.glob("phase3/stage4/foundry_handoff/**/*")):
        if not hf.is_file() or hf.stat().st_size == 0:
            continue
        if hf.suffix.lower() in (".gds", ".gds2", ".gdsii", ".oas"):
            continue
        try:
            txt = hf.read_text(errors="replace")[:20000]
        except OSError:
            continue
        rel = str(hf.relative_to(project))
        # #449 field-audit hardening: `\bTODO\b` misses the `TODO_foo`
        # key shape (underscore is a word char — no boundary), so a
        # hand-crafted TODO_* key could bypass the scan. Match the
        # underscore-suffixed forms too; PENDING_FOUNDRY_* stays clean.
        n_todo = len(re.findall(r"\bTODO(?:_\w+)?\b|\bTBD(?:_\w+)?\b", txt))
        if n_todo:
            substance_findings.append({
                "severity": "ERROR",
                "rule": "FOUNDRY_HANDOFF_TODO_MARKERS",
                "message": (f"{rel}: {n_todo} TODO/TBD marker(s) — a "
                            f"handoff member with open placeholders is "
                            f"not a deliverable (#437b). Foundry-supplied "
                            f"fields belong in the PENDING_FOUNDRY_* "
                            f"namespace (#449)."),
            })
        if hf.suffix.lower() == ".json":
            try:
                jd = json.loads(txt)
            except ValueError:
                jd = None
            if isinstance(jd, dict):
                for k in jd:
                    if str(k).startswith("PENDING_FOUNDRY_"):
                        pending_foundry_fields.append(f"{rel}:{k}")
                cc = jd.get("cell_count")
                if isinstance(cc, (int, float)) and cc < 0:
                    substance_findings.append({
                        "severity": "ERROR",
                        "rule": "FOUNDRY_HANDOFF_CELL_COUNT_INVALID",
                        "message": (f"{rel}: cell_count={cc} — a negative "
                                    f"count is an unfilled placeholder "
                                    f"(#437b)."),
                    })
                if str(jd.get("pdk", "")).strip().lower() == "unknown":
                    substance_findings.append({
                        "severity": "ERROR",
                        "rule": "FOUNDRY_HANDOFF_PDK_UNKNOWN",
                        "message": (f"{rel}: pdk=unknown — a mask spec "
                                    f"that cannot name its process is not "
                                    f"submittable (#437b)."),
                    })

    waiver = _step_waived(project, args.step_label)
    if substance_findings and not waiver:
        verdict, rc = "FAIL", 1
        findings = substance_findings
        report = {"program": _GATE_NAME, "verdict": verdict,
                  "findings": findings}
        out = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out)
        print(out)
        return rc
    if missing and not waiver:
        verdict, rc = "SKIP", 2
        findings = [{"severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                      "message": f"missing: {missing}"}]
    elif missing and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
    elif chip_gds_finding is not None and not waiver:
        verdict, rc = "FAIL", 1
        findings = [chip_gds_finding]
    elif chip_gds_finding is not None and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
    else:
        verdict, rc = "PASS", 0
        ok_msg = (f"all {len(_REQUIRED_FILES)} required artefacts present"
                  + (f" + chip GDS {chip_gds.name!r}" if chip_gds else ""))
        findings = [{"severity": "INFO", "rule": "FILES_PRESENT",
                      "message": ok_msg}]

    # #449 — PENDING_FOUNDRY_* open items: a NAMED INFO finding so the
    # tapeout checklist lists them; never an ERROR (foundry-supplied by
    # definition).
    if pending_foundry_fields:
        findings.append({
            "severity": "INFO",
            "rule": "FOUNDRY_HANDOFF_PENDING_FOUNDRY",
            "message": (f"{len(pending_foundry_fields)} foundry-supplied "
                        f"open item(s) pending before tapeout (#449): "
                        + "; ".join(pending_foundry_fields[:12])),
        })

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": _REQUIRED_FILES,
        "found": found,
        "missing": missing,
        "ic_name": ic_name,
        "physical_top_candidates": physical_tops,  # actual PnR top(s)
        "chip_gds": str(chip_gds) if chip_gds else None,
        "scribe_only": scribe_only,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "pending_foundry_fields": pending_foundry_fields,  # #449 open items
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if missing:
        print(f"  missing: {missing}")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket','?')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
