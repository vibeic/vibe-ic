#!/usr/bin/env python3
"""sdc_validator_check.py — validate SDC against L8 timing constraints.

Replaces skill `sdc-validator` (archived).

Three independent checks:

  1. STRUCTURE — every .sdc must carry create_clock / set_input_delay /
     set_output_delay.

  2. SEARCH-ROOT HONESTY — `[SKIP] no .sdc files` must mean "this project
     ships no SDC", not "I was pointed somewhere that has none". Those two
     were byte-identical outputs at exit 0, so a gate handed the wrong
     positional (the 8/d2 defect) or a project whose SDC producer wrote
     outside `phase2/stage2/constraints` certified step 8 from files it
     never read. When the searched roots are empty but the project carries
     .sdc files elsewhere, the program exits 1 with
     `SDC_SEARCH_ROOT_MISDIRECTED` and names both the roots it searched and
     the files it found.

EXIT CODES — this program speaks the repo's three-value gate contract
(`flow_compliance_check._check_program_exit_zero`), not two-value:

    0  PASS         at least one .sdc was READ and is clean
    1  FAIL         something the program looked at is wrong
    2  NOT CHECKED  nothing was read; the step is VACUOUS, not satisfied

Everything that reads NOTHING now exits 2, never 0:

  * no .sdc anywhere under the project — the honest empty case, still not a
    failure (step 8's first all_of member, `sdc_syntax_check`, is what
    blocks a design that needs constraints and ships none);
  * a positional that does not exist or is not a directory — a caller
    defect, which at exit 0 was recorded as an ordinary PASS of a program
    that never opened a file.

Exit 0 previously covered all three, so ABSENT and READ-AND-CLEAN were
indistinguishable at the exit-code layer and no `__VACUOUS_HINT__` was
raised. At exit 2 the compliance report labels the step VACUOUS-PASS, which
is what "I did not read anything" is supposed to look like. Both exit-2
paths DISCLOSE THEIR DENOMINATOR the way the PASS path does ("N SDC file(s)
OK"): how many search roots were declared, the state of each, how many .sdc
the project-wide scan found outside them, and how many directories that
scan walked.

§4.05 — the project-wide scan PRUNES the staged reference/oracle vocabulary
(`_reference_flow_boundary.OFF_LIMITS_TREE_SEGMENTS`). A design whose only
constraint file is a staged upstream `.../reference_flow/pre_syn/golden.sdc`
used to be reported as SDC_SEARCH_ROOT_MISDIRECTED with the golden file
NAMED in the diagnostic — a message that points the author straight at the
oracle. Those directories are now never walked, and are disclosed by COUNT
only. That is also the correct verdict on the merits: a staged upstream
reference flow is not this run's constraint output, so a project carrying
only one has produced no SDC and belongs in the exit-2 not-checked tier.

  3. L8 CROSS-CHECK (`--l8`, L8 CROSS-CHECK) — the cross-check the flow has
     declared since Wave 82 ("`sdc_validator_check` cross-checks the SDC
     against L8_TIMING_WAVEFORM constraints; complements sdc_syntax_check
     which only validates SDC syntax") but never implemented: `--l8` was
     accepted and then never read, so the only PASS/FAIL logic in the whole
     program was three literal substring tests. Now the clock periods L8
     declares are compared against the periods the SDC creates, every
     primary clock L8 declares must be constrained by some SDC, and an L8
     that declares two DIFFERENT periods under one clock name is reported in
     its own right — an SDC cannot be validated against a contradictory
     constraint set.

The L8 cross-check is ADDITIVE: the three-directive structural test is
unchanged, and a project invoked without `--l8` (or whose L8 carries no
clock records at all — timing_windows/timing_constants/waveforms are
routinely empty) is judged by checks 1 and 2 alone.

Check 2 is NOT additive and is not meant to be: it converts a class of
silent exit-0 skips into failures. On a project whose SDC is where the flow
declares it, it never runs at all — the stray scan is reached only after the
search-root glob has already come back empty.

WHAT IS GRADED — superseded generator decks are set aside
---------------------------------------------------------
The three-directive structural test above is applied to the project's
CONSTRAINT SET, not to every byte with an `.sdc` suffix. `sdc_gen` names its
output `{top}.sdc` from a top it resolves PER RUN, so a change in that
resolution leaves the previous run's file orphaned in the same directory
this program globs. Grading it answers "are the design's constraints
complete?" with the presence of a stale artifact: step 8 FAILs permanently —
voiding every step that depends on it — over a file constraining a module
the design does not declare and nothing downstream consumes.

Such a deck is SET ASIDE (never deleted; see `partition_decks` for the
four-part predicate and why the fix lives in the consumer). It is DISCLOSED
on every verdict — in the PASS/FAIL line and in the `sdc_files_superseded`
key of the JSON report — because a checker that quietly narrows its own
denominator is the failure this program's exit contract exists to prevent.
And when EVERY deck found is superseded, the verdict is exit 2 (NOT
CHECKED), never exit 0: nothing constraining a declared top was read.
"""
import argparse, json, os, re, sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
import _path_layout as _pl
import _reference_flow_boundary as _rfb
import _design_module_set as _dms
import sdc_constraints as _sdc

