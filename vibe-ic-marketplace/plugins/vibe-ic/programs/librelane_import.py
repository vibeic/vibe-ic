#!/usr/bin/env python3
"""librelane_import.py — import a LibreLane run into the canonical tree (llv1 W6).

Under ``--librelane`` the layout is LibreLane's. vibe-ic's gates still read the
canonical tree (``phase2/stage2/synth``, ``phase3/stage3/pnr``, ...), so every
file a gate reads must arrive there from the run that produced it, bound to it
by sha256, with a provenance row that says who produced it (W19).

WHAT IT KEYS ON
---------------
The run's OWN records, never folder ordinals:
  * ``flow.log`` lists every step LibreLane started, in order, by instance id
    (``_tool_log_provenance.flow_log_steps``, a calibrated reader);
  * each folder's ``config.json`` names the step class that wrote it; the two
    must agree (an instance id is the class id, or the class id plus ``-N``).
A rule names a step CLASS and takes its one TOP-LEVEL run: a run nested inside
a composite step (``Odb.DiodesOnPorts`` re-running ``DetailedPlacement``) is
never the stage's database. A rule that names an anchor (``after``) takes the
top-level run that follows the anchor's run. More than one candidate is
refused by name, never chosen by position. The chosen step must have written
its ``state_out.json`` (LibreLane writes it only after the step's ``run()``).

A RUN IMPORTS ONLY WHEN IT FINISHED
-----------------------------------
LibreLane writes ``Flow complete.`` to flow.log only after every step it was
asked to run returned (``--to`` included) and no deferred error is left; its
failure message is printed after flow.log is closed, so a failed run simply
stops. ``flow_status`` (a calibrated reader) reads the LAST invocation (from
its ``Starting…`` line). Without ``Flow complete.`` after its last started step
the import refuses (``LL_IMPORT_FLOW_INCOMPLETE``, naming that step, its folder
and its transcripts): an aborted run is an honest FAIL with the tool's own
log, never a partial import whose missing steps read as "not performed". A
segment declared with ``to`` must also end at that step, finished.

SEGMENTS
--------
The two-segment plan (W5) is ONE call: ``import_segments(project,
[(seg1_run_dir, "Checker.NetlistAssignStatements"), (seg2_run_dir, None)])``
(CLI: ``librelane_import.py <project> <seg1>=Checker.NetlistAssignStatements
<seg2>``). Each rule is taken from the one segment that ran it (two segments
running it is refused). Consecutive segments must meet at adjacent top-level
flow-loop slots; a step skipped by both is a segment gap, not a flow step the
tool does not perform. ``not_performed`` is computed only after that check.

WHAT IT WRITES
--------------
* The canonical files, COPIED (never symlinked; a symlink at a destination is
  replaced, not written through). State views go through
  ``librelane_contract._copy_state_views`` with a ``path_map`` from the path the
  run recorded to where the run now lives; a view recorded by an EARLIER step
  is refused, since the row would attribute it to the wrong step.
* One provenance row per imported step: a witnessed row
  (``_tool_log_provenance.witnessed_row``, decision 4a) when the step's own
  tool logs support one, else a #365 back-fill (``reconstructed: true``). Each
  row gets the artefact-derived measurement ``_runner_measurement`` states.
* ``phase3/stage3/pnr/openroad.log`` assembled from the OpenROAD step logs in
  flow order. Every inserted section is bracketed by a marker naming its source
  log and sha256; the assembled file is itself a back-fill row.
* W0's import manifest (``reports/phase3/impl/import_manifest.json``,
  schema ``vibe-ic/external-flow-import/2``), written ONLY through
  ``_external_flow_manifest.write_manifest``, which validates every row
  against the disk. One run is written flat (``run_dir``, ``rows``,
  ``flow_status``); two segment runs as ``segments: [{name, run_dir,
  flow_status, rows}]`` (W0's segment extension, see that module). Rows are
  in W0's final field names (flow step, canonical path, tool-run path,
  sha256 on both sides, tool, tool step id, step_dir, the source logs the
  step's witness cites, exit code, measurement), run-relative to their
  segment's ``run_dir`` (itself project-relative). Also ``not_performed``
  (every rule no segment performed), and, as importer fields, ``top``,
  ``removed`` (files an earlier import of the same runs wrote that this one
  does not) and ``openroad_log``.

ALL OR NOTHING
--------------
Every rule is planned, and every refusal raised, BEFORE anything is written.
The writes then run under a journal: if one still fails, every path is
restored. A project whose manifest records an import of OTHER runs is refused
(a different run needs a fresh project); re-importing the same runs removes
the canonical files the earlier import wrote and this one does not, only while
their bytes still match the previous manifest. Importer records and any run
tree can never be deletion targets.

WHAT IT DOES NOT DO
-------------------
Reports whose grammar vibe-ic's own consumers were not measured against
(LibreLane's STA summaries and antenna reports) go under
``reports/phase3/librelane/<flow step>/``, never under a sign-off name: the
kept vibe-ic decks own those (decision 11g). KLayout DRC and Netgen LVS JSON
are the narrow exception: their typed report readers are run at import time,
so a bounded preview cannot enter the canonical tree under a report filename.
The importer judges nothing: a step this flow did not do is listed in
``not_performed`` for the verdict layer (W14).

chip-AGNOSTIC: no design, PDK, corner or cell literal. The top comes from the
run's own ``resolved.json``; corners come from the state, and the nominal SPEF
is the state corner the RCX step's own ``DEFAULT_CORNER`` matches.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _external_flow_manifest as _efm  # noqa: E402
import _path_layout as _pl  # noqa: E402
import _runner_measurement  # noqa: E402
import _tool_log_provenance as _tlp  # noqa: E402
from _atomic_artefact import write_json, write_text  # noqa: E402
from librelane_contract import Refusal, _copy_state_views, _load, digest  # noqa: E402

FLOW = "librelane"
#: W0's import manifest, written only through `_efm.write_manifest`.
MANIFEST_REL = _efm.MANIFEST_REL
RECEIPT_DIR_REL = "reports/phase3/librelane_import"
OPENROAD_LOG_MARK_BEGIN = "# >>> LIBRELANE"
OPENROAD_LOG_MARK_END = "# <<< LIBRELANE"
_PNR_STAGE_MARKER = "PNR_STAGE:"

#: Step class -> the PnR stage marker the log readers already key on. Only
#: classes whose work is the same stage are marked.
_STAGE_OF = {
    "OpenROAD.Floorplan": "floorplan",
    "OpenROAD.GlobalPlacement": "placement",
    "OpenROAD.CTS": "cts",
    "OpenROAD.ResizerTimingPostCTS": "hold_repair",
    "OpenROAD.GlobalRouting": "global_route",
    "OpenROAD.DetailedRouting": "detailed_route",
}

Dest = Callable[[Path, str, str], Path]


@dataclass(frozen=True)
class View:
    """A state view (``def``, ``spef:*``) the step itself wrote."""
    key: str
    dest: Dest            # (project, top, corner-or-"") -> path


@dataclass(frozen=True)
class Files:
    """Files the step wrote in its folder, by glob relative to it."""
    pattern: str
    dest: Dest            # (project, top, path-relative-to-step) -> path


@dataclass(frozen=True)
class Rule:
    flow_step: str
    step: str             # LibreLane step CLASS id
    sources: Tuple[Any, ...]
    after: Optional[str] = None   # take the top-level run after this class's


#: The View key of the nominal SPEF: resolved per run from the RCX step's own
#: ``DEFAULT_CORNER`` (``_nominal_corner``), never from a corner literal.
NOMINAL_SPEF = "spef:<nominal>"


def _ll_reports(step: str) -> Dest:
    return lambda p, top, rel: _pl.reports_phase3_dir(p) / "librelane" / step / rel


def _corner_spef(p: Path, top: str, corner: str) -> Path:
    return _pl.extracted_dir(p) / "spef_corners" / f"{top}.{corner.strip('*_')}.spef"


IMPORT_RULES: Tuple[Rule, ...] = (
    Rule("9", "Yosys.Synthesis", (
        View("nl", lambda p, top, _: _pl.synth_dir(p) / "netlist.v"),
        Files("reports/stat.json", _ll_reports("9")),
        Files("reports/stat.rpt", _ll_reports("9")))),
    Rule("10", "OpenROAD.STAPrePNR", (
        Files("summary.rpt", _ll_reports("10")),
        Files("*/*.rpt", _ll_reports("10")))),
    # Floorplan + PDN: the state after the grid is generated.
    Rule("15", "OpenROAD.GeneratePDN", (
        View("def", lambda p, top, _: _pl.pnr_dir(p) / "floorplan.def"),
        View("odb", lambda p, top, _: _pl.pnr_dir(p) / "librelane_floorplan.odb"))),
    Rule("15.5ic", "OpenROAD.PadRing", (
        View("def", lambda p, top, _: _pl.pnr_dir(p) / "padring.def"),)),
    Rule("17", "OpenROAD.DetailedPlacement", (
        View("def", lambda p, top, _: _pl.pnr_dir(p) / "placed.def"),
        View("odb", lambda p, top, _: _pl.pnr_dir(p) / "librelane_placed.odb"))),
    Rule("19", "OpenROAD.CTS", (
        View("def", lambda p, top, _: _pl.pnr_dir(p) / "post_cts.def"),
        Files("cts.rpt", lambda p, top, _: _pl.cts_dir(p) / "clock_tree.rpt"))),
    Rule("20", "OpenROAD.ResizerTimingPostCTS", (
        View("def", lambda p, top, _: _pl.pnr_dir(p) / "post_hold.def"),
        View("odb", lambda p, top, _: _pl.pnr_dir(p) / "post_hold.odb"))),
    Rule("21", "OpenROAD.DetailedRouting", (
        View("def", lambda p, top, _: _pl.pnr_dir(p) / "routed.def"),
        View("odb", lambda p, top, _: _pl.pnr_dir(p) / "librelane_routed.odb"),
        # the router's own marker report, where the route arm hands it
        # one match only: a second is refused, never picked by name order
        Files("*.drc", lambda p, top, _: _pl.pnr_dir(p) / "routed_router.drc.rpt"))),
    Rule("22", "OpenROAD.RCX", (
        View("spef:*", _corner_spef),
        View(NOMINAL_SPEF, lambda p, top, _: _pl.extracted_dir(p) / f"{top}.spef"))),
    Rule("23", "OpenROAD.STAPostPNR", (
        Files("summary.rpt", _ll_reports("23")),
        Files("*/*.rpt", _ll_reports("23")))),
    # The post-route check: the top-level run after the detailed route (the
    # flow also checks after global routing, and inside RepairAntennas).
    Rule("26", "OpenROAD.CheckAntennas", (
        Files("reports/*.rpt", _ll_reports("26")),),
        after="OpenROAD.DetailedRouting"),
    Rule("31", "Magic.DRC", (Files("reports/*", _ll_reports("31")),)),
    Rule("31", "KLayout.DRC", (Files("reports/*", _ll_reports("31")),)),
    Rule("31", "Netgen.LVS", (Files("reports/*", _ll_reports("31")),)),
    Rule("34", "OpenROAD.FillInsertion", (
        View("def", lambda p, top, _: _pl.pnr_dir(p) / "filled.def"),)),
    Rule("37", "Magic.StreamOut", (
        View("gds", lambda p, top, _: _pl.gds_dir(p) / f"{top}.gds"),
        Files("magic-streamout.log",
              lambda p, top, _: _pl.pnr_dir(p) / "magic_stream_out.log"))),
    Rule("37", "KLayout.StreamOut", (
        View("klayout_gds",
             lambda p, top, _: _pl.pnr_dir(p) / f"{top}.klayout_stream_out.gds"),)),
    Rule("37.5ip", "Magic.WriteLEF", (
        View("lef", lambda p, top, _: _pl.gds_dir(p).parent / "hardmacro" / f"{top}.lef"),)),
)

_INSTANCE_SUFFIX = re.compile(r"-\d+$")
_STARTING = "Starting…"
_FLOW_COMPLETE = "Flow complete."
_SAVING_VIEWS = "Saving views to '"
#: LibreLane's flows/sequential.py: a step not executed in this invocation
#: (outside --from/--to, or --skip), and the gating notice printed before a
#: step whose RUN_* variable is off. steps/checker.py: a checker's deferred
#: error, raised again at the end in place of `Flow complete.`.
_SKIP_STEP_RE = re.compile(r"^Skipping step '(.+)'…$")
_GATING_RE = re.compile(r"^Gating variable for step '([^']+)' set to 'False'")
_DEFERRED_SUFFIX = " - deferred"
#: A segment's declared terminal step: a LibreLane step class id.
_STEP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9]*$")


def _class_of(instance_id: str) -> str:
    return _INSTANCE_SUFFIX.sub("", instance_id)


@dataclass
class Ran:
    """One step the run started, located and cross-checked."""
    instance: str
    step: str             # class id from the folder's own config.json
    rel: str              # folder relative to the run directory
    folder: Path
    pos: int              # position in the flow's own start order
    run_dir: Path

    @property
    def top_level(self) -> bool:
        return "/" not in self.rel

    @property
    def completed(self) -> bool:
        """LibreLane writes state_out.json only after the step's run()."""
        return (self.folder / "state_out.json").is_file()


