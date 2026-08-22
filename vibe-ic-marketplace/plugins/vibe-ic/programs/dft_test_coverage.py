#!/usr/bin/env python3
"""dft_test_coverage.py — raw FAULT coverage vs sign-off TEST coverage (#603).

WHY (vibe-ic#603)
=================
The OSS Fault engine reports RAW FAULT coverage, ``detected / total_faults``.
Professional ATPG sign-off reports TEST coverage, ``detected / (total -
untestable)``, where the untestable (AU, ATPG-untestable) faults — those NO
test can detect — are removed from the denominator. On a design wrapped in a
pad frame wider than its core (``caravel_user_project``: a 16-bit counter
inside a 128-bit-LA / 38-bit-GPIO / 32-bit-Wishbone frame) most stuck-at faults
sit on nets the core never connects. They are untestable BY CONSTRUCTION, so
the raw ratio drags below the 95 % foundry floor on exactly the design where it
means least. This program computes BOTH numbers and keeps them distinguishable;
it never lets one stand in for the other.

WHAT IT IS, AND IS NOT
======================
`atpg_untestable_fault_classify` answers the STRUCTURAL half — which NETS can
carry no test — from the cut netlist + liberty. This program is the COVERAGE
half: it reads Fault's own coverage metadata (``coverage.yml``: the fault
points and the sa0/sa1 detected sets), maps each fault site to its net, and
computes ``test_coverage_pct`` by removing from the denominator only the
UNCOVERED faults whose net the classifier proved untestable.

SOUNDNESS — the intersection with Fault's OWN result is the load-bearing guard
====================================================================
A false PASS (excluding a fault that IS testable, inflating coverage) is the
one failure mode that matters. Two independent guards make that impossible:

  1. AN EXCLUDED FAULT MUST BE ONE FAULT LEFT UNDETECTED. The excluded set is
     ``uncovered ∩ untestable_net``. A fault Fault DETECTED is testable by
     demonstration and is NEVER removed — so the net classifier's coarseness
     (it works per-NET; testability is per-FAULT-polarity) cannot inflate the
     number: a constant-driven primary output whose net is marked
     "uncontrollable" but whose sa1 Fault detected keeps that sa1 in the
     denominator, and only its genuinely-redundant sa0 is removed. Fault's own
     detection result disambiguates the polarity for free.

  2. THE ACCOUNTING CANNOT EXCEED 100 %. ``covered`` and ``excluded`` are
     disjoint subsets of the 2·|faultPoints| universe (excluded ⊆ uncovered =
     universe − covered), so ``covered + excluded ≤ total`` and therefore
     ``test = covered/(total − excluded) ≤ 100`` ALWAYS. A computed value above
     100 % would be a bug and is asserted against.

Fault's ``sa0Uncovered`` / ``sa1Uncovered`` LISTS are deliberately NOT used for
the denominator: on the measured caravel artefact they carry 746 + 746 entries
while ``total − covered`` is 1139, i.e. they double-count. Uncovered is derived
as ``universe − covered`` so the arithmetic identity holds.

chip-AGNOSTIC: cut netlist + liberty + Fault coverage metadata in, two coverage
numbers out. No PDK, vendor or design name appears in any rule.

USAGE
-----
    dft_test_coverage.py --cut-netlist cut_netlist.v --coverage-yml coverage.yml \\
        --liberty a.lib [--liberty b.lib] [--top MODULE] [--json OUT]

EXIT CODES
----------
    0 = computed        2 = could not compute (unreadable input, no liberty
                            resolved, no fault points, classifier refused)

There is no exit 1: this program MEASURES, it does not judge. The gate
(dft_atpg_coverage_check) that consumes ``test_coverage_pct`` is where a verdict
belongs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atpg_untestable_fault_classify as au  # noqa: E402
import _dft_bit_expand as bx  # noqa: E402
from _source_record_merge import merge_source_records  # noqa: E402

RC_OK, RC_CANNOT = 0, 2

# Liberty output-pin roles are read from the liberty in the classifier; here we
# only need the fault-site → net mapping, which the classifier's own module
# parse already resolves pin-by-pin. A fault site in Fault's coverage.yml is one
# of three shapes:
#   `la_data_in [100]`  — a bit-selected port/wire net  → `la_data_in[100]`
#   `_195_.A1`          — an instance pin               → the net at that pin
#   `_332_`             — a bare wire net               → itself
_SITE_BIT_RE = re.compile(r'^([\w$\\/.\[\]-]+?)\s*\[\s*(\d+)\s*\]$')
_SITE_PIN_RE = re.compile(r'^(\\?[^\s.]+)\.(\w+)$')


def parse_coverage_yaml(text: str) -> dict:
    """Fault's coverage.yml → {ratio, faultPoints, sa0Covered, sa1Covered}.

    A hand parse (not a YAML dep): the file is a flat set of ``key:`` sections
    each followed by ``- item`` lines. The `ratio` scalar and the four list
    sections are all this program needs. Robust to the leading `\\` Verilog
    escapes Fault emits on hierarchical names (``\\_327_.d``).
    """
    ratio = None
    sections: dict = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r'^([A-Za-z]\w*):\s*(.*)$', line)
        if m:
            cur = m.group(1)
            if cur == "ratio":
                try:
                    ratio = float(m.group(2))
                except (TypeError, ValueError):
                    ratio = None
                cur = None
            else:
                sections.setdefault(cur, [])
            continue
        if cur is not None:
            s = line.strip()
            if s.startswith("- "):
                sections[cur].append(s[2:].strip())
    return {
        "ratio": ratio,
        "faultPoints": sections.get("faultPoints", []),
        "sa0Covered": sections.get("sa0Covered", []),
        "sa1Covered": sections.get("sa1Covered", []),
    }


def build_pin_net_map(instances) -> dict:
    """``{(inst, pin): net}`` from the classifier's parsed instance list."""
    out: dict = {}
    for _cell, inst, conns in instances:
        for pin, net in conns.items():
            out[(inst, pin)] = net.strip().lstrip("\\").rstrip()
    return out