# ----- exit-code contract -------------------------------------------

#: `flow_compliance_check._check_program_exit_zero`: 0 PASS, 1 FAIL,
#: 2 VACUOUS_PASS (the "I ran but read nothing" tier, rendered VACUOUS-PASS
#: in the compliance report via the `__VACUOUS_HINT__` sentinel).
RC_PASS = 0
RC_FAIL = 1
RC_NOT_CHECKED = 2

# ----- search roots and the misdirection diagnostic ------------------

#: The directories this program validates, as (display, resolver). The
#: positional is the PROJECT ROOT; these are resolved from it, which is why
#: handing the gate `phase2/stage2/constraints` produced the doubled
#: `phase2/stage2/constraints/phase2/stage2/constraints`.
_SEARCH_ROOTS = (
    ("phase2/stage1/fpga", _pl.fpga_early_dir),
    ("phase2/stage2/constraints", _pl.constraints_dir),
)

#: VCS/tool metadata that cannot hold a project's constraints.
_METADATA_PRUNE_DIRS = frozenset({".git", ".hg", ".svn", "__pycache__",
                                  ".venv", "node_modules"})

#: Pruned from the stray scan. Two disjoint reasons:
#:
#:   * metadata — cannot hold a project's constraints;
#:   * §4.05 — a staged reference / golden / expected-solution tree. The scan
#:     exists to build a MESSAGE, and naming `.../reference_flow/pre_syn/
#:     golden.sdc` in that message points the design author at the oracle just
#:     as effectively as reading it would. The vocabulary is imported, never
#:     re-spelled, so it cannot drift from `floorplan_contract`'s copy.
#:
#: It is also the right verdict on the merits: a staged upstream reference
#: flow is not this run's constraint output, so a project whose only .sdc
#: lives there has produced none and belongs in the NOT-CHECKED tier — not in
#: a MISDIRECTED failure that tells the author to go read it.
#:
#: Nothing ELSE is pruned: a `.sdc` under `input/` that is not in an
#: off-limits tree is still evidence that the project carries constraint
#: files the declared search roots do not see, which is what the diagnostic
#: reports.
_SCAN_PRUNE_DIRS = frozenset(
    _METADATA_PRUNE_DIRS | _rfb.OFF_LIMITS_TREE_SEGMENTS)

#: The scan runs only when the search roots came back empty, i.e. only on an
#: already-broken project, and stops once it has enough evidence to name the
#: problem. Listing every stray is not the point; proving one exists is.
_STRAY_SCAN_LIMIT = 8


def search_roots(project: Path) -> List[Path]:
    """The directories `find_sdc_files` globs, in glob order."""
    return [fn(Path(project)) for _, fn in _SEARCH_ROOTS]


def find_sdc_files(project: Path) -> List[Path]:
    """Every `*.sdc` directly under a search root, deterministically ordered."""
    out: List[Path] = []
    for root in search_roots(project):
        if root.is_dir():
            out.extend(sorted(root.glob("*.sdc")))
    return out


# ----- superseded generator decks ------------------------------------
#
# `sdc_gen` names its output `{top}.sdc` and stamps `# Top entity: {top}`
# into it. `top` is resolved PER RUN (`--top-name`, else a board wrapper,
# else L9's `top_module`, else the literal `chip_top` fallback), so a change
# in that resolution between runs leaves the earlier file behind under a
# DIFFERENT name in the SAME directory this program globs. The orphan
# constrains a module the design does not declare, nothing downstream
# consumes it, and it fails the three-directive structural test forever —
# so step 8 FAILs permanently while the design's own constraint set is
# complete. Measured on the tracked corpus: 4 roots carry >=2 generated
# decks under different `# Top entity:` names.
#
# WHY THE FIX IS HERE AND NOT IN THE GENERATOR
# --------------------------------------------
# The generator knows only the top IT resolved this run, which is exactly
# the unstable quantity. Keying a DELETION on it inverts on any project
# whose L9 declares a top the RTL does not contain: the deck for the module
# that EXISTS is destroyed and the deck for the phantom is kept. The
# consumer, by contrast, can key on what the project DECLARES, and it sees
# BOTH search roots — a generator-side cleanup that walks one directory
# leaves the identical orphan in the other. Nothing is removed from disk
# here: a file that is merely not graded stays available for inspection,
# and being wrong about it costs a stale artifact instead of a lost one.
#
# THE PREDICATE
# -------------
# A deck is SUPERSEDED only when the project itself refutes it, on all four
# counts:
#
#   1. it carries this flow's generator banner (`sdc_constraints`'
#      GENERATED_BANNER) — a hand-authored SDC or one from another tool is
#      never anyone's to set aside;
#   2. it is ATTRIBUTABLE — it names its `# Top entity:`;
#   3. that name is ABSENT from the design's own module set, per the #760
#      arbiter (`_design_module_set.reconcile_declared_top`), which answers
#      `unverifiable` — never `absent` — when nothing was staged or nothing
#      parsed, so an unreadable design refutes nothing; and
#   4. that name is not the top the project DECLARES for this run
#      (`L9.top_module`, or the generator's `chip_top` fallback when L9
#      declares none) — the deck the flow is producing RIGHT NOW is graded
#      no matter what the module set says about it.
#
# (4) is what keeps this from becoming the generator's bug in mirror image.
# On the corpus's `usb_pd`, L9 declares `usb_pd_engine`, which `grep`
# refutes; the only staged tops are `chip_top` and `usb_pd_bmc_phy`. Rules
# (3) and (4) together keep BOTH decks: `chip_top.sdc` because chip_top is a
# real module, `usb_pd_engine.sdc` because it is what this run declares. The
# incomplete one still FAILs step 8, which is the honest verdict.

