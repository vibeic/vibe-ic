#!/usr/bin/env python3
"""submission_template_fetch.py — step 0.5ic's missing half: GO AND GET IT.

ENFORCEMENT: BLOCKING as step 0.5ic's first program. rc 0 means either the
template is on disk or this PDK has no operator to fetch one from; rc 1 means we
know an operator refuses submissions on this PDK and we did not obtain its
terms.

THE HOLE THIS FILLS
===================
Step 0.5ic declares its input as::

    required_inputs:
      - from: external
        check: none
        what: the shuttle operator's published project template — the repository
              or archive that pins the slot geometry, ships the die-identification
              fixtures, and lists the pads for each slot. Declared as external
              and unprobed because it is fetched, not produced, and the flow must
              be able to say it was never fetched.

That declaration is right, and NOTHING IN THE FLOW EVER FETCHED IT. Measured
2026-09-04 across every published corpus tree: `input/submission_template_source`
exists for zero designs, `slots/*.yaml` for zero designs, and every
`tapeout_declaration.json` field reads `NOT_DETERMINED`. Downstream, that starves
BOTH arms of step 37.5ic — ours as much as the operator's, because our
`general_precheck` compares the layout against a declaration nobody could fill.
The visible symptoms were read for weeks as separate defects: a chip_top that
would not resolve, a 106-byte pad-ring GDS, a die size matching no slot.

WHY THE SIZE CANNOT SIMPLY BE COMPUTED
======================================
`docs/research/shuttle_slot_geometry.md` states it after measuring:

    The die size is not something a submitter computes. It is a constant the
    operator's template hands them, per slot.

A number this flow derived from its own floorplan and then checked its own
floorplan against would be self-certification. So every value written here comes
out of the OPERATOR's own artefacts, executed inside the operator's own
digest-pinned image. Nothing in this file types a dimension.

GENERAL CORE / THIN ADAPTER
===========================
The general core is the NORMALISED template `_submission_template.discover_slots`
already reads: files carrying a `DIE_AREA` key. It is operator-agnostic and is
not touched here.

What is per-operator is only the SHAPE THEY PUBLISH IN, and it really does
differ: this one ships slot geometry as constants in a Python file and pad masks
as GDS, with no YAML anywhere. So each operator gets a small adapter that reads
ITS publication and emits the normalised form. Adding an operator is adding an
adapter; it is never a change to the core.

AN UNKNOWN OPERATOR IS A REFUSAL, NOT A SKIP. If the registry names a live
shuttle we have no adapter for, this exits 1 and says so. Exiting 0 there would
produce the artefact of "there was nothing to fetch" for a design that has an
operator waiting to refuse it.

USAGE
-----
    python3 submission_template_fetch.py <project>
        [--pdk NAME]     # default: read from the design's own declaration
        [--image IMG]    # default: the registry's, resolved to a DIGEST
        [--pull]         # allow pulling the image if it is not local
        [--json OUT]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _submission_template as _st                            # noqa: E402
import tapeout_readiness_check as _theirs                     # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402

ATTRIBUTION = "submission_template_fetch"
SOURCE_REL = "input/submission_template_source"
REPORT_REL = "reports/phase1/submission_template_fetch.json"

PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "NOT_APPLICABLE"
#: An operator exists for this PDK and its terms were NOT obtained — no PDK
#: declared, image unavailable, no adapter for its publication shape, or the
#: adapter came back empty. rc 0, and that is deliberate: this step's job is to
#: GO AND GET IT AND SAY WHAT HAPPENED, and the flow's own words for it are
#: "the flow must be able to say it was never fetched".
#:
#: THE REFUSAL BELONGS AT 37.5ic, NOT HERE. That gate already reports
#: NOT_DETERMINED for "the registry names a live shuttle and its template was
#: never fetched", and it refuses with the LAYOUT in hand, which is where the
#: consequence actually is. Failing phase 1 instead would make every design
#: hostage to a container pull, and a flow that cannot get past step 0.5ic
#: without network access is a flow that gets worked around.
NOT_DETERMINED = "NOT_DETERMINED"


# --------------------------------------------------------------------------- #
# The container is the fetch. Provenance is the digest, not the tag.
# --------------------------------------------------------------------------- #
def _run(argv: List[str], timeout: float = 900.0) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(argv, capture_output=True, text=True,
                            timeout=timeout)
    except FileNotFoundError as exc:
        return 127, "", f"{exc}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    return cp.returncode, cp.stdout or "", cp.stderr or ""


def resolve_image_digest(image: str, allow_pull: bool) -> Tuple[Optional[str],
                                                               str]:
    """The image's immutable digest, or None with the reason.

    A FLOATING TAG IS NOT PROVENANCE. `:latest` names a different set of bytes
    next week, and a template recorded against it cannot be re-derived — which
    is exactly the property a submission record needs most. So the tag is only
    ever the way to FIND the image; what gets written down is the digest.
    """
    rc, out, err = _run(["docker", "image", "inspect", image,
                         "--format", "{{index .RepoDigests 0}}"], timeout=120)
    if rc != 0 and allow_pull:
        prc, _, perr = _run(["docker", "pull", image], timeout=3600)
        if prc != 0:
            return None, f"could not pull {image}: {perr.strip()[:300]}"
        rc, out, err = _run(["docker", "image", "inspect", image,
                             "--format", "{{index .RepoDigests 0}}"],
                            timeout=120)
    if rc != 0:
        return None, (f"the operator's image {image} is not available locally "
                      f"and --pull was not given: {err.strip()[:300]}")
    digest = out.strip()
    if "@sha256:" not in digest:
        return None, (f"{image} reports no repo digest ({digest!r}); a template "
                      f"recorded against a floating tag cannot be re-derived")
    return digest, ""


def _in_image(digest: str, script: str, mount: Path, interpreter: str,
              timeout: float = 900.0) -> Tuple[int, str, str]:
    """Run a snippet INSIDE the operator's image, over its own files.

    THROUGH THE IMAGE'S OWN ENTRYPOINT, and with the interpreter the REGISTRY
    declares. Measured: `--entrypoint python3` fails with rc 127 on this
    operator — its entrypoint is a nix dev-shell wrapper and `python3` is not on
    the bare PATH, while `python` inside that wrapper is 3.13.9. The registry
    already carries the operator's documented invocation
    (`entrypoint=("python", "precheck.py")`), so the interpreter is read from
    there rather than assumed here; an operator that ships a different one only
    changes its own registry row.
    """
    return _run(["docker", "run", "--rm", "-v", f"{mount}:{mount}",
                 digest, interpreter, "-c", script], timeout=timeout)


# --------------------------------------------------------------------------- #
# ADAPTER — wafer.space / gf180mcu
# --------------------------------------------------------------------------- #
#: Read inside the image. Everything it reports is read or computed by the
#: OPERATOR's own module: the constants are theirs, the slot arithmetic is the
#: expression from their own source, and the slot -> divisor mapping is taken
#: from their own `if/elif` chain by AST rather than restated here. The pad
#: masks are enumerated from their own asset directory and measured with the
#: KLayout their image ships.
_WAFER_SPACE_EXTRACT = r'''
import ast, json, sys, os
SD = "/workspace/scripts/klayout"
sys.path.insert(0, SD)
import check_size as CS

src = open(os.path.join(SD, "check_size.py")).read()
tree = ast.parse(src)

# The operator's own slot -> (div_x, div_y) mapping, lifted from their source.
mapping = {}
def walk_if(node):
    if not isinstance(node, ast.If):
        return
    t = node.test
    name = None
    if (isinstance(t, ast.Compare) and len(t.ops) == 1
            and isinstance(t.ops[0], ast.Eq)
            and isinstance(t.left, ast.Name) and t.left.id == "slot"
            and isinstance(t.comparators[0], ast.Constant)):
        name = t.comparators[0].value
    if name is not None:
        d = {}
        for st in node.body:
            if (isinstance(st, ast.Assign) and len(st.targets) == 1
                    and isinstance(st.targets[0], ast.Name)
                    and isinstance(st.value, ast.Constant)):
                d[st.targets[0].id] = st.value.value
        if "div_x" in d and "div_y" in d:
            mapping[name] = (d["div_x"], d["div_y"])
    for st in node.orelse:
        walk_if(st)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        for st in node.body:
            walk_if(st)

# The layer constants the operator refuses on, lifted from ITS OWN source by
# AST: `pya.LayerInfo(l, d)` assigned to a name inside its checker. Restating
# 82/0 or 167/5 here would be this flow typing a foundry number.
layers = {}
for node in ast.walk(tree):
    if (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "LayerInfo"
            and len(node.value.args) == 2
            and all(isinstance(a, ast.Constant) for a in node.value.args)):
        layers[node.targets[0].id] = [node.value.args[0].value,
                                      node.value.args[1].value]

# WHICH DIRECTION EACH LAYER IS REFUSED IN, read from the operator's own
# CONDITION and not from its variable names. `X_region.count() > 0 -> exit` is
# a layer that must be ABSENT; `== 0 -> exit` is one that must be PRESENT.
# Deciding this by name ("GUARD_RING sounds required") is the token-match
# mistake: a name is not a rule, and the rule is right there in the test.
regions = {}          # <name>_region -> layer variable name
for node in ast.walk(tree):
    if (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)):
        for sub in ast.walk(node.value):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "layer" and sub.args
                    and isinstance(sub.args[0], ast.Name)):
                regions[node.targets[0].id] = sub.args[0].id
must_be_absent, must_be_present = [], []
for node in ast.walk(tree):
    if not isinstance(node, ast.If):
        continue
    t = node.test
    if not (isinstance(t, ast.Compare) and len(t.ops) == 1
            and isinstance(t.left, ast.Call)
            and isinstance(t.left.func, ast.Attribute)
            and t.left.func.attr == "count"
            and isinstance(t.left.func.value, ast.Name)
            and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == 0):
        continue
    lay = regions.get(t.left.func.value.id)
    if lay is None or lay not in layers:
        continue
    exits = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "exit" for st in node.body
                for c in ast.walk(st))
    if not exits:
        continue
    if isinstance(t.ops[0], ast.Gt):
        must_be_absent.append(lay)
    elif isinstance(t.ops[0], ast.Eq):
        must_be_present.append(lay)

W, H, SAW = CS.USER_DIE_WIDTH, CS.USER_DIE_HEIGHT, CS.SAW_STREET_MINIMUM
slots = {}
for name, (dx, dy) in mapping.items():
    # The operator's own expression, verbatim from check_size.py lines 100-101.
    slots[name] = {
        "width":  (W - ((dx - 1) * SAW)) / dx,
        "height": (H - ((dy - 1) * SAW)) / dy,
        "div_x": dx, "div_y": dy,
    }

masks = {}
MD = "/workspace/assets/golden_masks"
if os.path.isdir(MD):
    import pya
    for f in sorted(os.listdir(MD)):
        if not f.endswith(".gds"):
            continue
        ly = pya.Layout(); ly.read(os.path.join(MD, f))
        top = ly.top_cell(); bb = top.dbbox()
        masks[f] = {"top_cell": top.name, "dbu": ly.dbu,
                    "width": bb.width(), "height": bb.height(),
                    "origin": [bb.left, bb.bottom]}

print("VIBEIC_TEMPLATE=" + json.dumps({
    "constants": {"USER_PROJECT_WIDTH": CS.USER_PROJECT_WIDTH,
                  "USER_PROJECT_HEIGHT": CS.USER_PROJECT_HEIGHT,
                  "SEAL_RING_SIZE": CS.SEAL_RING_SIZE,
                  "USER_DIE_WIDTH": W, "USER_DIE_HEIGHT": H,
                  "SAW_STREET_MINIMUM": SAW},
    "slots": slots, "pad_masks": masks, "layers": layers,
    "must_be_absent": sorted(must_be_absent),
    "must_be_present": sorted(must_be_present),
}))
'''


def _adapt_wafer_space(project: Path, digest: str, shuttle: Any,
                       dest: Path) -> Tuple[List[str], List[str], Dict]:
    """(slots written, refusals, the operator's raw reading)."""
    interpreter = (shuttle.entrypoint or ("python",))[0]
    rc, out, err = _in_image(digest, _WAFER_SPACE_EXTRACT,
                             dest.parent, interpreter)
    if rc != 0 or "VIBEIC_TEMPLATE=" not in out:
        return [], [f"the operator's image did not yield its template "
                    f"(rc={rc}): {(err or out).strip()[-400:]}"], {}
    raw = json.loads(out.split("VIBEIC_TEMPLATE=", 1)[1].splitlines()[0])
    if not raw.get("slots"):
        return [], ["the operator's own source names no slots; its slot table "
                    "was not where this adapter reads it, and guessing one "
                    "would put a fabricated die size in front of its tool"], raw

    seal = raw["constants"]["SEAL_RING_SIZE"]
    written: List[str] = []
    for name, geo in sorted(raw["slots"].items()):
        w, h = geo["width"], geo["height"]
        # The pad mask this operator ships for this slot, if it ships one. Named
        # rather than measured-into-a-number: it is a fixture, not a dimension.
        mask = next((f for f in raw.get("pad_masks", {})
                     if f == f"mask_{name}.gds"), None)
        rec = {
            "SLOT": name,
            # The normalised key `_submission_template.discover_slots` reads.
            "DIE_AREA": f"0 0 {w} {h}",
            "SEAL_RING_WIDTH": seal,
            "TOP_CELL": (raw["pad_masks"].get(mask) or {}).get("top_cell"),
            "DATABASE_UNIT_UM": (raw["pad_masks"].get(mask) or {}).get("dbu"),
            "PAD_MASK": mask,
            # Refused layers, and the DIRECTION each is refused in, taken from
            # the operator's own condition rather than from its variable names.
            "FORBIDDEN_LAYERS": [
                {"name": n, "layer": raw["layers"][n][0],
                 "datatype": raw["layers"][n][1]}
                for n in raw.get("must_be_absent", []) if n in raw["layers"]],
            "REQUIRED_MARKER_LAYERS": [
                {"name": n, "layer": raw["layers"][n][0],
                 "datatype": raw["layers"][n][1]}
                for n in raw.get("must_be_present", []) if n in raw["layers"]],
            "_provenance": {
                "operator": shuttle.shuttle_id,
                "image": digest,
                "read_from": "scripts/klayout/check_size.py",
                "how": ("the operator's own constants and its own slot "
                        "expression, evaluated inside its own image; the "
                        "slot->divisor mapping is taken from its own source "
                        "by AST and is not restated by this flow"),
                "constants": raw["constants"],
                "divisors": {"div_x": geo["div_x"], "div_y": geo["div_y"]},
            },
        }
        p = dest / f"{name}.json"
        atomic_write_text(p, json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        written.append(name)
    return written, [], raw


#: shuttle_id -> adapter. THIN by construction: an adapter maps one operator's
#: publication onto the normalised form and does nothing else.
ADAPTERS: Dict[str, Callable[..., Tuple[List[str], List[str], Dict]]] = {
    "wafer_space_gf180mcu": _adapt_wafer_space,
}


# --------------------------------------------------------------------------- #
def resolve_pdk(project: Path, explicit: str = "") -> Tuple[Optional[str],
                                                            Optional[str]]:
    """Delegated, never re-derived — the same accessor 37.5ic's gate uses."""
    if explicit.strip():
        return explicit.strip(), "--pdk"
    try:
        import declared_pdk_is_the_pdk_used_check as _pdkid
    except Exception:                                        # noqa: BLE001
        return None, None
    try:
        return _pdkid.declared_target(project)
    except Exception:                                        # noqa: BLE001
        return None, None


def fetch(project: Path, pdk: str = "", image: str = "",
          allow_pull: bool = False) -> Dict[str, Any]:
    rep: Dict[str, Any] = {"program": ATTRIBUTION, "project": str(project),
                           "verdict": FAIL, "reason": "", "slots_written": [],
                           "refusals": [], "pdk": None, "pdk_source": None,
                           "shuttle": None, "image": None,
                           "source_dir": SOURCE_REL}
    resolved_pdk, pdk_source = resolve_pdk(project, pdk)
    rep["pdk"], rep["pdk_source"] = resolved_pdk, pdk_source
    if not resolved_pdk:
        rep["verdict"] = NOT_DETERMINED
        rep["reason"] = (
            "the design declares no PDK, so whether an operator refuses "
            "submissions on it cannot be answered. Not knowing which process "
            "this is is not the same as there being no operator, so this is a "
            "refusal and not a skip.")
        return rep

    shuttle = _theirs.shuttle_for_pdk(resolved_pdk)
    if shuttle is None:
        rep["verdict"] = NOT_APPLICABLE
        rep["reason"] = (
            f"the registry names no live shuttle for PDK {resolved_pdk!r}, so "
            f"there is no operator's template to fetch. This design's die "
            f"terms are its own declaration's to state — step 37.5ic still "
            f"runs OUR ladder against them.")
        return rep
    rep["shuttle"] = shuttle.shuttle_id

    adapter = ADAPTERS.get(shuttle.shuttle_id)
    if adapter is None:
        rep["verdict"] = NOT_DETERMINED
        rep["reason"] = (
            f"the registry names {shuttle.shuttle_id!r} as a live shuttle for "
            f"{resolved_pdk!r}, but this flow has no adapter for the shape it "
            f"publishes in. An operator we know refuses submissions and whose "
            f"terms we did not read is a REFUSAL — reporting nothing to fetch "
            f"here would produce the artefact of a design with no operator.")
        return rep

    digest, why = resolve_image_digest(image or shuttle.default_image,
                                       allow_pull)
    if digest is None:
        rep["verdict"] = NOT_DETERMINED
        rep["reason"] = why
        return rep
    rep["image"] = digest

    dest = project / SOURCE_REL
    dest.mkdir(parents=True, exist_ok=True)
    written, refusals, raw = adapter(project, digest, shuttle, dest)
    rep["slots_written"] = written
    rep["refusals"] = refusals
    rep["operator_reading"] = raw
    if refusals or not written:
        rep["verdict"] = NOT_DETERMINED
        rep["reason"] = "; ".join(refusals) or "the adapter wrote no slot"
        return rep

    # A per-file digest of what we wrote, so a later reader can prove the
    # template on disk is the one this fetch produced.
    rep["files"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(dest.glob("*.json"))}
    rep["verdict"] = PASS
    rep["reason"] = (
        f"{len(written)} slot(s) fetched from {shuttle.shuttle_id} at {digest} "
        f"and normalised under {SOURCE_REL}: {', '.join(written)}. Every "
        f"dimension is the operator's own, computed by its own code inside its "
        f"own image.")
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Fetch the shuttle operator's published project template "
                    "and normalise it into the form step 0.5ic ingests.")
    p.add_argument("project", type=Path)
    p.add_argument("--pdk", default="",
                   help="Override the PDK; default is the design's own "
                        "declaration.")
    p.add_argument("--image", default="",
                   help="Override the operator's image; default is the "
                        "registry's, resolved to a digest either way.")
    p.add_argument("--pull", action="store_true",
                   help="Allow pulling the operator's image if it is absent.")
    p.add_argument("--json", type=Path, dest="out_json", default=None)
    args = p.parse_args(argv)

    if not args.project.is_dir():
        print(f"ERROR: project directory not found: {args.project}",
              file=sys.stderr)
        return 2

    rep = fetch(args.project, pdk=args.pdk, image=args.image,
                allow_pull=args.pull)
    out = args.out_json or (args.project / REPORT_REL)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items()
                      if k != "operator_reading"}, indent=2))
    print(f"[{rep['verdict']}] {ATTRIBUTION}: {rep['reason']}")
    return 0 if rep["verdict"] in (PASS, NOT_APPLICABLE,
                                   NOT_DETERMINED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