def site_to_net(site: str, pin_net: dict):
    """Map a Fault fault site to the net it sits on, or None if unmappable.

    None → NOT excludable (conservative: an unmapped site is never removed from
    the denominator, so a mapping gap can only leave coverage lower, never
    inflate it)."""
    s = site.strip()
    m = _SITE_BIT_RE.match(s)
    if m:
        return m.group(1).strip() + "[" + m.group(2) + "]"
    m = _SITE_PIN_RE.match(s)
    if m:
        return pin_net.get((m.group(1).lstrip("\\").rstrip(), m.group(2)))
    return s.lstrip("\\").rstrip()


def compute(cut_netlist: Path, coverage_yml: Path, liberties=None, top=None,
            directions=None) -> dict:
    """Pure computation. Returns the test-coverage dict (or a refusal dict).

    ``directions`` — a pre-parsed ``{cell: {pin: dir}}`` map may be supplied
    directly (the in-flow caller reads the std-cell Liberty out of the EDA
    container and parses it host-side); otherwise it is read from ``liberties``
    (file paths). Exactly one source of pin directions is required."""
    cyaml = parse_coverage_yaml(coverage_yml.read_text(errors="replace"))
    points = cyaml["faultPoints"]
    if not points:
        return {"computed": False,
                "reason": "no faultPoints in coverage.yml — Fault enumerated "
                          "no fault site, so there is no coverage to split"}

    # Structural untestable NET set — the classifier is the oracle for WHICH
    # nets can carry no test; we intersect its answer with Fault's uncovered
    # faults below.
    if directions is None:
        # Same rule as the classifier's own `--liberty` merge: a liberty that
        # names a cell but declares no pin DIRECTION for it (a `pg_pin`-only
        # block) yields `{cell: {}}`, and under `dict.update` that emptiness
        # would erase another liberty's real pin map purely because it sorted
        # later. An emptied cell drops out of `classify()` entirely, taking its
        # observability edges with it, which INFLATES the reported coverage.
        directions = merge_source_records(
            (au.parse_liberty_pin_directions(p.read_text(errors="replace"))
             for p in (Path(lp) for lp in (liberties or [])) if p.is_file()),
            on_conflict="richer",
        )[0]
    else:
        directions = dict(directions)
    if not directions:
        return {"computed": False,
                "reason": "no liberty resolved — pin directions unknown, so no "
                          "net can be soundly classified untestable"}
    directions[au._ASSIGN_CELL] = {"Y": "output"}
    directions[bx.CONST_DRIVER_CELL] = {"Y": "output"}  # no input pin → tie source
    cut_text = cut_netlist.read_text(errors="replace")
    mod = au.parse_module(cut_text, top)
    if mod is None or not mod[2]:
        return {"computed": False,
                "reason": f"no module with instances found in {cut_netlist}"}
    name, ports, instances = mod

    # BIT-LEVEL elaboration (#603 item 2): replace the classifier's whole-bus
    # assign edges with per-bit identity gates + constant drivers, so the
    # per-bit unused pad frame (la_data_in[100], io_out middle bits) resolves as
    # unobservable / uncontrollable rather than collapsing into a base name that
    # also carries the CONNECTED bits. Real cell instances are kept as-is; the
    # fault-site → net map is built from THOSE (the synthetic gates carry no
    # fault site). Any assignment that cannot be elaborated bit-exactly is kept
    # as the classifier's coarse whole-bus edge (see _dft_bit_expand soundness).
    real_instances = [(c, i, cc) for (c, i, cc) in instances
                      if c != au._ASSIGN_CELL]
    widths = bx.parse_widths(cut_text)
    extra, opaque_assigns = bx.expand_assignments(cut_text, widths, au._ASSIGN_CELL)
    augmented = real_instances + extra

    lib_masters = {c for c, _i, _c2 in real_instances}
    res = au.classify(ports, augmented, directions, au.constant_cells(directions))
    if not res["nets"] or len(res["unresolved_cells"]) >= len(lib_masters):
        return {"computed": False,
                "reason": (f"{len(res['unresolved_cells'])} of {len(lib_masters)} "
                           "cell masters did not resolve against the liberty — "
                           "no driver/load edge was built, so the untestable set "
                           "would be empty for want of input, not for want of "
                           "untestable faults")}
    # The two untestable net classes are trusted DIFFERENTLY, from measured
    # reliability across the corpus (caravel / subservient / sha256):
    #   * UNCONTROLLABLE (a net driven only by constants) is a LOCAL structural
    #     fact and measured reliable — 0 covered faults land on an uncontrollable
    #     net on subservient/sha256; caravel's 262 are the expected constant-
    #     driven observable-PO case, disambiguated per-polarity by intersecting
    #     with Fault's uncovered set.
    #   * UNOBSERVABLE is a GLOBAL backward closure and measured fragile on large
    #     flat cut netlists — hundreds of covered faults landed on nets it called
    #     unreachable (a bit-elaboration limit). It is therefore gated by the
    #     per-net covered oracle below (never exclude on a net Fault detected).
    uncontrollable = set(res["uncontrollable"])
    unobservable = set(res["unobservable"])
    pin_net = build_pin_net_map(real_instances)

    # ── raw accounting: Fault's OWN, so raw == Fault's ratio exactly ──────
    # total = 2·|faultPoints|, covered = |sa0Covered| + |sa1Covered| — these
    # are the numerator/denominator behind Fault's `ratio` scalar, reproduced
    # verbatim so the raw number this program reports never disagrees with the
    # engine's. (uncovered is derived as total − covered, NOT from the
    # sa*Uncovered lists, which double-count — see module docstring.)
    total = 2 * len(points)
    covered = len(cyaml["sa0Covered"]) + len(cyaml["sa1Covered"])
    raw_pct = (covered / total * 100.0) if total else 0.0

    # ── excluded set: uncovered ∩ untestable, per polarity, unique sites ──
    # Uncovered per polarity = the unique fault points NOT in that polarity's
    # covered set. A fault is excludable only if it is (a) one Fault left
    # undetected AND (b) on a net the classifier proved untestable AND (c) on a
    # net Fault detected NO fault on.
    #
    # RULE (c) is the load-bearing per-net soundness oracle. A net that carries
    # even one DETECTED fault is testable by demonstration, so the structural
    # closure that called it untestable is WRONG on that net — and a bit-level
    # elaboration bug (measured on sha256/subservient: hundreds of covered faults
    # landed on nets the observability closure called unreachable) becomes
    # HARMLESS, because such a net is never a source of exclusions. Only nets on
    # which Fault agrees "nothing here was detected" can contribute untestable
    # faults, so a closure error can no longer over-exclude a testable fault.
    uniq_points = set(points)
    cov0 = uniq_points & set(cyaml["sa0Covered"])
    cov1 = uniq_points & set(cyaml["sa1Covered"])
    unc0 = uniq_points - cov0
    unc1 = uniq_points - cov1
    covered_nets = {n for n in (site_to_net(s, pin_net) for s in (cov0 | cov1))
                    if n is not None}

    def _untestable(net):
        if net is None:
            return False
        if net in uncontrollable:            # reliable, per-polarity via uncovered
            return True
        if net in unobservable and net not in covered_nets:   # closure-bug-gated
            return True
        return False

    def excl(uncovered_sites):
        return [s for s in uncovered_sites if _untestable(site_to_net(s, pin_net))]

    e0, e1 = excl(unc0), excl(unc1)
    excluded = len(e0) + len(e1)
    # GUARD 2 (hard invariant): an excluded fault is one left undetected, so the
    # excluded count can never exceed the uncovered count. Clamp to enforce
    # test ≤ 100 % even if Fault's list/point accounting is internally
    # inconsistent, and record that the clamp did not fire in the common case.
    uncovered_faults = max(total - covered, 0)
    excluded_effective = min(excluded, uncovered_faults)
    denom = total - excluded_effective
    test_pct = (covered / denom * 100.0) if denom else 0.0

    # GUARD 1 (informational): covered faults on an UNCONTROLLABLE net — a
    # non-zero count is the expected net-vs-fault coarseness (a detected fault on
    # a constant-driven observable primary output; the DETECTED polarity stays in
    # the denominator, only the redundant uncovered polarity is removed).
    coarse0 = sum(1 for s in cov0 if site_to_net(s, pin_net) in uncontrollable)
    coarse1 = sum(1 for s in cov1 if site_to_net(s, pin_net) in uncontrollable)

    # GUARD 3 (diagnostic): covered faults on an UNOBSERVABLE net. On a large flat
    # cut netlist the backward closure calls some reachable nets unreachable; this
    # counts them. It is NOT a soundness failure here because the per-net covered
    # oracle (_untestable) refuses to exclude on ANY net Fault detected — so these
    # nets contribute zero exclusions regardless of the closure's error.
    covered_on_unobservable = sum(
        1 for s in (cov0 | cov1) if site_to_net(s, pin_net) in unobservable)

    # GUARD 2 (hard invariant): an excluded fault is one left undetected, so the
    # excluded count can never exceed the uncovered count → test ≤ 100 %.
    assert test_pct <= 100.0 + 1e-9, (
        f"test_coverage {test_pct} > 100 — excluded ({excluded_effective}) "
        f"exceeded uncovered ({uncovered_faults}); accounting is unsound")
    # HARD per-net soundness: no fault we exclude may sit on a net Fault detected.
    assert not (set(e0) | set(e1)) & {  # excluded sites whose net is covered
        s for s in (set(e0) | set(e1)) if site_to_net(s, pin_net) in covered_nets
        and site_to_net(s, pin_net) not in uncontrollable}, \
        "excluded a fault on an observable covered net — over-exclusion"

    return {
        "computed": True,
        "module": name,
        "cut_netlist": str(cut_netlist),
        "coverage_yml": str(coverage_yml),
        "fault_points": len(points),
        "fault_points_unique": len(uniq_points),
        "total_faults": total,
        "covered_faults": covered,
        # Raw FAULT coverage — Fault's own ratio is authoritative and reported
        # verbatim; the unique-point recomputation is carried alongside so the
        # test/raw comparison uses one consistent basis.
        "fault_reported_ratio_pct": (round(cyaml["ratio"] * 100.0, 4)
                                     if cyaml["ratio"] is not None else None),
        "raw_coverage_pct": round(raw_pct, 4),
        # Sign-off TEST coverage — the number sign-off is judged on.
        "test_coverage_pct": round(test_pct, 4),
        "untestable_faults_excluded": excluded_effective,
        "untestable_faults_excluded_raw": excluded,
        "untestable_nets": len(uncontrollable | unobservable),
        "unobservable_nets": len(res["unobservable"]),
        "uncontrollable_nets": len(res["uncontrollable"]),
        "opaque_assignments": opaque_assigns,
        "excluded_sa0_sites": sorted(e0),
        "excluded_sa1_sites": sorted(e1),
        "covered_on_uncontrollable_net": {"sa0": coarse0, "sa1": coarse1},
        "covered_on_unobservable_net": covered_on_unobservable,
        "lift_pct": round(test_pct - raw_pct, 4),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cut-netlist", required=True)
    ap.add_argument("--coverage-yml", required=True)
    ap.add_argument("--liberty", action="append", default=[])
    ap.add_argument("--top")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    cut = Path(a.cut_netlist)
    cov = Path(a.coverage_yml)
    if not cut.is_file():
        print(f"[SKIP] dft_test_coverage: cut netlist {cut} not readable",
              file=sys.stderr)
        return RC_CANNOT
    if not cov.is_file():
        print(f"[SKIP] dft_test_coverage: coverage.yml {cov} not readable",
              file=sys.stderr)
        return RC_CANNOT

    res = compute(cut, cov, a.liberty, a.top)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(res, indent=2) + "\n")
    if not res.get("computed"):
        print(f"[SKIP] dft_test_coverage: {res.get('reason')}", file=sys.stderr)
        return RC_CANNOT
    print(f"dft_test_coverage: module {res['module']} — raw fault coverage "
          f"{res['raw_coverage_pct']:.4f}% vs TEST coverage "
          f"{res['test_coverage_pct']:.4f}% (excluded "
          f"{res['untestable_faults_excluded']} untestable of "
          f"{res['total_faults']} faults; +{res['lift_pct']:.4f} pts)")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
