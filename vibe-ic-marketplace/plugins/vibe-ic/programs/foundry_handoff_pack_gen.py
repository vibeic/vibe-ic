#!/usr/bin/env python3
"""foundry_handoff_pack_gen.py — emit Step 35 foundry handoff package skeleton.

v1.6.36 — closes the Step 35 runner-vs-flow drift waiver. The flow YAML
expects a foundry-deliverable kit at `phase3/stage4/foundry_handoff/`
(mask_spec.json, wat_plan.json, scribe_line_layout.gds,
corner_test_vectors.json) plus an audit summary at
`reports/phase3/foundry_handoff_audit.json`.

The full kit is authored by the production team + foundry-interface
engineer. This generator emits a SKELETON pre-filled with the design's
real cell count, area, GDS path, and a TODO list pointing at the human
fields that still need to be authored (foundry-specific mask layer
table, WAT structure list, scribe-line PCM coordinates, corner test
vectors). It does NOT fabricate foundry data.

Substance gate (foundry_handoff_package_check) verifies the kit is
complete before tapeout — this generator just gives the engineer a
deterministic starting point so the rest of the workflow doesn't stall.

chip-AGNOSTIC. Exits 0 on success, 2 if project dir missing or
prerequisites absent.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402


def _read_text(p: Path) -> str:
    try:
        return p.read_text(errors="ignore")
    except Exception:
        return ""


def _parse_design_area(area_rpt: Path) -> dict:
    """Best-effort parse of OpenROAD report_design_area output."""
    out = {"die_area_um2": None, "core_area_um2": None,
           "utilization_pct": None}
    text = _read_text(area_rpt)
    if not text:
        return out
    for line in text.splitlines():
        ln = line.strip().lower()
        m = re.search(r"design area\s+([0-9.]+)", ln)
        if m:
            out["die_area_um2"] = float(m.group(1))
        m = re.search(r"core area\s+([0-9.]+)", ln)
        if m:
            out["core_area_um2"] = float(m.group(1))
        m = re.search(r"utilization[:\s]+([0-9.]+)", ln)
        if m:
            out["utilization_pct"] = float(m.group(1))
    return out


def _parse_synth_cell_count(synth_log: Path):
    """Extract Yosys 'Number of cells' line. Returns None on miss —
    ORGANIC-20260606 #446: never -1 (a negative count is the unfilled
    placeholder the substance gate rightly FAILs)."""
    text = _read_text(synth_log)
    for line in text.splitlines():
        if "Number of cells" in line:
            try:
                return int(line.split()[-1].replace(",", ""))
            except Exception:
                return None
    return None


def _count_netlist_instances(synth_dir: Path):
    """#446 fallback — count cell instantiations in the gate netlist
    when synth.log lacks the Yosys summary. Yosys names instances
    `_N_`; generic instantiations are `<cell> <inst> (`. Returns None
    when no netlist / no instances found (never a fabricated count)."""
    for nl in sorted(synth_dir.glob("*.v")):
        text = _read_text(nl)
        if not text:
            continue
        n = len(re.findall(r"^\s*\\?[A-Za-z_][\w$]*\s+\\?_?\w+_?\s*\(",
                           text, re.MULTILINE))
        # subtract module headers (they match the same shape)
        n -= len(re.findall(r"^\s*module\s+\w+\s*\(", text, re.MULTILINE))
        if n > 0:
            return n
    return None


def _detect_pdk_name(pdk_dir: Path):
    """#446 — derive the PDK identity from the PDK's OWN files (liberty
    stem up to the double-underscore cell-library separator, else tech
    LEF stem). Returns None when nothing is derivable — never the
    literal 'unknown' the substance gate FAILs on."""
    lib_dir = pdk_dir / "liberty"
    if lib_dir.is_dir():
        for f in sorted(lib_dir.glob("*.lib")):
            stem = f.stem
            return stem.split("__")[0] if "__" in stem else stem
    lef_dir = pdk_dir / "lef"
    if lef_dir.is_dir():
        for f in sorted(lef_dir.glob("*.tlef")) + sorted(lef_dir.glob("*.lef")):
            return f.stem
    return None


def _read_l_doc(project: Path, name: str) -> dict:
    """Load a phase1/generated_docs L doc. Returns {} on any miss so the
    fallback chain stays robust against absent/corrupt upstream files."""
    p = _pl.generated_docs_dir(project) / name
    try:
        data = json.loads(p.read_text(errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ic_name sentinels Phase 1 emits when nothing was extracted — these are
# NOT real names, so they must not pre-empt the --top / RTL fallbacks.
_IC_NAME_SENTINELS = {"unknown_ic", "unknown", "n/a", "none", "tbd"}


def _l1_ic_name(project: Path):
    """#467 — the design top from L1_DATASHEET[ic_name], when it is a real
    populated value (not a Phase-1 not-found sentinel). Returns None
    otherwise so the caller can fall back to --top / RTL detection."""
    name = _read_l_doc(project, "L1_DATASHEET.json").get("ic_name")
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or name.lower() in _IC_NAME_SENTINELS:
        return None
    return name


def _process_nm_from_pdk_text(text: str):
    """Extract a process-node nanometre integer from a free-text PDK /
    foundry statement (e.g. '130nm', '0.18um', 'IHP SG13G2 130 nm').
    Returns None when no node is stated."""
    if not isinstance(text, str) or not text:
        return None
    # explicit nm
    m = re.search(r"(\d+(?:\.\d+)?)\s*nm", text, re.IGNORECASE)
    if m:
        try:
            return int(round(float(m.group(1))))
        except ValueError:
            return None
    # micron form (0.18um -> 180nm)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:um|µm|micron)", text, re.IGNORECASE)
    if m:
        try:
            return int(round(float(m.group(1)) * 1000))
        except ValueError:
            return None
    return None


def _l19_pdk_target(project: Path):
    """#467 — the target PDK from L19_CONSTRAINTS_PDK[fields][pdk_target],
    when populated. Returns None on miss/empty."""
    fields = _read_l_doc(project, "L19_CONSTRAINTS_PDK.json").get("fields")
    if not isinstance(fields, dict):
        return None
    pt = fields.get("pdk_target")
    if not isinstance(pt, str):
        return None
    pt = pt.strip()
    return pt or None


def _l1_tapeout_metadata(project: Path) -> dict:
    """L1 tapeout_metadata as a dict (or {} when absent)."""
    tm = _read_l_doc(project, "L1_DATASHEET.json").get("tapeout_metadata")
    return tm if isinstance(tm, dict) else {}


def _l1_tapeout_pdk(project: Path):
    """#467 — fallback PDK statement from L1 tapeout_metadata. Prefers an
    explicit foundry name, else the process_node string. Returns None when
    neither is present."""
    tm = _l1_tapeout_metadata(project)
    for key in ("foundry", "process_node"):
        v = tm.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _l1_tapeout_node_nm(project: Path):
    """#467 — process-node nm parsed from the L1 tapeout_metadata PDK
    statement (the process_node field, then the foundry name). Returns None
    when no node digits are present."""
    tm = _l1_tapeout_metadata(project)
    for key in ("process_node", "foundry"):
        nm = _process_nm_from_pdk_text(tm.get(key))
        if nm is not None:
            return nm
    return None


def _resolve_design_top(project: Path, top_arg):
    """#467 — design_top fallback chain: L1 ic_name → --top argument →
    RTL-derived top module (legacy). Never a fabricated literal unless even
    the RTL scan finds nothing (then the historical 'chip_top' default)."""
    name = _l1_ic_name(project)
    if name:
        return name
    if isinstance(top_arg, str) and top_arg.strip():
        return top_arg.strip()
    return _detect_top_name(project)


# The PnR script OpenROAD actually executed names the PDK tree every liberty /
# tech-LEF / cell-LEF it read came from. That is GROUND TRUTH for "which PDK
# produced this GDS" — it is the files, not a statement about the files.
_SIGNOFF_PDK_RE = re.compile(r"/foss/pdks/([A-Za-z0-9._-]+)/")


def _pdk_from_signoff_flow(project: Path):
    """The PDK that ACTUALLY produced the shipped GDS, read off the sign-off
    PnR script's own asset paths. Returns None when the script is absent or
    references more than one PDK tree (ambiguous → never guess).

    chip-AGNOSTIC: pure path grammar over the flow's own generated script."""
    tcl = _pl.pnr_dir(project) / "pnr.tcl"
    try:
        names = set(_SIGNOFF_PDK_RE.findall(tcl.read_text(errors="replace")))
    except OSError:
        return None
    return next(iter(names)) if len(names) == 1 else None


