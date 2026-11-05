#!/usr/bin/env python3
"""
foundry_handoff_package_check.py — gate (v1.6.13 Wave 88, integerised
in v1.6.14 Wave 90, renumbered Step 34 → 35 in v1.6.15 Wave 91, and
Step 35 → 38 by the later renumbering the flow yaml already carries).

Step 38 — foundry-handoff kit completeness

ENFORCEMENT: blocking at canonical Step 38 when --design-release is selected.
The unflagged historical interface only judges the legacy planning skeleton;
it never certifies a complete technical design release.

WHERE THE VERDICT IS CONSUMED: the flow's step 38 gate clause
(`program_exit_zero: "foundry_handoff_package_check . --json
reports/phase3/foundry_handoff_check.json"`), judged by flow_compliance_check.
No runner spawns this gate inline: R-0915-141 (#2525) moved phase3_one_shot_runner's
pre-audit producer slot to `foundry_handoff_pack_gen`, the program that PRODUCES
the kit, because a gate's own `--json` verdict can never be the step's produced
evidence. The runner never withheld the release on this exit status even before
that, so the step-38 clause is, and was, where it decides.

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

Default rationale when SKIP: the kit is incomplete — required members are
absent. (It used to read "Foundry-handoff kit assembler not shipped.", which
was false and cost a real investigation: the assembler IS shipped and IS wired
— `foundry_handoff_pack_gen`, in `phase3_one_shot_runner.
_DERIVED_ARTEFACT_GENERATORS`. Worse, this key is emitted on EVERY verdict,
PASS and FAIL included, so a FAIL report carried a sentence saying the producer
did not exist. It is a constant, never a statement about the run.)

Usage
-----
    python3 foundry_handoff_package_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import json
import re
import sys
from pathlib import Path
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)
import _gate_authorship as _ga  # R-0915-152 (who invoked this writer)
import _foundry_signoff_pdk as _fsp
import _gds_geometry as _geometry


#: The owner token `foundry_handoff_pack_gen.OWNER_US` writes for an item this
#: flow itself must close (the generator's own constant, read here as data).
_OWNER_THIS_FLOW = "this_flow"


def _closing_evidence_problems(project, evidence, package=None):
    """Why a CLOSED this_flow item's evidence does not stand ([] = it does).

    Every entry must name a file under the project whose sha256 is the one
    recorded; a pattern file must also name the trace it was converted from,
    and that trace must still hash to what the pattern says."""
    if not isinstance(evidence, list) or not evidence:
        return ["no evidence list"]
    bad = []
    root = Path(project).resolve()
    package = (Path(package) if package is not None else
               root / 'phase3/stage4/foundry_handoff').resolve()
    def current_file(value):
        for base in (package, root):
            path = (base / str(value)).resolve()
            if path.is_relative_to(base) and path.is_file():
                return path
        return None
    for ev in evidence:
        if not isinstance(ev, dict) or not ev.get("path"):
            bad.append(f"malformed entry {ev!r}")
            continue
        f = current_file(ev['path'])
        if f is None:
            bad.append(f"{ev['path']}: absent")
            continue
        if sha256_file(f) != ev.get("sha256"):
            bad.append(f"{ev['path']}: sha256 differs from the record")
            continue
        try:
            doc = json.loads(f.read_text(errors="replace"))
        except (OSError, ValueError):
            doc = None
        # The vector file IS the pattern a tester loads; the header only
        # describes it. Re-hash it (U18 r2: a deleted or fabricated .vec.gz
        # passed while the header still hashed).
        vf = doc.get("vectors_file") if isinstance(doc, dict) else None
        if not isinstance(vf, dict) or not vf.get("path"):
            bad.append(f"{ev['path']}: names no vectors_file")
            continue
        v = current_file(vf['path'])
        if v is None or sha256_file(v) != vf.get("sha256"):
            bad.append(f"{ev['path']}: its vectors_file {vf['path']} is "
                       f"absent or no longer hashes to the header's record")
            continue
        src = doc.get("source_trace") if isinstance(doc, dict) else None
        if not isinstance(src, dict) or not src.get("path"):
            bad.append(f"{ev['path']}: names no source trace")
            continue
        t = current_file(src['path'])
        if t is None or sha256_file(t) != src.get("sha256"):
            bad.append(f"{ev['path']}: its source trace {src['path']} is "
                       f"absent or no longer hashes to the pattern's record")
            continue
        # ...and the trace must be the one Step 5 recorded for this case, in
        # a state the design PASSED — not any file that happens to hash.
        trace_root = root
        if t.is_relative_to(package / 'archive/project'):
            trace_root = package / 'archive/project'
        trace_ref = dict(src, path=t.relative_to(trace_root).as_posix())
        if trace_root != root:
            # Normal Step38 still checks the current source project. Only the
            # relocated archive consumer uses its retained immutable copies.
            current = root / trace_ref['path']
            if not current.is_file() or sha256_file(current) != src.get('sha256'):
                bad.append(f"{ev['path']}: its current source trace changed or is missing")
                continue
            trace_root = root
        if not _is_step5_passed_trace(trace_root, doc.get("case"), trace_ref):
            bad.append(f"{ev['path']}: its source trace is not the trace the "
                       f"Step-5 record ({_STEP5_RECORD_REL}) lists for a "
                       f"PASSED case {doc.get('case')!r}")
    return bad


#: Step 5's functional record (`full_stack_functional_tb`), read as a path.
_STEP5_RECORD_REL = ("phase2/stage1/sim_full_stack/functional/"
                     "functional_cases.json")


def _is_step5_passed_trace(root, case, src):
    try:
        rec = json.loads((Path(root) / _STEP5_RECORD_REL).read_text())
    except (OSError, ValueError):
        return False
    for c in (rec.get("cases") if isinstance(rec, dict) else None) or []:
        if not isinstance(c, dict) or c.get("name") != case:
            continue
        tr = c.get("trace") or {}
        return (c.get("state") == "passed"
                and bool(tr.get("scope_verified"))
                and tr.get("vcd") == src.get("path")
                and tr.get("sha256") == src.get("sha256"))
    return False


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


def pdk_consistency_findings(project, signoff_pdk):
    """Refuse kit members that name a process different from the sign-off flow."""
    if signoff_pdk is None:
        return []
    findings = []
    json_members = [rel for rel in _REQUIRED_FILES
                    if isinstance(rel, str) and rel.endswith(".json")]
    for rel in json_members:
        path = project / rel
        try:
            member = json.loads(path.read_text(errors="replace"))
        except (OSError, ValueError):
            continue  # existing member/substance checks own unreadable JSON
        if not isinstance(member, dict):
            continue
        if "pdk" not in member:
            # Dropping the key must not escape the rule it feeds.
            findings.append({
                "severity": "ERROR",
                "rule": "FOUNDRY_HANDOFF_PDK_UNDECLARED",
                "message": (f"{rel}: kit member names no pdk, but the "
                            f"sign-off flow used {signoff_pdk!r}; a mask "
                            f"deliverable must state its process."),
            })
            continue
        declared = member["pdk"]
        if declared != signoff_pdk:
            findings.append({
                "severity": "ERROR",
                "rule": "FOUNDRY_HANDOFF_PDK_MISMATCH",
                "message": (f"{rel}: kit declares pdk={declared!r}, but the "
                            f"sign-off flow used {signoff_pdk!r}; regenerate "
                            f"the pack from the signed-off flow."),
            })
    return findings
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
# NOT a statement about the run: this key is written into the report under every
# verdict, PASS and FAIL included. Its old text — "Foundry-handoff kit assembler
# not shipped." — was also FALSE (the assembler is shipped and wired), and a FAIL
# report carrying it was read as "the producer is missing", sending an
# investigation after a program that already exists. The text now names the only
# thing a SKIP from this gate actually means.
_WAIVER_RATIONALE = ('Foundry-handoff kit incomplete: required member(s) absent '
                     'and the step is not waived.')

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


def _read_shuttle_precheck(project, assembly=None):
    """(exists, is_an_operators, verdict, operator) off 37.5ic's own report.

    `exists` is a fact about the FILE and keeps its old meaning, because the
    emitted report publishes it as `shuttle_precheck_present`. `is_an_operators`
    is the new, separate question -- see `_verdict_is_an_operators` -- and it is
    the one the shuttle-path rules key on. An UNREADABLE report answers True to
    both: a corrupt file must stay a non-pass on the shuttle path, exactly as
    before, so a parse failure can never become "there was no operator".

    `verdict` is None when the file is present but unparseable — which is NOT
    an accept: an unreadable verdict is reported as NOT_DETERMINED so that a
    corrupt report cannot become a quiet pass."""
    if assembly is not None:
        provider = selected_provider_precheck(assembly)
        return (bool(provider.get('retained_report')), True,
                provider['technical_precheck_status'], provider.get('provider'))
    if (project / 'reports/flow109/plan.json').is_file():
        from submission_template_check import slot_rules_are_owed
        if not slot_rules_are_owed(project, None)[0]:
            return False, False, None, None
    p = project / _SHUTTLE_PRECHECK_REPORT
    if not p.is_file():
        return False, False, None, None
    try:
        data = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return True, True, "NOT_DETERMINED", None
    if not isinstance(data, dict):
        return True, True, "NOT_DETERMINED", None
    return (True,
            _verdict_is_an_operators(data),
            data.get("verdict") or "NOT_DETERMINED",
            data.get("shuttle") or data.get("shuttle_id"))


def _verdict_is_an_operators(data):
    """Is this report an OPERATOR'S acceptance, or our own arm saying there is
    no operator to ask?

    THE FILE'S PRESENCE IS NOT THE ANSWER, and reading it as one is what made a
    DIE's hand-off fail. `tapeout_precheck` writes this report on every run that
    reaches 37.5ic, including the runs where its own docstring says the absence
    is legitimate:

        NOT_APPLICABLE  the registry names no live shuttle for this PDK. THE ONLY
                        absence that is not a defect -- the owner's "one fewer arm".
        NOT_DETERMINED  the arm should have run and could not.

    MEASURED on spm run13 and run8 (8HD-4, `_lane_icspm5`), both DIEs:

        verdict                  NOT_APPLICABLE
        arm_state                NOT_APPLICABLE
        arm_ran                  false
        verdict_is_the_operators false
        shuttle                  null
        reason   "validated informational catalogue; owner DIE has no operator purchase"

    The report states IN ITS OWN FIELDS that no operator was asked. Treating it
    as a shuttle hand-off made this gate emit
    `FOUNDRY_HANDOFF_SHUTTLE_PRECHECK_REFUSED` naming "the shuttle operator
    (unnamed in the report)" -- an ERROR about a refusal by a party that does not
    exist, on every digital DIE, however good the layout.

    CONSERVATIVE BY CONSTRUCTION. Only an EXPLICIT `verdict_is_the_operators:
    false` re-classifies. A report that omits the field is read exactly as
    before, so no existing kit changes meaning and a silence is never credited
    as "there was no operator" -- the same rule `tapeout_precheck` applies when
    it refuses to write NOT_APPLICABLE for a PDK it could not determine.
    """
    flag = data.get("verdict_is_the_operators")
    return flag is not False


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


# ── shared resolver: "is there a chip GDS a handoff kit could describe?" ──
# field (foundry-handoff hollow chip GDS) — the PRODUCER side of this gate had no chip-GDS predicate at
# all, and this gate had only a name-and-non-zero-size one. MEASURED on two
# benchmark runs (spm_gf180mcuD_20260831_a1, subservient_gf180mcuD_20260831_d1):
# PnR FAILed, so `step_gds` never ran, so NO .gds exists anywhere in either tree
# — and `foundry_handoff_pack_gen` still wrote a complete mask spec, WAT probe
# plan and ATE corner-vector kit for that absent die. Its only refusal (#654)
# keys on `antenna.json:routing_incomplete`, which both runs record as FALSE:
# routing COMPLETED, with a residual violation. So the one guard was silent on
# exactly the case it exists for.
#
# And the expensive form, measured end to end on a copy of the real spm run
# tree: a structurally valid GDSII stream of 108 bytes — HEADER, BGNLIB,
# LIBNAME, UNITS, a top structure carrying the design's own name, ENDSTR,
# ENDLIB, and NOT ONE geometry record — was packaged and signed off by this gate
# as PASS, "all 4 required artefacts present + chip GDS 'spm.gds'".
#
# A packager that launders an absent or hollow die into a deliverable is worse
# than no packager. The resolver lives HERE, in the gate that owns the "what
# counts as the chip GDS" question, so the producer and the gate cannot drift
# apart on the naming rules (`_find_chip_gds` / `_SCRIBE_LINE_GDS_HINTS` / the
# three search roots).
#
# The geometry predicate is the SAME one the hardmacro gate uses —
# `analog_a5_layout_check._gds_geometry_count`, imported the way
# `analog_hardmacro_check._gds_geometry_records` imports it — so "carries
# geometry" means one thing across the flow. A 0-byte GDS never reaches it:
# `_find_chip_gds` already skips `st_size <= 0`, so an empty file lands in the
# ABSENT arm and keeps the rule step 35 already emits for it.
# The module's own directory is put on sys.path first. The bare
# `from _atomic_artefact import ...` at the top of this file already assumes
# programs/ is importable, but THIS import decides a verdict: if it silently
# failed the gate would report GEOMETRY_PREDICATE_UNAVAILABLE on every project,
# which is a corpus-wide red bought for nothing. A gate invoked through a copy
# or a symlink elsewhere gets sys.path[0] = that other directory, so make it
# explicit rather than inherited.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # pragma: no cover - programs/ is on sys.path by the line above
    from analog_a5_layout_check import _gds_geometry_count
except ImportError:
    _gds_geometry_count = None  # type: ignore[assignment]

RULE_NO_CHIP_GDS = 'FOUNDRY_HANDOFF_NO_CHIP_GDS_TO_PACKAGE'
RULE_HOLLOW_CHIP_GDS = 'FOUNDRY_HANDOFF_HOLLOW_CHIP_GDS'
RULE_GEOMETRY_PREDICATE_UNAVAILABLE = (
    'FOUNDRY_HANDOFF_GEOMETRY_PREDICATE_UNAVAILABLE')


# ---------------------------------------------------------------------------
# THE LAYOUT MEMBER IS THE SIGNED-OFF GDS, BYTE FOR BYTE.
#
# MEASURED on spm run23 (lane icspm5): a full phase-3 re-run moved pnr/spm.gds
# and stage4/gds/spm.gds a7bf4526... -> 46459f4a... (signed off: DRC/LVS PASS),
# while stage4/foundry_handoff/spm.gds kept a7bf4526... . The runner packaged
# members copy-if-ABSENT (`if dst.is_file(): continue`) and by HARDLINK, so the
# first run's member was never refreshed -- and the rename that rewrote the
# source left the link pointing at the old inode. The package could ship a GDS
# other than the one signed off, and nothing here compared them.
# `layout_member_sources` is the ONE answer to "which file is member X derived
# from" for the producer and this gate alike; `stale_layout_members` is the
# comparison this gate now refuses on.
# ---------------------------------------------------------------------------
RULE_STALE_LAYOUT_MEMBER = "FOUNDRY_HANDOFF_STALE_LAYOUT_MEMBER"
_LAYOUT_SCRIBE_HINTS = ("scribe_line", "scribeline", "scribe-line", "frame")
_LAYOUT_ROOTS = ("phase3/stage4/gds", "phase3/stage3/pnr")   # signed-off first


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def layout_member_sources(project):
    """{member name: the file it must be derived from}. The SIGNED-OFF GDS
    (`phase3/stage4/gds/<name>`) set wins; PnR is a fallback only when that
    set is empty. Scribe stubs and comparison references are never
    members (their own rules name them)."""
    project = Path(project)
    out = {}
    for rel in _LAYOUT_ROOTS:
        root = project / rel
        if not root.is_dir():
            continue
        for g in sorted(root.glob("*.gds")):
            if any(h in g.stem.lower() for h in _LAYOUT_SCRIBE_HINTS):
                continue
            if any(g.name.lower().endswith(sfx)
                   for sfx in REFERENCE_ONLY_SUFFIXES):
                continue
            out.setdefault(g.name, g)
        if out:
            break
    return out


def stale_layout_members(project, selected_sources=None):
    """Package layout members whose bytes are not their source's -- by sha256,
    against the signed-off GDS of the same name (else the member's own derived
    source), plus any member whose recorded digest (mask_spec.json
    `layout_members`) no longer matches it."""
    project = Path(project)
    hd = project / "phase3/stage4/foundry_handoff"
    if not hd.is_dir():
        return []
    sources = selected_sources if selected_sources is not None else layout_member_sources(project)
    recorded = {}
    try:
        spec = json.loads((hd / "mask_spec.json").read_text(errors="replace"))
        if isinstance(spec, dict) and isinstance(spec.get("layout_members"), dict):
            recorded = spec["layout_members"]
    except (OSError, ValueError):
        recorded = {}
    stale = []
    for m in sorted(hd.glob("*.gds")):
        if not m.is_file() or m.stat().st_size == 0:
            continue
        src = sources.get(m.name)
        if src is None or not src.is_file():
            continue
        m_sha, s_sha = sha256_file(m), sha256_file(src)
        rec = recorded.get(m.name) if isinstance(recorded.get(m.name), dict) else {}
        why = None
        if m_sha != s_sha:
            why = "member bytes differ from the signed-off source"
        elif rec and rec.get("sha256") and rec.get("sha256") != m_sha:
            why = "mask_spec.json records a different digest for this member"
        if why:
            stale.append({"member": str(m.relative_to(project)),
                          "member_sha256": m_sha,
                          "source": str(src.relative_to(project)) if src.is_relative_to(project) else str(src),
                          "source_sha256": s_sha, "why": why})
    return stale


# ---------------------------------------------------------------------------
# THE LAYOUT MEMBER IS THE TOOL'S FINAL GDS WHEN STEP 37 RAN THROUGH LIBRELANE.
#
# Migration 38 (review70 step 38): LibreLane/OpenROAD have no hand-off step, so
# step 38 stays a vibe-ic packaging gate, but once step 37 is switched to the
# tool (`phase3/librelane_switch.json` steps."37" = librelane | dual) the layout
# the foundry receives must be the bytes LibreLane's finishing chain produced.
# `librelane_step37.run` records them in `phase3/librelane/37-promotion.json`
# (`source_sha256` = the selected arm's finished GDS; `canonical` = the flow
# path it was copied to). The stale-member rule above compares the member with
# the signed-off copy; this one compares it with the TOOL's output, so a copy
# re-finished in place after promotion (the old prefinish path) or a member
# left from a direct run cannot ship under a LibreLane sign-off. Direct mode is
# unchanged: there is no tool record to compare with.
# ---------------------------------------------------------------------------
RULE_LAYOUT_NOT_TOOL_OUTPUT = "FOUNDRY_HANDOFF_LAYOUT_NOT_THE_TOOL_OUTPUT"
_LL_PROMOTION = "phase3/librelane/37-promotion.json"


def tool_layout_binding(project, assembly=None):
    """Findings (list of dicts) binding the package layout member to the
    LibreLane step-37 promotion receipt. [] when step 37 ran direct or the
    kit has not been written yet."""
    project = Path(project)
    hd = project / "phase3/stage4/foundry_handoff"
    if not hd.is_dir():
        return []
    if assembly is not None:
        # The provider-finishing owner has validated the original stream and
        # the new final output. Do not compare that output with the earlier
        # core-only promotion as if they were the same material subject.
        member = hd / Path(assembly['gds']).name
        if not member.is_file() or sha256_file(member) != assembly['sha256']:
            return [{"why": "package differs from the admitted provider assembly"}]
        return []
    try:
        from librelane_contract import Refusal, selected_mode
    except ImportError as exc:
        return [{"why": f"librelane_contract unavailable ({exc}); the step-37 "
                        f"mode cannot be read"}]
    try:
        mode = selected_mode(project, "37")
    except Refusal as exc:
        return [{"why": f"phase3/librelane_switch.json is invalid: {exc}"}]
    except (OSError, ValueError) as exc:
        return [{"why": f"phase3/librelane_switch.json unreadable: {exc}"}]
    if mode == "direct":
        return []
    receipt = project / _LL_PROMOTION
    try:
        rec = json.loads(receipt.read_text(errors="replace"))
    except (OSError, ValueError):
        rec = None
    if not isinstance(rec, dict):
        return [{"mode": mode, "why": (
            f"step 37 is switched to {mode!r} but {_LL_PROMOTION} is absent or "
            f"unreadable, so no member can be shown to be the tool's GDS")}]
    src_sha = rec.get("source_sha256")
    canonical = rec.get("canonical")
    if not (isinstance(src_sha, str) and len(src_sha) == 64
            and isinstance(canonical, str) and canonical):
        return [{"mode": mode, "why": (
            f"{_LL_PROMOTION} names no source_sha256/canonical path")}]
    name = Path(canonical).name
    member = hd / name
    if not member.is_file():
        return [{"mode": mode, "member": str(member.relative_to(project)),
                 "why": f"the package carries no {name}, the member step 37 "
                        f"promoted"}]
    m_sha = sha256_file(member)
    if m_sha != src_sha:
        return [{"mode": mode, "member": str(member.relative_to(project)),
                 "member_sha256": m_sha, "tool_source": rec.get("source"),
                 "tool_source_sha256": src_sha,
                 "why": "member bytes are not LibreLane's final GDS"}]
    return []


def gds_files_on_disk(project):
    """EVERY `*.gds` under the three roots — any size, any name, frame or die.

    Distinct from `_any_real_gds`, deliberately. It answers "did stream-out
    write anything at all here", which is the question that separates "this flow
    has not reached stream-out yet" from "this flow streamed something and what
    it streamed is not a die". The producer refuses on the second and not the
    first; the GATE refuses on both, and already did on the first.
    """
    project = Path(project)
    out = []
    for root in (project / "phase3/stage4/foundry_handoff/gds",
                 project / "phase3/stage4/gds",
                 project / "gds"):
        if root.is_dir():
            out.extend(sorted(root.glob("*.gds")))
    return out


def _any_real_gds(project):
    """Non-empty, non-scribe .gds files under the three roots `_find_chip_gds`
    searches. Used when L1.ic_name is absent, so a project that never ran
    phase 1 is still measured on whether a die was streamed at all rather than
    silently treated as packageable."""
    out = []
    for root in (project / "phase3/stage4/foundry_handoff/gds",
                 project / "phase3/stage4/gds",
                 project / "gds"):
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*.gds")):
            if any(h in f.stem.lower() for h in _SCRIBE_LINE_GDS_HINTS):
                continue
            try:
                if f.stat().st_size > 0:
                    out.append(f)
            except OSError:
                continue
    return out


def packageable_chip_gds(project, selected=None):
    """Return (gds_path_or_None, rule_or_None, detail).

    `rule` is None only when a real, geometry-carrying chip GDS is on disk.
    Every other return NAMES the rule the caller must refuse under — never a
    bare False, so a refusal always says which predicate decided it.

    An unavailable geometry parser is its OWN named refusal, not a skipped
    predicate: a packager that cannot evaluate "is this die hollow" must refuse
    to package, never pack on the strength of a check it could not run.
    """
    project = Path(project)
    ic_name = _read_l1_ic_name(project)
    chip_gds, scribe_only, physical_tops = _find_chip_gds(project, ic_name)
    if selected is not None:
        chip_gds = Path(selected)
    if chip_gds is None:
        # No L1.ic_name is not a licence to package: fall back to "did the flow
        # stream ANY non-scribe, non-empty die?" before concluding absence.
        fallback = [] if ic_name else _any_real_gds(project)
        if not fallback:
            where = ("only scribe-line / frame GDS present"
                     if scribe_only else "no .gds present")
            return None, RULE_NO_CHIP_GDS, (
                f"{where} under phase3/stage4/foundry_handoff/gds/ or "
                f"phase3/stage4/gds/ or gds/ "
                f"(L1.ic_name={ic_name!r}, physical PnR top(s)="
                f"{physical_tops or '(none resolved)'}). There is no die to "
                f"describe, so a mask spec / WAT plan / ATE vector kit written "
                f"now would describe nothing.")
        chip_gds = fallback[0]
    if _gds_geometry_count is None:
        return chip_gds, RULE_GEOMETRY_PREDICATE_UNAVAILABLE, (
            "analog_a5_layout_check._gds_geometry_count could not be imported, "
            "so whether {} carries geometry cannot be evaluated".format(
                chip_gds.name))
    try:
        records = _gds_geometry_count(chip_gds.read_bytes())
    except OSError as exc:
        return chip_gds, RULE_HOLLOW_CHIP_GDS, (
            f"{chip_gds.name}: unreadable ({exc})")
    if records <= 0:
        return chip_gds, RULE_HOLLOW_CHIP_GDS, (
            f"{chip_gds.name}: the GDS stream carries no BOUNDARY/PATH/SREF/"
            f"AREF/BOX record — a hollow die is not a deliverable")
    return chip_gds, None, (
        f"{chip_gds.name}: {records} GDS geometry/placement record(s)")


#: Suffixes that name a layout kept for COMPARISON, never for delivery. Same set
#: the runner refuses to package (`phase3_one_shot_runner._REFERENCE_ONLY_SUFFIXES`),
#: asserted equal by test so the producer and the gate cannot drift apart.
REFERENCE_ONLY_SUFFIXES = (".prefinish.gds", ".ring_reference.gds")
RULE_REFERENCE_LAYOUT_IN_PACK = "FOUNDRY_HANDOFF_REFERENCE_LAYOUT_IN_PACK"



# The archive is a finite copy/index of existing producer outputs. It neither
# runs a signoff tool nor promotes a report merely because a filename exists.
RELEASE_MANIFEST = "release_manifest.json"
RELEASE_ROLES = ("final_gds", "physical_reference_netlist", "die_stack",
                 "stream_inputs", "layer_map", "stream_log", "tool_provenance",
                 "drc_report", "lvs_report", "antenna_report", "density_report",
                 "sta_report", "sdc", "spef")


def admitted_provider_release(project, record_path=None):
    """Use the finishing producer's reader for the selected release, if any."""
    project = Path(project)
    record = Path(record_path) if record_path else project / 'reports/phase3/provider_die_assembly.json'
    if record_path is None and not record.is_file():
        return None
    import die_finishing_gen as finishing_owner
    return finishing_owner.read_admitted_release(project, record)