def declared_top_modules(project: Path) -> List[str]:
    """The top module name(s) the PROJECT declares, from L-docs alone.

    `L9.top_module` when it carries one; otherwise the generator's own
    `chip_top` fallback, because with no declaration that IS the name every
    run resolves. A board wrapper is deliberately absent: it is a module in
    the staged RTL, so the module set already vouches for it.
    """
    l9 = _pl.generated_docs_dir(Path(project)) / "L9_INTEGRATION_SPEC.json"
    try:
        doc = json.loads(l9.read_text(errors="ignore"))
    except Exception:  # noqa: BLE001 — absent/unparseable L9 is not an error
        doc = None
    name = doc.get("top_module") if isinstance(doc, dict) else None
    if isinstance(name, str) and name.strip():
        return [name.strip()]
    return ["chip_top"]


def staged_module_set(project: Path) -> set:
    """Every module name this project stages, across RTL / FPGA / synth.

    Empty means "nothing staged or nothing parsed" — :func:`partition_decks`
    routes that through the #760 arbiter, which refuses to call any name
    absent against an empty set."""
    project = Path(project)
    return _dms.design_module_set([_pl.rtl_dir(project),
                                   _pl.fpga_early_dir(project),
                                   _pl.synth_dir(project)])


class DeckPartition(NamedTuple):
    """`live` decks to grade, and the `superseded` ones set aside.

    `superseded` is `[(path, declared_top), ...]`; it is DISCLOSED on every
    verdict, because a checker that silently narrows its own denominator is
    the failure mode this program's exit contract already exists to prevent.
    """
    live: List[Path]
    superseded: List[Tuple[Path, str]]


def partition_decks(project: Path, sdc_files: List[Path]) -> DeckPartition:
    """Split `sdc_files` into the decks to grade and the superseded ones.

    Order is preserved: `live` is `sdc_files` minus the superseded ones, in
    the glob order the caller built, so the issue list a project sees does
    not depend on this partition. The module set — the only expensive read
    here, since it walks the synthesis output as well as the RTL — is built
    only when some deck is actually a candidate for it; on a project whose
    decks all name the declared top, nothing beyond the SDC headers is read.
    """
    protected = set(declared_top_modules(project))
    candidates: List[Tuple[Path, str]] = []
    for sdc in sdc_files:
        top = _sdc.generated_top_entity_of(sdc)     # (1) + (2)
        if top is not None and top not in protected:              # (4)
            candidates.append((sdc, top))
    superseded: List[Tuple[Path, str]] = []
    if candidates:
        module_set = staged_module_set(project)
        superseded = [
            (sdc, top) for sdc, top in candidates                 # (3)
            if _dms.reconcile_declared_top(top, module_set)["verdict"]
            == _dms.ABSENT]
    dead = {p for p, _ in superseded}
    return DeckPartition([p for p in sdc_files if p not in dead], superseded)


def superseded_note(part: DeckPartition) -> str:
    """The denominator line for the decks that were NOT graded."""
    if not part.superseded:
        return ""
    return (f", {len(part.superseded)} superseded generator deck(s) not "
            f"graded ("
            + ", ".join(f"{p.name} -> top {t!r}" for p, t in part.superseded)
            + " — this flow's own earlier output for a top the design does "
              "not declare)")


