#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 #790 — `def_stage_progression_check` called a
real, DRC-clean, LVS-matching routed DEF "fabricated or missing" because it was
smaller in BYTES than the previous stage.

Check 2 enforces byte-monotone stage growth to catch a truncated / fabricated
stage. Byte size is only a PROXY for that; the instance count is the substance,
and a truncated DEF necessarily LOSES components. When the two disagree the
proxy was winning.

Measured on caravel_user_project x sky130A once #789 restored full-die well-tie
taps (134,178 of them):

    floorplan     247,682 B  components=   325  routing=no
    placed     51,885,969 B  components=134503  routing=yes
    post_cts   61,597,082 B  components=134613  routing=yes
    post_hold  61,597,082 B  components=134613  routing=yes
    routed     52,174,653 B  components=134748  routing=yes

    ✗ [size-non-monotone] routed.def (52174653 B) is SMALLER than
      post_hold.def (61597082 B).
    Result: FAIL — one or more stages fabricated or missing.

routed.def is ~15% smaller than post_hold.def yet carries 135 MORE instances:
detailed routing replaces the bulky per-net global-route GUIDE records with
actual wire segments. Independent proof the DEF is real and complete: the GDS
streamed from it is DRC-clean (0 violations) and netgen reports "Circuits match
uniquely" against the gate netlist — neither is possible for a truncated DEF.

Fix: a byte shrink is exempt when the stage STRICTLY GAINED instances. Narrow
and evidence-positive, in the same spirit as the #624 post_cts→post_hold no-op
exemption. A stage that shrinks AND loses (or merely holds) instances still
FAILs, and Check 1 (sha256 distinctness) plus Check 3 (instance-count growth)
are untouched — no fraud path is relaxed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))

_STAGES = ("floorplan", "placed", "post_cts", "post_hold", "routed")


def _def_text(n_components: int, pad: int, routed: bool, tag: str) -> str:
    """A DEF with `n_components` COMPONENTS, padded to a controlled size."""
    lines = ["VERSION 5.8 ;", "DESIGN top ;", "UNITS DISTANCE MICRONS 1000 ;",
             f"COMPONENTS {n_components} ;"]
    for i in range(n_components):
        lines.append(f"   - u{i} CELL + PLACED ( {i*100} {i*50} ) N ;")
    lines.append("END COMPONENTS")
    lines.append("SPECIALNETS 1 ;")
    lines.append("   - VPWR ( * VPWR )" + (" + ROUTED met1 0 ( 0 0 )"
                                           if routed else "") + " ;")
    lines.append("END SPECIALNETS")
    lines.append("NETS 1 ;")
    lines.append("   - n0 ( u0 A )" + (" + ROUTED met1 ( 0 0 ) ( 10 0 )"
                                       if routed else "") + " ;")
    lines.append("END NETS")
    # unique-per-stage filler so sha256 differs and size is controllable
    lines.append(f"# {tag} " + ("x" * max(pad, 1)))
    lines.append("END DESIGN")
    return "\n".join(lines) + "\n"


def _mk(tmp_path: Path, spec) -> Path:
    """spec: list of (stage, n_components, pad, routed)."""
    proj = tmp_path / "proj"
    d = proj / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    for stage, n, pad, routed in spec:
        (d / f"{stage}.def").write_text(_def_text(n, pad, routed, stage))
    return proj


def _run(proj: Path):
    out = proj / "dp.json"
    r = subprocess.run(
        [sys.executable, str(PROG_DIR / "def_stage_progression_check.py"),
         str(proj), "--json", str(out)], capture_output=True, text=True)
    data = json.loads(out.read_text()) if out.is_file() else {}
    return r.returncode, (r.stdout + r.stderr), data


def _rules(data) -> set:
    """Rule names across the gate's JSON channels (errors + warnings)."""
    out = set()
    for key in ("errors", "warnings", "findings"):
        for f in (data.get(key) or []):
            r = f.get("rule")
            if r:
                out.add(r)
            else:
                # older entries carry only a message — key off its shape
                m = str(f.get("message") or "")
                if "SMALLER than" in m:
                    out.add("size-non-monotone")
                elif "components vs" in m:
                    out.add("instance-count-regression")
                elif "routing" in m.lower():
                    out.add("no-routing")
    return out


# ── the defect ──────────────────────────────────────────────────────────
def test_shrink_with_instance_growth_is_not_a_failure(tmp_path):
    """The caravel shape: routed is smaller in bytes but has MORE instances."""
    rc, out, data = _run(_mk(tmp_path, [
        ("floorplan", 5, 10, False),
        ("placed", 100, 200, True),
        ("post_cts", 110, 5000, True),
        ("post_hold", 110, 5001, True),
        ("routed", 120, 100, True),      # smaller bytes, MORE components
    ]))
    assert "size-non-monotone" not in _rules(data), out
    assert rc == 0, out


# ── fraud detection must survive ────────────────────────────────────────
def test_shrink_with_instance_loss_still_fails(tmp_path):
    """A truncated stage LOSES components — still a hard FAIL."""
    rc, out, data = _run(_mk(tmp_path, [
        ("floorplan", 5, 10, False),
        ("placed", 100, 200, True),
        ("post_cts", 110, 5000, True),
        ("post_hold", 110, 5001, True),
        ("routed", 90, 100, True),       # smaller bytes AND fewer components
    ]))
    assert rc != 0, out
    assert _rules(data) & {"size-non-monotone", "instance-count-regression"}, out


def test_shrink_with_equal_instances_still_fails(tmp_path):
    """No instance growth = no positive evidence = the rule still bites."""
    rc, out, data = _run(_mk(tmp_path, [
        ("floorplan", 5, 10, False),
        ("placed", 100, 200, True),
        ("post_cts", 110, 9000, True),
        ("post_hold", 110, 9001, True),
        ("routed", 110, 100, True),      # smaller bytes, SAME components
    ]))
    assert rc != 0, out
    assert "size-non-monotone" in _rules(data), out


def test_duplicate_stage_still_caught(tmp_path):
    """Check 1 (sha256 distinctness) is untouched: identical stages are fraud
    regardless of the size rule."""
    proj = _mk(tmp_path, [
        ("floorplan", 5, 10, False),
        ("placed", 100, 200, True),
        ("post_cts", 110, 300, True),
        ("post_hold", 110, 300, True),
        ("routed", 120, 400, True),
    ])
    d = proj / "phase3" / "stage3" / "pnr"
    (d / "routed.def").write_text((d / "post_hold.def").read_text())
    rc, out, data = _run(proj)
    assert rc != 0, out


# ── no-leak ─────────────────────────────────────────────────────────────
def test_normal_monotone_progression_still_passes(tmp_path):
    rc, out, data = _run(_mk(tmp_path, [
        ("floorplan", 5, 10, False),
        ("placed", 100, 200, True),
        ("post_cts", 110, 300, True),
        ("post_hold", 110, 400, True),
        ("routed", 120, 500, True),
    ]))
    assert rc == 0, out
    assert "size-non-monotone" not in _rules(data)


def test_routing_presence_still_required(tmp_path):
    """Check 4 untouched."""
    rc, out, data = _run(_mk(tmp_path, [
        ("floorplan", 5, 10, False),
        ("placed", 100, 200, True),
        ("post_cts", 110, 300, True),
        ("post_hold", 110, 400, True),
        ("routed", 120, 500, False),     # no routing geometry
    ]))
    assert "no-routing" in _rules(data) or rc != 0, out