def selected_provider_precheck(assembly):
    """One selected-service basis for the kit, manifest and normal gate.

    An unreadable selected result remains owed; it cannot select an older
    checkpoint's operator or turn a technical precheck into order acceptance.
    """
    provider = {'status': 'NOT_MEASURED', 'technical_precheck_status': 'NOT_MEASURED',
                'accepted': False, 'reason': 'No bound provider precheck for the selected assembly',
                'materials': []}
    try:
        selected = assembly['basis']['provider_precheck']
        provider.update({key: selected.get(key) for key in
                         ('provider','slot','cob','official_revision','options','layout_sha256')})
        root = Path(assembly['report']).parents[2]
        materials = []
        for source in [selected['source'], *selected.get('files', [])]:
            path = Path(source['path'])
            if not path.is_absolute():path = root / path
            if (not path.is_file() or not source.get('sha256')
                    or sha256_file(path) != source['sha256']):
                raise ValueError('provider precheck material missing/changed: '+str(path))
            materials.append({'path':str(path),'sha256':source['sha256']})
        if selected['layout_sha256'] != assembly['sha256']:
            raise ValueError('provider precheck does not bind the selected final GDS')
        provider.update(status='NOT_SUBMITTED', technical_precheck_status=selected['status'],
                        retained_report={'source':materials[0]['path'],'sha256':materials[0]['sha256']},
                        materials=materials,
                        reason='Technical precheck is separate from provider acceptance or a slot reservation')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        provider['reason'] = str(exc)
    return provider