def flow_status(flow_log: str) -> Dict[str, Any]:
    """How the LAST invocation recorded in a run's flow.log ended.

    flow.log is appended per invocation, each opening with ``Starting…``.
    ``complete`` is True only when ``Flow complete.`` follows that
    invocation's last started step. ``last_started`` is ``(instance id,
    folder)`` of that step, or None; ``invocations`` counts ``Starting…``.
    """
    import instrument_calibration
    instrument_calibration.assert_calibrated("librelane_import::flow_status")
    lines = (flow_log or "").splitlines()
    starts = [i for i, l in enumerate(lines) if l == _STARTING]
    tail = lines[starts[-1] + 1:] if starts else lines
    last: Optional[Tuple[str, str]] = None
    after = 0
    for i, line in enumerate(tail):
        m = _tlp._RUNNING_RE.match(line)
        if m:
            last, after = (m.group(1), m.group(2)), i + 1
    return {"complete": _FLOW_COMPLETE in tail[after:],
            # LibreLane saves the final views only after its step loop ends,
            # before it raises the deferred errors that replace completion.
            "saved_views": any(l.startswith(_SAVING_VIEWS)
                               for l in tail[after:]),
            "last_started": last, "invocations": len(starts)}


def _last_invocation(flow_log: str) -> List[str]:
    lines = (flow_log or "").splitlines()
    starts = [i for i, l in enumerate(lines) if l == _STARTING]
    return lines[starts[-1] + 1:] if starts else lines


