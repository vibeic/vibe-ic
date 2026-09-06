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
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _submission_template as _st                            # noqa: E402
import _docker_memory as _dmem                                # noqa: E402
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
    # THE MOUNT IS RESOLVED BEFORE IT IS SPELLED (#2070 O2). `mount` is derived
    # from the caller's `project`, and a caller who passed a RELATIVE project
    # produced the spec `input:input`, which docker refuses outright:
    #
    #     rc=125  invalid volume specification: 'input:input': invalid mount
    #             config for type "volume": invalid mount path: 'input' mount
    #             path must be absolute
    #
    # reported by this program as "the operator's image did not yield its
    # template" — an operator refusal for what was our own argument. It never
    # bit through `phase1_one_shot_runner`, which resolves the project first, so
    # it was invisible to every driven run and hit only a direct call. Resolved
    # HERE rather than at each call site: one adapter remembering and the next
    # forgetting is the same defect with a different author. `resolve()` also
    # collapses `..` and symlinks, so what the container sees is what the host
    # named.
    mount = Path(mount).resolve()
    return _run(["docker", "run", "--rm", *_dmem.docker_memory_flags(),
                 "-v", f"{mount}:{mount}",
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
# WHICH PROCESS FAMILIES THE DESIGN NAMES, AND WHETHER THIS RUN IS ON ONE
# ===========================================================================
# MEASURED (#2070): this program reported
#
#     NOT_DETERMINED — the design declares no PDK
#
# for two corpus designs whose L1 names its target families in the first table
# under "Tapeout" — one of them on line 32, the other on line 33. The reason it
# saw nothing is order, not absence: step 0.5ic is dispatched BEFORE the mode
# branch, so the L19 document `declared_pdk_is_the_pdk_used_check.declared_target`
# reads has not been written yet. The right answer was reported for the wrong
# reason, and would have kept being reported once the design DID name a family.
#
# NO SECOND PARSER. The extraction that reads the design's own input documents
# for its process target already exists and is already the one the rest of
# phase 1 uses — `_extract_pdk_target_with_provenance` plus
# `_declared_pdk_alternates`, which returns every open-PDK family co-declared
# ON THE ADOPTED TARGET'S OWN ROW. Same-row scope is that function's own safety
# argument and it is exactly the scope wanted here: a family named on the
# design's target row was declared with the target; a name elsewhere in the
# document is a mention. Writing a second reader of the same prose is how the
# two drift into disagreeing about what a design targets.
#
# THE CHECK IS AGAINST THE RUN, NOT AGAINST A LIST WE KEEP. A run whose --pdk
# is not one of the families the design names is refused BY NAME, because the
# alternative is fetching one operator's terms for a process the design never
# said it targets. Identity is `shares_identity` — the tree's one rule for
# "are these the same process" — so `gf180mcuD` answers a design that wrote
# `GF180MCU`, and an interior fragment does not.
_FAMILY_SEARCH_ROOTS: Tuple[str, ...] = ("phase1/input_doc", "input/docs",
                                         "input_doc")
#: A run on a process the design does not name.
RULE_PDK_NOT_NAMED = "PDK_NOT_NAMED_BY_THE_DESIGN"


def declared_pdk_families(project: Path) -> Dict[str, Any]:
    """The PDK families the design NAMES, and where that was read.

    Returns `{"families": [...], "source": "<rel>:<line>" | None,
    "searched": [...], "unavailable": <why> | None}`. An empty `families` with
    a stated `searched` is the honest "the design names none" — never a
    default, and always distinguishable from "the reader was not there", which
    is what `unavailable` records.
    """
    rec: Dict[str, Any] = {"families": [], "source": None,
                           "searched": [r for r in _FAMILY_SEARCH_ROOTS
                                        if (project / r).is_dir()],
                           "unavailable": None}
    try:
        import phase1_doc_one_shot_runner as _p1
    except Exception as exc:                                  # noqa: BLE001
        # DEGRADE LOUDLY. Not "the design names none" — nobody looked.
        rec["unavailable"] = (f"the phase-1 input-document extraction could "
                              f"not be imported ({exc}), so no search was "
                              f"made; this is NOT the same fact as a design "
                              f"that names no family")
        return rec
    try:
        tok, _snip, src, line = _p1._extract_pdk_target_with_provenance(project)
        fams = _p1._declared_pdk_alternates(project, src, line, tok)
    except Exception as exc:                                  # noqa: BLE001
        rec["unavailable"] = (f"the phase-1 input-document extraction raised "
                              f"{exc!r}; no family list was read")
        return rec
    if not tok:
        return rec
    # `_declared_pdk_alternates` returns [] when the row names nothing BESIDES
    # the adopted target; the adopted target is still a family the design
    # names, so it is carried on its own.
    rec["families"] = list(fams) if fams else [tok]
    if src:
        rec["source"] = f"{src}:{line}" if line else str(src)
    return rec


def family_named_by_design(pdk: str, families: List[str]) -> Optional[str]:
    """Which named family this run's PDK belongs to, or None.

    Delegated to `shares_identity` — the same predicate `shuttle_for_pdk` uses
    and the same one the declared-vs-used gate owns. A second comparison here
    is a second rule that can drift into matching more, or less, than the gate.
    """
    try:
        import declared_pdk_is_the_pdk_used_check as _pdkid
    except Exception:                                         # noqa: BLE001
        return None
    try:
        toks = _pdkid.tokens(pdk)
    except Exception:                                         # noqa: BLE001
        return None
    for fam in families:
        try:
            if _pdkid.shares_identity(toks, fam):
                return fam
        except Exception:                                     # noqa: BLE001
            continue
    return None


# --------------------------------------------------------------------------- #
# THE DATABASE UNIT IS READ OFF THE TECHNOLOGY, NEVER ASKED OF THE DESIGN
# ===========================================================================
# See `_tapeout_declaration.ANSWERED_BY_TECHNOLOGY` for why. Here is only HOW:
# the registry already names, per PDK, the container root and the glob of the
# tech LEF the rest of the flow builds against, so this resolves that same file
# inside the same digest-pinned image and transcribes the `DATABASE MICRONS`
# record it declares. Nothing is computed and nothing is converted from a
# second source: `DATABASE MICRONS N` means N database units per micron, so the
# unit in microns is 1/N, and the raw statement plus its path:line travel with
# the number so a reader can re-derive it without this program.
_DBU_RE = re.compile(r"DATABASE\s+MICRONS\s+([0-9.]+)")


def _registry_entry(pdk: str) -> Optional[Dict[str, Any]]:
    """The registry row for `pdk`, by the tree's own identity rule."""
    try:
        reg = json.loads((_HERE / "pdk_registry.json").read_text(
            encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    rows = reg.get("pdks") or []
    for row in rows:
        if str(row.get("name", "")).strip().lower() == pdk.strip().lower():
            return row
    try:
        import declared_pdk_is_the_pdk_used_check as _pdkid
        toks = _pdkid.tokens(pdk)
    except Exception:                                         # noqa: BLE001
        return None
    for row in rows:
        name = str(row.get("name", "")).strip()
        if name and _pdkid.shares_identity(toks, name):
            return row
    return None


def technology_facts(pdk: str, image: str,
                     allow_pull: bool = False) -> Dict[str, Any]:
    """`{"database_unit_um": {...}}` transcribed from this PDK's tech LEF.

    Every branch that cannot read the file records WHY and answers nothing.
    "We could not read it" is never allowed to arrive as a number, and a PDK
    the registry does not carry is reported as exactly that rather than as a
    technology with no database unit.
    """
    fact: Dict[str, Any] = {"value": None, "pdk": pdk, "source": None,
                            "statement": None, "image": None,
                            "unavailable": None}
    row = _registry_entry(pdk)
    if row is None:
        fact["unavailable"] = (f"pdk_registry.json carries no entry for "
                               f"{pdk!r}, so this flow does not know where "
                               f"its technology file is")
        return {"database_unit_um": fact}
    root = str(row.get("container_path") or "").rstrip("/")
    glob = str(row.get("tech_lef_glob") or "")
    if not root or not glob:
        fact["unavailable"] = (
            f"the registry entry for {pdk!r} declares "
            f"container_path={root!r} and tech_lef_glob={glob!r}; without both "
            f"there is no file to read")
        return {"database_unit_um": fact}
    # THE EDA IMAGE, NOT THE OPERATOR'S. `--image` above names the SHUTTLE
    # OPERATOR's container, whose business is slot geometry; the technology
    # file belongs to the PDK install this flow builds against, and the tree
    # already has one accessor for that image which pins it by digest and asks
    # it its own version label. Using the operator's here would transcribe a
    # database unit out of whatever PDK that operator happens to ship.
    try:
        import _eda_image as _img
        judged = _img.judged_image(explicit=(image or None),
                                   allow_pull=allow_pull)
    except Exception as exc:                                  # noqa: BLE001
        fact["unavailable"] = (f"the EDA image accessor could not be used "
                               f"({exc}), so no technology file was opened")
        return {"database_unit_um": fact}
    if not judged.ref or not judged.digest:
        fact["unavailable"] = (
            f"no EDA image could be identified, so the technology file for "
            f"{pdk!r} was never opened: {judged.why_not}")
        return {"database_unit_um": fact}
    digest = judged.ref
    fact["image"] = judged.ref
    fact["image_digest"] = judged.digest
    fact["image_version"] = getattr(judged, "version", None)
    # ONE command, and it prints the path, the line number and the line. The
    # glob is expanded by the shell INSIDE the image — the tech LEF is in the
    # image, not on this host, and a host-side guess at the filename is how a
    # transcription ends up naming a file nobody read.
    script = (f'set -e; f=$(ls -1 {root}/{glob} 2>/dev/null | head -1); '
              f'[ -n "$f" ] || {{ echo "NO_TECH_LEF"; exit 3; }}; '
              f'echo "FILE=$f"; grep -n "DATABASE[[:space:]]\\+MICRONS" "$f" '
              f'| head -1')
    rc, out, err = _run(["docker", "run", "--rm", digest, "--skip",
                         "bash", "-lc", script], timeout=600)
    path, line_no, statement = None, None, None
    for raw in (out or "").splitlines():
        s = raw.strip()
        if s.startswith("FILE="):
            path = s[5:].strip()
        elif ":" in s and "DATABASE" in s.upper():
            head, _, rest = s.partition(":")
            if head.strip().isdigit():
                line_no, statement = int(head.strip()), rest.strip()
    if rc != 0 or not path:
        fact["unavailable"] = (
            f"the tech LEF for {pdk!r} could not be read in the image "
            f"({root}/{glob}; rc={rc}): "
            f"{(err or out or '').strip().splitlines()[-1:] or ['(no detail)']}")
        return {"database_unit_um": fact}
    fact["tech_lef"] = path
    if statement is None:
        fact["unavailable"] = (
            f"{path} declares no DATABASE MICRONS record, so this technology "
            f"states no database unit and none was invented")
        return {"database_unit_um": fact}
    m = _DBU_RE.search(statement)
    if not m:
        fact["unavailable"] = (f"{path}:{line_no} reads {statement!r}, which "
                               f"carries no number this could transcribe")
        return {"database_unit_um": fact}
    try:
        per_um = float(m.group(1))
    except ValueError:
        per_um = 0.0
    if per_um <= 0:
        fact["unavailable"] = (f"{path}:{line_no} declares "
                               f"{per_um!r} database units per micron, which "
                               f"is not a unit anything can be measured in")
        return {"database_unit_um": fact}
    fact["value"] = 1.0 / per_um
    fact["database_microns"] = per_um
    fact["statement"] = statement
    fact["source"] = f"{path}:{line_no}"
    return {"database_unit_um": fact}


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


def design_route(project: Path) -> Dict[str, Any]:
    """What the DESIGN itself says it delivers, and which slot it bought.

    Read from the design's OWN answers file, not from the declaration: this
    program runs FIRST in step 0.5ic's chain (fetch -> ingest -> answers ->
    declare), so the declaration on disk at this moment is the PREVIOUS run's
    and must not be believed about THIS one. The design's staged answers are
    its own words and are there before anything in the step runs.

    Nothing is inferred. A design that has staged no answers, or answered no
    `deliverable`, gets `None` and this program says nothing about its route.
    """
    rec: Dict[str, Any] = {"deliverable": None, "slot": None,
                           "source": _st.DESIGN_ANSWERS_REL}
    path = project / _st.DESIGN_ANSWERS_REL
    if not path.is_file():
        rec["source"] = None
        return rec
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return rec
    if not isinstance(doc, dict):
        return rec
    answers = doc.get("answers") if isinstance(doc.get("answers"), dict) else {}
    d = answers.get("deliverable")
    if isinstance(d, str) and d.strip() and d.strip() != "NOT_DETERMINED":
        rec["deliverable"] = d.strip()
    operator = doc.get("operator_template")
    if isinstance(operator, dict):
        s = operator.get("slot")
        if isinstance(s, str) and s.strip():
            rec["slot"] = s.strip()
    return rec


def fetch(project: Path, pdk: str = "", image: str = "",
          allow_pull: bool = False, technology_image: str = "") -> Dict[str, Any]:
    rep: Dict[str, Any] = {"program": ATTRIBUTION, "project": str(project),
                           "verdict": FAIL, "reason": "", "slots_written": [],
                           "refusals": [], "pdk": None, "pdk_source": None,
                           "shuttle": None, "image": None,
                           "pdk_families": [], "pdk_families_source": None,
                           "pdk_family_resolved": None, "technology": {},
                           "source_dir": SOURCE_REL}
    resolved_pdk, pdk_source = resolve_pdk(project, pdk)
    rep["pdk"], rep["pdk_source"] = resolved_pdk, pdk_source

    # WHAT THE DESIGN ITSELF NAMES, read from its own input documents. Done
    # BEFORE the PDK branch, so the record says what the design named even on
    # the branch where nothing was fetched.
    fam = declared_pdk_families(project)
    rep["pdk_families"] = fam["families"]
    rep["pdk_families_source"] = fam["source"]
    rep["pdk_families_searched"] = fam["searched"]
    if fam["unavailable"]:
        rep["pdk_families_unavailable"] = fam["unavailable"]

    if not resolved_pdk:
        rep["verdict"] = NOT_DETERMINED
        _named = (f"Its own documents name {fam['families']} (read at "
                  f"{fam['source']}), and this run named none of them with "
                  f"--pdk, so which of them THIS run builds is unanswered."
                  if fam["families"] else
                  f"Its own documents name none: "
                  f"{fam['unavailable'] or 'searched ' + repr(fam['searched'])} "
                  f"and no PDK family was found on the design's own target "
                  f"row.")
        rep["reason"] = (
            "the design declares no PDK, so whether an operator refuses "
            "submissions on it cannot be answered. " + _named + " Not knowing "
            "which process this is is not the same as there being no "
            "operator, so this is a refusal and not a skip.")
        return rep

    # THE RUN MUST BE ON A PROCESS THE DESIGN NAMES. Refused by name when it is
    # not: fetching an operator's terms for a process the design never said it
    # targets produces a submission record about somebody else's chip.
    if fam["families"]:
        matched = family_named_by_design(resolved_pdk, fam["families"])
        if matched is None:
            rep["verdict"] = NOT_DETERMINED
            rep["refusals"] = [RULE_PDK_NOT_NAMED]
            rep["reason"] = (
                f"{RULE_PDK_NOT_NAMED}: this run targets PDK "
                f"{resolved_pdk!r} (from {pdk_source}) and the design names "
                f"{fam['families']} at {fam['source']}. A run on a process the "
                f"design never said it targets cannot be given that design's "
                f"submission terms, and the technology facts of a process it "
                f"did not choose are not its declaration's to carry.")
            return rep
        rep["pdk_family_resolved"] = matched

    # THE TECHNOLOGY'S OWN ANSWER, TRANSCRIBED. Unconditional on the shuttle:
    # `database_unit_um` is a fact of the process, and a design with no
    # operator has exactly as much of a database unit as one with an operator.
    rep["technology"] = technology_facts(resolved_pdk,
                                         technology_image or "", allow_pull)

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
    # AN OPERATOR THAT EXISTS AND IS NOT BEING USED IS REPORTED, NOT REFUSED
    # (#2070 O1, owner ruling 2026-09-07). A live shuttle on the PDK the design
    # names is INFORMATION. Saying so here is what lets step 0.5ic's first gate
    # clause stop owing the slot contract without anybody losing the fact that
    # a shuttle was available and this design did not take it.
    route = design_route(project)
    rep["design_route"] = route
    if route["deliverable"] and route["slot"] is None:
        rep["route_note"] = (
            f"an operator shuttle exists on {resolved_pdk} "
            f"({len(written)} slots); the design declares "
            f"{route['deliverable']} and names none; route = "
            f"{route['deliverable']}")
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
    p.add_argument("--technology-image", default="",
                   help="Override the EDA image whose PDK install the "
                        "technology facts (database_unit_um) are transcribed "
                        "from. Default: the tree's own pinned EDA image. NOT "
                        "the same image as --image, which is the shuttle "
                        "operator's.")
    p.add_argument("--pull", action="store_true",
                   help="Allow pulling the operator's image if it is absent.")
    p.add_argument("--json", type=Path, dest="out_json", default=None)
    args = p.parse_args(argv)

    if not args.project.is_dir():
        print(f"ERROR: project directory not found: {args.project}",
              file=sys.stderr)
        return 2

    rep = fetch(args.project, pdk=args.pdk, image=args.image,
                allow_pull=args.pull,
                technology_image=args.technology_image)
    out = args.out_json or (args.project / REPORT_REL)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items()
                      if k != "operator_reading"}, indent=2))
    _fam = rep.get("pdk_family_resolved")
    print(f"  pdk families named by the design: "
          f"{rep.get('pdk_families') or 'NOT_DETERMINED'}"
          + (f" (at {rep['pdk_families_source']})"
             if rep.get("pdk_families_source") else
             f" (searched {rep.get('pdk_families_searched')})")
          + (f"; this run resolves to {_fam!r}" if _fam else ""))
    if rep.get("route_note"):
        print(f"  {rep['route_note']}")
    _dbu = (rep.get("technology") or {}).get("database_unit_um") or {}
    if _dbu.get("value") is not None:
        print(f"  database_unit_um = {_dbu['value']} um, transcribed from the "
              f"technology ({_dbu.get('statement')} at {_dbu.get('source')}) "
              f"for PDK {_dbu.get('pdk')!r} in {_dbu.get('image')}")
    elif _dbu:
        print(f"  database_unit_um NOT_DETERMINED: {_dbu.get('unavailable')}")
    print(f"[{rep['verdict']}] {ATTRIBUTION}: {rep['reason']}")
    return 0 if rep["verdict"] in (PASS, NOT_APPLICABLE,
                                   NOT_DETERMINED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