def design_release_sources(project, layout, assembly=None):
    """Existing selected producers supply the archive readset and judgments."""
    import librelane_signoff_evidence as native
    import librelane_signoff as timing
    import librelane_contract as lc
    project = Path(project).resolve()
    files, validation, external = {}, {}, {}
    physical_project = Path(assembly["report"]).parents[2] if assembly else project
    def add(path, role, bundle=None):
        path = Path(path)
        if not path.is_absolute():
            path = project / path
        path = path.resolve()
        if not path.is_file() or path.stat().st_size == 0:
            return
        digest = sha256_file(path)
        entry = files.setdefault(str(path), {"sha256": digest, "roles": []})
        if role not in entry["roles"]:
            entry["roles"].append(role)
        if bundle and path.is_relative_to(bundle[0]):
            # Keep the producer's source.spice -> cells.spice and driver ->
            # pdk_runset/... relative references without rewriting its bytes.
            entry['native_bundle'] = {'sha256':bundle[1],
                                      'relative':path.relative_to(bundle[0]).as_posix()}
    def retained(folder, role, owner_project=project):
        """Archive the actual native State, configuration and report files."""
        collected = set()
        def keep(path, kind):
            path = Path(path)
            if path.is_file():
                add(path, kind)
                collected.add(str(path.resolve()))
        for name in ('config.json', 'state_in.json', 'state_out.json', 'metrics.json',
                     'COMMANDS', 'invocation.log'):
            keep(folder / name, 'tool_provenance')
        for path in (folder / 'reports').rglob('*'):
            if path.is_file():
                keep(path, role)
        config_path = folder / 'config.json'
        config = json.loads(config_path.read_text())
        mapping_path = folder / 'pdk_root.json'
        mapping = json.loads(mapping_path.read_text()) if mapping_path.is_file() else {}
        mounts = mapping.get('requested_mounts') or mapping.get('mounts_under_it') or []
        for source in lc._walk_paths(config):
            path = lc.resolve_state_pdk_asset(source, pdk=config.get('PDK'), mounts=mounts)
            if path is None:
                continue
            if path.suffix.lower() in ('.lym', '.lyt', '.lyp', '.map'):
                keep(path, 'layer_map')
            elif role == 'lvs_report' and path.suffix.lower() in ('.spice', '.sp', '.cdl', '.tcl'):
                keep(path, 'tool_provenance')
            elif not path.is_relative_to(project):
                external[str(path)] = {'reason': 'Configured native tool/PDK dependency'}
        state_path = folder / 'state_out.json'
        state = json.loads(state_path.read_text())
        if role == 'lvs_report':
            before = json.loads((folder / 'state_in.json').read_text())
            for key, value in (('physical_reference_netlist', before.get('pnl') or before.get('nl')),
                               ('lvs_report', state.get('spice'))):
                if value:
                    path = Path(value)
                    keep(path if path.is_absolute() else owner_project / path, key)
        return collected
    add(layout, 'final_gds')
    if assembly:
        add(assembly['report'],'stream_inputs')
        validation['provider_assembly']={'verdict':'PASS','sha256':assembly['sha256'],'basis':assembly.get('basis',{})}
        try:
            import wafer_space_precheck as provider_pv
            pv = provider_pv.read_signoff_evidence(project, Path(assembly['report']).resolve())
            for kind in ('drc','antenna','density'):
                row = pv['rows'][kind]
                validation[kind] = {'verdict':row['verdict'], 'gds_sha256':pv['gds_sha256'],
                                    'rows':{kind:row}, 'scope':pv['scope'],
                                    'disclosures':pv.get('disclosures', [])}
            for ref in pv['finite_files']:
                roles = [kind+'_report' for kind in ('drc','antenna','density')
                         if kind+'_raw_report' in ref['roles']]
                for role in roles or ['tool_provenance']:
                    add(ref['path'], role)
        except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
            for kind in ('drc','antenna','density'):
                validation[kind] = {'verdict':'NOT_MEASURED', 'reason':str(exc)}
    # This is the same strict retained reader used by normal signoff gates.
    for kind in ('drc','lvs','antenna','density'):
        if assembly and kind != 'lvs':
            continue  # Selected provider PV and internal LVS have separate owners.
        measurement_project = physical_project
        selected_ll_record = None
        if kind == 'lvs' and assembly and 'lvs' in (assembly.get('basis', {}).get('current_signoff') or {}):
            try:
                selected = assembly['basis']['current_signoff']['lvs']
                selected_ll_record = Path(selected['path'])
                if not selected_ll_record.is_absolute():selected_ll_record = physical_project / selected_ll_record
                selected_ll_record = selected_ll_record.resolve()
                measurement_project = selected_ll_record.parents[2]
                if not selected_ll_record.is_file():
                    raise ValueError('Selected native LVS report missing')
            except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
                validation[kind] = {'verdict':'NOT_MEASURED', 'reason':str(exc)}
                continue
        report_path = measurement_project / 'reports/phase3/lvs_verdict.json'
        if selected_ll_record is not None:
            # The assembly's normal publisher selected this exact owner record;
            # an unrelated older canonical report is not a fallback authority.
            report_path = selected_ll_record
        ll_publication = None
        if kind == 'lvs' and report_path.is_file() and selected_ll_record is None:
            try:
                published = json.loads(report_path.read_text())
                if published.get('librelane_pv'):
                    owner_path = Path(published['librelane_pv'])
                    if not owner_path.is_absolute():owner_path = measurement_project / owner_path
                    if owner_path.resolve() != (measurement_project / native.pv.RECORD_REL.format(half='lvs')).resolve():
                        raise ValueError('LL canonical LVS publication names another owner record')
                    ll_publication = published
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                validation[kind] = {'verdict':'NOT_MEASURED', 'reason':str(exc)}
                continue
        if kind == 'lvs' and report_path.is_file() and ll_publication is None and selected_ll_record is None:
            try:
                import klayout_pdk_lvs as native_lvs
                verdict = native_lvs.read_current_verdict(measurement_project, report_path, layout)
                circuits = verdict['native_result']['circuits']
                subject = verdict.get('requested_subject') or verdict['layout_source']
                validation[kind] = {
                    'verdict': verdict['status'],
                    'gds_sha256': subject['sha256'],
                    'requested_subject': subject,
                    'native_layout_source': verdict['layout_source'],
                    'subject_equivalence': verdict.get('subject_equivalence'),
                    'record': str(report_path),
                    'rows': {'unmatched_circuits': {'value': sum(row['status'] != 'Match' for row in circuits)}},
                    'tool': verdict['tool'], 'tool_version': verdict.get('tool_version'),
                    'options': verdict.get('options')}
                add(report_path, 'lvs_report')
                materials = []
                for name in ('layout_source','reference_source','native_result','deck','driver_source',
                             'source_netlist','extracted_netlist','log','inputs_manifest',
                             'cell_library_bundle'):
                    entry = verdict.get(name)
                    if not isinstance(entry, dict) or not entry.get('path'):
                        continue
                    role = ('physical_reference_netlist' if name == 'reference_source'
                            else 'lvs_report' if name in ('native_result','log') else 'tool_provenance')
                    materials.append((entry, role))
                dependencies = [*verdict.get('cell_libraries', []),
                                *verdict.get('runset_sources', []),
                                *verdict.get('producer_sources', [])]
                for name in ('library_translation','extraction_basis','subject_equivalence'):
                    dependencies.extend(entry for entry in (verdict.get(name) or {}).values()
                                        if isinstance(entry, dict) and entry.get('path'))
                materials.extend((entry, 'tool_provenance') for entry in dependencies)
                paths = [(Path(entry['path']) if Path(entry['path']).is_absolute()
                          else measurement_project / entry['path']).resolve()
                         for entry, _role in materials]
                # Recomparison can keep the original extraction bundle and a
                # second driver/tools directory. Preserve their common finite
                # path hierarchy; never scan or copy the surrounding directory.
                bundle = (Path(_os.path.commonpath([str(path.parent) for path in paths])),
                          sha256_file(report_path))
                for (entry, role), path in zip(materials, paths):
                    if not path.is_file() or not path.stat().st_size:
                        raise ValueError('native LVS bundle source missing: '+str(path))
                    add(path, role, bundle)
                original_deck = (verdict.get('deck') or {}).get('original_source')
                if original_deck:
                    external[original_deck['path']] = {'sha256':original_deck['sha256'],
                        'reason':'Original PDK source; the native producer snapshot is archived separately'}
            except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
                validation[kind] = {'verdict': 'NOT_MEASURED', 'reason': str(exc)}
            continue
        result = native.obligation(measurement_project, kind, layout=Path(layout))
        validation[kind] = result or {"verdict":"NOT_MEASURED","reason":"No selected native producer; no legacy PASS inferred"}
        if not result:
            continue
        lvs_materials = set()
        try:
            if ll_publication is not None:
                add(report_path, 'lvs_report')
                lvs_materials.add(str(report_path.resolve()))
                if result['verdict'] == 'PASS' and (ll_publication.get('status') != 'PASS'
                        or ll_publication.get('compare_performed') is not True):
                    raise ValueError('LL canonical LVS publication does not record a completed clean compare')
            folders = set()
            for row in result.get('rows',{}).values():
                if row.get('record'):add(row['record'],kind+'_report')
                if row.get('source'):add(row['source'],'tool_provenance')
                if row.get('source'):folders.add(Path(row['source']).parent)
            for folder in folders:
                lvs_materials.update(retained(folder,kind+'_report',measurement_project))
                if kind == 'lvs':
                    config = json.loads((folder/'config.json').read_text())
                    if (config.get('meta') or {}).get('step') == 'Magic.SpiceExtraction':
                        if config.get('MAGIC_EXT_USE_GDS') is not True or config.get('MAGIC_EXT_ABSTRACT') is not False:
                            raise ValueError('LL extraction is not full devices from the final GDS')
                        state = json.loads((folder/'state_out.json').read_text())
                        spice = Path(state.get('spice') or '')
                        if not spice.is_absolute():spice = measurement_project / spice
                        if not spice.is_file() or not spice.stat().st_size:
                            raise ValueError('Native extracted SPICE missing')
                        add(spice,'lvs_report');lvs_materials.add(str(spice.resolve()))
            if kind == 'lvs' and lvs_materials:
                bundle = (Path(_os.path.commonpath([str(Path(path).parent) for path in lvs_materials])),
                          sha256_file(measurement_project / native.pv.RECORD_REL.format(half='lvs')))
                for path in lvs_materials:
                    if path in files:
                        files[path]['native_bundle'] = {'sha256':bundle[1], 'relative':Path(path).relative_to(bundle[0]).as_posix()}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if validation[kind]['verdict'] != 'FAIL':
                validation[kind] = {'verdict':'NOT_MEASURED','reason':str(exc)}
    try:
        settled = lc.settled_floorplan_geometry(project)
        validation['die_stack'] = {"verdict":"PASS","retained_core_die_um":settled[0],"core_um":settled[1],"source":settled[2]}
        if assembly:
            validation['die_stack']['provider_assembly_basis']=assembly.get('basis',{})
        # Preserve the existing declared stack/geometry inputs. Actual native
        # config/state/receipt files also arrive through retained producers.
        for rel in ('phase3/librelane_floorplan_core.json','reports/phase3/floorplan_rectangles.json',
                    'phase1/generated_docs/L19_CONSTRAINTS_PDK.json','generated_docs/L19_CONSTRAINTS_PDK.json',
                    'input/submission_template/tapeout_declaration.json'):
            add(rel,'die_stack')
    except (OSError, ValueError, lc.Refusal) as exc:
        validation['die_stack'] = {"verdict":"NOT_MEASURED","reason":str(exc)}
    try:
        import _prestream_native as views
        state = views.final_state(project, streamed=True)
        if state is None:
            raise ValueError('Native stream State missing')
        canonical = views.finished_gds(project, state)
        if not assembly and canonical.read_bytes() != Path(layout).read_bytes():
            raise ValueError('stream subject differs from selected final GDS')
        validation['stream'] = {"verdict":"PASS", "canonical":str(canonical)}
        retained(state.parent, 'stream_log')
        config = json.loads((state.parent / 'config.json').read_text())
        for key in ('KLAYOUT_DEF_LAYER_MAP', 'KLAYOUT_TECH', 'KLAYOUT_PROPERTIES'):
            value = config.get(key)
            if value:
                path = lc.resolve_state_pdk_asset(value, pdk=config.get('PDK'))
                if path is not None:
                    add(path, 'layer_map')
    except (OSError, ValueError, KeyError, lc.Refusal) as exc:
        validation['stream'] = {"verdict":"NOT_MEASURED","reason":str(exc)}
    try:
        import sta_corner_record_completeness_check as sta_corners
        arm = sta_corners.read_tool_arm(project)
        if arm is None:
            raise ValueError('No retained native STA source selected')
        gaps = {name:row.get('scope_gaps') for name,row in arm['corners'].items() if row.get('scope_gaps')}
        if gaps:
            raise ValueError(f'incomplete STA scene coverage: {gaps}')
        record = project / timing.SIGNOFF_RECORD
        doc = json.loads(record.read_text()); state = Path(doc['sta_state'])
        views = json.loads(state.read_text())
        add(record,'sta_report');retained(state.parent,'sta_report')
        add(views['sdc'],'sdc')
        for path in (views.get('spef') or {}).values():
            add(path,'spef')
        for role, key in (('timed_reference_netlist','pnl'),('timed_reference_netlist','nl')):
            if views.get(key):add(views[key],role)
        import eda_report_audit as sta_audit
        from dataclasses import asdict
        complete = sta_corners.evaluate_tool(project, arm)
        verdict = complete['verdict']
        report_audit = None
        subjects = [Path(row['files'][timing.CORNER_REPORT]['path']) for row in arm['corners'].values()
                    if timing.CORNER_REPORT in row['files']]
        if subjects:
            with sta_audit.scoped_discovery([Path(arm['folder'])]), sta_audit.named_subjects(subjects):
                judged = sta_audit._check_sta(project)
            report_audit = asdict(judged)
            if verdict == 'PASS':
                verdict = judged.verdict or ('PASS' if judged.passed else 'FAIL')
            elif any(finding.rule == 'STA_REAL_VIOLATION_FOUND' for finding in judged.findings):
                verdict = 'FAIL'
        validation['sta'] = {"verdict":verdict,"corner_consumer":complete,
                             "report_consumer":report_audit,"basis":timing.tool_arm_basis(arm),
                             "scope":"Retained timed netlist/SDC/SPEF and routing checkpoint; not a new parasitic measurement of provider finishing"}
    except (OSError, ValueError, KeyError, lc.Refusal) as exc:
        validation['sta'] = {"verdict":"NOT_MEASURED","reason":str(exc)}
    # These are retained electrical/logic closure results, not extra provider
    # uploads. No P0/audit/checker is dispatched by the archive assembler.
    for rel in ('phase3/final/metrics.json','reports/phase3/signoff_metrics_aggregate.json',
                'reports/phase3/lec_post_layout.json','reports/phase3/erc.rpt',
                'reports/phase3/ir_drop.rpt','reports/phase3/em.rpt',
                'reports/phase3/power.rpt','reports/phase3/layout_receipts.json',
                'reports/phase3/general_precheck.json','reports/phase3/shuttle_precheck.json',
                'input/step_0_5ic_answers.json','input/submission_template/operator_answers.json'):
        add(rel,'internal_closure')
    provider = None
    if assembly:
        provider = selected_provider_precheck(assembly)
        for material in provider.pop('materials'):
            add(material['path'], 'provider_precheck')
        validation['provider_precheck'] = {'verdict': provider['technical_precheck_status'],
                                           'gds_sha256': assembly['sha256']}
    return {"files":files,"validation":validation,"external_dependencies":external,
            "provider_submission":provider}