def all_decks_superseded_message(project: Path, part: DeckPartition) -> str:
    """The exit-2 line for "every deck found is a superseded orphan".

    NOT exit 0. Nothing that constrains a top this project declares was
    read, so the step is VACUOUS, not satisfied — the same tier as "no .sdc
    anywhere". Collapsing it into a PASS is precisely how a narrowing filter
    turns into "step 8 made unfailable"."""
    return (
        "[SKIP] sdc_validator_check: NOT CHECKED — all "
        f"{len(part.superseded)} .sdc file(s) under the declared search "
        "root(s) ("
        + ", ".join(d for d, _ in _SEARCH_ROOTS)
        + ") are superseded generator decks ("
        + ", ".join(f"{p.name} -> top {t!r}" for p, t in part.superseded)
        + "); the project declares top(s) "
        + ", ".join(repr(t) for t in declared_top_modules(project))
        + " and stages no constraint file for them, so 0 file(s) were graded")


class StrayScan(NamedTuple):
    """The project-wide `.sdc` scan, WITH the denominators it consumed.

    `dirs_walked` and `dirs_pruned_off_limits` are what let the exit-2 SKIP
    disclose its own scope instead of asserting "no .sdc" with no evidence
    of how hard it looked."""
    strays: List[Path]
    dirs_walked: int
    dirs_pruned_off_limits: int
    dirs_pruned_metadata: int
    truncated: bool


def scan_for_stray_sdc(project: Path,
                       limit: int = _STRAY_SCAN_LIMIT) -> StrayScan:
    """`.sdc` files under `project` that no search root covers, plus scope.

    Only called when the search roots yielded nothing, so an empty result
    means "this project genuinely ships no SDC the flow could have produced"
    and a non-empty one means "the SDC exists, the searched roots just do not
    see it".

    A search root is skipped but NOT pruned: `find_sdc_files` globs `*.sdc`
    directly under it, so `phase2/stage2/constraints/sub/top.sdc` is an SDC
    the roots cannot see and is correctly reported as one.

    §4.05 trees ARE pruned, and counted rather than named — see
    `_SCAN_PRUNE_DIRS`."""
    root = Path(project)
    covered = {r.resolve() for r in search_roots(root)}
    found: List[Path] = []
    walked = off_limits = metadata = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root, onerror=None):
        walked += 1
        keep = []
        for d in sorted(dirnames):
            low = d.lower()
            if low in _rfb.OFF_LIMITS_TREE_SEGMENTS:
                off_limits += 1
            elif low in _METADATA_PRUNE_DIRS or d in _METADATA_PRUNE_DIRS:
                metadata += 1
            else:
                keep.append(d)
        dirnames[:] = keep
        here = Path(dirpath)
        try:
            if here.resolve() in covered:
                continue
        except OSError:
            pass
        if truncated:
            continue
        for fn in sorted(filenames):
            if fn.endswith(".sdc"):
                found.append(here / fn)
                if len(found) >= limit:
                    # Stop COLLECTING, but keep walking: the pruned-directory
                    # denominator this scan reports must describe the whole
                    # project, not the prefix that happened to fill the list.
                    truncated = True
                    break
    return StrayScan(found, walked, off_limits, metadata, truncated)


def stray_sdc_files(project: Path,
                    limit: int = _STRAY_SCAN_LIMIT) -> List[Path]:
    """`.sdc` files under `project` that no search root covers."""
    return scan_for_stray_sdc(project, limit).strays


def _off_limits_note(scan: StrayScan) -> str:
    """§4.05: disclose the pruned trees by COUNT, never by path. Naming them
    is the leak — the message would tell the author exactly which staged
    golden file to go and copy."""
    if not scan.dirs_pruned_off_limits:
        return ""
    return (f"; {scan.dirs_pruned_off_limits} staged reference/oracle "
            f"director(y/ies) were NOT scanned (§4.05 — a staged upstream "
            f"reference flow is not this run's constraint output)")


def misdirected_search_root_issue(project: Path) -> Optional[str]:
    """The `SDC_SEARCH_ROOT_MISDIRECTED` diagnostic, or None when the
    project truly carries no SDC at all."""
    return misdirection_diagnostic(scan_for_stray_sdc(project), Path(project))


def misdirection_diagnostic(scan: StrayScan, root: Path) -> Optional[str]:
    """`SDC_SEARCH_ROOT_MISDIRECTED` for an already-performed scan."""
    if not scan.strays:
        return None
    shown = []
    for s in scan.strays:
        try:
            shown.append(str(s.relative_to(root)))
        except ValueError:
            shown.append(str(s))
    count = (f"at least {len(scan.strays)}" if scan.truncated
             else str(len(scan.strays)))
    return (
        "SDC_SEARCH_ROOT_MISDIRECTED: the searched roots ("
        + ", ".join(d for d, _ in _SEARCH_ROOTS)
        + f" under {root}) hold no .sdc, but the project carries "
        + f"{count} .sdc file(s) elsewhere: "
        + ", ".join(shown)
        + " — step 8 cannot be certified from files it did not read. Either "
          "the positional handed to sdc_validator_check is not the project "
          "root, or the SDC producer wrote outside the declared constraints "
          "directory"
        + _off_limits_note(scan))


