#!/usr/bin/env python3
"""analog_hardmacro_check.py — deterministic gate for analog hardmacro deliverables

Validates that each analog block has a complete hardmacro package under
hardmacro/<block>/ containing:
  - <block>.gds  (carries REAL GDS geometry — see below)
  - <block>.lef  (contains MACRO and PIN keywords)
  - <block>.lib  (declares at least one Liberty `cell (<name>) { … }` group)
  - <block>.v    (declares at least one Verilog `module <name>`)

The .lib and .v predicates used to be bare substring tests — `"cell" not in
text.lower()` and `"module" not in text`. Measured: a Verilog file whose ONLY
occurrence of the word was inside a `//` comment ("// this is a submodule
placeholder comment mentioning module keyword", plus `wire`/`assign` lines and
no declaration at all) satisfied HARDMACRO_V_NO_MODULE and the block was signed
off HARDMACRO_COMPLETE; a Liberty file containing only "/* the release was
cancelled */" satisfied HARDMACRO_LIB_NO_CELL on the substring inside
"cancelled". Both predicates now strip comments and require the DECLARATION to
be PRESENT — the good thing asserted, not the bad token absent.

The GDS predicate used to be `exists() and st_size != 0`. Measured: 500 bytes
of non-GDS noise placed at hardmacro/<block>/<block>.gds, alongside a valid
LEF/LIB/V, produced `[PASS] analog_hardmacro_check` + HARDMACRO_COMPLETE —
while the SIBLING A5 gate, on the exact same bytes, reported 0 geometry
records and rejected it. A hardmacro is the artefact digital PnR instantiates;
size is not evidence that a layout exists. The predicate is now the same
record walk A5 uses (`analog_a5_layout_check._gds_geometry_count`: BOUNDARY /
PATH / SREF / AREF / BOX), so the gate of record for A8 is no longer weaker
than its sibling on the identical file type. It sits AFTER the
deterministic-stub short-circuit, so the PASS_WITH_STUB tier is untouched.

Self-skips when:
  - No analog blocks detected (no analog_block_list.json or empty)

Usage:
    python3 analog_hardmacro_check.py <project_dir>
    python3 analog_hardmacro_check.py <project_dir> --json reports/gates/hardmacro.json

Exit codes:
    0 = PASS: at least one analog block was found, its hardmacro package is
        complete, and the artefact chain names what that package models.
        PASS_STRUCTURE_ONLY — also rc 0, in its own disclosed tier — when what
        it models is a library default and the chain says so.
    1 = FAIL (missing or corrupt hardmacro files, or nothing anywhere names
        what the package models)
    2 = VACUOUS: nothing was examined — this project declares no analog block,
        so there is no hardmacro package to deliver. #521: this used to be
        rc 0, which credited the gate in the plain PASS tier on 183 of the 200
        tracked project roots. Also rc 2 for an IO / parse error.

═══ WHY THIS GATE ASKS WHAT THE PACKAGE MODELS ═══════════════════════════
THE INVARIANT, with no tool, step or block name in it:

    Two gates that certify ONE artefact must not disagree about it.

THIS gate is the one `flow/phase1_phase2_phase3.yaml` DECLARES for A8
(`program_exit_zero: "analog_hardmacro_check . --json
reports/phase2/gates/hardmacro.json"`). `analog_liberty_nonzero_delay_check` —
which reads the `design_content` record and grades the very `.lib` inside the
package this gate signs off — appears ZERO times in that YAML.

MEASURED, over one complete synthetic package (.gds + .lef + .lib + .v) on
three trees identical in every artefact except the one recorded
`design_content` value:

    analog_a8_hardmacro_gen_check      PASS / PASS / PASS
    analog_hardmacro_check             PASS / PASS / PASS
    analog_liberty_nonzero_delay_check PASS / PASS_STRUCTURE_ONLY / FAIL

The two gates that answer for the STEP could not tell the trees apart. The
rule is a property of the PACKAGE, so every gate over it asks the same
question, through ONE shared site
(`_analog_a_check_common.hardmacro_content`) rather than a copied predicate.

ASKED LAST, after every deliverable and content rule (GDS geometry, LEF
MACRO/PIN, Liberty cell, Verilog module), each of which names a deeper cause
and answers this one as a side effect. The deterministic-STUB short-circuit is
untouched and never reaches the question: a stub marker is ITSELF a disclosure
of what the package is, and PASS_WITH_STUB is its own already-disclosed tier.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import _path_layout as _pl
import _vacuous_exit as _vx
import _analog_a_check_common as _acc
from _analog_stub_marker import is_stub_text  # v1.6.177 (#72 P1-6)
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)
# ONE parser for "does this GDS carry geometry", shared with the A5 gate so the
# two cannot drift apart on the same file type. Guarded: a checker must never
# be silently disarmed by an import error, so an unavailable parser is a hard
# error at use time (see _gds_geometry_records), not a skipped predicate.
try:
    from analog_a5_layout_check import _gds_geometry_count
except ImportError:  # pragma: no cover - programs/ is always on sys.path
    _gds_geometry_count = None  # type: ignore[assignment]


def _gds_geometry_records(path: Path) -> int:
    """Number of GDS geometry/placement records in `path`.

    Raises RuntimeError when the shared parser could not be imported — a gate
    that cannot evaluate its own predicate must say so, never return a value
    that reads as "clean". Deliberately NOT caught in main(): an uncaught
    exception exits 1, which flow_compliance_check reads as FAIL. Returning
    rc 2 would be read as VACUOUS_PASS — silently green — which is the failure
    mode this predicate exists to end.
    """
    if _gds_geometry_count is None:
        raise RuntimeError(
            "analog_a5_layout_check._gds_geometry_count unavailable; the GDS "
            "geometry predicate cannot be evaluated")
    try:
        return _gds_geometry_count(path.read_bytes())
    except OSError:
        return 0


# ── declaration parsers (replacing the old bare substring tests) ───────────
# Comments are stripped FIRST so a mention inside `//`, `/* */` or Liberty's
# own `/* */` can never stand in for a declaration.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")

# `module <identifier>` — Verilog identifiers are [A-Za-z_][A-Za-z0-9_$]* or an
# escaped identifier (`\name ` ). `module` must be a whole word.
_V_MODULE_DECL_RE = re.compile(
    r"(?:^|[^\w$])module\s+(?:\\\S+|[A-Za-z_][\w$]*)")
# Liberty group header `cell (<name>) {` — `cell` must be a whole word, so
# "cancelled" / "excellent" cannot satisfy it, and so can a `test_cell` /
# `scaled_cell` group (both are prefixed by a word character). The name is any
# non-empty, space-free token so digit-leading and quoted cell names are
# accepted; an empty `cell ()` is not.
_LIB_CELL_DECL_RE = re.compile(
    r"(?:^|[^\w])cell\s*\(\s*[\"']?[^)\s\"']+[\"']?\s*\)",
    re.IGNORECASE)


def _strip_comments(text: str) -> str:
    """Remove `/* … */` and `// …` comments. Shared by the Verilog and
    Liberty predicates — both languages use exactly these two forms."""
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", text))


def has_verilog_module_decl(text: str) -> bool:
    """True iff `text` declares at least one Verilog module OUTSIDE comments."""
    return bool(_V_MODULE_DECL_RE.search(_strip_comments(text)))


def has_liberty_cell_decl(text: str) -> bool:
    """True iff `text` declares at least one Liberty `cell (<name>)` group
    OUTSIDE comments."""
    return bool(_LIB_CELL_DECL_RE.search(_strip_comments(text)))


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_hardmacro_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _cite(path: Optional[Path], project: Path) -> Optional[str]:
    """Project-relative citation, never an exception. The FLOW invokes this
    gate as `analog_hardmacro_check . --json ...`, so `project` is `.` and
    `Path("phase3/x").relative_to(Path("."))` raises — a citation string is not
    worth a traceback in the gate that certifies the step."""
    if path is None:
        return None
    try:
        return str(Path(path).relative_to(project))
    except ValueError:
        return str(path)


def _load_block_list(project: Path) -> List[str]:
    bl = _pl.analog_dir(project) / "analog_block_list.json"
    if not bl.exists():
        return []
    try:
        data = json.loads(bl.read_text(errors="replace"))
        if isinstance(data, dict) and "blocks" in data:
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data["blocks"]]
        if isinstance(data, list):
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return []


def _scan_spec_blocks(project: Path) -> List[str]:
    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        return []
    found = []
    for spec in sorted(analog_dir.glob("*/spec.json")):
        found.append(spec.parent.name)
    return found


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    blocks = _load_block_list(project) or _scan_spec_blocks(project)

    if not blocks:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message="No analog blocks detected; skipping hardmacro check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return result

    hardmacro_dir = _pl.hardmacro_dir(project)
    analog_dir = _pl.analog_dir(project)
    complete = 0
    stub_blocks = 0   # v1.6.177 (#72 P1-6)
    incomplete = []
    structure_only: List[str] = []
    design_bound: List[str] = []
    undisclosed: List[str] = []

    for block in blocks:
        block_dir = hardmacro_dir / block
        missing = []

        gds = block_dir / f"{block}.gds"
        lef = block_dir / f"{block}.lef"
        lib = block_dir / f"{block}.lib"
        verilog = block_dir / f"{block}.v"

        # v1.6.177 (#72 P1-6) — honor deterministic-stub marker. If
        # ANY of the three textual artefacts (LEF/LIB/V) carries
        # the marker, the whole hardmacro is treated as a stub and
        # the GDS-presence + LEF/LIB content requirements are
        # relaxed (A7 stub deliberately omits .gds — replacing it
        # with a real one is the A5 magic-layout step's job).
        # chip-AGNOSTIC: marker is structural, not chip-class.
        stub_match = False
        for cand in (lef, lib, verilog):
            try:
                if cand.exists() and is_stub_text(
                        cand.read_text(errors="replace")):
                    stub_match = True
                    break
            except OSError:
                continue
        if stub_match:
            stub_blocks += 1
            complete += 1
            result.findings.append(Finding(
                rule="HARDMACRO_STUB_ACCEPTED",
                severity="INFO",
                message=(f"Block '{block}' hardmacro is a "
                         f"deterministic stub (PASS_WITH_STUB tier); "
                         f"GDS + content requirements relaxed."),
            ))
            continue

        # NOTE: this sits AFTER the stub short-circuit above on purpose — a
        # deterministic-stub hardmacro deliberately ships without a .gds and
        # keeps passing at the PASS_WITH_STUB tier.
        if not gds.exists() or gds.stat().st_size == 0:
            missing.append(f"{block}.gds")
        elif _gds_geometry_records(gds) <= 0:
            # Non-empty is not evidence of a layout. The identical bytes are
            # rejected by analog_a5_layout_check; A8 must not be the weaker
            # gate on the same file type.
            result.findings.append(Finding(
                rule="HARDMACRO_GDS_NO_GEOMETRY",
                severity="ERROR",
                message=(f"Block '{block}': GDS carries no "
                         f"BOUNDARY/PATH/SREF/AREF/BOX record "
                         f"({gds.stat().st_size} bytes of padding, garbage "
                         f"or an empty library) — not a layout"),
                file=str(gds),
            ))
            missing.append(f"{block}.gds (no geometry)")

        if not lef.exists():
            missing.append(f"{block}.lef")
        elif lef.exists():
            try:
                text = lef.read_text(errors="replace")
                if "MACRO" not in text:
                    result.findings.append(Finding(
                        rule="HARDMACRO_LEF_NO_MACRO",
                        severity="ERROR",
                        message=f"Block '{block}': LEF file missing MACRO keyword",
                        file=str(lef),
                    ))
                    missing.append(f"{block}.lef (no MACRO)")
                elif "PIN" not in text:
                    result.findings.append(Finding(
                        rule="HARDMACRO_LEF_NO_PIN",
                        severity="ERROR",
                        message=f"Block '{block}': LEF file missing PIN keyword",
                        file=str(lef),
                    ))
                    missing.append(f"{block}.lef (no PIN)")
            except OSError:
                missing.append(f"{block}.lef (unreadable)")

        if not lib.exists():
            missing.append(f"{block}.lib")
        elif lib.exists():
            try:
                text = lib.read_text(errors="replace")
                if not has_liberty_cell_decl(text):
                    result.findings.append(Finding(
                        rule="HARDMACRO_LIB_NO_CELL",
                        severity="ERROR",
                        message=(f"Block '{block}': Liberty file declares no "
                                 f"`cell (<name>)` group outside comments"),
                        file=str(lib),
                    ))
                    missing.append(f"{block}.lib (no cell)")
            except OSError:
                missing.append(f"{block}.lib (unreadable)")

        if not verilog.exists():
            missing.append(f"{block}.v")
        elif verilog.exists():
            try:
                text = verilog.read_text(errors="replace")
                if not has_verilog_module_decl(text):
                    result.findings.append(Finding(
                        rule="HARDMACRO_V_NO_MODULE",
                        severity="ERROR",
                        message=(f"Block '{block}': Verilog file declares no "
                                 f"`module <name>` outside comments"),
                        file=str(verilog),
                    ))
                    missing.append(f"{block}.v (no module)")
            except OSError:
                missing.append(f"{block}.v (unreadable)")

        if missing:
            incomplete.append(block)
            result.findings.append(Finding(
                rule="HARDMACRO_INCOMPLETE",
                severity="ERROR",
                message=(
                    f"Block '{block}' hardmacro incomplete: "
                    f"missing {', '.join(missing)}"
                ),
            ))
            continue

        # ── the certification question, asked LAST ────────────────────────
        bounded = _acc.hardmacro_content(analog_dir / block)
        cited = _cite(bounded.source, project)
        if bounded.klass == _acc.CONTENT_UNDISCLOSED:
            undisclosed.append(block)
            # `ceiling_source is None` covers BOTH "the artefact is absent" and
            # "the artefact is present and silent". Those send a reader to two
            # different places, so the message asks the filesystem rather than
            # inferring from a None.
            said = (f"`{_acc.CONTENT_GATE_OF_RECORD_ARTEFACT}` records no "
                    f"answer to"
                    if (analog_dir / block
                        / _acc.CONTENT_GATE_OF_RECORD_ARTEFACT).is_file()
                    else "no corner artefact exists to say")
            result.findings.append(Finding(
                rule="HARDMACRO_SUBJECT_UNDECLARED",
                severity="ERROR",
                message=(
                    f"Block '{block}': hardmacro package is complete "
                    f"(GDS+LEF+LIB+V), and {said} what circuit it models "
                    f"(`design_content`). Digital PnR will instantiate this "
                    f"macro as this design's and integration STA will close "
                    f"on its Liberty; a package that will not name its "
                    f"subject must not be signed off for it. Declaring "
                    f"`{_acc.CONTENT_STRUCTURE_ONLY}` is not a penalty — it "
                    f"certifies, in its own disclosed tier; declining to "
                    f"answer does not, or saying nothing would cost less than "
                    f"saying so."),
            ))
            continue

        complete += 1
        if bounded.klass == _acc.CONTENT_STRUCTURE_ONLY:
            structure_only.append(block)
            result.findings.append(Finding(
                rule="HARDMACRO_STRUCTURE_ONLY",
                severity="WARNING",
                message=(
                    f"Block '{block}' hardmacro complete (GDS+LEF+LIB+V) AND "
                    f"MODELLING A LIBRARY TOPOLOGY — `{cited}` records that "
                    f"its circuit came from a topology library with no bound "
                    f"input reaching any device parameter. The package is "
                    f"real and it is the default's; a floorplan that reserves "
                    f"area for it and an STA that closes on it are not closed "
                    f"on a designed macro."),
            ))
        else:
            design_bound.append(block)
            result.findings.append(Finding(
                rule="HARDMACRO_COMPLETE",
                severity="INFO",
                message=(f"Block '{block}' hardmacro complete (GDS+LEF+LIB+V);"
                         f" design content design-bound per `{cited}`"),
            ))

    if incomplete or undisclosed:
        result.passed = False

    # v1.6.177 (#72 P1-6) — verdict tier.
    total = len(blocks)
    verdict_tier = "PASS"
    if result.passed and stub_blocks and stub_blocks == total:
        verdict_tier = "PASS_WITH_STUB"
    elif result.passed and stub_blocks:
        verdict_tier = "PASS_WITH_STUB_PARTIAL"
    elif result.passed and structure_only and not design_bound:
        # Ranked below the stub tiers on purpose: a stub is a disclosure that
        # the package is not a package at all, which is a stronger statement
        # than "the package is real and it is a library default's". A project
        # that has both keeps the stub word and names the structure-only
        # subset in its summary.
        verdict_tier = "PASS_STRUCTURE_ONLY"

    result.summary = {
        "skipped": False,
        "total_blocks": total,
        "complete": complete,
        "stub_blocks": stub_blocks,
        "incomplete": incomplete,
        "design_bound_blocks": design_bound,
        "structure_only_blocks": structure_only,
        "undisclosed_blocks": undisclosed,
        "pass": result.passed,
        "verdict_tier": verdict_tier,
    }
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    # v1.6.144 (#57) — FPGA-prototype-stage stub waiver.
    import _fpga_stub_waiver as _stub
    _stub.add_fpga_stub_argparse(ap)
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    # v1.6.144 (#57) — demote missing-per-block-artifact failures to
    # PASS_WITH_WAIVERS at the FPGA prototype stage. Same gate re-fires
    # without the waiver at phase3.foundry_handoff for tapeout signoff.
    waiver_status: str = "PASS"
    if not result.passed and _stub.fpga_stub_waiver_active(args):
        result.passed = True
        waiver_status = "PASS_WITH_WAIVERS"
        result.summary["fpga_stub_waiver_applied"] = True
        result.summary["waiver_reason"] = _stub.fpga_stub_reason()
        for f in result.findings:
            if f.severity == "ERROR":
                f.severity = "WARNING"

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    # The tier travels on the verdict WORD. Only the NEW word is promoted onto
    # that line: `PASS_WITH_STUB` / `PASS_WITH_STUB_PARTIAL` have always lived
    # in the summary and rendered as a bare `[PASS]`, and changing that is a
    # separate decision with its own consumers. A waiver, when one is active,
    # still wins — it is the stronger statement about the verdict.
    tier = (result.summary or {}).get("verdict_tier") or "PASS"
    pass_token = waiver_status
    if pass_token == "PASS" and tier == "PASS_STRUCTURE_ONLY":
        pass_token = tier

    so_blocks = (result.summary or {}).get("structure_only_blocks") or []
    if not args.json:
        print(_vx.verdict_line("analog_hardmacro_check", result.passed,
                               skipped, reason, pass_token=pass_token))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    # LAST, SHORT, and on every path the gate can leave by — including the
    # `--json` path, which is the ONLY path the FLOW ever takes for this gate.
    # To stderr, for the same reason `announce_vacuous` is.
    if so_blocks:
        names = ", ".join(str(b) for b in so_blocks)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{_acc.STRUCTURE_ONLY_TOKEN} {len(so_blocks)} hardmacro "
              f"package(s) ({names}) model a library default, not a bound "
              f"input [analog_hardmacro_check]", file=sys.stderr)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