def run_cuts(flow_log: str) -> Dict[str, Any]:
    """Which steps the LAST invocation deliberately did not run.

    ``before``: ``Skipping step`` lines before its first started step (the
    ``--from`` signature); ``after``: after its last started step (``--to``);
    ``between``: between two started steps (``--skip``). A skip right after
    its ``Gating variable for step '<id>'`` notice is a RUN_* variable, not a
    cut: its step id goes to ``gated``. ``slots`` keeps each top-level loop
    iteration in order, including gated skips, for adjacent segment checks.
    """
    import instrument_calibration
    instrument_calibration.assert_calibrated("librelane_import::run_cuts")
    tail = _last_invocation(flow_log)
    running = [i for i, l in enumerate(tail) if _tlp._RUNNING_RE.match(l)]
    first = running[0] if running else len(tail)
    last = running[-1] if running else -1
    out: Dict[str, Any] = {"before": [], "between": [], "after": [],
                           "gated": [], "slots": []}
    for i, line in enumerate(tail):
        started = _tlp._RUNNING_RE.match(line)
        if started:
            parts = Path(started.group(2)).parts
            # Nested STA/corner runs have more folders after runs/<tag>.
            if "runs" in parts and len(parts) - 1 - parts.index("runs") == 2:
                out["slots"].append(("running", started.group(1)))
            continue
        g = _GATING_RE.match(line)
        if g:
            out["gated"].append(g.group(1))
            continue
        m = _SKIP_STEP_RE.match(line)
        if not m:
            continue
        out["slots"].append(("skipped", m.group(1)))
        if i and _GATING_RE.match(tail[i - 1]):
            continue
        key = "before" if i < first else "after" if i > last else "between"
        out[key].append(m.group(1))
    return out


def deferred_errors(flow_log: str) -> List[Tuple[str, str, str]]:
    """``(instance id, folder, message)`` for every deferred error the LAST
    invocation logged, each in the block of the step that raised it."""
    import instrument_calibration
    instrument_calibration.assert_calibrated("librelane_import::deferred_errors")
    out: List[Tuple[str, str, str]] = []
    cur: Optional[Tuple[str, str]] = None
    for line in _last_invocation(flow_log):
        m = _tlp._RUNNING_RE.match(line)
        if m:
            cur = (m.group(1), m.group(2))
        elif line.endswith(_DEFERRED_SUFFIX) and cur is not None:
            out.append((cur[0], cur[1], line[:-len(_DEFERRED_SUFFIX)]))
    return out


def run_index(run_dir: Path) -> List[Ran]:
    """Every step the run's own flow.log started, in order, cross-checked
    against the folder's config.json. Refuses on any disagreement."""
    flow_log = run_dir / "flow.log"
    if not flow_log.is_file():
        raise Refusal("LL_IMPORT_NO_FLOW_LOG", str(flow_log))
    started = _tlp.flow_log_steps(flow_log.read_text(errors="replace"))
    if not started:
        raise Refusal("LL_IMPORT_NO_STEPS", f"{flow_log} names no started step")
    out: List[Ran] = []
    for i, (instance, parts) in enumerate(started):
        if run_dir.name not in parts:
            raise Refusal("LL_IMPORT_FOREIGN_STEP",
                          f"{instance} ran at {'/'.join(parts)}, outside "
                          f"the run {run_dir.name}")
        k = len(parts) - 1 - parts[::-1].index(run_dir.name)
        rel = "/".join(parts[k + 1:])
        folder = run_dir / rel
        config = folder / "config.json"
        if not rel or not config.is_file():
            raise Refusal("LL_IMPORT_STEP_FOLDER_MISSING",
                          f"{instance}: {folder}")
        recorded = (_load(config).get("meta") or {}).get("step")
        if recorded != _class_of(instance):
            raise Refusal("LL_IMPORT_STEP_MISMATCH",
                          f"flow.log started {instance} in {rel}, whose "
                          f"config.json names {recorded!r}")
        out.append(Ran(instance, recorded, rel, folder, i, run_dir))
    return out


def _require_finished(run_dir: Path, index: List[Ran],
                      to: Optional[str]) -> Dict[str, Any]:
    """The segment's flow status, or a named refusal citing the tool's logs."""
    text = (run_dir / "flow.log").read_text(errors="replace")
    status = flow_status(text)
    last = index[-1]
    tops = [r for r in index if r.top_level]
    if not status["complete"] and status["saved_views"]:
        # The step loop ended (the final views were saved) and LibreLane
        # still withheld `Flow complete.`: a checker's deferred error, raised
        # at the end. Blame THAT step, not the last one that ran.
        errs = deferred_errors(text)
        where = "; ".join(f"{sid} at {_rel_to_run(run_dir, d)}: {msg}"
                          for sid, d, msg in errs) or (
            "flow.log names no deferred error (see LibreLane's console)")
        raise Refusal(
            "LL_IMPORT_FLOW_INCOMPLETE",
            f"{run_dir}: every step returned, but LibreLane withheld "
            f"'{_FLOW_COMPLETE}': {where}. A FAIL, never a partial import")
    if not status["complete"]:
        block = _tlp.step_block(text, last.instance, last.rel) or {}
        logs = ["/".join(p) for p in block.get("subprocess_logs", [])] or \
            [l.relative_to(run_dir).as_posix() for l in _step_logs(last.folder)]
        finished = ("it wrote its state_out.json" if last.completed
                    else "it never wrote its state_out.json")
        raise Refusal(
            "LL_IMPORT_FLOW_INCOMPLETE",
            f"{run_dir}/flow.log has no '{_FLOW_COMPLETE}' after its last "
            f"started step {last.instance} at {last.rel} ({finished}); the "
            f"tool's own log: {', '.join(logs) or 'none on disk'}. LibreLane "
            "did not finish this run: a FAIL, never a partial import")
    cuts = run_cuts(text)
    if cuts["between"]:
        raise Refusal(
            "LL_IMPORT_STEPS_SKIPPED",
            f"{run_dir} ran with steps skipped (--skip): "
            f"{', '.join(cuts['between'])}. Their outputs would read as steps "
            "the flow does not perform")
    if to is None and cuts["after"]:
        raise Refusal(
            "LL_IMPORT_RUN_CUT_SHORT",
            f"{run_dir} stopped after {tops[-1].instance if tops else None} "
            f"and skipped {len(cuts['after'])} later step(s) (first: "
            f"{cuts['after'][0]}) — the --to signature; declare it "
            "(RUN_DIR=<StepClass>) and import it with the segment that "
            "continues it")
    if to is not None:
        end = tops[-1] if tops else None
        if end is None or end.step != to or not end.completed:
            raise Refusal(
                "LL_IMPORT_SEGMENT_END_MISMATCH",
                f"{run_dir} was declared to run --to {to}, but its last "
                f"top-level step is {end.instance if end else None}"
                + ("" if end is None or end.completed else " (unfinished)"))
    return {"complete": True, "evidence": _FLOW_COMPLETE,
            "last_started": last.instance,
            "last_top_level": tops[-1].instance if tops else None,
            "to": to, "invocations": status["invocations"],
            "from_cut": bool(cuts["before"]), "to_cut": bool(cuts["after"]),
            "gated": cuts["gated"]}


