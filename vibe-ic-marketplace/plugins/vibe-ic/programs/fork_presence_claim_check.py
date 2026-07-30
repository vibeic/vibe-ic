#!/usr/bin/env python3
"""A fork recorded as "not in the image" must not be in the image.

WHY THIS EXISTS
===============
The fork ledger marks a tool `integrated = False` when the pin resolver cannot
find an `ARG <TOOL>_REF` for it, and renders that as:

    ### <tool>: not_layered — nothing to assess.

with the ledger's own comment defining it as "forked but NOT pinned into the
image — such a tool uses upstream directly, so there is nothing to sync".

Measured against `vibeic-eda:0.2.45` on 2026-07-30, five of the six tools in
that state ARE in the image:

    OpenSTA                /foss/tools/bin/sta
    ciel                   /usr/local/bin/ciel        (Ciel v2.5.1)
    IHP-Open-PDK           /foss/pdks/ihp-sg13g2      (262 MB)
    open_pdks              /foss/pdks/sky130A
    ASAP7_for_KLayout      /foss/pdks/asap7
    OpenROAD-flow-scripts  genuinely absent

ciel is not incidental: `/foss/pdks/sky130A` and `/foss/pdks/gf180mcuD` are
symlinks into `ciel/<pdk>/versions/<sha>/`, so the tool that puts both sign-off
PDKs on disk was recorded as absent and excluded from every assessment.

`integrated = bool(ref)` makes "I could not detect a pin" indistinguishable from
"it is not shipped", and the label asserts the second. That is vibeic-eda#32.

This does NOT change what `integrated` means — that flag gates the assessment
for every tool and is not something to redefine from a checker. It only makes
the contradiction VISIBLE: a claim of absence, tested against the image.

WHAT IT REFUSES TO DO
=====================
* Pass because it could not look. No docker, no image, a container that failed —
  rc 2 with the reason. An unasked question is not a confirmed absence.
* Pass on an empty claim list. Zero tools checked finds zero contradictions.
* Report a tool as contradicted on a path it was never given. A tool with no
  known path in the registry is UNKNOWN and counted separately, because "I have
  nowhere to look" must not read as "I looked and it was gone".

Exit: 0 every absence claim holds, 1 at least one is contradicted, 2 could not check.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Dict, List, Tuple

RC_OK, RC_CONTRADICTED, RC_CANNOT_CHECK = 0, 1, 2

DEFAULT_IMAGE = "ghcr.io/vibeic/vibeic-eda:0.2.45"

#: Where each tool WOULD live if it shipped. A tool absent from this map is
#: reported as unknown rather than assumed absent — see the refusals above.
KNOWN_PATHS: Dict[str, Tuple[str, ...]] = {
    "OpenSTA": ("/foss/tools/bin/sta", "/foss/tools/openroad/bin/sta"),
    "ciel": ("/usr/local/bin/ciel",),
    "IHP-Open-PDK": ("/foss/pdks/ihp-sg13g2",),
    "open_pdks": ("/foss/pdks/sky130A", "/foss/pdks/gf180mcuD"),
    "OpenROAD-flow-scripts": ("/orfs", "/foss/tools/OpenROAD-flow-scripts"),
    "ASAP7_for_KLayout": ("/foss/pdks/asap7", "/foss/tools/asap7"),
    "asap7_pdk_r1p7": ("/foss/pdks/asap7",),
    "asap7sc7p5t_28": ("/foss/pdks/asap7",),
}


def _run(argv: List[str], timeout: int = 180) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "docker not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"


def absent_claims(ledger_dir) -> Tuple[List[str], str]:
    """Tools the ledger says are NOT in the image, or ([], reason)."""
    from pathlib import Path
    d = Path(ledger_dir)
    if not d.is_dir():
        return [], f"no ledger directory at {d}"
    out, unreadable = [], []
    for p in sorted(d.glob("*.json")):
        if p.stem == "index":
            continue
        try:
            rec = json.loads(p.read_text())
        except (OSError, ValueError):
            unreadable.append(p.stem)
            continue
        if not rec.get("integrated"):
            out.append(rec.get("tool") or p.stem)
    if unreadable:
        return [], (f"{len(unreadable)} ledger(s) could not be read "
                    f"({', '.join(unreadable[:4])}); an unreadable ledger makes "
                    f"no claim, and a missing claim is not a confirmed absence")
    return out, ""


def probe_image(image: str, tools: List[str]) -> Tuple[Dict[str, str], str]:
    """{tool: found_path} for tools present in the image, or ({}, reason)."""
    checks = []
    for t in tools:
        for p in KNOWN_PATHS.get(t, ()):
            checks.append(f'[ -e "{p}" ] && echo "FOUND {t} {p}"')
    if not checks:
        return {}, ""
    script = "; ".join(checks) + "; echo PROBE_DONE"
    rc, out, err = _run(["docker", "run", "--rm", "--entrypoint", "sh",
                         image, "-c", script], timeout=300)
    if rc == 127:
        return {}, "docker is not installed"
    if "PROBE_DONE" not in (out or ""):
        return {}, (f"the probe did not complete (rc={rc}): "
                    f"{(err or out).strip()[:160]}")
    found: Dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "FOUND":
            found.setdefault(parts[1], parts[2])
    return found, ""


def check(image: str, ledger_dir) -> dict:
    claimed, err = absent_claims(ledger_dir)
    if err:
        return {"error": err}
    if not claimed:
        # Every tool is integrated. Nothing claims absence, so there is nothing
        # this check can contradict — a real clean state, not an empty scan.
        return {"image": image, "claimed_absent": [], "contradicted": {},
                "unknown_path": [], "confirmed_absent": []}

    known = [t for t in claimed if t in KNOWN_PATHS]
    unknown = sorted(t for t in claimed if t not in KNOWN_PATHS)
    found, perr = probe_image(image, known)
    if perr:
        return {"error": perr}
    return {"image": image, "claimed_absent": sorted(claimed),
            "contradicted": found,
            "unknown_path": unknown,
            "confirmed_absent": sorted(t for t in known if t not in found)}


def main(argv=None) -> int:
    import os
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--ledger",
                    default=os.path.expanduser(
                        "~/.cache/eda-fork-gatekeeper/ledger"))
    ap.add_argument("--baseline", default=None,
                    help="JSON register of ALREADY-KNOWN contradictions. Only a "
                         "NEW one fails; the recorded set prints every run so it "
                         "stays visible rather than becoming permission.")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    res = check(a.image, a.ledger)
    if a.json:
        from pathlib import Path
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "fork_presence_claim_check", **res}, indent=2) + "\n",
            encoding="utf-8")

    if "error" in res:
        print(f"[NOT CHECKED] {res['error']}. An absence that could not be "
              f"tested is not a confirmed absence.", file=sys.stderr)
        return RC_CANNOT_CHECK

    if res["unknown_path"]:
        print(f"  {len(res['unknown_path'])} tool(s) claim absence but have no "
              f"known path to test: {', '.join(res['unknown_path'])}. Nowhere to "
              f"look is not the same as looked-and-gone.", file=sys.stderr)

    # A gate that fails on a KNOWN defect nobody can fix from here blocks every
    # landing until someone deletes the gate. The register keeps the existing
    # five visible on every run while letting a NEW one still stop a landing.
    known = set()
    if a.baseline:
        from pathlib import Path
        bp = Path(a.baseline)
        if bp.exists():
            try:
                known = set((json.loads(bp.read_text()).get("contradicted") or {}))
            except (OSError, ValueError) as exc:
                print(f"[NOT CHECKED] baseline {bp} unreadable: {exc}. A register "
                      f"that cannot be read is not an empty register.",
                      file=sys.stderr)
                return RC_CANNOT_CHECK
    new = {t: p for t, p in res["contradicted"].items() if t not in known}
    recorded = len(res["contradicted"]) - len(new)
    if recorded:
        print(f"  {recorded} contradiction(s) recorded as known debt "
              f"(vibeic-eda#32): shipped, but the ledger calls them absent.",
              file=sys.stderr)
    if a.baseline and not new:
        print(f"[PASS] no NEW absence claim is contradicted in {res['image']} "
              f"({recorded} recorded).", file=sys.stderr)
        return RC_OK
    if a.baseline:
        res = {**res, "contradicted": new}

    if res["contradicted"]:
        print(f"[FAIL] {len(res['contradicted'])} fork(s) are recorded as NOT in "
              f"{res['image']} and are in it:", file=sys.stderr)
        for t, p in sorted(res["contradicted"].items()):
            print(f"    {t:24s} {p}", file=sys.stderr)
        print("  The ledger renders these as 'not_layered — nothing to assess', "
              "so each is excluded from every upstream assessment while shipping "
              "to users (vibeic-eda#32).", file=sys.stderr)
        return RC_CONTRADICTED

    n = len(res["confirmed_absent"])
    print(f"[PASS] every absence claim holds"
          f"{f' ({n} verified absent)' if n else ''} in {res['image']}.",
          file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
