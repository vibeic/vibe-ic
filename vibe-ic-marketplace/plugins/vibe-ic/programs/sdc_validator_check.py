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
     .sdc files elsewhere, the program now exits 1 with
     `SDC_SEARCH_ROOT_MISDIRECTED` and names both the roots it searched and
     the files it found. A project with no .sdc anywhere still SKIPs at
     exit 0 — that case is blocked by `sdc_syntax_check`, step 8's first
     all_of member.

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
"""
import argparse, json, os, re, sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl

# ----- search roots and the misdirection diagnostic ------------------

#: The directories this program validates, as (display, resolver). The
#: positional is the PROJECT ROOT; these are resolved from it, which is why
#: handing the gate `phase2/stage2/constraints` produced the doubled
#: `phase2/stage2/constraints/phase2/stage2/constraints`.
_SEARCH_ROOTS = (
    ("phase2/stage1/fpga", _pl.fpga_early_dir),
    ("phase2/stage2/constraints", _pl.constraints_dir),
)

#: Pruned from the stray scan: VCS/tool metadata that cannot hold a
#: project's constraints. NOTHING else is pruned — a vendor .sdc under
#: `input/` is still evidence that the project carries constraint files the
#: declared search roots do not see, which is what the diagnostic reports.
_SCAN_PRUNE_DIRS = frozenset({".git", ".hg", ".svn", "__pycache__",
                              ".venv", "node_modules"})

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


def stray_sdc_files(project: Path,
                    limit: int = _STRAY_SCAN_LIMIT) -> List[Path]:
    """`.sdc` files under `project` that no search root covers.

    Only called when the search roots yielded nothing, so an empty result
    means "this project genuinely ships no SDC" and a non-empty one means
    "the SDC exists, the searched roots just do not see it".

    A search root is skipped but NOT pruned: `find_sdc_files` globs `*.sdc`
    directly under it, so `phase2/stage2/constraints/sub/top.sdc` is an SDC
    the roots cannot see and is correctly reported as one."""
    root = Path(project)
    covered = {r.resolve() for r in search_roots(root)}
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=None):
        dirnames[:] = sorted(d for d in dirnames if d not in _SCAN_PRUNE_DIRS)
        here = Path(dirpath)
        try:
            if here.resolve() in covered:
                continue
        except OSError:
            pass
        for fn in sorted(filenames):
            if fn.endswith(".sdc"):
                found.append(here / fn)
                if len(found) >= limit:
                    return found
    return found


def misdirected_search_root_issue(project: Path) -> Optional[str]:
    """The `SDC_SEARCH_ROOT_MISDIRECTED` diagnostic, or None when the
    project truly carries no SDC at all."""
    strays = stray_sdc_files(project)
    if not strays:
        return None
    root = Path(project)
    shown = []
    for s in strays:
        try:
            shown.append(str(s.relative_to(root)))
        except ValueError:
            shown.append(str(s))
    count = (f"at least {len(strays)}" if len(strays) >= _STRAY_SCAN_LIMIT
             else str(len(strays)))
    return (
        "SDC_SEARCH_ROOT_MISDIRECTED: the searched roots ("
        + ", ".join(d for d, _ in _SEARCH_ROOTS)
        + f" under {root}) hold no .sdc, but the project carries "
        + f"{count} .sdc file(s) elsewhere: "
        + ", ".join(shown)
        + " — step 8 cannot be certified from files it did not read. Either "
          "the positional handed to sdc_validator_check is not the project "
          "root, or the SDC producer wrote outside the declared constraints "
          "directory")


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


def _emit(args, sdc_files, issues) -> None:
    """Print the verdict and — always, so a FAIL leaves its evidence file
    behind too — write the JSON report when one was requested."""
    if issues:
        print(f"[FAIL] sdc_validator_check: {len(issues)} issue(s)")
        for i in issues[:5]:
            print(f"  - {i}")
    if args.json:
        try:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps({
                "verdict": "FAIL" if issues else "PASS",
                "search_roots": [str(r) for r in search_roots(args.project)],
                "sdc_files_checked": [str(p) for p in sdc_files],
                "l8": str(args.l8) if args.l8 else None,
                "issues": issues,
            }, indent=2))
        except OSError:
            pass


# ----- CLI ----------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--l8", type=Path,
                   help="L8_TIMING_WAVEFORM JSON to cross-check the SDC "
                        "clock periods against")
    p.add_argument("--json", type=Path, help="optional JSON output path")
    args = p.parse_args()
    sdc_files = find_sdc_files(args.project)
    # L8 self-consistency is a property of L8 alone, so it is evaluated
    # BEFORE the no-SDC skip: a contradictory constraint document must not
    # be able to hide behind an empty SDC glob.
    l8_doc, l8_err = load_l8(args.l8)
    l8_self = l8_self_issues(l8_doc, l8_err)
    if not sdc_files:
        # An empty glob has two very different causes and used to print the
        # same line at the same exit code for both. Separate them before
        # skipping: a project that carries .sdc the search roots cannot see
        # has NOT been validated, and must not exit 0.
        misdirected = misdirected_search_root_issue(args.project)
        pre = ([misdirected] if misdirected else []) + l8_self
        if pre:
            _emit(args, [], pre)
            return 1
        print("[SKIP] sdc_validator_check: no .sdc files")
        return 0
    issues = []
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
    _emit(args, sdc_files, issues)
    if issues:
        return 1
    n_clocks = len(l8_clock_periods(l8_doc))
    print(f"[PASS] sdc_validator_check: {len(sdc_files)} SDC file(s) OK"
          + (f", {n_clocks} L8 clock(s) cross-checked" if n_clocks else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