def _rel_to_run(run_dir: Path, printed: str) -> str:
    """A folder as LibreLane printed it (``runs/<tag>/<dir>``), run-relative."""
    parts = Path(printed).parts
    if run_dir.name in parts:
        k = len(parts) - 1 - parts[::-1].index(run_dir.name)
        return "/".join(parts[k + 1:]) or printed
    return printed


def _select(index: List[Ran], rule: Rule) -> Tuple[Optional[Ran], str]:
    """The one top-level run a rule imports, or ``(None, why none)``."""
    runs = [r for r in index if r.step == rule.step]
    if not runs:
        return None, f"the run's own flow.log never started {rule.step}"
    cand = [r for r in runs if r.top_level]
    if not cand:
        return None, (f"{rule.step} ran only nested inside a composite step "
                      f"({', '.join(r.rel for r in runs)}), never as a stage")
    if rule.after:
        anchors = [r.pos for r in index if r.step == rule.after and r.top_level]
        if not anchors:
            return None, (f"the run never ran {rule.after}, so no {rule.step} "
                          "follows it")
        cand = [r for r in cand if r.pos > anchors[-1]]
        if not cand:
            return None, f"no top-level {rule.step} ran after {rule.after}"
    if len(cand) > 1:
        raise Refusal("LL_IMPORT_AMBIGUOUS_STEP",
                      f"flow step {rule.flow_step}: {len(cand)} top-level runs "
                      f"of {rule.step} ({', '.join(r.rel for r in cand)}); "
                      "the import never picks one by position")
    return cand[0], ""


def _duration_ms(folder: Path) -> Optional[int]:
    rt = folder / "runtime.txt"
    try:
        h, m, s = rt.read_text().strip().split(":")
        return int(round((int(h) * 3600 + int(m) * 60 + float(s)) * 1000))
    except (OSError, ValueError):
        return None


def _validate_imported_report(path: Path) -> None:
    """Refuse bounded previews at the two typed DRC/LVS report boundaries.

    The importer copies tool bytes, but these two filenames are read by
    downstream verdict consumers as complete machine reports.  A 4096-byte
    presentation preview therefore cannot be allowed to masquerade as a
    report merely because it has a ``.json`` suffix.  The check is deliberately
    limited to the producer-owned report names; all other LibreLane payloads
    remain opaque copies as before.
    """
    if path.name not in {"drc.klayout.json", "lvs.netgen.json"}:
        return
    try:
        if path.name == "drc.klayout.json":
            report = json.loads(path.read_text(encoding="utf-8"))
            complete = (isinstance(report, dict) and
                        isinstance(report.get("total"), int) and
                        not isinstance(report.get("total"), bool) and
                        report.get("total", -1) >= 0 and
                        all(isinstance(value, int) and
                            not isinstance(value, bool) and value >= 0
                            for value in report.values()))
        else:
            # Use the same structural E1 reader as the LVS verdict consumer;
            # an unreadable or non-E1 object is absent, never a pass.
            import lvs_verdict_tokens as _lvs_verdict_tokens
            complete = _lvs_verdict_tokens.load_json_report(path) is not None
    except (OSError, UnicodeError, ValueError, TypeError):
        complete = False
    if not complete:
        raise Refusal(
            "LL_IMPORT_REPORT_INCOMPLETE",
            f"{path}: bounded preview or incomplete typed report; "
            "complete producer JSON is required")


def _copy(src: Path, dst: Path) -> None:
    """Copy bytes; a symlink at the destination is replaced, never followed."""
    if src.is_symlink():
        raise Refusal("LL_IMPORT_SOURCE_SYMLINK", str(src))
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".import.tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    if digest(src) != digest(dst):
        raise Refusal("LL_IMPORT_COPY_MISMATCH", f"{src} -> {dst}")


def _recorded_root(value: str, rel: str) -> Optional[str]:
    marker = "/" + rel.strip("/") + "/"
    return value[:value.index(marker)] if marker in value else None


def _nominal_corner(ran: Ran, corners: List[str]) -> str:
    """The state's SPEF corner key the step's own DEFAULT_CORNER matches."""
    default = _load(ran.folder / "config.json").get("DEFAULT_CORNER")
    if not isinstance(default, str) or not default:
        raise Refusal("LL_IMPORT_NO_NOMINAL_CORNER",
                      f"{ran.instance}: config.json states no DEFAULT_CORNER")
    hits = [c for c in corners if fnmatch.fnmatchcase(default, c)]
    if len(hits) != 1:
        raise Refusal("LL_IMPORT_NO_NOMINAL_CORNER",
                      f"{ran.instance}: DEFAULT_CORNER {default} matches "
                      f"{hits or 'none'} of the state's corners {corners}")
    return hits[0]


def _state_views(state: Dict[str, Any], key: str,
                 ran: Ran) -> List[Tuple[str, str]]:
    """``(view, corner)`` pairs a View source names; ``spef:*`` expands."""
    base, _, corner = key.partition(":")
    value = state.get(base)
    if not corner:
        return [(base, "")] if isinstance(value, str) and value else []
    if not isinstance(value, dict):
        return []
    if key == NOMINAL_SPEF:
        c = _nominal_corner(ran, sorted(value))
        return [(f"{base}:{c}", c)]
    if corner == "*":
        return [(f"{base}:{c}", c) for c in sorted(value)]
    return [(key, corner)] if corner in value else []


def _step_logs(folder: Path) -> List[Path]:
    """The tool transcripts the step itself wrote (its folder and corner
    subfolders), excluding nested sub-steps, which have their own config."""
    logs = []
    for p in sorted(folder.rglob("*.log")):
        parent = p.parent
        nested = False
        while parent != folder:
            if (parent / "config.json").is_file():
                nested = True
                break
            parent = parent.parent
        if not nested and p.is_file() and not p.is_symlink():
            logs.append(p)
    return logs


