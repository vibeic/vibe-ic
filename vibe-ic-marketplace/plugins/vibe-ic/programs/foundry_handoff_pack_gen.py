#!/usr/bin/env python3
"""foundry_handoff_pack_gen.py — assemble the Step38 design-release package.

The release copies the admitted final design GDS without changing its bytes.
Its physical hierarchy root is the mask specification's design_top; the L1
product/project label is recorded separately as design_label. Existing package
and technical signoff consumers remain responsible for release acceptance.

Provider-specific submission requirements and manufacturing/test services are
separate from universal design-release requirements. Mask preparation, reticle
frames and PCM/WAT may be supplied by the foundry or shuttle provider. The
applicable submission contract decides what the designer must deliver. This
program records unresolved service data as owned open items; it does not
invent it or claim that a foundry accepted an order.

A yield target is a contract/planning value, not measured silicon yield.
Loadboards, ATE preparation, wafer acceptance and post-silicon yield belong to
their applicable manufacturing/test arrangements; they are not universal
preconditions for releasing every IC's GDS. The existing Step5-derived ATE
pattern checks and all existing physical/signoff gates are unchanged here.

chip-AGNOSTIC. Exits 0 when the package was emitted, 1 for an explicit top
contradicting the measured hierarchy, and 2 when project/native prerequisites are
unavailable. A skeleton-emission exit is not a foundry acceptance verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import _foundry_signoff_pdk as _fsp  # noqa: E402
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)
# ONE resolver for "what is the chip GDS", shared with the Step-35 gate that
# grades this kit, so producer and gate cannot drift apart (field: foundry-handoff hollow chip GDS).
import foundry_handoff_package_check as _fhpc  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402  (vibe-ic#1082)
import _gds_admission as _ga  # noqa: E402
import ate_pattern_gen as _ate  # noqa: E402  (U18: our own open item)

RELEASE_APPROVAL_REL = "input/release_approval.json"


def read_release_approval(project: Path, gds: Path) -> dict:
    """Read D81's one accountable approval input for the actual released GDS.

    JSON object: approved (boolean true), approved_by (nonempty string),
    gds (project-relative file path), gds_sha256 (the GDS's SHA-256 hex string).
    The accountable release owner supplies this input; the plugin never signs.
    """
    project, gds = Path(project).resolve(), Path(gds).resolve()
    approval = json.loads((project / RELEASE_APPROVAL_REL).read_text())
    if not isinstance(approval, dict):
        raise ValueError("release approval must be a JSON object")
    if approval.get("approved") is not True:
        raise ValueError("accountable release owner has not approved this release")
    if not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip():
        raise ValueError("release approval requires approved_by")
    selected = Path(approval.get("gds", ""))
    if selected.is_absolute() or ".." in selected.parts or project / selected != gds:
        raise ValueError("release approval does not name the final project GDS")
    if approval.get("gds_sha256") != hashlib.sha256(gds.read_bytes()).hexdigest():
        raise ValueError("release approval does not approve the final GDS bytes")
    return approval


def execute(project: Path, context: dict) -> dict:
    """D81's release entry. Its approval and invocation belong to the owner."""
    from tapeout_declaration_gen import final_gds
    project = Path(project).resolve()
    result = {"step_id": "D81", "context_sha256": context.get("context_sha256"),
              "program": "foundry_handoff_pack_gen", "approval_input": RELEASE_APPROVAL_REL}
    try:
        result["approval"] = read_release_approval(project, final_gds(project))
        programs = Path(__file__).resolve().parent
        rc = subprocess.run([sys.executable, '-B', str(programs / 'tapeout_docs_gen.py'),
            '--project', str(project), '--out-dir', str(_pl.reports_phase3_dir(project) / 'docs'),
            '--plugin-version', _pmd.running_plugin_version()], cwd=project).returncode
        if rc == 0:
            rc = subprocess.run([sys.executable, '-B', str(programs / 'ic_release_docs_gen.py'),
                str(project)], cwd=project).returncode
        if rc == 0:
            rc = main([str(project)])
        if rc == 0:
            import tapeout_checklist_gen as checklist
            rc = checklist.main([str(project)])
        if rc == 0:
            rc = _fhpc.main([str(project)])
        status = "PASS" if rc == 0 else "FAIL" if rc == 1 else "NOT_MEASURED"
        result["exit_code"] = rc
    except FileNotFoundError as exc:
        status, result["reason"] = "NOT_MEASURED", str(exc)
    except (OSError, ValueError, TypeError) as exc:
        status, result["reason"] = "FAIL", str(exc)
    return {**result, "component_status": status, "default_row_status": status,
            "completed": status == "PASS"}


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
    when no netlist / no instances found (never a fabricated count).

    The count is the MAXIMUM over the candidate netlists, not the first
    one that yields a hit. `sorted(glob("*.v"))` is FILESYSTEM ORDER, and
    the synth directory holds more than the mapped netlist: yosys drops
    techmap helper libraries (`_dlatch_map.v`, 192 bytes, ONE
    instantiation) beside the design's own netlist, and `_` (0x5F) sorts
    ahead of every lowercase letter. First-hit-wins therefore returned
    `1` for a design whose routed DEF declares 79499 components, and that
    `1` was written into `mask_spec.json` + the handoff `README.txt` as
    the chip's cell count — the number a foundry reads.

    MAX is the right reducer here and needs no threshold: a helper file
    can only ever contribute FEWER instantiations than the netlist that
    instantiates the design, so taking the largest candidate is monotone
    in the real answer and stays `None` when nothing parses."""
    best = None
    for nl in sorted(synth_dir.glob("*.v")):
        text = _read_text(nl)
        if not text:
            continue
        n = len(re.findall(r"^\s*\\?[A-Za-z_][\w$]*\s+\\?_?\w+_?\s*\(",
                           text, re.MULTILINE))
        # subtract module headers (they match the same shape)
        n -= len(re.findall(r"^\s*module\s+\w+\s*\(", text, re.MULTILINE))
        if n > 0 and (best is None or n > best):
            best = n
    return best


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


def _resolve_design_top(project: Path, top_arg, gds: Path | None = None):
    """Measure the released hierarchy; unknown metadata stays unknown.

    Product labels and filenames are not physical cell names. A supplied
    --top constrains a measured unique root; it never renames that root.
    This metadata reader does not replace the existing GDS/signoff gates.
    """
    facts = {"top": None, "source": (str(gds.relative_to(project)) if gds.is_relative_to(project) else str(gds)) if gds else None,
             "method": "GDS STRNAME/SNAME", "root_candidates": [], "reason": None}
    if gds is None:
        facts["reason"] = "No final GDS available to measure the physical top"
        return facts
    import _gds_geometry as geometry
    try:
        layout = geometry.read_layout(gds)
    except (OSError, geometry.GdsError) as exc:
        facts["reason"] = f"Physical hierarchy could not be read: {exc}"
        return facts
    roots = layout.top_cells()
    facts["root_candidates"] = roots
    if layout.truncated or layout.dangling_references() or len(roots) != 1:
        facts["reason"] = "Final GDS has no unique complete physical root"
        return facts
    actual = roots[0]
    if isinstance(top_arg, str) and top_arg.strip() and top_arg.strip() != actual:
        raise ValueError(f"--top {top_arg!r} differs from final GDS root {actual!r}")
    facts["top"] = actual
    measured = geometry.flattened_bbox(layout, actual)
    if measured.complete and measured.bbox and layout.dbu_um:
        facts["bbox_um"] = [value * layout.dbu_um for value in measured.bbox]
    return facts


# The PnR script OpenROAD actually executed names the PDK tree every liberty /
# tech-LEF / cell-LEF it read came from. That is GROUND TRUTH for "which PDK
# produced this GDS" — it is the files, not a statement about the files.
def _signoff_flow_texts(project: Path):
    """The sign-off flow's published paths, or disk paths in a live run."""
    yield from _fsp.signoff_flow_texts(project)


def _pdk_from_signoff_flow(project: Path):
    """One actual sign-off PDK, or None when evidence is absent/ambiguous."""
    return _fsp.pdk_from_signoff_flow(project)


# ─────────────────────────────────────────────────────────────────────────────
# THE CORNERS THIS DESIGN WAS ACTUALLY SIGNED OFF AT (Step-38 enhancement)
#
# `corner_test_vectors.json` used to ship these two lines:
#
#     "PENDING_FOUNDRY_voltage_corners": ["VDD_min", "VDD_nom", "VDD_max"],
#     "PENDING_FOUNDRY_temperature_corners_celsius": [-40, 25, 85, 125],
#
# Neither is pending on the foundry and neither was measured. They are CANNED
# LITERALS wearing an honest-looking prefix, and they are wrong for every design
# in the published corpus. MEASURED over the 8 published roots that carry a
# hand-off kit, reading the liberty files the sign-off flow itself consumed:
#
#     8 of 8    resolve at least one liberty corner
#     2 of 8    resolve the full three-corner set
#               ff_n40C_1v95 / tt_025C_1v80 / ss_100C_1v40
#
# So the kit shipped a foundry `[-40, 25, 85, 125] °C` for a design signed off
# at -40 / 25 / 100 °C — a temperature the design was never characterised at,
# and the one it WAS characterised at missing. A fabricated value behind a
# PENDING_ prefix is worse than an empty field, because it is actionable.
#
# The corners are OURS and the flow already knows them. `_pdk_from_signoff_flow`
# established the mechanism: the assets the sign-off flow actually consumed are
# ground truth. The liberty BASENAME carries the operating point, so the same
# walk that names the PDK also names the corners.
#
# THE GRAMMAR IS MEASURED, NOT REMEMBERED — every liberty basename shipped in
# the pinned image was enumerated (2026-08-20, sha256:66c33ff2…):
#
#   form A   sky130 / gf180mcu   ..._<proc>_<T>C_<V>.lib
#            sky130_fd_sc_hd__tt_025C_1v80.lib          25 C   1.80 V
#            gf180mcu_fd_io__ff_n40C_5v50.lib          -40 C   5.50 V
#   form B   IHP                 ..._<proc>_<V>V_<T>C.lib   (order swapped,
#                                `p` for the decimal point, `m` for minus)
#            sg13g2_stdcell_typ_1p20V_25C.lib           25 C   1.20 V
#            sg13cmos5l_io_fast_1p32V_3p6V_m40C.lib    -40 C   1.32 + 3.6 V
#   form C   asap7               asap7sc7p5t_AO_RVT_TT_nldm_211120.lib
#   form D   nangate45           NangateOpenCellLibrary_typical.lib
#
# Forms C and D carry NO operating point in the name. They must resolve to
# NOT_DETERMINED — never to a default — and the count of basenames that failed
# to parse is reported so the non-answer is a datum.
#
# BOTH DELIMITERS ARE LOAD-BEARING, and each was put there by a measured false
# positive in the shipped filename set:
#   * `asap7sc7p5t` -> `7p5` would read as 7.5 V. It is a CELL HEIGHT (7.5
#     track). Requiring `_` before the token excludes it.
#   * `gf180mcu_fd_sc_mcu7t5v0__…` -> `5v0` would read as 5.0 V from the
#     LIBRARY NAME rather than from the corner. Same `_` guard excludes it;
#     the real `_5v00.` in the corner field still matches.
#   * `sky130_ef_io__gpiov2_pad_…` -> `v2` needs a digit before `v`, and has
#     `o`. Excluded by the digit requirement.
# ─────────────────────────────────────────────────────────────────────────────

# A liberty file anywhere under a PDK tree, as the flow's own artefacts spell it.
_SIGNOFF_LIB_RE = re.compile(r"/foss/pdks/[^\s'\";:)\]]*?\.lib")

# `_1v80` / `_5v00` / `_1p20V` / `_3p6V` — delimited on the left, and closed by
# a delimiter or an optional unit suffix on the right.
_LIB_VOLT_RE = re.compile(r"(?<=_)(\d{1,2})[vp](\d{1,2})V?(?=_|\.|$)")
# `_025C` / `_n40C` / `_m40C` / `_125C` — `n` and `m` both spell a minus sign.
_LIB_TEMP_RE = re.compile(r"(?<=_)([nm]?)(\d{1,3})C(?=_|\.|$)")


def _corner_from_liberty_name(stem: str):
    """(volts, temps) parsed out of ONE liberty basename.

    Returns two lists, either of which may be empty. A file naming several
    rails (`…_1v95_1v65.lib` — core and IO) yields every one of them: picking
    one would be a guess about which rail the reader means."""
    volts = [float(f"{a}.{b}") for a, b in _LIB_VOLT_RE.findall(stem)]
    temps = [(-1 if sign else 1) * int(digits)
             for sign, digits in _LIB_TEMP_RE.findall(stem)]
    return volts, temps


def _signoff_liberty_corners(project: Path) -> dict:
    """The operating corners the sign-off flow's OWN liberty files declare.

    Reads the same published-tree-restricted artefact set `_pdk_from_signoff_
    flow` reads, so it inherits that function's contract: on a published tree
    only tracked files count, because the question is what a reader RECEIVES.

    Never guesses. When no liberty path is named, or none of the ones named
    carry an operating point in their filename, the corners come back empty and
    `liberty_seen` / `liberty_unparsed` state the size of the search that
    established it."""
    seen: set = set()
    volts: set = set()
    temps: set = set()
    unparsed: list = []
    for p in _signoff_flow_texts(project):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for hit in _SIGNOFF_LIB_RE.findall(text):
            seen.add(hit)
    for lib in sorted(seen):
        stem = lib.rsplit("/", 1)[-1]
        v, t = _corner_from_liberty_name(stem)
        if not v and not t:
            unparsed.append(stem)
            continue
        volts.update(v)
        temps.update(t)
    return {
        "voltages_v": sorted(volts),
        "temperatures_celsius": sorted(temps),
        "liberty_files": sorted(lib.rsplit("/", 1)[-1] for lib in seen),
        "liberty_seen": len(seen),
        "liberty_unparsed": sorted(unparsed),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SHUTTLE OR DEDICATED MASK SET — the split that decides who owns this kit
#
# On a multi-project shuttle the submitter buys a SLOT, not a reticle. The
# scribe line, the PCM structures, the stepper and the mask layer table are the
# OPERATOR's, and `PENDING_FOUNDRY` is then the correct answer rather than a
# gap — the defect is only that the note never said WHO it was pending on. On a
# dedicated mask set the same fields are the customer's problem.
#
# Step 38 did not know which case it was in. It still cannot be TOLD — nothing
# in the flow declares it — but it can now MEASURE the one case that leaves
# evidence: step 37.5ic runs the shuttle operator's own container and writes
# `reports/phase3/shuttle_precheck.json`, which names the operator, its
# lifecycle status and the verdict it returned. A design that has asked a
# shuttle operator for a verdict is on the shuttle path, and the operator's
# identity is then a fact off a run rather than a declaration.
#
# THE ABSENCE OF THAT REPORT IS NOT A DEDICATED MASK SET. It is the far more
# likely case that 37.5ic has not run. Reading absence as "dedicated" would
# rebuild this repository's own recurring defect — an empty result made
# indistinguishable from a determined one — one level up, so the third value is
# UNDECLARED and it is neither of the other two.
# ─────────────────────────────────────────────────────────────────────────────

MODE_SHUTTLE = "shuttle"
MODE_DEDICATED = "dedicated"
MODE_UNDECLARED = "undeclared"

_SHUTTLE_PRECHECK_REPORT = "reports/phase3/shuttle_precheck.json"


def _sha256_of(path: Path):
    """sha256 of a file, or None when it cannot be read."""
    import hashlib
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _handoff_mode(project: Path, assembly=None) -> dict:
    """Which of the two situations this hand-off is in, and on what evidence.

    Precedence:
      1. an explicit L1 `tapeout_metadata.handoff_mode` declaration, when the
         spec carries one. NOTHING IN THE FLOW WRITES THIS KEY TODAY — it is
         read here so that the declaration, when the flow gains one, lands in
         a place that already consumes it rather than needing this program
         changed again. Its absence is the ordinary case, not an error.
      2. `reports/phase3/shuttle_precheck.json` — 37.5ic asked an operator, so
         this is the shuttle path and the operator is named.
      3. UNDECLARED. Not dedicated. See the block comment above.
    """
    if assembly is not None:
        provider = _fhpc.selected_provider_precheck(assembly)
        report = provider.get('retained_report') or {}
        return {'mode':MODE_SHUTTLE,'basis':'selected provider assembly: '+provider['reason'],
                'operator':provider.get('provider'),'operator_status':'TECHNICAL_PRECHECK_ONLY',
                'precheck_verdict':provider['technical_precheck_status'],
                'precheck_report':report.get('source'),'precheck_report_sha256':report.get('sha256'),
                'accepted':False}
    declared = _l1_tapeout_metadata(project).get("handoff_mode")
    if isinstance(declared, str) and declared.strip().lower() in (
            MODE_SHUTTLE, MODE_DEDICATED):
        return {
            "mode": declared.strip().lower(),
            "basis": "L1_DATASHEET.tapeout_metadata.handoff_mode",
            "operator": None,
            "operator_status": None,
            "precheck_verdict": None,
            "precheck_report": None,
            "precheck_report_sha256": None,
        }
    rpt = project / _SHUTTLE_PRECHECK_REPORT
    if rpt.is_file():
        try:
            data = json.loads(rpt.read_text(errors="replace"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        # WHOSE VERDICT IS IT. 37.5ic writes this report on EVERY run that
        # reaches it, including the runs where its own arm reports that the
        # registry names no live shuttle for this PDK -- the one absence
        # `tapeout_precheck` documents as "not a defect". Such a report is not
        # an operator's acceptance and this is not the shuttle path.
        # MEASURED on spm run13 and run8 (8HD-4), both DIEs:
        #   verdict NOT_APPLICABLE · arm_ran false · shuttle null
        #   verdict_is_the_operators FALSE
        # Keyed on an EXPLICIT false only, so a report that omits the field
        # resolves exactly as it did before and no existing kit changes meaning.
        # `foundry_handoff_package_check._verdict_is_an_operators` asks the same
        # question the same way: this mode is re-derived there and compared, so
        # the two MUST agree or the kit is reported as mis-stating its own mode.
        if data.get("verdict_is_the_operators") is False:
            return {
                "mode": MODE_UNDECLARED,
                "basis": (
                    f"{_SHUTTLE_PRECHECK_REPORT} is present but records "
                    f"verdict_is_the_operators=false "
                    f"(verdict={data.get('verdict')!r}, shuttle="
                    f"{data.get('shuttle')!r}): step 37.5ic ran and found no "
                    f"operator to ask for this PDK, so no operator acceptance "
                    f"is part of this hand-off."),
                "operator": None,
                "operator_status": None,
                "precheck_verdict": data.get("verdict"),
                "precheck_report": _SHUTTLE_PRECHECK_REPORT,
                "precheck_report_sha256": _sha256_of(rpt),
            }
        return {
            "mode": MODE_SHUTTLE,
            "basis": _SHUTTLE_PRECHECK_REPORT,
            "operator": data.get("shuttle") or data.get("shuttle_id"),
            "operator_status": data.get("shuttle_status") or data.get("status"),
            "precheck_verdict": data.get("verdict"),
            "precheck_report": _SHUTTLE_PRECHECK_REPORT,
            "precheck_report_sha256": _sha256_of(rpt),
        }
    return {
        "mode": MODE_UNDECLARED,
        "basis": (f"no {_SHUTTLE_PRECHECK_REPORT} on disk and no L1 "
                  f"tapeout_metadata.handoff_mode declaration. Absence of a "
                  f"shuttle precheck is NOT a dedicated mask set — step 37.5ic "
                  f"most likely has not run."),
        "operator": None,
        "operator_status": None,
        "precheck_verdict": None,
        "precheck_report": None,
        "precheck_report_sha256": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# WHO OWNS EACH OPEN ITEM — the PENDING_FOUNDRY_* pile, differentiated
#
# Nine fields carried the same prefix and the same silence about who would
# close them. Three of them are not the foundry's at all:
#
#   voltage_corners / temperature_corners_celsius   OURS, and DERIVABLE NOW —
#       they are the corners the sign-off liberty files declare. They no longer
#       appear here because they are no longer pending on anybody.
#   test_patterns                                   OURS. The L10 seeds are
#       already in this member; converting them to ATE vectors is work we owe,
#       not a foundry reply.
#
# Two more are a CONTRACT rather than a foundry deliverable, and on a shuttle
# they do not exist: a slot buyer has no per-customer lot yield target and no
# private WAT limit table.
#
# `owner` is the party who closes the item. `closed_by` names the artefact that
# would close it, so the note says what to go and get. `applies_in_mode` says
# which of the two situations the item exists in at all.
# ─────────────────────────────────────────────────────────────────────────────

OWNER_OPERATOR = "shuttle_operator"     # the party that owns the reticle
OWNER_FOUNDRY = "foundry"
OWNER_CONTRACT = "customer_foundry_contract"
OWNER_TEST_HOUSE = "test_house"
OWNER_US = "this_flow"

_BOTH = (MODE_SHUTTLE, MODE_DEDICATED, MODE_UNDECLARED)
_DEDICATED_ONLY = (MODE_DEDICATED, MODE_UNDECLARED)

#: field -> (owner-on-dedicated, closing artefact, modes it exists in)
_OPEN_ITEM_OWNERS = {
    "PENDING_FOUNDRY_mask_layers": (
        OWNER_FOUNDRY,
        "the process mask layer index -> GDS layer/datatype table",
        _BOTH),
    "PENDING_FOUNDRY_reticle_steppers": (
        OWNER_FOUNDRY,
        "the reticle field size, alignment-mark set and kerf width for the "
        "stepper the lot runs on",
        _BOTH),
    "PENDING_FOUNDRY_wat_structures": (
        OWNER_FOUNDRY,
        "the PCM structure list probed in the scribe line",
        _BOTH),
    "PENDING_FOUNDRY_yield_target_pct": (
        OWNER_CONTRACT,
        "the lot acceptance agreement",
        _DEDICATED_ONLY),
    "PENDING_FOUNDRY_acceptance_criteria": (
        OWNER_CONTRACT,
        "the per-parameter WAT limit table in the lot acceptance agreement",
        _DEDICATED_ONLY),
    "PENDING_FOUNDRY_test_patterns": (
        OWNER_US,
        "conversion of the L10 seeds already listed in this member into ATE "
        "patterns from the cocotb / Verilator traces this flow produced",
        _BOTH),
    "PENDING_FOUNDRY_loadboard_id": (
        OWNER_TEST_HOUSE,
        "the ATE loadboard part number and revision from the test house",
        _BOTH),
    "PENDING_FOUNDRY_scribe_line_layout": (
        OWNER_FOUNDRY,
        "the scribe-line PCM / alignment frame GDS from the mask-set kit",
        _BOTH),
}

#: On a shuttle these belong to the SLOT OPERATOR, not to the submitter's
#: foundry contact: the reticle, its scribe line and its PCM structures are
#: shared across every project in the shuttle and are the operator's to define.
_OPERATOR_OWNED_ON_SHUTTLE = (
    "PENDING_FOUNDRY_mask_layers",
    "PENDING_FOUNDRY_reticle_steppers",
    "PENDING_FOUNDRY_wat_structures",
    "PENDING_FOUNDRY_scribe_line_layout",
)

STATUS_OPEN = "OPEN"
STATUS_NA = "NOT_APPLICABLE_IN_MODE"
#: An item this flow owned and closed, with the evidence that closed it.
STATUS_CLOSED = "CLOSED"


def _open_item(field: str, mode_info: dict) -> dict:
    """The ownership record for ONE open item, resolved against the mode.

    An unknown field is NOT silently owner-less: it is recorded with
    `owner: null` and an explicit reason, and the gate FAILs on exactly that
    shape. A new PENDING_FOUNDRY_* field added without an owner is the shrug
    this whole structure exists to stop, so it must be loud."""
    mode = mode_info.get("mode") or MODE_UNDECLARED
    spec = _OPEN_ITEM_OWNERS.get(field)
    if spec is None:
        return {
            "field": field,
            "owner": None,
            "owner_name": None,
            "closed_by": None,
            "applies_in_mode": None,
            "status": STATUS_OPEN,
            "note": ("no ownership declared for this field in "
                     "_OPEN_ITEM_OWNERS — an open item that does not name "
                     "who closes it is not a disclosure."),
        }
    owner, closed_by, modes = spec
    if mode == MODE_SHUTTLE and field in _OPERATOR_OWNED_ON_SHUTTLE:
        owner = OWNER_OPERATOR
    return {
        "field": field,
        "owner": owner,
        # The operator's identity is a MEASURED fact off 37.5ic's report when
        # the mode is shuttle, and null otherwise — never a placeholder name.
        "owner_name": (mode_info.get("operator")
                       if owner == OWNER_OPERATOR else None),
        "closed_by": closed_by,
        "applies_in_mode": list(modes),
        "status": STATUS_OPEN if mode in modes else STATUS_NA,
    }


def _open_items(fields, mode_info: dict) -> list:
    return [_open_item(f, mode_info) for f in fields]


def _pending_foundry_count(handoff_dir: Path):
    """(fields_in_json_members, total_including_the_scribe_note).

    TWO NUMBERS BECAUSE THERE ARE TWO POPULATIONS, and the one number that
    used to stand here silently conflated them. The literal `9` it replaces
    counted PENDING_FOUNDRY_* KEYS inside the JSON members and did not count
    the scribe-line note; the GATE's `pending_foundry_fields` does count the
    note, which is why a corpus kit with nine keys reports "10 open items".
    Quoting either number where the other is meant is a different measurement,
    not a rounding error, so both are stated.

    Counted off the members on disk, so neither can disagree with the kit it
    describes. The literal was right only for as long as nobody changed the
    field set — and this change does: the two corner fields stop being pending
    on anybody, so the JSON count goes 9 -> 7."""
    n = 0
    for m in sorted(handoff_dir.glob("*.json")):
        try:
            data = json.loads(m.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            n += sum(1 for k in data if str(k).startswith("PENDING_FOUNDRY_"))
    note = (handoff_dir / "scribe_line_layout.PENDING_FOUNDRY.txt").is_file()
    return n, n + (1 if note else 0)


def _pdk_statements_diverge(signoff: str, spec: str) -> bool:
    """Do these two PDK statements describe DIFFERENT processes?

    A plain `signoff != spec` was the test, and it reported a divergence for
    three things that are not one. MEASURED over the published corpus:

        case only            sky130A vs sky130a          1 cell
        family vs variant    sky130A vs sky130           5 cells
        no PDK stated        'N/A (protocol spec, not a tapeout)'
                                                        12 of 194 L19 docs

    Nine of twelve reports were noise, and noise in a divergence channel is
    worse than silence: it trains a reader to skip the one line that says a
    130 nm IHP die is about to ship described as sky130.

    The three real ones survive. `sky130A` vs `sky130B` also survives — they
    share a family but neither contains the other, so the variant rule cannot
    swallow a genuine disagreement."""
    a, b = (signoff or "").strip(), (spec or "").strip()
    if not a or not b:
        return False
    # A spec that does not state a PDK IDENTIFIER states nothing to disagree
    # with. Prose is a non-statement, not a conflicting statement.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", b):
        return False
    la, lb = a.lower(), b.lower()
    if la == lb:                              # case only
        return False
    if la.startswith(lb) or lb.startswith(la):  # family vs variant
        return False
    return True


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
    mismatch = (spec if (signoff and spec
                         and _pdk_statements_diverge(signoff, spec)) else None)
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


def _routing_incomplete(project: Path):
    """True / False / None — the fact the antenna step RECORDED (#654).

    None means it was never recorded, which is NOT False: the caller must not
    read a missing key as a routed design."""
    try:
        f = _pl.reports_phase3_dir(project) / "antenna.json"
        if not f.is_file():
            return None
        data = json.loads(f.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "routing_incomplete" not in data:
        return None
    return bool(data.get("routing_incomplete"))


def package_layout_members(project: Path, destination: Path | None = None, selected_sources: dict | None = None) -> dict:
    """(Re)derive every handoff LAYOUT member from its signed-off source.

    EVERY time, never copy-if-absent, and by COPY, never hardlink. MEASURED on
    spm run23: a phase-3 re-run moved the signed-off GDS a7bf4526... ->
    46459f4a... and the package kept a7bf4526..., because the member was
    written once (`if dst.is_file(): continue`) as a hardlink, and the source's
    rewrite-by-rename left the link on the old inode. A member whose bytes equal
    its source and share no inode with it is kept; anything else is replaced
    atomically (temp + os.replace). Returns the per-member record the package
    publishes: member sha256 and bytes, source path and source sha256.
    """
    import os
    import shutil
    project = Path(project)
    sources = selected_sources if selected_sources is not None else _fhpc.layout_member_sources(project)
    # This is the package assembler.  The phase-3 runner and the executable
    # handoff entry point check admission before calling it; callers that hand
    # this function explicit sources can inspect the assembled members.
    hd = Path(destination) if destination is not None else _pl.foundry_handoff_dir(project)
    hd.mkdir(parents=True, exist_ok=True)
    members, written, kept, zero = {}, [], [], []
    for name, src in sources.items():
        if src.stat().st_size == 0:
            zero.append(name)
            continue
        dst = hd / name
        s_sha = _fhpc.sha256_file(src)
        same_inode = False
        if dst.is_file():
            try:
                same_inode = os.path.samefile(dst, src)
            except OSError:
                same_inode = False
        if (dst.is_file() and not dst.is_symlink() and not same_inode
                and _fhpc.sha256_file(dst) == s_sha):
            kept.append(name)
        else:
            tmp = hd / f".{name}.tmp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            written.append(name)
        members[name] = {
            "sha256": _fhpc.sha256_file(dst),
            "bytes": dst.stat().st_size,
            "source": str(src.relative_to(project)) if src.is_relative_to(project) else str(src),
            "source_sha256": s_sha,
            "signed_off_source": src.parent == _pl.gds_dir(project),
        }
    return {"members": members, "written": written, "kept": kept,
            "zero_byte_sources": zero}


def _portable_ate_patterns(project, handoff_dir, ate):
    """Keep the current kit's ATE links relative and retain their real inputs."""
    import shutil
    project, handoff_dir = Path(project).resolve(), Path(handoff_dir).resolve()
    def retain(ref):
        source = (project / ref['path']).resolve()
        if not source.is_relative_to(project) or _ate.sha256_file(source) != ref['sha256']:
            raise ValueError('ATE source changed before packaging: '+str(source))
        relative = Path('archive/project') / source.relative_to(project)
        target = handoff_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return dict(ref, path=relative.as_posix())
    for pattern in ate['patterns']:
        header = (project / pattern['path']).resolve()
        doc = json.loads(header.read_text())
        vector = (project / doc['vectors_file']['path']).resolve()
        if (not vector.is_relative_to(handoff_dir)
                or _ate.sha256_file(vector) != doc['vectors_file']['sha256']):
            raise ValueError('ATE vector changed before packaging: '+str(vector))
        doc['vectors_file']['path'] = vector.relative_to(handoff_dir).as_posix()
        doc['source_trace'] = retain(doc['source_trace'])
        doc['step5_record'] = retain(doc['step5_record'])
        _aa.write_text(header, json.dumps(doc, indent=2)+'\n')
        pattern.update(path=header.relative_to(handoff_dir).as_posix(),
                       sha256=_ate.sha256_file(header), source_trace=doc['source_trace'])
        ate['step5_record'] = doc['step5_record']
    return ate


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("project", type=Path)
    p.add_argument(
        "--top", default=None,
        help="silicon top module name; #467 fallback used only when "
             "L1_DATASHEET[ic_name] is an empty / not-found sentinel.")
    p.add_argument("--json", type=Path, default=None,
                   help="also publish the mask specification here (relative "
                        "to project); the canonical package is always retained")
    p.add_argument("--release-record", type=Path, help="existing provider assembly admission record; no arbitrary layout override")
    p.add_argument("--out-dir", type=Path, help="new timestamp destination; source project stays read-only")
    args = p.parse_args(argv)

    project = args.project.resolve()
    if args.out_dir is not None and args.out_dir.exists():
        print("FAIL: timestamp output directory already exists; preserve the prior version", file=sys.stderr)
        return 1
    if not project.is_dir():
        print(f"VACUOUS_PASS: project dir missing: {project}",
              file=sys.stderr)
        return 2

    # ORGANIC #654 — a handoff pack for a layout the router never finished is
    # the most expensive form this failure takes. The fact is already on disk:
    # the antenna step records `routing_incomplete` beside `net_violations: 0`,
    # and that pair on one line IS the trap. `grep -c routing_incomplete` over
    # this file used to return 0.
    #
    # A MISSING key is not False — a run whose antenna step never reached the
    # in-session post-repair path records nothing, and reading that as "routing
    # is fine" would rebuild the defect one level up. Only an explicit True
    # refuses.
    _ri = _routing_incomplete(project)
    if _ri is True:
        print("VACUOUS_PASS: detailed routing is INCOMPLETE (recorded by the "
              "antenna step in reports/phase3/antenna.json). Refusing to write "
              "a foundry handoff pack for a layout with no realized "
              "interconnect. Finish routing, then re-run.", file=sys.stderr)
        return 2

    # field (foundry-handoff hollow chip GDS) — the SECOND refusal, and the one #654 could not reach.
    # #654 keys on `antenna.json:routing_incomplete`. MEASURED on the two
    # benchmark runs this was written from (spm_gf180mcuD_20260831_a1 and
    # subservient_gf180mcuD_20260831_d1), that key is FALSE — detailed routing
    # COMPLETED, with one residual violation, which is why `pnr` is FAIL and NOT
    # why routing is incomplete. So #654 stayed silent while this generator
    # wrote a full mask spec, WAT probe plan and ATE corner-vector kit for a
    # chip whose GDS does not exist anywhere in the tree (`step_gds` never ran:
    # the runner gates stream-out on `pnr.status == "PASS"`, correctly).
    #
    # The kit exists to describe ONE artefact — the die. Writing it for a
    # streamed non-die is the laundering this program must not do, so the
    # predicate is asked BEFORE the handoff directory is created: a refusal
    # leaves NO half-kit on disk for the next reader to mistake for a
    # deliverable.
    #
    # SCOPE, stated because the narrower rule was a deliberate choice and the
    # wider one was MEASURED: this refuses when stream-out HAS written a .gds
    # and what it wrote is not a die (0-byte, hollow, frame-only). It does NOT
    # refuse a tree with no .gds at all. Two reasons. (1) That tree is already
    # rc=1 FAIL `FOUNDRY_HANDOFF_CHIP_GDS_MISSING` at the gate — no false green
    # to close, only a skeleton the gate has already refused. (2) The wider rule
    # was implemented and reddened 38 tests across 9 files whose fixtures run
    # this generator on a bare project to check its FIELD DERIVATION (design_top
    # from L1.ic_name, pdk from L19, cell counts, TODO semantics); making all
    # nine plant a GDS would rewrite what those tests are about to buy a
    # property the gate already holds.
    #
    # It does NOT soften the gate either: `foundry_handoff_package_check`
    # evaluates `chip_gds_finding` BEFORE its `missing -> SKIP (rc=2)` branch,
    # so an absent kit still exits rc=1 FAIL rather than the VACUOUS_PASS the
    # flow runner reads rc=2 as. Verified end to end on a copy of the spm run
    # tree.
    release_info = None
    record = args.release_record or project / "reports/phase3/provider_die_assembly.json"
    if args.release_record is not None or record.is_file():
        try:
            release_info = _fhpc.admitted_provider_release(project, record)
        except (OSError, ValueError, RuntimeError, AttributeError) as exc:
            print(f"FAIL: provider assembly admission refused: {exc}", file=sys.stderr)
            return 1
    _gds, _rule, _detail = _fhpc.packageable_chip_gds(
        project, selected=release_info['gds'] if release_info else None)
    if _rule is not None and (_rule != _fhpc.RULE_NO_CHIP_GDS
                              or _fhpc.gds_files_on_disk(project)):
        if args.out_dir is None:
            _ga.quarantine_visible_gds(project, f"foundry handoff refused: {_rule}")
            _ga.quarantine_handoff_package(project, f"foundry handoff refused: {_rule}")
        print(f"VACUOUS_PASS: {_rule}: {_detail} Refusing to write a foundry "
              f"handoff pack. Produce the sign-off GDS first (canonical step "
              f"37 stream-out), then re-run.", file=sys.stderr)
        return 2

    # In a phase-3 run, a mask also needs the current routed-basis and byte
    # receipt. A direct caller with an explicit GDS can assemble the kit;
    # the runner checks admission before invoking this entry point.
    gate = _ga.gate_record(project)
    if (release_info is None and (gate or _ga.admission_path(project).is_file())
            and not _ga.admitted_package_sources(
                project, _fhpc.layout_member_sources(project))):
        if args.out_dir is None:
            _ga.quarantine_visible_gds(project, "foundry handoff refused: GDS lacks current admission")
            _ga.quarantine_handoff_package(project, "foundry handoff refused: GDS lacks current admission")
        print("NOT_MEASURED: GDS admission refused foundry handoff; "
              "no GDS packaged", file=sys.stderr)
        return 2

    # Use the admitted chip selected by the shared resolver, with the exact
    # signed-off source the layout-member copier will publish. A filename or
    # L1 product label cannot replace the binary hierarchy's root.
    sources = ({Path(release_info["gds"]).name: Path(release_info["gds"])}
               if release_info else _fhpc.layout_member_sources(project))
    primary_gds = sources.get(_gds.name, _gds) if _gds is not None else None
    try:
        physical_top = _resolve_design_top(project, args.top, primary_gds)
        design_top = physical_top["top"]
    except (OSError, ValueError) as exc:
        print(f"FAIL: FOUNDRY_HANDOFF_PHYSICAL_TOP_INVALID: {exc}", file=sys.stderr)
        return 1
    design_label = _l1_ic_name(project) or project.name

    handoff_dir = args.out_dir.resolve() if args.out_dir is not None else _pl.foundry_handoff_dir(project)
    if args.out_dir is None and handoff_dir.exists():
        shutil.rmtree(handoff_dir)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    audit_dir = (handoff_dir / "archive/project/reports/phase3"
                 if args.out_dir is not None else _pl.reports_phase3_dir(project))
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Collect design facts from artefacts the runner produced.
    pnr = _pl.pnr_dir(project)
    synth = _pl.synth_dir(project)

    cells = _parse_synth_cell_count(synth / "synth.log")
    if cells is None:
        cells = _count_netlist_instances(synth)  # #446 netlist fallback
    area = _parse_design_area(pnr / "area.rpt")
    if release_info:
        # The retained core plan is not the resized provider die. Keep both
        # identities, deriving current physical area from this selected GDS.
        area["retained_core_die_area_um2"] = area["die_area_um2"]
        bbox = physical_top.get("bbox_um")
        area["die_area_um2"] = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) if bbox else None

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
    # design_top  <- the admitted final GDS hierarchy, resolved above.
    # pdk         <- L19 pdk_target → L1 tapeout PDK statement → PDK files.
    # process_nm  <- PDK-file derivation → node parsed from the spec PDK text.
    # Honest null is preserved only when ALL upstream sources are empty —
    # projects genuinely missing the value still get null (corpus-sweep
    # guard). PENDING_FOUNDRY_* semantics unchanged (#449).
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

    # WHICH OF THE TWO SITUATIONS THIS KIT IS IN. Resolved once and carried by
    # every member, so a reader who opens ONE member still learns whether the
    # reticle is theirs or the slot operator's — and so the gate can compare
    # the mode the kit CLAIMS against the evidence on disk.
    mode_info = _handoff_mode(project, assembly=release_info)

    # The corners the sign-off liberty files declare. Measured, not defaulted.
    corners = _signoff_liberty_corners(project)

    # Step 1: mask_spec.json — deterministic starting point. The mask
    # layer table is foundry-specific so we mark it TODO.
    mask_spec = {
        "schema_version": "1.0",
        "generated_by": _pmd.emitted_by("foundry_handoff_pack_gen"),
        "design_identity": _ident,
        "design_top": design_top,
        "design_label": design_label,
        "physical_top": physical_top,
        "process_node_nm": process_nm,
        "pdk": pdk_name,
        "gds_path": (str(primary_gds.relative_to(project)) if primary_gds.is_relative_to(project) else str(primary_gds)) if primary_gds else None,
        "gds_size_bytes": (primary_gds.stat().st_size
                           if primary_gds else 0),
        "cell_count": cells,
        "die_area_um2": area["die_area_um2"],
        "retained_core_die_area_um2": area.get("retained_core_die_area_um2"),
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
        "handoff_mode": mode_info,
        "open_items": _open_items(
            ("PENDING_FOUNDRY_mask_layers",
             "PENDING_FOUNDRY_reticle_steppers"), mode_info),
    }
    # THE LAYOUT MEMBERS, derived from the signed-off GDS on EVERY run and
    # recorded (member + source sha256) in the package's own spec, which
    # foundry_handoff_package_check compares against the signed-off bytes.
    _layout = package_layout_members(project, handoff_dir, sources if release_info else None)
    mask_spec["layout_members"] = _layout["members"]
    if _layout["written"]:
        print(f"[handoff] layout member(s) (re)derived from the signed-off GDS: "
              f"{', '.join(_layout['written'])}")
    mask_json = json.dumps(mask_spec, indent=2, ensure_ascii=False) + "\n"
    mask_path = handoff_dir / "mask_spec.json"
    _aa.write_text(mask_path, mask_json)
    if args.json is not None:
        output = (handoff_dir if args.out_dir is not None else project) / args.json
        if output.resolve() != mask_path.resolve():
            _aa.write_text(output, mask_json)

    # Step 2: wat_plan.json — Wafer Acceptance Test plan.
    # #446: carries the design/PDK facts so two different designs can
    # never emit byte-identical plans; TODOs remain only for the
    # genuinely foundry-supplied content.
    wat_plan = {
        "schema_version": "1.0",
        "generated_by": _pmd.emitted_by("foundry_handoff_pack_gen"),
        "design_identity": _ident,
        "design_top": design_top,
        "design_label": design_label,
        "pdk": pdk_name,
        "process_node_nm": process_nm,
        "gds_path": (str(primary_gds.relative_to(project)) if primary_gds.is_relative_to(project) else str(primary_gds)) if primary_gds else None,
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
        "handoff_mode": mode_info,
        "open_items": _open_items(
            ("PENDING_FOUNDRY_wat_structures",
             "PENDING_FOUNDRY_yield_target_pct",
             "PENDING_FOUNDRY_acceptance_criteria"), mode_info),
    }
    _aa.write_text(handoff_dir / "wat_plan.json",
        json.dumps(wat_plan, indent=2, ensure_ascii=False) + "\n")

    # Step 3: corner_test_vectors.json — ATE corner test kit.
    # #446: seed the kit with THIS design's L10 test-case ids so the
    # pattern list is chip-specific (full vectors are converted from
    # sim traces downstream); TODOs only for foundry/ATE-supplied data.
    l10_ids = _l10_test_pattern_ids(project)
    # U18 — the test patterns are OURS (`OWNER_US`): convert the Step-5 traces
    # of every seed now. The item closes only when every seed Step 5 counted
    # as a functional case has a pattern; otherwise it stays OPEN, naming the
    # seeds and why, and the Step-38 gate refuses the kit.
    ate = _portable_ate_patterns(project, handoff_dir,
                                _ate.emit(project, handoff_dir / _ate.PATTERN_SUBDIR, l10_ids))
    patterns_closed = bool(l10_ids) and bool(ate["patterns"]) \
        and not ate["not_converted"]
    corner_kit = {
        "schema_version": "1.0",
        "generated_by": _pmd.emitted_by("foundry_handoff_pack_gen"),
        "design_identity": _ident,
        "design_top": design_top,
        "design_label": design_label,
        "pdk": pdk_name,
        "test_pattern_seeds_from_l10": l10_ids,
        "test_pattern_seed_count": len(l10_ids),
        # NOT pending on anybody. These are the corners the sign-off liberty
        # files declare, read off the flow's own asset paths — the same ground
        # truth `_pdk_from_signoff_flow` uses to name the PDK. What stood here
        # before was `["VDD_min","VDD_nom","VDD_max"]` and
        # `[-40, 25, 85, 125]`: canned literals wearing a PENDING_FOUNDRY_
        # prefix, wrong for every design in the published corpus, and
        # actionable enough for a foundry to test against. When the PDK's
        # liberty names carry no operating point (asap7, nangate45) these are
        # null and `corner_source` says NOT_DETERMINED — never a default.
        "corner_source": ("signoff_liberty" if (corners["voltages_v"]
                                                or corners["temperatures_celsius"])
                          else "NOT_DETERMINED"),
        "voltage_corners_v": corners["voltages_v"] or None,
        "temperature_corners_celsius": corners["temperatures_celsius"] or None,
        "signoff_liberty_files": corners["liberty_files"],
        # The size of the search that produced the answer — or that failed to.
        # A null corner set beside `liberty_seen: 0` and one beside
        # `liberty_seen: 5, liberty_unparsed: 5` are different facts.
        "corner_search": {
            "liberty_paths_seen": corners["liberty_seen"],
            "liberty_names_without_operating_point":
                corners["liberty_unparsed"],
        },
        "ate_patterns": ate["patterns"],
        "ate_patterns_not_converted": ate["not_converted"],
        "ate_patterns_excluded": ate["excluded"],
        "ate_patterns_step5_record": ate["step5_record"],
        "PENDING_FOUNDRY_test_patterns": (
            "Author: convert each L10 seed above into an ATE pattern "
            "(input vector + expected output + corner constraints) from "
            "cocotb/Verilator simulation traces — see "
            "vibe-ic:tapeout-checklist skill for guidance."
        ),
        "PENDING_FOUNDRY_loadboard_id": (
            "Author: ATE loadboard part number + revision."
        ),
        "handoff_mode": mode_info,
        "open_items": _open_items(
            ("PENDING_FOUNDRY_test_patterns",
             "PENDING_FOUNDRY_loadboard_id"), mode_info),
    }
    if patterns_closed:
        # Closed against its evidence: the pending key goes, the item stays on
        # the record as CLOSED with the files (and hashes) that closed it, and
        # the gate re-hashes every one of them.
        corner_kit.pop("PENDING_FOUNDRY_test_patterns")
        for it in corner_kit["open_items"]:
            if it["field"] == "PENDING_FOUNDRY_test_patterns":
                it["status"] = STATUS_CLOSED
                it["evidence"] = [{"path": p["path"], "sha256": p["sha256"]}
                                  for p in ate["patterns"]]
    _aa.write_text(handoff_dir / "corner_test_vectors.json",
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
        # THE NOTE NOW NAMES ITS OWNER. It used to say the frame was
        # "FOUNDRY-SUPPLIED" and stop, which is a shrug in two ways: it never
        # said WHICH foundry-side party owns it (on a shuttle it is the slot
        # operator, not the submitter's foundry contact), and it never said
        # what had been done to establish that we cannot produce it.
        #
        # The shape is borrowed from LibreLane's `KLayout.SealRing`, which
        # skips with "KLAYOUT_SEALRING_SCRIPT is unset. KLayout.SealRing may
        # not be supported for the {PDK} PDK. This step will be skipped." —
        # a legitimate skip that names the PDK and the missing variable, so a
        # reader knows exactly what would make it run. We do the same and add
        # the machine-readable half LibreLane does not have: this text is
        # accompanied by `open_items` records inside the JSON members, so a
        # refusal is a datum rather than a line in a log.
        _scribe_owner = _open_item(
            "PENDING_FOUNDRY_scribe_line_layout", mode_info)
        _owner_line = _scribe_owner["owner"]
        if _scribe_owner.get("owner_name"):
            _owner_line += f" ({_scribe_owner['owner_name']})"
        _aa.write_text(handoff_dir / "scribe_line_layout.PENDING_FOUNDRY.txt",
            "scribe_line_layout.gds is NOT generated by this flow, and is "
            "NOT a placeholder for one that could be (#446).\n"
            "\n"
            f"  handoff mode : {mode_info['mode']}\n"
            f"  mode basis   : {mode_info['basis']}\n"
            f"  owner        : {_owner_line}\n"
            f"  closed by    : {_scribe_owner['closed_by']}\n"
            "\n"
            "WHY THIS FLOW CANNOT PRODUCE IT — measured, not assumed.\n"
            "Every PDK tree in the pinned EDA image was searched on "
            "2026-08-20 for a shipped scribe / PCM / process-monitor layout:\n"
            "  - 'process_monitor'  0 files\n"
            "  - 'scribe'          17 files, NONE of them geometry: they are\n"
            "                      fill-deck keep-out constants, one layer\n"
            "                      declaration, and five matches on the\n"
            "                      English word 'described'\n"
            "  - libs.ref of all 6 PDK roots holds only standard cells, IO,\n"
            "    primitive devices and SRAM macros — no test-structure "
            "library\n"
            "So the frame is not a thing the flow declined to build. No open "
            "PDK ships one, because the scribe line belongs to whoever owns "
            "the reticle.\n"
            "\n"
            "Obtain it from the party named above and place it beside this "
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
        "Design-release package with provider/manufacturing service disclosures.\n"
        # #484: design NAME line is always present so two designs that share
        # the default top do not emit a byte-identical README.
        f"Design name: {project.name}\n"
        f"Design label: {design_label}\n"
        f"Physical GDS top: {design_top}\n"
        f"PDK: {pdk_name}\n"
        f"GDS: {(str(primary_gds.relative_to(project)) if primary_gds.is_relative_to(project) else str(primary_gds)) if primary_gds else '(none)'}"
        f" ({primary_gds.stat().st_size if primary_gds else 0} B)\n"
        "\n"
        "Portable design closure: release_manifest.json + SHA256SUMS.\n"
        "Archive paths are relative; original report paths are provenance.\n"
        "Use the source/member index after relocation; do not rewrite receipts.\n"
        "Provider upload subset is distinct from internal STA/SDC/SPEF/logic.\n"
        "External PDK/tool dependencies retain their versions and hashes;\n"
        "their presence is not a license to upload proprietary material.\n"
        "\n"
        "Package members and service disclosures:\n"
        "  mask_spec.json              — mask layer table + reticle config\n"
        "  wat_plan.json               — WAT probe plan + PCM structures\n"
        "  scribe_line_layout.gds      — foundry-supplied PCM/scribe layout\n"
        "                                (see scribe_line_layout.PENDING_FOUNDRY.txt)\n"
        "  corner_test_vectors.json    — ATE corner test kit\n"
        "\n"
        "PENDING_FOUNDRY_* entries identify unresolved provider/manufacturing\n"
        "service data, not seven universal GDS release prerequisites. Each carries an\n"
        "`open_items` record naming that party, the artefact that would close\n"
        "it, and whether it exists in the applicable hand-off mode. Substance\n"
        "gate `foundry_handoff_package_check` (Step 38) audits completeness\n"
        "and FAILs an open item that names no owner. The selected provider\n"
        "contract determines required submission material. Reticle frames/PCM\n"
        "may be provider services; yield targets, WAT limits and loadboards\n"
        "belong to applicable manufacturing/test arrangements. A yield target\n"
        "is not measured yield. This package does not attest order acceptance.\n"
        "\n"
        f"Handoff mode: {mode_info['mode']}"
        + (f" (operator: {mode_info['operator']})"
           if mode_info.get("operator") else "") + "\n"
        f"  basis: {mode_info['basis']}\n"
        "\n"
        "Sign-off corners, read off the liberty files the flow itself\n"
        "consumed (NOT foundry-supplied, NOT defaults):\n"
        f"  voltage_corners_v            = {corners['voltages_v'] or 'NOT_DETERMINED'}\n"
        f"  temperature_corners_celsius  = {corners['temperatures_celsius'] or 'NOT_DETERMINED'}\n"
        f"  from {corners['liberty_seen']} liberty path(s) named by the flow\n"
        "\n"
        "Authored design facts auto-included:\n"
        f"  cell_count    = {cells}\n"
        f"  die_area_um2  = {area['die_area_um2']}\n"
        f"  process_nm    = {process_nm}\n"
        f"  pdk           = {pdk_name}\n"
    )

    release = _fhpc.emit_design_release(project, handoff_dir, primary_gds, physical_top, assembly=release_info)
    # Step 5: audit summary
    _pending_counts = _pending_foundry_count(handoff_dir)
    audit_path = audit_dir / "foundry_handoff_audit.json"
    audit = {
        "program": "foundry_handoff_pack_gen",
        "version": "1.1.0",
        "open_items": mask_spec["open_items"] + wat_plan["open_items"] + corner_kit["open_items"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "verdict": "SKELETON_EMITTED",
        "design_release": {"archive_status":release["archive_status"],"missing":release["missing"],"incomplete_validation":release["incomplete_validation"]},
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
            "design_label": design_label,
            "physical_top": physical_top,
            "cell_count": cells,
            "die_area_um2": area["die_area_um2"],
            "core_area_um2": area["core_area_um2"],
            "process_nm": process_nm,
            "pdk": pdk_name,
            "gds_size_bytes": (primary_gds.stat().st_size
                               if primary_gds else 0),
        },
        # COUNTED, not asserted. This was the literal `9` for as long as there
        # happened to be nine PENDING_FOUNDRY_* fields; it did not move when a
        # field was added or removed, so it could only ever have been right by
        # coincidence. It is now derived from the members actually written, and
        # it drops to seven in this change because the two corner fields stopped
        # being pending on anybody.
        "pending_foundry_count": _pending_counts[0],
        # The same items as the gate's `pending_foundry_fields` counts them —
        # the JSON keys PLUS the scribe-line note. See _pending_foundry_count.
        "pending_open_items_total": _pending_counts[1],
        # WHOSE ACCEPTANCE, AND WHAT THEY SAID (Q4). On the shuttle path the
        # operator's own precheck verdict is the most load-bearing thing in the
        # hand-off — it is the ONE judgement in this flow we do not write. The
        # kit REFERENCES it by path and pins the bytes it saw, rather than
        # copying it: a copy can drift from the report it was copied from, and
        # "the artefact changed after the evidence" is this repository's own
        # worst failure shape.
        "handoff_mode": mode_info,
        "signoff_corners": {
            "source": ("signoff_liberty" if (corners["voltages_v"]
                                             or corners["temperatures_celsius"])
                       else "NOT_DETERMINED"),
            "voltage_corners_v": corners["voltages_v"] or None,
            "temperature_corners_celsius": corners["temperatures_celsius"] or None,
            "liberty_paths_seen": corners["liberty_seen"],
        },
        "notes": (
            "Skeleton emits design facts + PENDING_FOUNDRY_* open items. "
            "Provider-specific submission and manufacturing/test contracts "
            "determine which service data is owed and by whom. "
            "Substance audit performed by foundry_handoff_package_check."
        ),
    }
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
    package_audit = handoff_dir / "archive/project/reports/phase3/foundry_handoff_audit.json"
    if package_audit.resolve() != audit_path.resolve():
        _aa.write_text(package_audit, json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
    _fhpc.seal_design_release(handoff_dir)
    print(json.dumps({
        "verdict": audit["verdict"],
        "out_dir": str(handoff_dir),
        "audit": str(audit_path),
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