# ----- the exit-2 (NOT CHECKED) disclosures --------------------------

def search_root_states(project: Path) -> List[Tuple[str, str]]:
    """``(display_name, state)`` per declared search root, where state is
    ``absent`` (not a directory) or ``empty`` (a directory holding no
    ``*.sdc``). Only ever called when the glob came back empty, so no root
    can be in any other state."""
    out: List[Tuple[str, str]] = []
    for display, fn in _SEARCH_ROOTS:
        root = fn(Path(project))
        out.append((display, "empty" if root.is_dir() else "absent"))
    return out


def no_sdc_anywhere_message(project: Path, scan: StrayScan) -> str:
    """The exit-2 SKIP line, WITH its denominator.

    The PASS line discloses how many files it read ("N SDC file(s) OK"); a
    skip that discloses nothing is indistinguishable from a skip that never
    looked. So this states how many roots were declared and what state each
    is in, how many directories the project-wide scan walked, and how many
    it declined to walk."""
    states = search_root_states(project)
    pruned = []
    if scan.dirs_pruned_metadata:
        pruned.append(f"{scan.dirs_pruned_metadata} metadata")
    if scan.dirs_pruned_off_limits:
        pruned.append(
            f"{scan.dirs_pruned_off_limits} staged reference/oracle")
    scope = f"{scan.dirs_walked} director(y/ies) scanned"
    if pruned:
        scope += ", " + " + ".join(pruned) + " pruned"
    return (
        "[SKIP] sdc_validator_check: NOT CHECKED — no .sdc file(s) under "
        f"{len(states)} declared search root(s) ("
        + ", ".join(f"{d} [{s}]" for d, s in states)
        + f"), and 0 elsewhere in the project ({scope})")


def positional_inside_off_limits(project: Path) -> Optional[str]:
    """The off-limits segment in the positional AS THE CALLER WROTE IT, or
    None.

    Pruning descendants alone leaves the leak reachable one level deeper:
    handed `<design>/input/reference_flow/pre_syn` directly, the scan starts
    INSIDE the oracle tree, so nothing prunes it and the diagnostic
    enumerates the staged golden files by name again. Measured on the
    tracked corpus, 2 of the 6 positionals from which the scan can reach a
    staged `.sdc` are of exactly this shape.

    Checked on the path as given — the shipped step-8 gate passes `.` (cwd =
    the project), whose only part is `.`, so it can never trip this."""
    hits = [p for p in Path(project).parts
            if p.lower() in _rfb.OFF_LIMITS_TREE_SEGMENTS]
    return hits[-1] if hits else None


def off_limits_positional_message(project: Path, segment: str) -> str:
    """The exit-2 line for a positional pointing INTO a staged tree.

    Echoes only the segment the caller themselves typed; it enumerates
    nothing, because enumerating is the leak."""
    return (
        f"[SKIP] sdc_validator_check: NOT CHECKED — the positional "
        f"{project} sits inside a staged reference/oracle tree "
        f"({segment!r}) and its {len(_SEARCH_ROOTS)} declared search root(s) "
        f"("
        + ", ".join(d for d, _ in _SEARCH_ROOTS)
        + ") hold no .sdc. §4.05: a staged upstream tree is not this run's "
          "constraint output, so its contents are neither read nor listed. "
          "Point this at the PROJECT ROOT")


def unusable_positional_message(project: Path) -> str:
    """The exit-2 line for a positional that is not a directory.

    At exit 0 this was recorded as an ordinary PASS of a program that never
    opened a file — a certificate issued for a path that does not exist."""
    kind = "does not exist" if not Path(project).exists() else "is not a directory"
    return (
        f"[SKIP] sdc_validator_check: NOT CHECKED — the positional "
        f"{project} {kind}, so 0 of {len(_SEARCH_ROOTS)} declared search "
        f"root(s) ("
        + ", ".join(d for d, _ in _SEARCH_ROOTS)
        + ") could be resolved and 0 .sdc file(s) were read. The positional "
          "is the PROJECT ROOT")


# ----- L8 <-> SDC cross-check ---------------------------------------

#: Relative tolerance on a period comparison. 1 % absorbs the rounding that
#: frequency->period conversion introduces (133 MHz -> 7.5188 ns vs a written
#: 7.52 ns) without absorbing a real constraint mismatch (10.0 vs 8.0 ns).
_PERIOD_REL_TOL = 0.01

#: `create_clock ... -name <n> ... -period <p> [get_ports <x>]`. Parsed
#: field-wise rather than positionally: SDC argument order is free, `-name`
#: is optional (the clock then takes its source object's name), and the
#: target may be `[get_ports {clk}]`, `[get_ports clk]` or `[get_pins ...]`.
_CREATE_CLOCK_RE = re.compile(r"^[ \t]*create_clock\b(?P<args>[^\n]*)", re.M)
_CREATE_GEN_CLOCK_RE = re.compile(
    r"^[ \t]*create_generated_clock\b(?P<args>[^\n]*)", re.M)