def _source_logs(ran: Ran, tool_file: Path, cited: List[str]) -> List[Path]:
    """The transcripts of the process that wrote ``tool_file``: the logs in
    the file's own directory (a corner subfolder has its own), else the
    step's main log, which LibreLane names after the step folder. Only logs
    the step's witness cites (``cited``, run-relative) are named; a
    back-fill cites none, so it names none."""
    logs = [l for l in _step_logs(ran.folder)
            if l.relative_to(ran.run_dir).as_posix() in cited
            and l != tool_file]      # a file never witnesses its own run
    here = [l for l in logs if l.parent == tool_file.parent]
    if here:
        return here
    slug = re.sub(r"^\d+-", "", ran.folder.name) + ".log"
    main = [l for l in logs if l.parent == ran.folder and l.name == slug]
    if main:
        return main
    top = [l for l in logs if l.parent == ran.folder]
    return top if len(top) == 1 else []


def _file_row(project: Path, ran: Ran, tool_file: Path, dest: Path,
              cited: List[str], view: Optional[str] = None) -> Dict[str, Any]:
    """One manifest row, in the final field names of the W0 import-manifest
    schema (``vibe-ic/external-flow-import/2``, lane llf) and with W0's
    meaning: ``tool_run_path``, ``step_dir`` and ``source_logs`` are relative
    to the row's ``run_dir``, itself project-relative. ``measurement`` is the
    artefact-derived record, or None when nothing can be stated about this
    file — never a guessed one. The flow step and ``exit_code`` are filled
    in by the caller."""
    rel = dest.relative_to(project).as_posix()
    row: Dict[str, Any] = {
        "canonical_path": rel,
        "tool_run_path": tool_file.relative_to(ran.run_dir).as_posix(),
        "canonical_sha256": "sha256:" + digest(dest),
        "tool_run_sha256": "sha256:" + digest(tool_file),
        "flow": FLOW,
        "tool": _tlp.underlying_tool(ran.instance),
        "tool_step_id": ran.instance,
        "step_dir": ran.rel,
        "source_logs": [{"path": l.relative_to(ran.run_dir).as_posix(),
                         "sha256": "sha256:" + digest(l)}
                        for l in _source_logs(ran, tool_file, cited)],
        # W0's rule: the one measurement a row may carry is the record read
        # from the imported artefact itself, or null.
        "measurement": _efm.derived_measurement(
            project, rel, _tlp.underlying_tool(ran.instance) or ""),
    }
    if view:
        row["view"] = view
    return row


@dataclass
class _ViewCall:
    """One state-view copy, validated before anything is written."""
    state_path: Path
    targets: Dict[str, Path]
    receipt: Path
    path_map: Dict[str, str]
    sources: Dict[str, Path]      # view -> the step's file it resolves to


@dataclass
class _StepPlan:
    rule: Rule
    ran: Ran
    views: List[_ViewCall]
    files: List[Tuple[Path, Path]]            # (tool file, canonical dest)
    files_receipt: Optional[Path]

    def dests(self) -> List[Tuple[Path, Path]]:
        """Every (canonical dest, tool file) this step writes."""
        out = [(d, c.sources[v]) for c in self.views
               for v, d in c.targets.items()]
        return out + [(d, s) for s, d in self.files]

    def receipts(self) -> List[Path]:
        return [c.receipt for c in self.views] + \
            ([self.files_receipt] if self.files_receipt else [])


def _plan_step(project: Path, ran: Ran, rule: Rule, top: str,
               receipts: Path) -> _StepPlan:
    """Resolve every source of one rule, raising every refusal it can meet;
    writes nothing."""
    run_dir = ran.run_dir
    state_path = ran.folder / "state_out.json"
    state = _load(state_path) if state_path.is_file() else {}
    receipt = receipts / f"{rule.flow_step}_{ran.instance}.json"
    plan = _StepPlan(rule, ran, [], [], None)
    for src in rule.sources:
        if isinstance(src, View):
            pairs = _state_views(state, src.key, ran)
            if not pairs:
                raise Refusal("LL_IMPORT_VIEW_MISSING",
                              f"{ran.instance} state has no {src.key}")
            targets: Dict[str, Path] = {}
            sources: Dict[str, Path] = {}
            path_map: Dict[str, str] = {}
            for view, corner in pairs:
                base, _, c = view.partition(":")
                value = state[base][c] if c else state[base]
                root = _recorded_root(value, f"{run_dir.name}/{ran.rel}")
                if root is None:
                    raise Refusal("LL_IMPORT_VIEW_NOT_OWN",
                                  f"{ran.instance} {view} = {value}: written by "
                                  "another step, not by this one")
                guest = root + "/" + run_dir.name
                path_map[guest] = str(run_dir)
                source = Path(str(run_dir) + value[len(guest):])
                if not source.is_file():
                    raise Refusal("LL_IMPORT_VIEW_MISSING",
                                  f"{ran.instance} {view}: {source}")
                if source.is_symlink():
                    raise Refusal("LL_IMPORT_SOURCE_SYMLINK", str(source))
                targets[view] = src.dest(project, top, corner)
                sources[view] = source.resolve()
            if len(set(path_map)) != 1:
                raise Refusal("LL_IMPORT_VIEW_ROOTS", f"{ran.instance}: {path_map}")
            slug = src.key.replace(":", "_").replace("*", "all") \
                .replace("<", "").replace(">", "")
            plan.views.append(_ViewCall(
                state_path, targets,
                receipt.with_name(f"{receipt.stem}_{slug}.json"),
                path_map, sources))
        else:
            found = sorted(p for p in ran.folder.glob(src.pattern) if p.is_file())
            if not found:
                raise Refusal("LL_IMPORT_FILE_MISSING",
                              f"{ran.instance}: no {src.pattern} in {ran.rel}")
            for path in found:
                if path.is_symlink():
                    raise Refusal("LL_IMPORT_SOURCE_SYMLINK", str(path))
                _validate_imported_report(path)
                rel = path.relative_to(ran.folder).as_posix()
                plan.files.append((path, src.dest(project, top, rel)))
    if plan.files:
        plan.files_receipt = receipt.with_name(f"{receipt.stem}_files.json")
    return plan


class _Journal:
    """Every path the import writes, with what it held before, so a failure
    after the first write restores the project exactly."""

    def __init__(self, project: Path):
        self.root = Path(tempfile.mkdtemp(prefix=".librelane_import.",
                                          dir=project))
        self.saved: Dict[Path, Optional[Path]] = {}

    def touch(self, path: Path) -> None:
        path = Path(path)
        if path in self.saved:
            return
        if path.exists() or path.is_symlink():
            keep = self.root / str(len(self.saved))
            if path.is_symlink():
                os.symlink(os.readlink(path), keep)
            else:
                shutil.copy2(path, keep)
            self.saved[path] = keep
        else:
            self.saved[path] = None

    def remove(self, path: Path) -> None:
        self.touch(path)
        if path.exists() or path.is_symlink():
            path.unlink()

    def rollback(self) -> None:
        for path, keep in self.saved.items():
            if path.exists() or path.is_symlink():
                path.unlink()
            if keep is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(keep, path)
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _provenance_row(project: Path, ran: Ran,
                    outputs: Dict[str, Path]) -> Dict[str, Any]:
    """``outputs`` maps each canonical path to the file the step wrote."""
    try:
        row = _tlp.witnessed_row(
            project, flow=FLOW, step_id=ran.instance, run_dir=ran.run_dir,
            step_dir=ran.rel, outputs=outputs,
            duration_ms=_duration_ms(ran.folder))
    except _tlp.WitnessRefused as exc:
        # #365: what the runner could not see being written is a back-fill.
        row = {"tool": _tlp.underlying_tool(ran.instance) or FLOW,
               "command": f"librelane step {ran.instance}", "exit_code": 0,
               "duration_ms": None, "reconstructed": True,
               "timestamp": _dt.datetime.now(_dt.timezone.utc)
               .strftime("%Y-%m-%dT%H:%M:%SZ"),
               "outputs": {rel: "sha256:" + digest(project / rel)
                           for rel in outputs},
               "note": f"imported, not witnessed: {exc}"}
    return _runner_measurement.attach(project, row)