def _resolve_pdk_and_node(project: Path, pdk_from_files, node_from_files):
    """#467 — pdk / process node fallback chain.

    pdk: the PDK that PRODUCED the GDS → L19 pdk_target → L1 tapeout PDK
         statement → PDK files.
    process_nm : PDK-file derivation → node parsed from the spec PDK text.
    Honest null preserved only when ALL sources are empty.

    SIGN-OFF PDK WINS OVER THE SPEC TARGET. #467 put the spec facts first
    ("Upstream spec facts win over PDK-file derivation"), which is right for a
    requirements document and WRONG for a manufacturing hand-off: this pack
    ships a GDS, and that GDS was made by exactly one PDK. When the design is
    built on a PDK its spec does not name — which is the entire point of a
    cross-PDK benchmark matrix, and routine whenever a design is ported — the
    pack declared the ASPIRATION and the foundry would receive the wrong
    process for the silicon in the same directory.

    MEASURED (spm x ihp-sg13cmos5l, plugin 1.6.4, image vibeic-eda:0.2.30
    id sha256:4182c63b10d1): every asset in phase3/stage3/pnr/pnr.tcl resolved
    under /foss/pdks/ihp-sg13cmos5l and the DRC ran the IHP deck, yet L19
    pdk_target was "sky130" (extracted from the spec's "target PDK family"
    prose), so mask_spec.json, wat_plan.json, corner_test_vectors.json,
    README.txt and scribe_line_layout all recorded `"pdk": "sky130"` beside an
    IHP GDS — and foundry_handoff_package_check returned PASS, because it
    checks that the files EXIST, never that they agree with the flow.

    The spec target is not discarded: when the two disagree the caller records
    it as `spec_pdk_target` so the divergence is visible rather than silently
    resolved either way."""
    l19 = _l19_pdk_target(project)
    l1 = _l1_tapeout_pdk(project)
    signoff = _pdk_from_signoff_flow(project)
    spec = l19 or l1
    pdk = signoff or spec or pdk_from_files
    # process node: trust the PDK-file derivation first (it knows the real
    # library), else parse a node out of the spec PDK text — L19 target
    # string, then the dedicated L1 tapeout process_node/foundry fields.
    node = node_from_files
    if node is None:
        node = (_process_nm_from_pdk_text(l19)
                or _l1_tapeout_node_nm(project))
    # Surface a spec-vs-silicon divergence instead of resolving it silently.
    mismatch = (spec if (signoff and spec and signoff != spec) else None)
    return pdk, node, mismatch