_NAME_ARG_RE = re.compile(
    r"-name\s+(?:\{\s*(?P<b>[^}]*?)\s*\}|(?P<p>[^\s\]\[]+))")
_PERIOD_ARG_RE = re.compile(r"-period\s+(?P<v>[-+0-9.eE]+)")
_GET_OBJ_RE = re.compile(
    r"\[\s*get_(?:ports|pins)\s+(?:\{\s*(?P<b>[^}]*?)\s*\}|(?P<p>[^\s\]\[]+))")

#: L8 containers that may carry clock records. `clocks` is the canonical
#: list; `clock_domains` is what several extraction strategies populate.
#: BOTH are scanned for the contradiction test — a name that appears in one
#: at 10.0 ns and in the other at 8.0 ns is contradictory wherever it sits.
_L8_CLOCK_CONTAINERS = ("clocks", "clock_domains")


def _entry_period_ns(entry: Dict[str, Any]) -> Optional[float]:
    """Period in ns for one L8 clock record.

    Field-name/unit variance across IC classes is TOLERATED rather than
    treated as a schema error: `period_ns` wins, then `freq_mhz`, then
    `freq_hz`. A record carrying none of them contributes no period (it is
    skipped, never failed) — range-only records (`freq_low_mhz` /
    `high_mhz`) do not pin a period and must not synthesise one.
    """
    for key, to_ns in (("period_ns", lambda v: v),
                       ("freq_mhz", lambda v: 1000.0 / v),
                       ("freq_hz", lambda v: 1e9 / v)):
        v = entry.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if float(v) <= 0:
            continue
        return round(float(to_ns(float(v))), 6)
    return None


def _entry_is_derived(entry: Dict[str, Any]) -> bool:
    """True for a generated/derived clock, which is constrained by
    `create_generated_clock` (owned by derived_clock_sdc_required_check),
    not by `create_clock` — so it must not be held to the create_clock
    coverage rule here.

    A self-referential `derived_from` equal to the record's own name carries
    no derivation information and is NOT treated as derived.
    """
    kind = str(entry.get("domain_kind") or "").lower()
    role = str(entry.get("role") or "").lower()
    if "derived" in kind or "generated" in kind:
        return True
    if role in ("derived", "generated", "generated_clock"):
        return True
    parent = entry.get("derived_from")
    if isinstance(parent, str) and parent and parent != entry.get("name"):
        return True
    return False


def _periods_agree(a: float, b: float) -> bool:
    return abs(a - b) <= max(_PERIOD_REL_TOL * max(abs(a), abs(b)), 1e-9)


def _distinct_periods(values: List[float]) -> List[float]:
    """Collapse a period list under the comparison tolerance."""
    out: List[float] = []
    for v in sorted(values):
        if not any(_periods_agree(v, k) for k in out):
            out.append(v)
    return out


def load_l8(path: Optional[Path]) -> Tuple[Optional[Dict[str, Any]],
                                           Optional[str]]:
    """Return ``(document, error)``. An absent `--l8` is NOT an error: the
    flow gate is conditioned on the file existing, and direct callers may
    omit it. A file that exists but cannot be read as a JSON object IS an
    error — the declared cross-check then cannot run at all."""
    if path is None:
        return None, None
    p = Path(path)
    if not p.is_file():
        return None, None
    try:
        doc = json.loads(p.read_text(errors="ignore"))
    except Exception as exc:  # noqa: BLE001
        return None, (f"L8 {p}: unreadable ({exc}) — the SDC cross-check the "
                      f"flow declares cannot run against it")
    if not isinstance(doc, dict):
        return None, (f"L8 {p}: top level is {type(doc).__name__}, not an "
                      f"object — the SDC cross-check cannot run against it")
    return doc, None