def _pnr_span(index: List[Ran]) -> List[Ran]:
    """The OpenROAD steps of the place-and-route session, in flow order.

    vibe-ic's ``openroad.log`` is the PnR session transcript (floorplan through
    routing), so the span runs from the first ``OpenROAD.Floorplan`` up to the
    first ``OpenROAD.RCX`` after it. The STA steps inside it are separate
    OpenSTA sessions with their own reports, and stay out of the transcript.
    """
    ids = [r.step for r in index]
    if "OpenROAD.Floorplan" not in ids:
        return []
    start = ids.index("OpenROAD.Floorplan")
    stop = next((i for i in range(start, len(ids)) if ids[i] == "OpenROAD.RCX"),
                len(ids))
    return [r for r in index[start:stop]
            if _tlp.underlying_tool(r.instance) == "openroad"
            and not r.step.startswith("OpenROAD.STA")]


def assemble_openroad_log(project: Path, index: List[Ran], dest: Path,
                          journal: Optional[_Journal] = None
                          ) -> Optional[Dict[str, Any]]:
    """The PnR-span step transcripts in flow order, each bracketed by a marker
    that names its source log and sha256."""
    parts: List[str] = []
    cited: List[Dict[str, str]] = []
    for ran in _pnr_span(index):
        stage = _STAGE_OF.get(ran.step)
        logs = _step_logs(ran.folder)
        if stage and logs:
            parts.append(f"{_PNR_STAGE_MARKER} {stage}\n")
        for log in logs:
            rel, sha = log.relative_to(project).as_posix(), "sha256:" + digest(log)
            text = log.read_text(errors="replace")
            parts.append(f"{OPENROAD_LOG_MARK_BEGIN} {ran.instance} {rel} {sha}\n")
            parts.append(text if text.endswith("\n") else text + "\n")
            parts.append(f"{OPENROAD_LOG_MARK_END} {ran.instance}\n")
            cited.append({"path": rel, "sha256": sha})
    if not cited:
        return None
    if journal is not None:
        journal.touch(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()
    write_text(dest, "".join(parts))
    return {"path": dest.relative_to(project).as_posix(),
            "sha256": "sha256:" + digest(dest),
            "sources": cited}


def _previous_import(project: Path) -> Optional[Dict[str, Any]]:
    path = project / MANIFEST_REL
    if not path.is_file():
        return None
    try:
        doc = _load(path)
    except (OSError, ValueError) as exc:
        raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE", f"{path}: {exc}")
    # Its canonical paths decide what this import deletes: W0 validates the
    # rows, then this importer protects its own records and EVERY segment's
    # run tree. The stale-file digest is checked below before any deletion.
    problems = _efm.validate_manifest(doc, project, verify_disk=False)
    if problems:
        raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                      f"{path} does not validate: {'; '.join(problems)}")
    all_runs = [Path(s["run_dir"]) for s in _efm.segments_of(doc)]
    protected = (Path("provenance.jsonl"), Path(MANIFEST_REL),
                 Path(RECEIPT_DIR_REL))
    for seg in _efm.segments_of(doc):
        for row in seg.get("rows") or []:
            dest = Path(row["canonical_path"])
            if any(dest == p or dest.is_relative_to(p) for p in protected) or \
                    any(dest == p or dest.is_relative_to(p) for p in all_runs):
                raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                              f"{path} claims importer-owned or run-tree "
                              f"canonical path {dest}; it cannot decide a "
                              "deletion")
    return doc


def _check_previous_ownership(project: Path, previous: Dict[str, Any]) -> None:
    """Authenticate old deletion candidates against this importer's rules.

    W0's manifest validator checks row shape without disk verification here:
    stale canonical files may legitimately be missing. Reconstruct the old
    rule's destinations from its recorded run and top, and independently hash
    the tool file. A matching canonical hash alone proves no ownership.
    """
    planned: Dict[Tuple[str, str, str, str], List[Tuple[Path, Path, Optional[str]]]] = {}
    for seg in _efm.segments_of(previous):
        run_dir = project / seg["run_dir"]
        status = seg.get("flow_status") or {}
        top = status.get("design_name")
        if not isinstance(top, str) or not top:
            raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                          f"{project / MANIFEST_REL}: previous segment "
                          f"{seg['run_dir']} has no recorded design name")
        for row in seg.get("rows") or []:
            rule = next((r for r in IMPORT_RULES
                         if r.flow_step == row["step_id"]
                         and r.step == _class_of(row["tool_step_id"])), None)
            rel = Path(row["step_dir"])
            source = run_dir / row["tool_run_path"]
            key = (seg["run_dir"], row["step_dir"], row["step_id"], top)
            if rule is None or len(rel.parts) != 1 or source.is_symlink() \
                    or not source.is_file():
                raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                              f"{project / MANIFEST_REL}: previous row "
                              f"{row['canonical_path']} has no owned tool source")
            config = run_dir / rel / "config.json"
            try:
                recorded = (_load(config).get("meta") or {}).get("step")
            except (OSError, ValueError, AttributeError):
                recorded = None
            if recorded != rule.step:
                raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                              f"{project / MANIFEST_REL}: previous row "
                              f"{row['canonical_path']} has no matching step")
            if "sha256:" + digest(source) != row["tool_run_sha256"]:
                raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                              f"{project / MANIFEST_REL}: previous row "
                              f"{row['canonical_path']} does not hash to its "
                              "tool-run source")
            if key not in planned:
                ran = Ran(row["tool_step_id"], rule.step, row["step_dir"],
                          run_dir / rel, 0, run_dir)
                try:
                    plan = _plan_step(project, ran, rule, top,
                                      project / RECEIPT_DIR_REL)
                except (Refusal, OSError, ValueError) as exc:
                    raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                                  f"{project / MANIFEST_REL}: cannot reconstruct "
                                  f"previous row {row['canonical_path']}: {exc}") from exc
                planned[key] = [(dest, call.sources[view], view)
                                for call in plan.views
                                for view, dest in call.targets.items()]
                planned[key] += [(dest, src, None) for src, dest in plan.files]
            dest = project / row["canonical_path"]
            if not any(dest == expected_dest and source.resolve() == expected_source
                       and row.get("view") == view
                       for expected_dest, expected_source, view in planned[key]):
                raise Refusal("LL_IMPORT_MANIFEST_UNREADABLE",
                              f"{project / MANIFEST_REL}: previous row "
                              f"{row['canonical_path']} is not a destination "
                              f"this importer produces from {row['tool_run_path']}")