def emit_design_release(project, destination, layout, physical_top, assembly=None):
    """Copy a portable, checksummed archive without writing the source tree."""
    import shutil
    project, destination = Path(project).resolve(), Path(destination).resolve()
    source = design_release_sources(project,layout,assembly=assembly) if layout else {
        "files":{},"validation":{},"external_dependencies":{}}
    from _release_docs_contract import DOC_ROOT
    for root in (project / DOC_ROOT / 'ic', project / 'reports/phase3/docs'):
        for path in sorted(root.rglob('*')):
            if path.is_file():
                source['files'][str(path)] = {'sha256': sha256_file(path),
                                             'roles': ['release_documentation']}
    members=[]
    for name, entry in source['files'].items():
        path=Path(name)
        bundle=entry.get('native_bundle')
        rel=(Path('archive/native_lvs')/bundle['sha256']/bundle['relative'] if bundle else
             Path('archive/project')/path.relative_to(project) if path.is_relative_to(project)
             else Path('archive/dependencies')/entry['sha256']/path.name)
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.is_file() or sha256_file(target)!=entry['sha256']:
            temporary=target.with_name('.'+target.name+'.tmp')
            shutil.copyfile(path,temporary);temporary.replace(target)
        members.append({"path":rel.as_posix(),"source":name,"sha256":entry['sha256'],
                        "bytes":target.stat().st_size,"roles":entry['roles']})
    roles={role for entry in members for role in entry['roles']}
    missing=[role for role in RELEASE_ROLES if role not in roles]
    incomplete=[kind for kind,row in source['validation'].items() if row.get('verdict')!='PASS']
    if not physical_top.get('top'):missing.append('physical_top')
    provider=source.get('provider_submission') or {"status":"NOT_MEASURED","accepted":False,
              "reason":"Provider contract/precheck must bind this final layout; no slot, CoB or submission approval inferred"}
    # Only the actual selected operator result can describe submission scope.
    precheck=project/'reports/phase3/shuttle_precheck.json'
    if not assembly and precheck.is_file() and (
            not (project / 'reports/flow109/plan.json').is_file() or _read_shuttle_precheck(project)[1]):
        provider['retained_report']={"source":str(precheck),"sha256":sha256_file(precheck)}
        try:
            report=json.loads(precheck.read_text())
            provider['reported_verdict']=report.get('verdict')
            provider['provider']=report.get('shuttle') or report.get('operator')
        except (OSError, ValueError, AttributeError) as exc:
            provider['reported_verdict']='NOT_MEASURED'
            provider['reason']='Unreadable retained provider result: '+str(exc)
    manifest={"schema":"vibeic.design_release/1","physical_top":physical_top,
              "assembly_record":str(assembly['report']) if assembly else None,
              "files":members,"required_roles":list(RELEASE_ROLES),"missing":missing,
              "validation":source['validation'],"incomplete_validation":incomplete,
              "external_dependencies":source['external_dependencies'],
              "archive_status":"COMPLETE" if not missing and not incomplete else "INCOMPLETE",
              "provider_submission":provider,
              "upload_subset":[entry['path'] for entry in members if 'final_gds' in entry['roles']],
              "scope":"Portable internal design-closure archive; provider upload requirements and acceptance are separate."}
    atomic_write_text(destination/RELEASE_MANIFEST,json.dumps(manifest,indent=2)+'\n')
    atomic_write_text(destination/'SHA256SUMS',''.join(f"{entry['sha256']}  {entry['path']}\n" for entry in members))
    return manifest



