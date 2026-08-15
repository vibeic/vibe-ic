#!/usr/bin/env python3
"""pdk_via_patch_meets_layer_min_width_check.py — a via's metal patch must
be at least as wide as that metal layer's own declared minimum width.

A tech LEF states both halves of this in the same file: `LAYER <m> ... TYPE
ROUTING ... WIDTH w ;` (or `MINWIDTH w ;`) is the layer's minimum width, and
the via states the patch it drops on that layer — in TWO forms, both of which
a router uses:

    VIA M4M5_PR DEFAULT             VIARULE M4M5_PR GENERATE
      LAYER met5 ;                    LAYER met5 ;
      RECT -0.71 -0.71 0.71 0.71 ;    ENCLOSURE 0.31 0.31 ;
                                      LAYER via4 ;
                                      RECT -0.4 -0.4 0.4 0.4 ;

Both say 1.42um: -0.71..0.71 directly, and 0.8 + 2*0.31 by the enclosure
arithmetic. When the patch is narrower than the width, the PDK contradicts
itself, and the contradiction is only invisible while every via happens to sit
in the middle of a wire. It becomes sign-off DRC the moment a wire ENDS on one:
the patch protrudes past the wire end, and in the protrusion the metal is
narrower than the layer's minimum.

MEASURED, not hypothesised (sky130A, 880x880um, 79499 instances, KLayout
sign-off deck on the shipped GDS):

  * the design routed 3 signal segments on the top metal; every one of them
    ended on the PDK's default top via
  * `sky130_fd_sc_hd__nom.tlef` declares `LAYER met5 ... WIDTH 1.6` and, 430
    lines later, gives all five M4M5 vias a 1.42um met5 patch
  * the deck reported 9 `m5.1` (min met5 width) items — 3 sites x 3 edge pairs
  * the geometry matched the via RECT to the nanometre at all three sites
  * replacing each offending polygon with its own bounding box (i.e. "the
    patch is as wide as the wire") and re-running the SAME deck took the run
    from 11 violations to 2, introducing nothing new

The router's own in-loop DRC recorded `violation report: 0` for the same
layout, so nothing upstream of sign-off sees this.

CORPUS, on the image this repo pins — 192 findings over 19 tech LEFs:

    sky130 (12 LEFs)  5 VIA + 5 VIARULE each, all five M4M5_PR* at 1.42um on
                      met5 (min 1.6)
    gf180  ( 6 LEFs)  8 VIA + 4 VIARULE each, every Metal4-Metal5 via under
                      Metal5's 0.44, plus two 2-cut vias 0.020um under
                      Metal2/Metal3
    nangate45 (1)     0 — it was reported NOT MEASURED because the sweep
                      globbed `*.tlef` and its tech LEF is `*.tech.lef`. It is
                      clean, which is a different statement and is now made.

THERE IS NO SUPPRESSION LIST, AND THAT IS THE POINT
---------------------------------------------------
The first version of this checker shipped a baseline recording all 108
findings it could then see. Measured against the real PDKs that made it:

    shipped baseline, 18 tech LEFs : [PASS] 108 recorded finding(s), 0 new
    empty baseline,  the same file : [FAIL] 5 new finding(s)

108 of 108 suppressed across 2 of 2 PDK families — a gate with nothing in the
shipped set it could fail on, while the defect it was written for was open.
A record that covers 100% of what exists is not a debt register; it is the
gate switched off, with a receipt.

So a finding is not suppressed by being written down. It stops being reported
in exactly two ways, both of which are MEASURED here rather than declared:

  (a) THE PDK IS FIXED. Grow the patch to the layer's own minimum and the
      arithmetic no longer fires. Nothing to record and nothing to expire —
      the finding is simply gone. `tools/pdk/pdk_via_min_width_patch.py` in
      the vibeic-eda fork is that transform, and it rewrites BOTH forms above.
  (b) THE LAYER IS OUT OF THE SIGNAL ROUTING RANGE. A latent defect on a layer
      no signal is routed on cannot fire. `--routing-max-layer` states that
      range — from the design's own `RT_MAX_LAYER`, or from
      `_pdk_via_analyzer.routing_layer_upper_bound` — and a finding above it
      is reported as MITIGATED, naming the range that mitigates it. Change the
      range and it comes straight back, because nothing was written down.

SEVERITY. A PDK defect is not something a plugin user can fix, so this never
blocks a design run: the phase-3 wiring emits it as an advisory beside the
route it affects, and escalates the wording when the affected layer is inside
that run's own routing range. `--advisory` gives a caller rc 0 while printing
every finding and the verdict it would otherwise have returned; it lowers the
exit code and hides nothing. The default verdict is FAIL, so anyone who runs
this by hand, and every caller that does not opt out, is told.

Usage:
    pdk_via_patch_meets_layer_min_width_check.py
        [--tech-lef A.tlef ...] [--pdk-root DIR ...] [--image TAG|--from-image]
        [--pdk-key-root DIR ...] [--routing-max-layer N|met4]
        [--advisory] [--json OUT]

Exit codes:
    0 = no unmitigated finding (or --advisory)
    1 = at least one unmitigated finding
    2 = no readable tech LEF (refuses rather than reporting clean)

chip-AGNOSTIC and PDK-AGNOSTIC: pure LEF arithmetic, no layer-name literal,
no per-PDK table, no threshold.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from _pdk_via_analyzer import (_routing_index, parse_tech_lef,
                               patch_extents)

#: The EDA image whose PDK trees this checker reads with `--from-image`. A LIVE
#: pointer: registered in `tools/vibeic-eda/sync_image_version.py`'s
#: `INSTALL_DOC_CANDIDATES`, so `--set` rewrites it and `--check` catches drift.
#: The alternative — naming an image in a comment — is a string nothing
#: resolves, which is how the first version of this file went red on the
#: image-version gate.
DEFAULT_IMAGE = "ghcr.io/vibeic/vibeic-eda:0.2.98"

#: Tech-LEF filename shapes. `*.tlef` alone misses nangate45, whose tech LEF is
#: `NangateOpenCellLibrary.tech.lef` — it was reported NOT MEASURED for exactly
#: that reason and is clean once looked at.
_TECH_LEF_SUFFIXES = (".tlef", ".tech.lef", ".techlef")

#: How much narrower than the layer's own width still counts as equal. LEF
#: distances are decimal micrometres; this is float-comparison slack, NOT a
#: tolerance on the rule.
_EPS = 1e-9

#: How many trailing path components identify a tech LEF when no `--pdk-key-root`
#: is given. The basename alone is not enough — two PDKs may ship the same
#: file name — and the absolute path is not stable across hosts or across a
#: PDK-version bump (the shipped trees sit under a content-hash directory).
#: `<library>/<techlef>/<file>` distinguishes the libraries and survives both.
_KEY_COMPONENTS = 3


def _is_tech_lef(name: str) -> bool:
    return any(name.endswith(s) for s in _TECH_LEF_SUFFIXES)


def lef_key(path: Path, key_roots: List[Path]) -> Tuple[str, str]:
    """`(key, scope)` for one tech LEF.

    Keying on the BASENAME would let two PDKs that ship a same-named tech LEF
    share one identity, so a finding in one would read as a finding in the
    other. Relative to a declared PDK root when one covers the file, and to
    the last few components otherwise — and the report says WHICH, because a
    key whose scope is not stated cannot be compared across runs.
    """
    rp = path.resolve()
    for root in key_roots:
        try:
            return (rp.relative_to(root.resolve()).as_posix(), "pdk-root")
        except ValueError:
            continue
    parts = rp.parts[-_KEY_COMPONENTS:]
    return ("/".join(parts), "path-suffix")


def findings_for_text(text: str, name: str, key: str = "",
                      scope: str = "caller") -> List[dict]:
    """Every (via form, via, routing layer) in one tech LEF's TEXT whose patch
    is narrower than the layer's own minimum width, in either axis.

    Text rather than a path because the caller that matters most — the phase-3
    runner — already holds the tech LEF as a string, resolved host-or-container.
    Making it open a file would add container plumbing that is already solved
    one line above the call site.
    """
    tl = parse_tech_lef(text)
    key = key or name
    out: List[dict] = []
    for blk in tl.blocks:
        for layer, (dx, dy) in sorted(patch_extents(tl, blk).items()):
            rl = tl.routing[layer]
            w = rl.min_width
            if dx + _EPS >= w and dy + _EPS >= w:
                continue
            out.append({
                "tech_lef": name,
                "lef_key": key,
                "key_scope": scope,
                "form": blk.kind,
                "via": blk.name,
                "layer": layer,
                "layer_index": _routing_index(layer),
                "patch_x_um": dx,
                "patch_y_um": dy,
                "layer_min_width_um": w,
                "layer_min_width_from": rl.width_source,
                "narrow_axis": ("x" if dx + _EPS < w else "")
                               + ("y" if dy + _EPS < w else ""),
                # RECORDED, never subtracted. See `_lead_comment_denial`: the
                # sky130 file annotates one of these five vias "we really do
                # not want to use it", and a finding that does not say so
                # claims more than the file does. A comment cannot lower the
                # verdict, or the file under audit would hold the switch.
                "source_denial": blk.source_denial,
                "source_comment": blk.source_comment,
                # The other half of the comparison has a polarity too: a
                # finding rests on the layer's own declared width, and if the
                # file's lead comment retires THAT, the finding rests on a
                # denied declaration. Same rule, same disclosure, no verdict.
                "layer_source_denial": rl.source_denial,
            })
    return sorted(out, key=lambda f: (f["lef_key"], f["form"], f["via"],
                                      f["layer"]))


def findings_for(lef: Path, key_roots: List[Path]) -> List[dict]:
    """`findings_for_text` over a file, with the entry key derived from where
    the file sits rather than from its basename. See `lef_key`."""
    key, scope = lef_key(lef, key_roots)
    return findings_for_text(lef.read_text(errors="ignore"), lef.name,
                             key, scope)


def _parse_max_layer(spec: Optional[str]) -> Optional[int]:
    """`--routing-max-layer` as an index. Accepts a bare index or a layer name
    (`met4`, `Metal4`, `M4`), because callers have it in both forms."""
    if spec is None:
        return None
    s = spec.strip()
    if s.isdigit():
        return int(s)
    return _routing_index(s)


def discover(pdk_roots: List[Path]) -> List[Path]:
    out: List[Path] = []
    for root in pdk_roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and _is_tech_lef(p.name):
                out.append(p)
    # `readlink -f` dedup: the shipped PDK trees are symlink farms onto one
    # content-hash directory, so the same bytes appear under several names.
    seen, uniq = set(), []
    for p in out:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def stage_from_image(image: str, dest: Path) -> Tuple[List[Path], str]:
    """Copy every tech LEF out of `image` into `dest`. `([], reason)` when the
    image cannot be opened — an unreachable image is NOT a clean PDK."""
    pats = " -o ".join(f'-name "*{s}"' for s in _TECH_LEF_SUFFIXES)
    script = (f'find /foss/pdks \\( {pats} \\) 2>/dev/null'
              f' | xargs -r -n1 readlink -f | sort -u'
              f' | while read -r f; do echo "###LEF $f"; cat "$f"; done')
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "bash", image,
             "-lc", script],
            capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return ([], f"docker unusable: {exc}")
    if r.returncode != 0:
        return ([], f"docker rc={r.returncode}: "
                    f"{(r.stderr or '').strip()[:200]}")
    out: List[Path] = []
    cur: Optional[Path] = None
    buf: List[str] = []

    def _flush():
        if cur is not None:
            cur.parent.mkdir(parents=True, exist_ok=True)
            cur.write_text("\n".join(buf) + "\n")
            out.append(cur)

    for line in r.stdout.splitlines():
        if line.startswith("###LEF "):
            _flush()
            cur, buf = dest / line[len("###LEF "):].lstrip("/"), []
        else:
            buf.append(line)
    _flush()
    if not out:
        return ([], f"{image} shipped no tech LEF under /foss/pdks")
    return (out, "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tech-lef", action="append", default=[],
                    help="tech LEF to check (repeatable)")
    ap.add_argument("--pdk-root", action="append", default=[],
                    help="directory to search for tech LEFs (repeatable)")
    ap.add_argument("--pdk-key-root", action="append", default=[],
                    help="entry keys are stated relative to this root "
                         "(repeatable); default is the last "
                         f"{_KEY_COMPONENTS} path components")
    ap.add_argument("--from-image", action="store_true",
                    help=f"read the tech LEFs out of {DEFAULT_IMAGE}")
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--routing-max-layer", default=None,
                    help="highest metal index (or layer name) signals are "
                         "routed on; a finding above it is MITIGATED")
    ap.add_argument("--advisory", action="store_true",
                    help="print everything and return 0. Lowers the exit "
                         "code; hides nothing.")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)

    key_roots = [Path(p) for p in args.pdk_key_root]
    readable = [p for p in (Path(x) for x in args.tech_lef) if p.is_file()]
    readable += discover([Path(p) for p in args.pdk_root])
    staged_note = ""
    tmp: Optional[object] = None
    if args.from_image:
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        got, why = stage_from_image(args.image, Path(tmp.name))
        readable += got
        staged_note = why or f"{len(got)} tech LEF(s) from {args.image}"

    seen, uniq = set(), []
    for p in readable:
        if p.resolve() not in seen:
            seen.add(p.resolve())
            uniq.append(p)
    readable = uniq

    if not readable:
        print("[REFUSE] pdk_via_patch_meets_layer_min_width_check: no "
              "readable tech LEF. An unchecked PDK is not a clean PDK, so "
              "this refuses rather than reporting 0 findings."
              + (f" ({staged_note})" if staged_note else ""), file=sys.stderr)
        return 2

    max_layer = _parse_max_layer(args.routing_max_layer)
    found: List[dict] = []
    for p in readable:
        found.extend(findings_for(p, key_roots))

    open_f, mitigated = [], []
    for f in found:
        li = f["layer_index"]
        if max_layer is not None and li is not None and li > max_layer:
            f["mitigation"] = (f"layer index {li} is above the declared "
                               f"signal routing range (max {max_layer}) — "
                               f"no signal terminates on this via")
            mitigated.append(f)
        else:
            open_f.append(f)

    verdict = "FAIL" if open_f else "PASS"
    report = {
        "program": "pdk_via_patch_meets_layer_min_width_check",
        "tech_lefs_checked": [str(p) for p in readable],
        "routing_max_layer": max_layer,
        "findings": found,
        "open_findings": open_f,
        "mitigated_findings": mitigated,
        "verdict": verdict,
        "exit_code": 0 if (args.advisory or not open_f) else 1,
    }
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")

    if staged_note:
        print(f"  {staged_note}")
    for f in open_f:
        # The WORD and the SENTENCE it came from. A finding that says the file
        # denies its own via, without quoting the file, cannot be checked by
        # the person reading it.
        note = (f" [the block's lead comment carries a denial "
                f"(\"{f['source_denial']}\"): \"{f['source_comment']}\"]"
                if f["source_denial"] else "")
        print(f"  [OPEN] {f['lef_key']}: {f['form']} {f['via']} puts a "
              f"{f['patch_x_um']:g} x {f['patch_y_um']:g} um patch on "
              f"{f['layer']}, whose own minimum "
              f"{f['layer_min_width_from']} in the same file is "
              f"{f['layer_min_width_um']:g} um "
              f"(narrow in {f['narrow_axis']}){note}")
    for f in mitigated:
        print(f"  [MITIGATED] {f['lef_key']}: {f['form']} {f['via']} on "
              f"{f['layer']} — {f['mitigation']}")

    if open_f:
        forms = sorted({f["form"] for f in open_f})
        print(f"[{'ADVISORY' if args.advisory else 'FAIL'}] {len(open_f)} via "
              f"patch(es) narrower than their own layer's minimum width, over "
              f"{len(readable)} tech LEF(s) ({'+'.join(forms)} form(s); "
              f"{len(mitigated)} mitigated). Each is a sign-off DRC violation "
              f"wherever a wire terminates on that via, and the router's "
              f"in-loop DRC does not see it. FIX: grow the patch to the "
              f"layer's own minimum in the PDK, or take the layer out of the "
              f"signal routing range. Recording them does not.")
        if args.advisory:
            print("  (--advisory: returning 0. The verdict above is FAIL.)")
        if tmp is not None:
            tmp.cleanup()
        return 0 if args.advisory else 1

    print(f"[PASS] {len(readable)} tech LEF(s): every via patch is at least "
          f"as wide as its own layer's declared minimum width"
          + (f" ({len(mitigated)} mitigated by the declared routing range)"
             if mitigated else "") + ".")
    if tmp is not None:
        tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
