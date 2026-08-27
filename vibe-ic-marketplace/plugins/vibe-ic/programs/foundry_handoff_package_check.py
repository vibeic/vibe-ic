#!/usr/bin/env python3
"""
foundry_handoff_package_check.py — gate (v1.6.13 Wave 88, integerised
in v1.6.14 Wave 90, renumbered Step 34 → 35 in v1.6.15 Wave 91, and
Step 35 → 38 by the later renumbering the flow yaml already carries).

Step 38 — foundry-handoff kit completeness

Behaviour
---------
* WAIVED (rc=0) — `waivers.json` declares step waived (evidence + ticket).
* FAIL (rc=1) — a 0-byte member, a TODO/TBD placeholder, an invalid
  cell_count / pdk=unknown, or no chip GDS matching the design's own name.
* SKIP (rc=2) — required kit members missing, step not waived, AND no
  substance defect found in what WAS present.
* PASS (rc=0) — every required kit member present AND every substance
  predicate below satisfied.

PRECEDENCE: FAIL outranks SKIP. rc=2 is NOT CHECKED (the flow runner reads it
as VACUOUS_PASS), so a substance ERROR the gate has already proved is never
downgraded to it by an incomplete kit — the members that are absent are named
in the FAIL report instead. See the ladder comment in `main`.

"Completeness" is measured against `_REQUIRED_FILES`, which now covers the
FOUR kit members the pack generator emits, not two of them. It previously
listed only mask_spec.json and wat_plan.json, so corner_test_vectors.json
could be absent and the scribe-line frame unaccounted for while the gate
reported "all required artefacts present" — measured on a real run where
scribe_line_layout.gds was absent and the PASS never mentioned it.
The fifth entry the flow yaml declares for Step 38,
reports/phase3/foundry_handoff_audit.json, is THIS gate's own output and is
deliberately not self-required here.

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
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


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
# Each entry is ONE required kit member. A tuple means "any ONE of these
# spellings satisfies this member" — used only for the scribe-line frame,
# which the flow cannot generate: foundry_handoff_pack_gen deliberately writes
# a plainly-named `.PENDING_FOUNDRY.txt` note instead of a file wearing the
# .gds name (#446), and the flow yaml declares exactly the same either-form
# requirement. NEITHER present is still a real gap — then nothing at all states
# where the frame is coming from.
_REQUIRED_FILES = [
    'phase3/stage4/foundry_handoff/mask_spec.json',
    'phase3/stage4/foundry_handoff/wat_plan.json',
    'phase3/stage4/foundry_handoff/corner_test_vectors.json',
    ('phase3/stage4/foundry_handoff/scribe_line_layout.gds',
     'phase3/stage4/foundry_handoff/scribe_line_layout.PENDING_FOUNDRY.txt'),
]
# The scribe-line note satisfies the requirement but is NOT a delivered
# artefact — when it is what satisfied the member, the open item is surfaced
# in `pending_foundry_fields` under this name so the tapeout checklist
# (tapeout_checklist_gen reads exactly that list) carries it as a reviewer
# to-do. Before this, the generator's honest disclosure was written to disk and
# read by nobody: the PENDING_FOUNDRY_* scan only inspects dict keys inside
# .json members, so a sibling .txt note could never appear in it.
_SCRIBE_PENDING_NOTE = (
    'phase3/stage4/foundry_handoff/scribe_line_layout.PENDING_FOUNDRY.txt')
_SCRIBE_PENDING_FIELD = 'PENDING_FOUNDRY_scribe_line_layout'
_WAIVER_RATIONALE = 'Foundry-handoff kit assembler not shipped.'

# ─────────────────────────────────────────────────────────────────────────────
# THE OPERATOR'S OWN REFUSAL, AND WHY THIS GATE HAS TO READ IT
#
# Step 37.5ic runs the shuttle operator's own container and writes its verdict
# to `reports/phase3/shuttle_precheck.json`. It is the ONE judgement in this
# flow that we do not write, and therefore the one that cannot be made to pass
# by editing a file in this repository.
#
# Step 38 did not know it existed. The flow declares `blocks_on: [37]` for this
# step — NOT 37.5ic — so a hand-off kit can be assembled, gated and reported
# COMPLETE while the operator's own tool has already refused the layout it
# describes. A kit whose central deliverable the counterparty has rejected is
# not a deliverable, and a gate that says "all required artefacts present" over
# that refusal is this repository's recurring shape once more: an empty or
# negative result made indistinguishable from a clean one.
#
# BLOCKING, deliberately, and scoped so it cannot fire spuriously:
#   * it fires ONLY when the precheck report EXISTS. No report -> the design is
#     not on a declared shuttle path and nothing here fires. Absence is never
#     read as a refusal, and never as an acceptance either.
#   * NOT_DETERMINED blocks as well as FAIL. `tapeout_readiness_check` returns
#     rc 1 for both, by its own docstring, "because a silence credited as a pass
#     is the defect this gate exists for". Accepting NOT_DETERMINED here would
#     re-open exactly that door one step downstream.
#
# The generator RECORDS the mode; this gate RE-DERIVES it from the same file on
# disk and compares. A kit that mis-states its own mode is caught, because the
# member is a generated artefact and the report is the evidence — checking the
# artefact against the evidence rather than trusting the artefact is the whole
# reason the generator and the checker are separate programs.
# ─────────────────────────────────────────────────────────────────────────────
_SHUTTLE_PRECHECK_REPORT = 'reports/phase3/shuttle_precheck.json'
_MODE_SHUTTLE = 'shuttle'
_MODE_UNDECLARED = 'undeclared'
#: `tapeout_readiness_check` emits exactly three; only one of them is an accept.
_PRECHECK_ACCEPTS = ('PASS',)


def _read_shuttle_precheck(project):
    """(exists, verdict, operator) read straight off 37.5ic's own report.

    `verdict` is None when the file is present but unparseable — which is NOT
    an accept: an unreadable verdict is reported as NOT_DETERMINED so that a
    corrupt report cannot become a quiet pass."""
    p = project / _SHUTTLE_PRECHECK_REPORT
    if not p.is_file():
        return False, None, None
    try:
        data = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return True, "NOT_DETERMINED", None
    if not isinstance(data, dict):
        return True, "NOT_DETERMINED", None
    return (True,
            data.get("verdict") or "NOT_DETERMINED",
            data.get("shuttle") or data.get("shuttle_id"))


def _member_alternatives(entry):
    """Normalise a _REQUIRED_FILES entry to its tuple of accepted spellings."""
    return entry if isinstance(entry, tuple) else (entry,)


def _member_label(entry):
    """Human/report label for a required-kit member."""
    return " OR ".join(_member_alternatives(entry))

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

    # (a) DEF DESIGN line — prefer the final routed / signoff / pnr / repair DEF
    # (the physical database the chip GDS is streamed from). Scan only the DEF
    # header (first lines): DESIGN is emitted right after VERSION/UNITS.
    def _def_rank(p):
        s = str(p).lower()
        return 0 if any(k in s for k in ("routed", "signoff", "/pnr/",
                                         "/postroute_timing_repair/")) else 1
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

    found, missing = [], []
    scribe_satisfied_by_note = False
    for entry in _REQUIRED_FILES:
        hit = next((alt for alt in _member_alternatives(entry)
                    if list(project.glob(alt))), None)
        if hit is None:
            missing.append(_member_label(entry))
        else:
            found.append(hit)
            if hit == _SCRIBE_PENDING_NOTE:
                scribe_satisfied_by_note = True

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
            atomic_write_text(Path(args.json), out)
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
    handoff_open_items = []          # the OWNED open items, per member
    declared_modes = set()           # what the kit says its mode is
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
                # ───────────────────────────────────────────────────────────
                # AN OPEN ITEM THAT NAMES NOBODY IS A SHRUG, NOT A DISCLOSURE.
                #
                # The nine PENDING_FOUNDRY_* fields were an undifferentiated
                # pile: they shared a prefix, they shared a silence about who
                # would close them, and three of them were not the foundry's at
                # all. The prefix was doing the work of an answer.
                #
                # Each member the generator writes now carries an `open_items`
                # list pairing every PENDING field with the party that closes
                # it, the artefact that would close it, and whether the item
                # exists in this hand-off mode at all. This rule is what stops
                # that from decaying: a PENDING field with no owner named FAILs.
                #
                # SCOPE, so the corpus does not go red for history it cannot
                # change: the rule applies only to members that declare
                # `handoff_mode` — i.e. members this generation wrote. A kit
                # from an older generator carries neither key and is untouched.
                # Dropping `open_items` to escape the rule does not work: a
                # member that declares `handoff_mode` and omits `open_items` is
                # itself the finding.
                # ───────────────────────────────────────────────────────────
                if "handoff_mode" in jd:
                    owned = {}
                    items = jd.get("open_items")
                    if not isinstance(items, list):
                        substance_findings.append({
                            "severity": "ERROR",
                            "rule": "FOUNDRY_HANDOFF_UNOWNED_PENDING",
                            "message": (
                                f"{rel}: declares handoff_mode but carries no "
                                f"open_items list — every PENDING_FOUNDRY_* "
                                f"field must name the party that closes it."),
                        })
                        items = []
                    for it in items:
                        if isinstance(it, dict) and it.get("owner"):
                            owned[str(it.get("field"))] = it["owner"]
                    unowned = sorted(k for k in jd
                                     if str(k).startswith("PENDING_FOUNDRY_")
                                     and str(k) not in owned)
                    if unowned:
                        substance_findings.append({
                            "severity": "ERROR",
                            "rule": "FOUNDRY_HANDOFF_UNOWNED_PENDING",
                            "message": (
                                f"{rel}: {len(unowned)} PENDING_FOUNDRY_* "
                                f"field(s) with no owner named in open_items: "
                                f"{unowned}. An open item that does not say "
                                f"who closes it is a shrug, not a "
                                f"disclosure."),
                        })
                    for it in items:
                        if isinstance(it, dict):
                            handoff_open_items.append({
                                "member": rel,
                                "field": it.get("field"),
                                "owner": it.get("owner"),
                                "owner_name": it.get("owner_name"),
                                "closed_by": it.get("closed_by"),
                                "status": it.get("status"),
                            })
                    hm = jd.get("handoff_mode")
                    if isinstance(hm, dict) and hm.get("mode"):
                        declared_modes.add(str(hm["mode"]))
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

    # #446/#449 — the scribe-line frame is accounted for by a plainly-named
    # disclosure note rather than a delivered .gds. That is an OPEN FOUNDRY
    # ITEM, so it joins the same list the JSON-key scan feeds and reaches the
    # tapeout checklist. Prepended so it is never truncated out of the finding
    # message's first-12 slice.
    if scribe_satisfied_by_note:
        pending_foundry_fields.insert(
            0, f"{_SCRIBE_PENDING_NOTE}:{_SCRIBE_PENDING_FIELD}")

    # THE OPERATOR'S REFUSAL. See the block comment at _SHUTTLE_PRECHECK_REPORT.
    # Re-derived from the report on disk, never taken from the kit.
    precheck_present, precheck_verdict, precheck_operator = \
        _read_shuttle_precheck(project)
    evidence_mode = _MODE_SHUTTLE if precheck_present else _MODE_UNDECLARED

    if precheck_present and precheck_verdict not in _PRECHECK_ACCEPTS:
        substance_findings.append({
            "severity": "ERROR",
            "rule": "FOUNDRY_HANDOFF_SHUTTLE_PRECHECK_REFUSED",
            "message": (
                f"the shuttle operator "
                f"{precheck_operator or '(unnamed in the report)'} returned "
                f"{precheck_verdict!r} in {_SHUTTLE_PRECHECK_REPORT} (step "
                f"37.5ic). On the shuttle path the operator's own acceptance "
                f"is part of this hand-off, and it is the one verdict in this "
                f"flow we do not write. A kit assembled over a refusal — or "
                f"over a NOT_DETERMINED, which `tapeout_readiness_check` "
                f"treats as a non-pass for the same reason — is not a "
                f"deliverable."),
        })

    # A KIT THAT MIS-STATES ITS OWN MODE. The generator records the mode it
    # resolved; this gate resolved it independently from the same evidence. A
    # disagreement means the kit and the run describe different situations, and
    # the reader of the kit is the one who would be misled.
    if declared_modes and evidence_mode not in declared_modes:
        _basis = ("a shuttle precheck report is present" if precheck_present
                  else "no shuttle precheck report is present")
        substance_findings.append({
            "severity": "ERROR",
            "rule": "FOUNDRY_HANDOFF_MODE_MISDECLARED",
            "message": (
                f"kit members declare handoff_mode "
                f"{sorted(declared_modes)} but the evidence on disk says "
                f"{evidence_mode!r} ({_basis}). The mode decides who owns the "
                f"scribe line, the reticle and the mask layer table, so a "
                f"wrong one reassigns every open item in this kit."),
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
            atomic_write_text(Path(args.json), out)
        print(out)
        return rc

    # THE ORDER OF THIS LADDER IS LOAD-BEARING. Every SUBSTANCE verdict the
    # gate has already reached — the 0-byte scan, the placeholder/pdk scan
    # above, and `chip_gds_finding` here — is evaluated BEFORE the
    # `missing -> SKIP` branch, because rc=2 is NOT CHECKED (flow_compliance_
    # check reads it as VACUOUS_PASS) and an incomplete kit must never
    # SILENCE a defect the gate has proved on the artefacts it DID have.
    #
    # This ordering was inverted while `_REQUIRED_FILES` named only 2 members
    # and the inversion was latent; widening it to the 4 members the pack
    # generator emits armed it. Anti-scribe control (#60 P2-7) — mask_spec +
    # wat_plan present, L1.ic_name set, and the only GDS under
    # phase3/stage4/gds/ being the foundry frame `scribe_line_layout.gds`:
    # with `missing` first that kit exited rc=2 SKIP and the SCRIBE_ONLY /
    # CHIP_GDS_MISSING ERROR disappeared from the report that
    # `tapeout_checklist_gen` reads, so the chip-GDS defect dropped off the
    # tape-out checklist. It is rc=1 FAIL here, kit complete or not.
    #
    # An incomplete kit is NOT silently forgiven by this reordering: the flow
    # yaml declares all four members as Step-38 `required_outputs`, so their
    # absence is reported as MISSING by the step-level check independently of
    # this rc, and the members that are absent are named in the FAIL report
    # below as well.
    if waiver and (missing or chip_gds_finding is not None):
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
    elif chip_gds_finding is not None:
        verdict, rc = "FAIL", 1
        findings = [chip_gds_finding]
        if missing:
            findings.append({
                "severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                "message": f"missing: {missing}"})
    elif missing:
        verdict, rc = "SKIP", 2
        findings = [{"severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                      "message": f"missing: {missing}"}]
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
        # Report the LABELS (tuple entries flattened to "A OR B") so the JSON
        # stays a list of strings for downstream readers.
        "required_files": [_member_label(e) for e in _REQUIRED_FILES],
        "found": found,
        "missing": missing,
        "ic_name": ic_name,
        "physical_top_candidates": physical_tops,  # actual PnR top(s)
        "chip_gds": str(chip_gds) if chip_gds else None,
        "scribe_only": scribe_only,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "pending_foundry_fields": pending_foundry_fields,  # #449 open items
        # The same open items, DIFFERENTIATED: each one paired with the party
        # that closes it and the artefact that would. `pending_foundry_fields`
        # is kept unchanged beside it because `tapeout_checklist_gen` reads
        # exactly that key, and a consumer contract is not something to break
        # in passing.
        "handoff_open_items": handoff_open_items,
        "handoff_mode_declared": sorted(declared_modes),
        "handoff_mode_from_evidence": evidence_mode,
        "shuttle_precheck_present": precheck_present,
        "shuttle_precheck_verdict": precheck_verdict,
        "shuttle_operator": precheck_operator,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if missing:
        print(f"  missing: {missing}")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket','?')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