def _fixed_dests(rule: Rule, project: Path, top: str) -> List[Path]:
    """The canonical paths a rule writes whatever the run holds (a View's
    dest that does not depend on the corner)."""
    out = []
    for src in rule.sources:
        if isinstance(src, View) and src.key.partition(":")[2] in ("", NOMINAL_SPEF[5:]):
            out.append(src.dest(project, top, ""))
    return out


def import_segments(project: Path,
                    segments: List[Tuple[Path, Optional[str]]]) -> Dict[str, Any]:
    """Import the ordered segment runs (each inside ``project``) as one tree.

    Each segment is ``(run_dir, to)``, ``to`` being the step class the run
    was declared to stop at (``--to``), or None for a run to the flow's end.
    Nothing is written unless every rule plans cleanly; see the module
    docstring.
    """
    project = Path(project).resolve()
    if not segments:
        raise Refusal("LL_IMPORT_NO_SEGMENTS", "no run to import")
    segs: List[Tuple[Path, Optional[str]]] = []
    top_of: Dict[Path, str] = {}
    for run_dir, to in segments:
        run_dir = Path(run_dir).resolve()
        try:
            run_dir.relative_to(project)
        except ValueError:
            raise Refusal("LL_IMPORT_RUN_OUTSIDE_PROJECT", str(run_dir))
        if to is not None and not _STEP_ID.match(to):
            raise Refusal("LL_IMPORT_BAD_SEGMENT_END", repr(to))
        resolved = run_dir / "resolved.json"
        name = _load(resolved).get("DESIGN_NAME") if resolved.is_file() else None
        if not isinstance(name, str) or not name:
            raise Refusal("LL_IMPORT_NO_DESIGN_NAME", str(resolved))
        # Segments may name different tops: on the Chip flow segment 1
        # synthesizes the core and segment 2 lays out the chip top (plan W5,
        # D7). Each rule names its destinations by ITS segment's top.
        top_of[run_dir] = name
        segs.append((run_dir, to))
    if len({r for r, _ in segs}) != len(segs):
        raise Refusal("LL_IMPORT_SEGMENT_REPEATED", str([str(r) for r, _ in segs]))
    #: the layout's top: the last segment's (for rules no segment performed)
    top = top_of[segs[-1][0]]
    run_rels = [r.relative_to(project).as_posix() for r, _ in segs]

    # ── plan: every refusal is raised here, before anything is written ──
    manifest: Dict[str, Any] = {"not_performed": [], "removed": []}
    segments: List[Dict[str, Any]] = []
    seg_of: Dict[Path, Dict[str, Any]] = {}
    indexes: List[List[Ran]] = []
    loops: List[List[Tuple[str, str]]] = []
    for i, (run_dir, to) in enumerate(segs):
        index = run_index(run_dir)
        status = _require_finished(run_dir, index, to)
        status["flow_log_sha256"] = "sha256:" + digest(run_dir / "flow.log")
        status["design_name"] = top_of[run_dir]
        loops.append(run_cuts((run_dir / "flow.log").read_text(errors="replace"))
                     ["slots"])
        if i == 0 and status["from_cut"]:
            raise Refusal(
                "LL_IMPORT_STARTS_MID_FLOW",
                f"{run_dir} began mid-flow (--from): the steps before it are "
                "in no segment of this import. Import it after the segment "
                "that ran them")
        if i == len(segs) - 1 and (to is not None or status["to_cut"]):
            raise Refusal(
                "LL_IMPORT_ENDS_AT_TO",
                f"the import's last segment {run_dir} stopped at --to "
                f"{to or status['last_top_level']}: the steps after it are in "
                "no segment of this import, and would read as steps the flow "
                "does not perform. Import it together with the segment that "
                "continues it")
        indexes.append(index)
        segments.append({"name": f"segment-{i + 1}",
                         "run_dir": run_dir.relative_to(project).as_posix(),
                         "flow_status": status, "rows": []})
        seg_of[run_dir] = segments[-1]
    for i in range(len(loops) - 1):
        earlier, later = loops[i], loops[i + 1]
        if not any(kind == "running" for kind, _ in earlier) or not any(
                kind == "running" for kind, _ in later):
            raise Refusal(
                "LL_IMPORT_LOOP_UNVERIFIED",
                f"the top-level loop slots of {segs[i][0]} and "
                f"{segs[i + 1][0]} cannot be read from their flow.logs")
        last = max(j for j, (kind, _) in enumerate(earlier)
                   if kind == "running")
        first = next(j for j, (kind, _) in enumerate(later)
                     if kind == "running")
        if first < last + 1:
            raise Refusal(
                "LL_IMPORT_SEGMENT_OVERLAP",
                f"{segs[i][0]} ends at loop slot {last}, but {segs[i + 1][0]} "
                f"starts at slot {first}; their top-level runs overlap")
        if first > last + 1:
            missed = [name for kind, name in later[last + 1:first]]
            raise Refusal(
                "LL_IMPORT_SEGMENT_GAP",
                f"{segs[i][0]} ends at loop slot {last}, but {segs[i + 1][0]} "
                f"starts at slot {first}: {first - last - 1} step(s) between "
                f"segments were skipped by both: {missed}")
    previous = _previous_import(project)
    if previous is not None:
        before = [s.get("run_dir") for s in _efm.segments_of(previous)]
        if before != run_rels:
            raise Refusal("LL_IMPORT_OTHER_RUN_PRESENT",
                          f"{project / MANIFEST_REL} already records an import "
                          f"of {before}; importing {run_rels} over it would "
                          "leave files of both. A different run needs a fresh "
                          "project")
        _check_previous_ownership(project, previous)
    receipts = project / RECEIPT_DIR_REL
    plans: List[_StepPlan] = []
    for rule in IMPORT_RULES:
        chosen = []
        why: List[str] = []
        for index in indexes:
            ran, reason = _select(index, rule)
            if ran is not None:
                chosen.append(ran)
            else:
                why.append(reason)
        if len(chosen) > 1:
            raise Refusal("LL_IMPORT_SEGMENT_OVERLAP",
                          f"flow step {rule.flow_step} ({rule.step}) ran in "
                          f"{len(chosen)} segments: "
                          f"{', '.join(r.run_dir.name + '/' + r.rel for r in chosen)}")
        if not chosen:
            gated = [s["run_dir"] for s in segments
                     if rule.step in s["flow_status"]["gated"]]
            if gated:
                raise Refusal(
                    "LL_IMPORT_RULE_STEP_GATED",
                    f"flow step {rule.flow_step}: {rule.step} was gated off by "
                    f"its RUN_* variable in {gated}; the flow performs it, this "
                    "run's config turned it off")
            manifest["not_performed"].append({
                "flow_step": rule.flow_step, "tool_step": rule.step,
                "reason": "; ".join(dict.fromkeys(why)),
                "flow_complete": True})
            continue
        ran = chosen[0]
        if not ran.completed:
            raise Refusal("LL_IMPORT_STEP_NOT_COMPLETED",
                          f"{ran.instance} at {ran.rel} wrote no state_out.json")
        plans.append(_plan_step(project, ran, rule, top_of[ran.run_dir],
                                receipts))
    writes: Dict[Path, Path] = {}
    for plan in plans:
        for dest, src in plan.dests():
            if dest in writes and writes[dest] != src:
                raise Refusal("LL_IMPORT_AMBIGUOUS_SOURCE",
                              f"{dest.relative_to(project)} would be written "
                              f"from both {writes[dest]} and {src}")
            writes[dest] = src
    stale_rows = {project / r["canonical_path"]: r
                  for seg in (_efm.segments_of(previous) if previous else [])
                  for r in seg.get("rows") or []
                  if isinstance(r, dict) and r.get("canonical_path")
                  and project / r["canonical_path"] not in writes}
    stale = sorted(path for path in stale_rows
                   if path.exists() or path.is_symlink())
    for path in stale:
        row = stale_rows[path]
        if (path.is_symlink() or not path.is_file() or
                "sha256:" + digest(path) != row["canonical_sha256"]):
            raise Refusal(
                "LL_IMPORT_STALE_CANONICAL",
                f"{path} is no longer the file this import recorded "
                f"({row['canonical_sha256']}); leave it untouched")
    for entry in manifest["not_performed"]:
        rule = next(r for r in IMPORT_RULES if r.step == entry["tool_step"]
                    and r.flow_step == entry["flow_step"])
        left = [d for d in _fixed_dests(rule, project, top)
                if (d.exists() or d.is_symlink()) and d not in stale
                and d not in writes]
        if left:
            raise Refusal("LL_IMPORT_STALE_CANONICAL",
                          f"flow step {rule.flow_step} was not performed by "
                          f"these runs, yet {[str(d.relative_to(project)) for d in left]} "
                          "exists and no earlier import of these runs "
                          "accounts for it")

    # ── write, under a journal ──
    journal = _Journal(project)
    try:
        for path in stale:
            journal.remove(path)
            manifest["removed"].append(path.relative_to(project).as_posix())
        prov: List[Dict[str, Any]] = []
        for plan in plans:
            for dest in [d for d, _ in plan.dests()] + plan.receipts():
                journal.touch(dest)
            outputs: Dict[str, Path] = {}
            written: List[Tuple[Path, Path, Optional[str]]] = []
            for call in plan.views:
                # Native Classic runs do not carry run_chain's RCX receipt.
                # Planning above binds the native flow, step and mapped source;
                # this transfer records copied bytes, not an RCX measurement.
                doc = _copy_state_views(call.state_path, call.targets,
                                        path_map=call.path_map)
                write_json(call.receipt, doc)
                for view, row in doc["views"].items():
                    dest = Path(row["dest"])
                    source = Path(row["source"]).resolve()
                    outputs[dest.relative_to(project).as_posix()] = source
                    written.append((source, dest, view))
            for path, dest in plan.files:
                _copy(path, dest)
                outputs[dest.relative_to(project).as_posix()] = path
                written.append((path, dest, None))
            row = _provenance_row(project, plan.ran, outputs)
            cited = [l["path"] for l in (row.get("witness") or {}).get("logs", [])]
            rows = [_file_row(project, plan.ran, src, dest, cited, view=view)
                    for src, dest, view in written]
            files = [r for r in rows if "view" not in r]
            if plan.files_receipt is not None:
                write_json(plan.files_receipt,
                           {"step": plan.ran.instance, "folder": plan.ran.rel,
                            "run_dir": plan.ran.run_dir.relative_to(project)
                            .as_posix(), "files": files})
            prov.append(row)
            kind = ("witnessed" if row.get("reconstructed") is False
                    else "reconstructed")
            for r in rows:
                r.update({"step_id": plan.rule.flow_step,
                          "exit_code": row["exit_code"],
                          "timestamp": row["timestamp"], "provenance": kind})
                seg_of[plan.ran.run_dir]["rows"].append(r)
        log = assemble_openroad_log(project, [r for ix in indexes for r in ix],
                                    _pl.pnr_dir(project) / "openroad.log",
                                    journal)
        if log is not None:
            manifest["openroad_log"] = log
            prov.append(_runner_measurement.attach(project, {
                "tool": "openroad",
                "command": "librelane_import.assemble_openroad_log",
                "exit_code": 0, "duration_ms": None, "reconstructed": True,
                "timestamp": _dt.datetime.now(_dt.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outputs": {log["path"]: log["sha256"]},
                "note": "assembled from LibreLane step logs; every section's "
                        "marker cites its source log and sha256"}))
        journal.touch(project / "provenance.jsonl")
        journal.touch(project / MANIFEST_REL)
        with (project / "provenance.jsonl").open("a") as fh:
            for row in prov:
                fh.write(json.dumps(row) + "\n")
        extra = {"top": top, "removed": manifest["removed"]}
        if len(set(top_of.values())) > 1:
            extra["tops"] = [top_of[r] for r, _ in segs]
        if "openroad_log" in manifest:
            extra["openroad_log"] = manifest["openroad_log"]
        try:
            if len(segments) == 1:
                seg = segments[0]
                path = _efm.write_manifest(
                    project, flow=FLOW, run_dir=seg["run_dir"],
                    rows=seg["rows"], flow_status=seg["flow_status"],
                    not_performed=manifest["not_performed"], extra=extra)
            else:
                path = _efm.write_manifest(
                    project, flow=FLOW, segments=segments,
                    not_performed=manifest["not_performed"], extra=extra)
        except _efm.ManifestError as exc:
            raise Refusal("LL_IMPORT_MANIFEST_INVALID", str(exc)) from None
    except BaseException:
        journal.rollback()
        raise
    journal.close()
    return json.loads(path.read_text(encoding="utf-8"))


def import_run(project: Path, run_dir: Path,
               to: Optional[str] = None) -> Dict[str, Any]:
    """Import one LibreLane run (inside ``project``); ``to`` is the step it
    was declared to stop at, if any."""
    return import_segments(project, [(run_dir, to)])


def _segment_arg(text: str) -> Tuple[Path, Optional[str]]:
    head, sep, tail = text.rpartition("=")
    if sep and _STEP_ID.match(tail):
        return Path(head), tail
    return Path(text), None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("segments", nargs="+", type=_segment_arg,
                    metavar="RUN_DIR[=TO_STEP]",
                    help="each segment run in order; `=<StepClass>` declares "
                         "the step the run was asked to stop at (--to)")
    a = ap.parse_args(argv)
    try:
        doc = import_segments(a.project, a.segments)
    except Refusal as exc:
        print(f"REFUSED {exc.code}: {exc}", file=sys.stderr)
        return 1
    segs = _efm.segments_of(doc)
    print(f"imported {sum(len(s['rows']) for s in segs)} file(s) from "
          f"{len(segs)} finished run(s); {len(doc['not_performed'])} rule(s) "
          "not performed by them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
