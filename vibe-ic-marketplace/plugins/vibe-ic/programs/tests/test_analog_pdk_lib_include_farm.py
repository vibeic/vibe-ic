"""Corner-sweep include resolution across a MULTI-DIRECTORY staged PDK.

A PDK's composed corner shim reaches its prerequisite / device libs by BARE
RELATIVE NAME. Measured on ngspice-46 (both `.lib <file> <sec>` and `.include`):
such a target is found iff it sits in the INCLUDING FILE's directory OR in the
process cwd — those two, nothing else; there is no -I option and `set
sourcepath` does not apply. So when a PDK stages its libs across several
directories, a cross-directory hop satisfies neither and every corner dies with
`ERROR, library file … not found` / `exit(1)`; and since no EXISTING directory
holds the whole closure, no choice of cwd alone can fix it either.

analog_pdk_deck_context therefore CREATES such a directory, farming the shim's
include CLOSURE into one directory of symlinks. The sweep must then also RUN
from that farm: co-location supplies the first hop, cwd supplies every hop after
it (ngspice reverts to the PDK's real directory once it follows a farm symlink).
Both halves are required — test_sim_cwd_is_the_farm pins the coupling.

These tests pin BOTH halves: the farm resolves a legitimately-split staged set,
AND it never silently substitutes a lib it had to guess at.

NDA hygiene: SYNTHETIC family names only (MyFoundry X180) — no NDA token.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_pdk_deck_context as APDC          # noqa: E402
import analog_real_corner_sweep as ARS          # noqa: E402


def _device_lib(sections=("ss", "tt", "ff")) -> str:
    out = ["* MyFoundry X180 device lib (NO NDA content)"]
    for sec in sections:
        out.append(f".lib {sec}")
        out.append(".subckt myfoundry_x180_nch d g s b w=1 l=1")
        out.append(".ends")
        out.append(".subckt myfoundry_x180_pch d g s b w=1 l=1")
        out.append(".ends")
        out.append(".endl")
    return "\n".join(out) + "\n"


def _shim_text(device_basename: str, sections=("ss", "tt", "ff")) -> str:
    """A composed corner shim: defines the corner sections, but the devices come
    from a SIBLING lib pulled in by BARE RELATIVE NAME."""
    out = ["* MyFoundry X180 composed corner shim (NO NDA content)"]
    for sec in sections:
        out.append(f".lib {sec}")
        out.append(f".lib {device_basename} {sec}")
        out.append(".endl")
    return "\n".join(out) + "\n"


def _stage_split(tmp_path: Path, device_name="mfx180_dev.lib",
                 shim_name="mfx180_corners.lib"):
    """Stage a shim and its device lib in DIFFERENT directories (the shape that
    made every corner fail) and return (res, shim, device)."""
    a, b = tmp_path / "bridge", tmp_path / "models"
    a.mkdir(), b.mkdir()
    shim, dev = a / shim_name, b / device_name
    shim.write_text(_shim_text(device_name))
    dev.write_text(_device_lib())
    res = {"available": True, "source": "project_custom_pdk",
           "family": "myfoundryx180", "target": "MyFoundry X180 (custom node)",
           "spice_libs": [str(shim), str(dev)], "spice_lib": str(shim),
           "drc_deck": None, "lvs_deck": None}
    return res, shim, dev


# ── the fix: a split staged set resolves ────────────────────────────────────

def test_split_staged_libs_are_colocated_for_the_shim(tmp_path):
    res, shim, dev = _stage_split(tmp_path)
    ctx = APDC.custom_family_context(res, farm_dir=tmp_path / "farm")
    assert ctx.status == "OK"
    # the deck now loads the shim THROUGH the farm …
    model_lib = Path(ctx.model_lib)
    assert model_lib.parent.parent == tmp_path / "farm"
    assert model_lib.is_symlink() and model_lib.resolve() == shim.resolve()
    # … where its bare-name target is a resolvable sibling.
    sibling = model_lib.parent / dev.name
    assert sibling.is_symlink() and sibling.resolve() == dev.resolve()
    assert ctx.include_farm["ambiguous"] == 0
    assert ctx.include_farm["missing"] == 0


# vibe-ic#193 — THE XFAIL THAT USED TO LIVE HERE IS RETIRED, and the reason is
# a measurement, not a preference.
#
# It asserted afec053fb's ENTRY-LIB(shim)-primary intent (`model_lib ==
# res["spice_lib"] == spice_libs[0]`) against HEAD's device-defining-lib pick
# (#149 / v1.4.58), and was marked `xfail(strict=True)` so that ADOPTING the
# afec ordering would turn the suite red rather than XPASS in silence.
#
# It only half worked. An xfail is satisfied by ANY failure of its body, so it
# could distinguish exactly one of the four ways the runtime's primary selection
# can change. Measured, one mutation at a time, on this tree:
#
#   runtime mutation                        marker verdict   rc
#   --------------------------------------  ---------------  --  -------
#   primary = spice_libs[0] (afec adoption)  FAILED (XPASS)   1   caught
#   primary = None (elects nothing)          xfailed          0   BLIND
#   primary = an unstaged third path         xfailed          0   BLIND
#   selection raises                         xfailed          0   BLIND
#
# A marker whose stated job is "if this ever XPASSes the runtime policy changed"
# was reporting success for three of the four changes it existed to catch. The
# explicit assertions in test_issue193_custom_pdk_primary_selection_ngspice.py
# catch ALL FOUR — measured across this file plus that one, in the same four
# mutations and the order above: 7, 12, 11 and 16 tests red, rc 1 every time.
# So the record lives there, as assertions on the CURRENT behaviour with the
# alternative recorded beside them, which is what this repo prefers over a
# marker that is green in any world but one.
#
# Nothing about the owner's decision changed. Adopting the afec ordering still
# turns the suite red — 7 named tests, headed by test_head_diverges_from_spice_
# libs0_only_in_the_split_staging — so whoever adopts it still has to come back
# and say so. Same ceremony, now total instead of one-quarter. THIS test keeps
# the policy-NEUTRAL job it is named for: no farm_dir means raw staged paths,
# and it stays green under either policy.
def test_no_farm_dir_keeps_the_raw_path(tmp_path):
    """Opt-in: a caller that asks for no farm gets exactly the previous paths.

    Deliberately says nothing about WHICH staged lib is elected — that is the
    open architectural question and it is recorded in the #193 file. What is
    asserted here is the opt-in contract: no farm is built, and the elected lib
    is one of the raw staged paths rather than anything under a farm directory.
    """
    res, _shim, _dev = _stage_split(tmp_path)
    ctx = APDC.custom_family_context(res)
    assert ctx.include_farm is None
    assert ctx.model_lib in res["spice_libs"], (
        "no farm_dir must leave the elected lib as one of the RAW staged paths; "
        f"got {ctx.model_lib} for staged {res['spice_libs']}")
    assert not Path(ctx.model_lib).is_symlink()


def test_known_open_pdk_never_farms(tmp_path):
    """sky130/gf180 include by ABSOLUTE path — the fast path is untouched."""
    ctx = APDC.resolve_deck_context("sky130", farm_dir=tmp_path / "farm")
    assert ctx.source == "known_family"
    assert ctx.include_farm is None
    assert not (tmp_path / "farm").exists()


def test_farm_excludes_itself_from_git(tmp_path):
    """The link names carry the PDK's own basenames — they must never be
    committable."""
    res, _shim, _dev = _stage_split(tmp_path)
    APDC.custom_family_context(res, farm_dir=tmp_path / "farm")
    assert (tmp_path / "farm" / ".gitignore").read_text().strip() == "*"


def test_sim_cwd_is_the_farm(tmp_path):
    """The sweep runs ngspice from the model lib's parent. Once that lib is
    farmed, the parent IS the farm — and it must stay that way: co-location gets
    the first hop, cwd gets the rest, and each alone still fails."""
    res, _shim, _dev = _stage_split(tmp_path)
    ctx = APDC.custom_family_context(res, farm_dir=tmp_path / "farm")
    sim_cwd = Path(ctx.model_lib).parent
    assert sim_cwd == Path(ctx.include_farm["dir"])
    # every closure member is reachable from that cwd by BARE NAME
    for name in (Path(_shim).name, Path(_dev).name):
        assert (sim_cwd / name).exists()


# ── the load-bearing half: never guess ──────────────────────────────────────

def test_missing_include_target_fails_loudly(tmp_path):
    """A target genuinely absent from the staged set must NOT be papered over:
    the context fails honestly instead of loading some other lib."""
    res, shim, dev = _stage_split(tmp_path)
    res["spice_libs"] = [str(shim)]              # the device lib is not staged
    dev.unlink()
    ctx = APDC.custom_family_context(res, farm_dir=tmp_path / "farm")
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE"
    assert ctx.include_farm["missing"] >= 1
    farm_root = tmp_path / "farm"
    linked = [p.name for p in farm_root.rglob("*") if p.is_symlink()]
    assert dev.name not in linked                # nothing stood in for it


def test_ambiguous_include_target_is_never_guessed(tmp_path):
    """Two DIFFERENT staged files claim the target's basename and neither sits
    next to the shim → the farm must link NEITHER and the context must fail,
    rather than picking one at random."""
    res, shim, dev = _stage_split(tmp_path)
    other = tmp_path / "models_alt"
    other.mkdir()
    decoy = other / dev.name
    decoy.write_text(_device_lib(sections=("ss", "tt", "ff", "sf")))
    res["spice_libs"].append(str(decoy))
    ctx = APDC.custom_family_context(res, farm_dir=tmp_path / "farm")
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE"
    assert ctx.include_farm["ambiguous"] >= 1
    farm_root = tmp_path / "farm"
    linked = [p for p in farm_root.rglob("*") if p.is_symlink()]
    assert not any(p.resolve() == decoy.resolve() for p in linked)
    assert not any(p.resolve() == dev.resolve() for p in linked)


def test_same_directory_target_wins_over_a_remote_namesake(tmp_path):
    """Resolution order matches ngspice's own rule: a file NEXT TO the includer
    wins outright, so the farm can never pull in a remote namesake instead."""
    res, shim, dev = _stage_split(tmp_path)
    local = shim.parent / dev.name
    local.write_text(_device_lib())
    res["spice_libs"].append(str(local))
    closure, ambiguous, missing = APDC._resolve_include_closure(
        [shim], [Path(p) for p in res["spice_libs"]])
    assert not ambiguous and not missing
    assert local.resolve() in {p.resolve() for p in closure}
    assert dev.resolve() not in {p.resolve() for p in closure}


def test_two_root_sets_get_separate_farms(tmp_path):
    """The corner shim and the MC path can disagree about a basename; their
    farms must not shadow each other."""
    res, shim, dev = _stage_split(tmp_path)
    alt = tmp_path / "mc"
    alt.mkdir()
    mc = alt / "mfx180_mc.lib"
    mc.write_text(_shim_text(dev.name))
    libs = res["spice_libs"] + [str(mc)]
    a = APDC.build_lib_include_farm(libs, tmp_path / "farm", roots=[str(shim)])
    b = APDC.build_lib_include_farm(libs, tmp_path / "farm", roots=[str(mc)])
    assert a["dir"] != b["dir"]


def test_farm_is_idempotent(tmp_path):
    """Re-running a block must not disturb an existing farm."""
    res, shim, _dev = _stage_split(tmp_path)
    a = APDC.build_lib_include_farm(
        res["spice_libs"], tmp_path / "farm", roots=[str(shim)])
    b = APDC.build_lib_include_farm(
        res["spice_libs"], tmp_path / "farm", roots=[str(shim)])
    assert a == b


# ── the leaf-dereference defect that made co-location inert ─────────────────

def test_container_path_keeps_a_symlinked_leaf(tmp_path):
    """Resolving a symlinked LEAF moves the file into its target's directory and
    silently relocates every bare-name include it carries. Only the parent may
    be resolved."""
    real_dir, link_dir = tmp_path / "real", tmp_path / "link"
    real_dir.mkdir(), link_dir.mkdir()
    target = real_dir / "mfx180_corners.lib"
    target.write_text("* x\n")
    link = link_dir / target.name
    link.symlink_to(target)
    assert ARS._norm_host_path(link) == link
    assert ARS._norm_host_path(link).parent == link_dir


def test_norm_host_path_still_normalises_the_parent(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    f = real_dir / "mfx180_corners.lib"
    f.write_text("* x\n")
    via_dots = real_dir / ".." / "real" / f.name
    assert ARS._norm_host_path(via_dots) == f
    assert ARS._norm_host_path(f) == f


def test_norm_host_path_matches_resolve_for_plain_files(tmp_path):
    """No behaviour change for the non-symlink case (every open-PDK path)."""
    f = tmp_path / "plain.lib"
    f.write_text("* x\n")
    assert ARS._norm_host_path(f) == f.resolve()