def l8_clock_periods(doc: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """``{clock_name: {"periods": [...], "ports": {...}}}`` over every L8
    container that carries clock records."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(doc, dict):
        return out
    for container in _L8_CLOCK_CONTAINERS:
        entries = doc.get(container)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            if _entry_is_derived(entry):
                continue
            slot = out.setdefault(name.strip(), {"periods": [], "ports": set()})
            period = _entry_period_ns(entry)
            if period is not None:
                slot["periods"].append(period)
            pin = entry.get("source_pin")
            if isinstance(pin, str) and pin.strip():
                slot["ports"].add(pin.strip())
    return out


def _strip_comments(text: str) -> str:
    """Drop `#` comment lines and join backslash continuations so a
    multi-line create_clock is still parsed as one command."""
    text = text.replace("\\\n", " ")
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def sdc_clock_constraints(text: str) -> List[Dict[str, Any]]:
    """Every create_clock / create_generated_clock in one SDC, as
    ``{"name", "period", "ports", "generated"}``."""
    body = _strip_comments(text)
    out: List[Dict[str, Any]] = []
    for rx, generated in ((_CREATE_CLOCK_RE, False),
                          (_CREATE_GEN_CLOCK_RE, True)):
        for m in rx.finditer(body):
            args = m.group("args")
            nm = _NAME_ARG_RE.search(args)
            name = (nm.group("b") or nm.group("p")) if nm else None
            pm = _PERIOD_ARG_RE.search(args)
            period = None
            if pm:
                try:
                    period = round(float(pm.group("v")), 6)
                except ValueError:
                    period = None
            ports = {(g.group("b") or g.group("p") or "").strip()
                     for g in _GET_OBJ_RE.finditer(args)}
            out.append({"name": name, "period": period,
                        "ports": {p for p in ports if p},
                        "generated": generated})
    return out


def l8_self_issues(doc: Optional[Dict[str, Any]],
                   load_error: Optional[str]) -> List[str]:
    """Problems in L8 ITSELF that make the SDC unverifiable. Reported
    however many SDC files were found, because they are a property of the
    L8 document alone."""
    if load_error:
        return [load_error]
    issues: List[str] = []
    for name, slot in sorted(l8_clock_periods(doc).items()):
        distinct = _distinct_periods(slot["periods"])
        if len(distinct) > 1:
            issues.append(
                f"L8: clock {name!r} is declared with {len(distinct)} "
                f"conflicting periods ("
                + ", ".join(f"{p:g} ns" for p in distinct)
                + ") — an SDC cannot be validated against a contradictory "
                  "constraint set; fix the L8 producer or remove the "
                  "duplicate clock record")
    return issues


def l8_sdc_issues(doc: Optional[Dict[str, Any]],
                  per_file: List[Tuple[str, str]]) -> List[str]:
    """Cross-check L8's clock periods against the SDCs.

    ``per_file`` is ``[(display_name, sdc_text), ...]``. Coverage ("is this
    clock constrained at all?") is judged over the UNION of the SDCs — a
    project legitimately ships an ASIC SDC and an FPGA SDC that name the
    same physical clock differently (`-name clk_main [get_ports {clk}]`), so
    a clock counts as constrained when matched by name OR by target port in
    ANY of them. A period MISMATCH is reported per file, against the file
    that carries it.
    """
    clocks = l8_clock_periods(doc)
    if not clocks:
        return []
    parsed = [(nm, sdc_clock_constraints(txt)) for nm, txt in per_file]
    issues: List[str] = []
    for name, slot in sorted(clocks.items()):
        distinct = _distinct_periods(slot["periods"])
        if len(distinct) > 1:
            # Already reported by l8_self_issues; there is no single L8
            # period to compare the SDC against.
            continue
        aliases = {name} | set(slot["ports"])
        constrained_anywhere = False
        for fname, constraints in parsed:
            for c in constraints:
                if not ((c["name"] in aliases) or (c["ports"] & aliases)):
                    continue
                constrained_anywhere = True
                if c["generated"] or c["period"] is None or not distinct:
                    continue
                if not _periods_agree(c["period"], distinct[0]):
                    label = c["name"] or sorted(c["ports"])[0]
                    issues.append(
                        f"{fname}: create_clock {label!r} -period "
                        f"{c['period']:g} ns disagrees with L8 clock {name!r} "
                        f"period {distinct[0]:g} ns")
        if not constrained_anywhere:
            detail = f" (period {distinct[0]:g} ns)" if distinct else ""
            issues.append(
                f"L8 declares clock {name!r}{detail} but no SDC constrains "
                f"it — no create_clock matches that name or its source pin")
    return issues


# ----- the whole decision, as one pure function ---------------------

_VERDICT_FOR_RC = {RC_PASS: "PASS", RC_FAIL: "FAIL",
                   RC_NOT_CHECKED: "SKIP"}


class Verdict(NamedTuple):
    """Everything the CLI needs, decided WITHOUT writing anything.

    Factored out so the behaviour can be exercised — and measured across a
    corpus — by DRIVING it, not by asserting on this file's source text. A
    source-text assertion passes while the code it names raises at runtime;
    only a call proves an exit code."""
    rc: int
    lines: List[str]
    report: Dict[str, Any]


def evaluate(project: Path, l8: Optional[Path] = None) -> Verdict:
    """Decide the verdict for `project`. READ-ONLY: never writes, never
    creates a directory, so it is safe to run over a tracked corpus."""
    project = Path(project)
    roots = [str(r) for r in search_roots(project)]
    superseded: List[Tuple[Path, str]] = []

    def _verdict(rc: int, lines: List[str], issues: List[str],
                 sdc_files: List[Path]) -> Verdict:
        return Verdict(rc, lines, {
            "verdict": _VERDICT_FOR_RC[rc],
            "exit_code": rc,
            "search_roots": roots,
            "sdc_files_checked": [str(p) for p in sdc_files],
            # The denominator this verdict declined to grade, ALWAYS present
            # so a narrowed scope is visible in the evidence file rather than
            # inferable only from a count that got smaller.
            "sdc_files_superseded": [
                {"path": str(p), "top_entity": t,
                 "reason": "generated deck for a top the design does not "
                           "declare"}
                for p, t in superseded],
            "l8": str(l8) if l8 else None,
            "issues": issues,
        })

    # A positional that is not a directory resolved two search roots that
    # cannot exist and read zero files. At exit 0 that was an ordinary PASS.
    if not project.is_dir():
        return _verdict(RC_NOT_CHECKED,
                        [unusable_positional_message(project)], [], [])

    sdc_files = find_sdc_files(project)
    # L8 self-consistency is a property of L8 alone, so it is evaluated
    # BEFORE the no-SDC skip: a contradictory constraint document must not
    # be able to hide behind an empty SDC glob.
    l8_doc, l8_err = load_l8(l8)
    l8_self = l8_self_issues(l8_doc, l8_err)

    if not sdc_files:
        # An empty glob has several very different causes and used to print
        # the same line at the same exit code for all of them.
        #
        # Tested only once the declared roots have come back empty, so a real
        # project that merely happens to live under a path segment named
        # `reference` is still validated normally.
        off_limits = positional_inside_off_limits(project)
        if off_limits:
            return _verdict(
                RC_NOT_CHECKED,
                [off_limits_positional_message(project, off_limits)], [], [])
        scan = scan_for_stray_sdc(project)
        misdirected = misdirection_diagnostic(scan, project)
        pre = ([misdirected] if misdirected else []) + l8_self
        if pre:
            return _verdict(RC_FAIL, _fail_lines(pre), pre, [])
        # Nothing was READ. NOT CHECKED — with the scope that was searched.
        return _verdict(RC_NOT_CHECKED,
                        [no_sdc_anywhere_message(project, scan)], [], [])

    # A deck this flow's own generator wrote for a top the design does not
    # declare constrains nothing the run produces; grading it answers "are
    # the design's constraints complete?" with the presence of a stale
    # artifact. Set aside, never deleted, and always disclosed.
    part = partition_decks(project, sdc_files)
    superseded = part.superseded
    if not part.live:
        # Every file found is an orphan. NOT CHECKED, never PASS: no
        # constraint file for a declared top was read.
        if l8_self:
            return _verdict(RC_FAIL, _fail_lines(l8_self), l8_self, [])
        return _verdict(RC_NOT_CHECKED,
                        [all_decks_superseded_message(project, part)], [], [])
    sdc_files = part.live

    issues: List[str] = []
    for sdc in sdc_files:
        text = sdc.read_text(errors="ignore")
        if "create_clock" not in text:
            issues.append(f"{sdc.name}: missing create_clock")
        if "set_input_delay" not in text:
            issues.append(f"{sdc.name}: missing set_input_delay")
        if "set_output_delay" not in text:
            issues.append(f"{sdc.name}: missing set_output_delay")
    issues += l8_self
    issues += l8_sdc_issues(
        l8_doc, [(s.name, s.read_text(errors="ignore")) for s in sdc_files])
    if issues:
        return _verdict(RC_FAIL,
                        _fail_lines(issues, superseded_note(part)),
                        issues, sdc_files)
    n_clocks = len(l8_clock_periods(l8_doc))
    return _verdict(RC_PASS, [
        f"[PASS] sdc_validator_check: {len(sdc_files)} SDC file(s) OK"
        + (f", {n_clocks} L8 clock(s) cross-checked" if n_clocks else "")
        + superseded_note(part)
    ], [], sdc_files)


def _fail_lines(issues: List[str], note: str = "") -> List[str]:
    return ([f"[FAIL] sdc_validator_check: {len(issues)} issue(s){note}"]
            + [f"  - {i}" for i in issues[:5]])


# ----- CLI ----------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--l8", type=Path,
                   help="L8_TIMING_WAVEFORM JSON to cross-check the SDC "
                        "clock periods against")
    p.add_argument("--json", type=Path, help="optional JSON output path")
    args = p.parse_args()
    v = evaluate(args.project, args.l8)
    for line in v.lines:
        print(line)
    if args.json:
        # Written on EVERY verdict, so a FAIL and a NOT-CHECKED both leave
        # their evidence file behind — a missing report used to be the only
        # external signal that the program never ran.
        try:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(v.report, indent=2))
        except OSError:
            pass
    return v.rc


if __name__ == "__main__":
    sys.exit(main())