def _l10_test_pattern_ids(project: Path):
    """#446 — real ATE-pattern seeds from THIS design's L10 test cases
    (ids/names only; vectors are converted downstream). Empty list when
    no L10 doc exists."""
    l10 = project / "phase1" / "generated_docs" / "L10_TEST_CASES.json"
    try:
        data = json.loads(l10.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    cases = (data.get("test_cases") or data.get("fields", {}).get("test_cases")
             or [])
    out = []
    for c in cases:
        if isinstance(c, dict):
            ident = c.get("id") or c.get("name") or c.get("title")
            if ident:
                out.append(str(ident))
        elif isinstance(c, str):
            out.append(c)
    return out[:200]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("project", type=Path)
    p.add_argument(
        "--top", default=None,
        help="silicon top module name; #467 fallback used only when "
             "L1_DATASHEET[ic_name] is an empty / not-found sentinel.")
    args = p.parse_args(argv)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"VACUOUS_PASS: project dir missing: {project}",
              file=sys.stderr)
        return 2

    handoff_dir = _pl.foundry_handoff_dir(project)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    audit_dir = _pl.reports_phase3_dir(project)
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Collect design facts from artefacts the runner produced.
    pnr = _pl.pnr_dir(project)
    synth = _pl.synth_dir(project)
    gds_dir = _pl.gds_dir(project)
    gds_files = sorted(gds_dir.glob("*.gds")) + sorted(pnr.glob("*.gds"))
    primary_gds = gds_files[0] if gds_files else None

    cells = _parse_synth_cell_count(synth / "synth.log")
    if cells is None:
        cells = _count_netlist_instances(synth)  # #446 netlist fallback
    area = _parse_design_area(pnr / "area.rpt")

    pdk_dir = project / "input/pdk"
    # #446: derive the PDK identity from its own files; the old
    # `pdk_dir.name` ("pdk") / "unknown" placeholder fails the gate.
    pdk_from_files = _detect_pdk_name(pdk_dir) if pdk_dir.is_dir() else None
    # PDK / process node detection from the PDK's own liberty filenames.
    node_from_files = None
    for tag in ("180", "130", "65", "45", "28", "16", "12", "7"):
        # Heuristic: look for the tag in any .lib filename
        lib_dir = pdk_dir / "liberty"
        if lib_dir.is_dir():
            if any(tag in f.name for f in lib_dir.glob("*.lib")):
                node_from_files = int(tag)
                break

    # #467: upstream spec facts populate design_top / pdk / process node.
    # design_top  <- L1 ic_name → --top → RTL-derived top (legacy default).
    # pdk         <- L19 pdk_target → L1 tapeout PDK statement → PDK files.
    # process_nm  <- PDK-file derivation → node parsed from the spec PDK text.
    # Honest null is preserved only when ALL upstream sources are empty —
    # projects genuinely missing the value still get null (corpus-sweep
    # guard). PENDING_FOUNDRY_* semantics unchanged (#449).
    design_top = _resolve_design_top(project, args.top)
    pdk_name, process_nm, spec_pdk_target = _resolve_pdk_and_node(
        project, pdk_from_files, node_from_files)
    # #484: per-design identity stamp — the project NAME is always present
    # (design_top / pdk can both resolve null), so two designs never emit a
    # byte-identical handoff member that cross_design_identity_check (#454)
    # would flag as a canned cross-design report.
    _ident: dict = {"design": project.name}
    if design_top:
        _ident["top"] = str(design_top)
    if pdk_name:
        _ident["pdk"] = str(pdk_name)
    # The design was built on a PDK its own spec does not name. `pdk` above is
    # the one that made the GDS in this pack; keep the spec target visible so
    # the divergence is a recorded fact rather than a silent resolution.
    if spec_pdk_target:
        _ident["spec_pdk_target"] = str(spec_pdk_target)
        _ident["pdk_source"] = "signoff_flow"

    # Step 1: mask_spec.json — deterministic starting point. The mask
    # layer table is foundry-specific so we mark it TODO.
    mask_spec = {
        "schema_version": "1.0",
        "generated_by": "foundry_handoff_pack_gen v1.1",
        "design_identity": _ident,
        "design_top": design_top,
        "process_node_nm": process_nm,
        "pdk": pdk_name,
        "gds_path": (str(primary_gds.relative_to(project))
                     if primary_gds else None),
        "gds_size_bytes": (primary_gds.stat().st_size
                           if primary_gds else 0),
        "cell_count": cells,
        "die_area_um2": area["die_area_um2"],
        "core_area_um2": area["core_area_um2"],
        "utilization_pct": area["utilization_pct"],
        "PENDING_FOUNDRY_mask_layers": (
            "Author: per-foundry mask layer index → GDS layer mapping "
            "(typically 30+ rows: Diff, Poly, Active, Contact, M1-Mn, "
            "VIA1-VIAn-1, etc.). Foundry shuttle ships a template — "
            "fill against your final routing stack."
        ),
        "PENDING_FOUNDRY_reticle_steppers": (
            "Author: stepper field size, alignment marks, kerf width."
        ),
    }
    (handoff_dir / "mask_spec.json").write_text(
        json.dumps(mask_spec, indent=2, ensure_ascii=False) + "\n")

    # Step 2: wat_plan.json — Wafer Acceptance Test plan.
    # #446: carries the design/PDK facts so two different designs can
    # never emit byte-identical plans; TODOs remain only for the
    # genuinely foundry-supplied content.
    wat_plan = {
        "schema_version": "1.0",
        "generated_by": "foundry_handoff_pack_gen v1.1",
        "design_identity": _ident,
        "design_top": design_top,
        "pdk": pdk_name,
        "process_node_nm": process_nm,
        "gds_path": (str(primary_gds.relative_to(project))
                     if primary_gds else None),
        "PENDING_FOUNDRY_wat_structures": (
            "Author: list of PCM (Process Control Monitor) structures "
            "to be probed in the scribe line. Common entries: NMOS Vt, "
            "PMOS Vt, n+ contact resistance, p+ contact resistance, "
            "M1 sheet R, via chains (M1-M2..Mn-1-Mn), comb structures."
        ),
        "PENDING_FOUNDRY_yield_target_pct": (
            "Author: minimum acceptable yield (e.g. 80%) for the lot."
        ),
        "PENDING_FOUNDRY_acceptance_criteria": (
            "Author: pass/fail thresholds for each WAT parameter."
        ),
    }
    (handoff_dir / "wat_plan.json").write_text(
        json.dumps(wat_plan, indent=2, ensure_ascii=False) + "\n")

    # Step 3: corner_test_vectors.json — ATE corner test kit.
    # #446: seed the kit with THIS design's L10 test-case ids so the
    # pattern list is chip-specific (full vectors are converted from
    # sim traces downstream); TODOs only for foundry/ATE-supplied data.
    l10_ids = _l10_test_pattern_ids(project)
    corner_kit = {
        "schema_version": "1.0",
        "generated_by": "foundry_handoff_pack_gen v1.1",
        "design_identity": _ident,
        "design_top": design_top,
        "pdk": pdk_name,
        "test_pattern_seeds_from_l10": l10_ids,
        "test_pattern_seed_count": len(l10_ids),
        "PENDING_FOUNDRY_voltage_corners": ["VDD_min", "VDD_nom", "VDD_max"],
        "PENDING_FOUNDRY_temperature_corners_celsius": [-40, 25, 85, 125],
        "PENDING_FOUNDRY_test_patterns": (
            "Author: convert each L10 seed above into an ATE pattern "
            "(input vector + expected output + corner constraints) from "
            "cocotb/Verilator simulation traces — see "
            "vibe-ic:tapeout-checklist skill for guidance."
        ),
        "PENDING_FOUNDRY_loadboard_id": (
            "Author: ATE loadboard part number + revision."
        ),
    }
    (handoff_dir / "corner_test_vectors.json").write_text(
        json.dumps(corner_kit, indent=2, ensure_ascii=False) + "\n")

    # Step 4: scribe line — ORGANIC-20260606 #446: NO file wearing the
    # .gds name unless it IS a GDS. The old 137-byte text placeholder
    # named scribe_line_layout.gds was a fabricated artifact (and
    # byte-identical across designs). The need is recorded in a
    # plainly-named TODO note; a real foundry-supplied scribe GDS, when
    # present, is left untouched.
    scribe_path = handoff_dir / "scribe_line_layout.gds"
    if scribe_path.is_file():
        try:
            head = scribe_path.read_bytes()[:64]
        except OSError:
            head = b""
        if head.startswith(b"# PLACEHOLDER"):
            scribe_path.unlink()  # remove the old fabricated placeholder
    if not scribe_path.is_file():
        (handoff_dir / "scribe_line_layout.PENDING_FOUNDRY.txt").write_text(
            "scribe_line_layout.gds is FOUNDRY-SUPPLIED (PCM structures "
            "+ alignment marks) and is NOT generated here (#446). Obtain "
            "it from the shuttle/foundry kit and place it beside this "
            "note before tapeout.\n"
            # #484: the design NAME line is ALWAYS present (design_top / pdk
            # can both be null for two pre-resolution designs, which made
            # this honest PENDING note byte-identical and falsely flagged as
            # a canned cross-design report by cross_design_identity_check).
            f"# design: {project.name}\n"
            f"# design_top: {design_top}\n"
            f"# pdk: {pdk_name}\n")
    readme = handoff_dir / "README.txt"
    readme.write_text(
        "Foundry handoff package — auto-generated skeleton (v1.1).\n"
        # #484: design NAME line is always present so two designs that share
        # the default top do not emit a byte-identical README.
        f"Design name: {project.name}\n"
        f"Design: {design_top}\n"
        f"PDK: {pdk_name}\n"
        f"GDS: {str(primary_gds.relative_to(project)) if primary_gds else '(none)'}"
        f" ({primary_gds.stat().st_size if primary_gds else 0} B)\n"
        "\n"
        "Required artefacts:\n"
        "  mask_spec.json              — mask layer table + reticle config\n"
        "  wat_plan.json               — WAT probe plan + PCM structures\n"
        "  scribe_line_layout.gds      — foundry-supplied PCM/scribe layout\n"
        "                                (see scribe_line_layout.PENDING_FOUNDRY.txt)\n"
        "  corner_test_vectors.json    — ATE corner test kit\n"
        "\n"
        "PENDING_FOUNDRY_* entries inside each JSON mark fields the foundry /\n"
        "production team supplies before tape-out (open items). Substance\n"
        "gate `foundry_handoff_package_check` (Step 35) audits completeness.\n"
        "\n"
        "Authored design facts auto-included:\n"
        f"  cell_count    = {cells}\n"
        f"  die_area_um2  = {area['die_area_um2']}\n"
        f"  process_nm    = {process_nm}\n"
        f"  pdk           = {pdk_name}\n"
    )

    # Step 5: audit summary
    audit_path = audit_dir / "foundry_handoff_audit.json"
    audit = {
        "program": "foundry_handoff_pack_gen",
        "version": "1.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "verdict": "SKELETON_EMITTED",
        "artefacts": {
            "mask_spec": "phase3/stage4/foundry_handoff/mask_spec.json",
            "wat_plan": "phase3/stage4/foundry_handoff/wat_plan.json",
            "scribe_layout": ("phase3/stage4/foundry_handoff/scribe_line_layout.gds"
                              if (handoff_dir / "scribe_line_layout.gds").is_file()
                              else "phase3/stage4/foundry_handoff/scribe_line_layout.PENDING_FOUNDRY.txt"),
            "corner_test_vectors":
                "phase3/stage4/foundry_handoff/corner_test_vectors.json",
        },
        "design_facts": {
            "top": design_top,
            "cell_count": cells,
            "die_area_um2": area["die_area_um2"],
            "core_area_um2": area["core_area_um2"],
            "process_nm": process_nm,
            "pdk": pdk_name,
            "gds_size_bytes": (primary_gds.stat().st_size
                               if primary_gds else 0),
        },
        "pending_foundry_count": 9,  # PENDING_FOUNDRY_* fields (#449)
        "notes": (
            "Skeleton emits design facts + PENDING_FOUNDRY_* open items. "
            "Production tape-out requires foundry-supplied scribe layout + "
            "human-authored WAT plan + ATE test patterns. "
            "Substance audit performed by foundry_handoff_package_check."
        ),
    }
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "verdict": audit["verdict"],
        "out_dir": str(handoff_dir.relative_to(project)),
        "audit": str(audit_path.relative_to(project)),
    }, indent=2))
    return 0


def _detect_top_name(project: Path) -> str:
    """Return the silicon top module name (best-effort)."""
    rtl_dir = _pl.rtl_dir(project)
    for cand in ("chip_top_asic.sv", "chip_top.sv"):
        if (rtl_dir / cand).is_file():
            return cand.removesuffix(".sv")
    # fall back to whatever first .sv defines `module ...`
    if rtl_dir.is_dir():
        for f in sorted(rtl_dir.glob("*.sv")):
            text = f.read_text(errors="ignore")
            m = re.search(r"\bmodule\s+(\w+)", text)
            if m:
                return m.group(1)
    return "chip_top"


if __name__ == "__main__":
    sys.exit(main())