def seal_design_release(destination):
    """Include the producer's own metadata and write ordinary SHA256SUMS."""
    destination=Path(destination)
    doc=json.loads((destination/RELEASE_MANIFEST).read_text())
    candidates=[p for p in destination.rglob('*') if p.is_file()
                and p.relative_to(destination).as_posix() not in (RELEASE_MANIFEST,'SHA256SUMS')]
    known={entry['path'] for entry in doc['files']}
    for path in sorted(candidates):
        rel=path.relative_to(destination).as_posix()
        if rel not in known:
            doc['files'].append({"path":rel,"source":"generated by foundry_handoff_pack_gen",
                                 "sha256":sha256_file(path),"bytes":path.stat().st_size,
                                 "roles":["package_metadata"]})
    atomic_write_text(destination/RELEASE_MANIFEST,json.dumps(doc,indent=2)+'\n')
    sums=''.join(f"{entry['sha256']}  {entry['path']}\n" for entry in doc['files'])
    sums+=f"{sha256_file(destination/RELEASE_MANIFEST)}  {RELEASE_MANIFEST}\n"
    atomic_write_text(destination/'SHA256SUMS',sums)
    return doc


def check_design_release(package):
    """Verify the package after relocation; original absolute paths are provenance only."""
    package=Path(package).resolve();bad=[]
    try:
        doc=json.loads((package/RELEASE_MANIFEST).read_text())
        if doc.get('schema')!='vibeic.design_release/1':raise ValueError('unknown design-release manifest')
        roles=set()
        expected_sums=''.join(f"{entry['sha256']}  {entry['path']}\n" for entry in doc['files'])
        expected_sums+=f"{sha256_file(package/RELEASE_MANIFEST)}  {RELEASE_MANIFEST}\n"
        if (package/'SHA256SUMS').read_text()!=expected_sums:
            bad.append('SHA256SUMS differs from the complete package manifest')
        for entry in doc['files']:
            path=(package/entry['path']).resolve()
            if not path.is_relative_to(package) or not path.is_file() or path.stat().st_size!=entry['bytes'] or sha256_file(path)!=entry['sha256']:
                bad.append(f"missing/changed archive member: {entry.get('path')}")
            roles.update(entry['roles'])
        actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
        indexed={entry['path'] for entry in doc['files']} | {RELEASE_MANIFEST,'SHA256SUMS'}
        if actual != indexed:bad.append('package file manifest is incomplete')
        bad.extend('required role absent: '+role for role in RELEASE_ROLES if role not in roles)
        bad.extend('signoff not measured/passed: '+kind for kind in ('drc','lvs','antenna','density','die_stack','stream','sta')
                   if (doc.get('validation',{}).get(kind) or {}).get('verdict')!='PASS')
        final_entries=[entry for entry in doc['files'] if 'final_gds' in entry['roles']]
        if len(final_entries)!=1:
            bad.append('exactly one selected final GDS required')
        else:
            final=final_entries[0]
            import _gds_geometry as geometry
            facts=geometry.read_layout(package/final['path'])
            if facts.truncated or facts.top_cells()!=[doc.get('physical_top',{}).get('top')]:
                bad.append('physical top differs from archived final GDS')
            for kind in ('drc','lvs','antenna','density'):
                evidence=doc.get('validation',{}).get(kind) or {}
                if evidence.get('gds_sha256')!=final['sha256']:
                    bad.append(kind+': signoff subject differs from selected final GDS')
                rows=evidence.get('rows') or {}
                if not rows or any(type(row.get('value')) is not int or row['value']!=0 for row in rows.values()):
                    bad.append(kind+': missing or nonzero measured counts')
        if doc.get('archive_status')!='COMPLETE' or doc.get('missing') or doc.get('incomplete_validation'):
            bad.append('archive is incomplete')
        if doc.get('assembly_record') and (doc.get('provider_submission') or {}).get('technical_precheck_status')!='PASS':
            bad.append('selected provider technical precheck has not passed for this assembly')
        if not doc.get('physical_top',{}).get('top'):bad.append('physical top not measured')
        corner = package / 'corner_test_vectors.json'
        if corner.is_file():
            for item in json.loads(corner.read_text()).get('open_items', []):
                if item.get('owner') == _OWNER_THIS_FLOW and item.get('status') == 'CLOSED':
                    bad.extend(_closing_evidence_problems(package / 'archive/project',
                                                         item.get('evidence'), package))
    except (OSError, ValueError, KeyError, TypeError, _geometry.GdsError) as exc:
        bad.append(str(exc));doc={}
    return doc,bad


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    parser.add_argument("--design-release", action="store_true", help="require the complete portable design-closure archive")
    parser.add_argument("--package-dir", type=Path, help="validate a relocated timestamp package without original project paths")
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    if args.package_dir:
        doc, bad = check_design_release(args.package_dir)
        report={"program":_GATE_NAME,"verdict":"FAIL" if bad else "PASS",
                "scope":"PORTABLE_DESIGN_RELEASE","findings":bad,"archive":doc}
        if args.json:atomic_write_text(Path(args.json),json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2));return 1 if bad else 0

    assembly = None
    if args.design_release:
        try:
            index_path = project / 'phase3/stage4/foundry_handoff' / RELEASE_MANIFEST
            index = json.loads(index_path.read_text()) if index_path.is_file() else {}
            assembly = admitted_provider_release(project, index.get('assembly_record'))
        except (OSError, ValueError, RuntimeError, AttributeError) as exc:
            report = {'program': _GATE_NAME, 'verdict': 'FAIL', 'scope': 'DESIGN_RELEASE',
                      'technical_release_complete': False,
                      'findings': [{'severity': 'ERROR', 'rule': 'DESIGN_RELEASE_ADMISSION_INVALID',
                                    'message': str(exc)}]}
            if args.json:atomic_write_text(Path(args.json),json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2));return 1
    selected_sources = {Path(assembly['gds']).name: Path(assembly['gds'])} if assembly else None

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
    if assembly:
        chip_gds = project / 'phase3/stage4/foundry_handoff' / Path(assembly['gds']).name
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

    # field (foundry-handoff hollow chip GDS) — SUBSTANCE, not merely presence. `_find_chip_gds`
    # accepts any non-empty file with the right name, so a structurally valid
    # GDSII stream carrying ZERO geometry records — 108 bytes — satisfied the
    # v1.6.162 chip-GDS requirement and this gate PASSED the kit around it.
    #
    # WHY IT IS IN THE GATE AND NOT ONLY IN THE PRODUCER, measured: with the
    # producer-side refusal alone, the hollow case moved from rc=0 PASS to rc=2
    # SKIP, and `flow_compliance_check` reads rc=2 as VACUOUS_PASS. The same
    # green in a different exit code is not a fix. A producer-only refusal is
    # also deletable — hand-write the four kit JSONs beside a hollow GDS and
    # nothing looks at the die. Keyed here, on the artefact, no choice of writer
    # evades it.
    #
    # It fires ONLY when a chip GDS was actually identified: an absent GDS is
    # already FOUNDRY_HANDOFF_CHIP_GDS_MISSING above, and re-reporting it here
    # would double-count one defect.
    if chip_gds is not None and chip_gds_finding is None:
        _pkg_gds, _pkg_rule, _pkg_detail = packageable_chip_gds(project, selected=chip_gds if assembly else None)
        if _pkg_rule in (RULE_HOLLOW_CHIP_GDS,
                         RULE_GEOMETRY_PREDICATE_UNAVAILABLE):
            chip_gds_finding = {
                "severity": "ERROR",
                "rule": _pkg_rule,
                "message": (
                    f"{_pkg_detail}. A chip GDS that carries no geometry is "
                    f"not a deliverable: the handoff kit describes a die that "
                    f"does not exist. Step 35 PASS requires a chip-named GDS "
                    f"whose stream carries layout records."),
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
                  "scope": "DESIGN_RELEASE" if args.design_release else "LEGACY_SKELETON",
                  "findings": findings,
                  "zero_byte_members": zero_members}
        # R-0915-152 -- the document states WHO INVOKED this writer, beside the
        # verdict it already composes. Unstated role == producer, so the run's
        # own path is unchanged.
        report.setdefault("scope", "DESIGN_RELEASE" if args.design_release else "LEGACY_SKELETON")
        report.setdefault("technical_release_complete", False)
        _ga.stamp(report)
        out = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(Path(args.json), out)
        print(out)
        return rc

    # R-0915-146 — A COMPARISON REFERENCE IS NOT A DELIVERABLE.
    #
    # MEASURED on spm run22: the handoff pack carried `chip_top.prefinish.gds`
    # (73,850,996 B) hardlinked beside the shipped `spm.gds` (102,923,002 B). That
    # is the PRE-FINISHING layout, retained by the gds step so stream-out/finishing
    # fidelity can be measured against it, and 29 MB smaller than the real mask set
    # because fill, seal ring and snap had not happened yet. The run's own write
    # ledger classes it `written_never_declared`: nothing declares it a deliverable.
    #
    # A hand-off package is what a foundry taped out FROM. A second, differently
    # named, entirely plausible GDS inside it is an invitation to tape out the wrong
    # layout, and no downstream check would notice: it is non-empty, it parses, and
    # it carries real geometry. The runner no longer packages one; this gate refuses
    # one however it arrived, because "the producer stopped doing it" is not the
    # same guarantee as "the package cannot contain it".
    stale = stale_layout_members(project, selected_sources=selected_sources)
    if stale:
        verdict, rc = "FAIL", 1
        _s0 = stale[0]
        findings = [{
            "severity": "ERROR",
            "rule": RULE_STALE_LAYOUT_MEMBER,
            "message": (
                f"{len(stale)} handoff layout member(s) are not the signed-off "
                f"GDS: {_s0['member']} sha256 {_s0['member_sha256'][:12]}... vs "
                f"{_s0['source']} sha256 {_s0['source_sha256'][:12]}... "
                f"({_s0['why']}). A foundry tapes out the package; a member "
                f"that is not byte-identical to the signed-off layout ships a "
                f"design nothing signed off. Re-run foundry_handoff_pack_gen, "
                f"which re-derives every member from the signed-off GDS."),
        }]
        report = {"program": _GATE_NAME, "verdict": verdict,
                  "findings": findings, "stale_layout_members": stale}
        report.setdefault("scope", "DESIGN_RELEASE" if args.design_release else "LEGACY_SKELETON")
        report.setdefault("technical_release_complete", False)
        _ga.stamp(report)
        out = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(Path(args.json), out)
        print(out)
        return rc

    unbound = tool_layout_binding(project, assembly=assembly)
    if unbound:
        verdict, rc = "FAIL", 1
        findings = [{
            "severity": "ERROR",
            "rule": RULE_LAYOUT_NOT_TOOL_OUTPUT,
            "message": (
                f"step 37 ran through LibreLane but the hand-off layout member "
                f"is not its final GDS: {unbound[0]['why']}. The package must "
                f"carry the bytes {_LL_PROMOTION} records (source_sha256)."),
        }]
        report = {"program": _GATE_NAME, "verdict": verdict,
                  "findings": findings, "tool_layout_binding": unbound}
        report.setdefault("scope", "DESIGN_RELEASE" if args.design_release else "LEGACY_SKELETON")
        report.setdefault("technical_release_complete", False)
        _ga.stamp(report)
        out = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(Path(args.json), out)
        print(out)
        return rc

    reference_members = []
    for hd in sorted(project.glob("phase3/stage4/foundry_handoff/**/*")):
        if not hd.is_file():
            continue
        name_lo = hd.name.lower()
        if any(name_lo.endswith(sfx) for sfx in REFERENCE_ONLY_SUFFIXES):
            reference_members.append(str(hd.relative_to(project)))
    if reference_members:
        verdict, rc = "FAIL", 1
        findings = [{
            "severity": "ERROR",
            "rule": RULE_REFERENCE_LAYOUT_IN_PACK,
            "message": (
                f"comparison-reference layout(s) inside the handoff pack: "
                f"{reference_members[:6]}. A retained pre-finishing or reference "
                f"GDS exists so fidelity can be MEASURED against it; shipping it "
                f"beside the mask set offers a foundry a second plausible layout "
                f"to tape out. Keep it under phase3/stage3/pnr/ where the fidelity "
                f"step reads it."),
        }]
        report = {"program": _GATE_NAME, "verdict": verdict,
                  "findings": findings,
                  "reference_members": reference_members}
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
    handoff_dir = project / "phase3/stage4/foundry_handoff"
    archive_sources = set()
    try:
        _index = json.loads((handoff_dir / RELEASE_MANIFEST).read_text())
        archive_sources = {entry['path'] for entry in _index.get('files', [])
                           if isinstance(entry, dict) and str(entry.get('path', '')).startswith('archive/')}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    for hf in sorted(project.glob("phase3/stage4/foundry_handoff/**/*")):
        # Copied producer evidence is checked by the archive's checksum/source
        # contract, not as newly authored mask/WAT placeholder instructions.
        if hf.relative_to(handoff_dir).as_posix() in archive_sources:
            continue
        if not hf.is_file() or hf.stat().st_size == 0:
            continue
        if hf.suffix.lower() in (".gds", ".gds2", ".gdsii", ".oas"):
            continue
        try:
            full = hf.read_text(errors="replace")
        except OSError:
            continue
        # The TODO/TBD scan reads the leading 20000 characters; a JSON member
        # is PARSED IN FULL. Parsing the cut text made every member longer
        # than the slice a silent non-dict, and with it every rule below
        # (owner, this_flow OPEN/CLOSED, mode) switched off without a word —
        # a kit with ~80 L10 seeds passed with our own item OPEN (U18 r2).
        txt = full[:20000]
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
                jd = json.loads(full)
            except ValueError as exc:
                jd = None
                # A member that does not parse carries no rule this gate can
                # apply; it is refused by name, never skipped.
                substance_findings.append({
                    "severity": "ERROR",
                    "rule": "FOUNDRY_HANDOFF_MEMBER_UNPARSEABLE",
                    "message": (f"{rel}: not valid JSON ({exc}); none of "
                                f"its open items can be judged."),
                })
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
                    # AN OPEN ITEM THIS FLOW OWNS IS UNFINISHED WORK, NOT A
                    # DISCLOSURE. The foundry, the operator, the test house and
                    # the contract close their items outside this flow, so
                    # their OPEN is an honest hand-off; `this_flow` names US,
                    # and a kit that still owes our own deliverable is not
                    # complete. Only an item recorded OPEN blocks: an item the
                    # generator resolved NOT_APPLICABLE_IN_MODE, or CLOSED
                    # against its evidence, does not.
                    for it in items:
                        if (isinstance(it, dict)
                                and it.get("owner") == _OWNER_THIS_FLOW
                                and str(it.get("status") or "").upper()
                                == "OPEN"):
                            substance_findings.append({
                                "severity": "ERROR",
                                "rule": "FOUNDRY_HANDOFF_THIS_FLOW_ITEM_OPEN",
                                "message": (
                                    f"{rel}: open item {it.get('field')!r} "
                                    f"is owned by this_flow and still OPEN "
                                    f"(closed by: {it.get('closed_by')}). "
                                    f"Work this flow owes is not a foundry "
                                    f"hand-off item; the kit is not "
                                    f"complete until it is closed."),
                            })
                    # A CLOSED item this flow owned is closed only by the files
                    # it names, re-hashed here; a status word alone closes
                    # nothing.
                    for it in items:
                        if not (isinstance(it, dict)
                                and it.get("owner") == _OWNER_THIS_FLOW
                                and str(it.get("status") or "").upper()
                                == "CLOSED"):
                            continue
                        bad = _closing_evidence_problems(project,
                                                         it.get("evidence"))
                        if bad:
                            substance_findings.append({
                                "severity": "ERROR",
                                "rule": "FOUNDRY_HANDOFF_THIS_FLOW_CLOSED_"
                                        "WITHOUT_EVIDENCE",
                                "message": (
                                    f"{rel}: item {it.get('field')!r} is "
                                    f"recorded CLOSED but its evidence does "
                                    f"not stand: {bad[:6]}"),
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
    # `precheck_is_an_operators` is FALSE when 37.5ic ran and reported that
    # there was no operator to ask (see `_verdict_is_an_operators`). That is not
    # the shuttle path, so neither the mode nor the operator-refusal rule below
    # applies to it.
    precheck_present, precheck_is_an_operators, precheck_verdict, \
        precheck_operator = _read_shuttle_precheck(project, assembly=assembly)
    evidence_mode = (_MODE_SHUTTLE if precheck_is_an_operators
                     else _MODE_UNDECLARED)
    if (project / 'reports/flow109/plan.json').is_file():
        from foundry_handoff_pack_gen import _handoff_mode
        evidence_mode = _handoff_mode(project, assembly)['mode']

    if precheck_is_an_operators and precheck_verdict not in _PRECHECK_ACCEPTS:
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

    archive_problems = []
    if args.design_release:
        _archive, archive_problems = check_design_release(project/'phase3/stage4/foundry_handoff')
        substance_findings.extend({"severity":"ERROR","rule":"DESIGN_RELEASE_INCOMPLETE","message":problem}
                                  for problem in archive_problems)

    waiver = _step_waived(project, args.step_label)
    signoff_pdk, pdk_candidates = _fsp.signoff_pdk_evidence(project)
    substance_findings.extend(pdk_consistency_findings(project, signoff_pdk))
    # A PASS where the kit/flow comparison ran must not look like one where
    # it could not: every report states which it was, and why.
    if signoff_pdk is not None:
        pdk_consistency = "CHECKED"
        pdk_notes = []
    else:
        pdk_consistency = ("NOT_DETERMINED:absent" if not pdk_candidates
                           else f"NOT_DETERMINED:ambiguous{pdk_candidates}")
        pdk_notes = [{
            "severity": "INFO",
            "rule": "FOUNDRY_HANDOFF_PDK_NOT_DETERMINED",
            "message": (f"the kit's pdk was not compared with the sign-off "
                        f"flow: {pdk_consistency} (/foss/pdks/<name>/ paths "
                        f"in the published phase2/phase3 files)."),
        }]
    if substance_findings and (not waiver or archive_problems):
        verdict, rc = "FAIL", 1
        findings = substance_findings + pdk_notes
        report = {"program": _GATE_NAME, "verdict": verdict,
                  "signoff_pdk": signoff_pdk,
                  "pdk_consistency": pdk_consistency,
                  "findings": findings}
        # R-0915-152 -- the document states WHO INVOKED this writer, beside the
        # verdict it already composes. Unstated role == producer, so the run's
        # own path is unchanged.
        report.setdefault("scope", "DESIGN_RELEASE" if args.design_release else "LEGACY_SKELETON")
        report.setdefault("technical_release_complete", False)
        _ga.stamp(report)
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
    # A waived substance finding is WAIVED, never PASS, and stays on the
    # record beside the waiver that covered it.
    if waiver and (missing or chip_gds_finding is not None
                   or substance_findings):
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
        findings.extend(substance_findings)
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

    findings.extend(pdk_notes)

    # #449 — Retain provider-owned and conditional manufacturing/test fields
    # as coordination information. The selected service defines applicability;
    # these fields are not universal designer submission prerequisites.
    if pending_foundry_fields:
        findings.append({
            "severity": "INFO",
            "rule": "FOUNDRY_HANDOFF_PENDING_FOUNDRY",
            "message": (f"{len(pending_foundry_fields)} provider-owned or conditional "
                        f"manufacturing/test field(s) retained for coordination; "
                        f"applicability follows the selected service contract, "
                        f"not universal designer submission prerequisites: "
                        + "; ".join(pending_foundry_fields[:12])),
        })

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "scope": "DESIGN_RELEASE" if args.design_release else "LEGACY_SKELETON",
        "technical_release_complete": bool(args.design_release and not archive_problems and verdict == "PASS"),
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
        "signoff_pdk": signoff_pdk,
        "pdk_consistency": pdk_consistency,
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
    # R-0915-152 -- the THIRD write path in this program, and the one a real run
    # takes: measured, the two early-return branches above are the refusal paths.
    _ga.stamp(out)
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
