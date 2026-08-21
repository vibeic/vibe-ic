"""What is LEFT of the include-farm file after vibe-ic#193 retired the farm.

THE FARM IS GONE, AND SO ARE ITS TESTS
======================================
This file used to pin a per-root symlink farm that co-located a split-staged
PDK's model libs so a composed corner shim's bare relative `.include` / `.lib`
targets resolved. That machinery existed for ONE reason: to load the resolver's
declared ENTRY lib (`spice_libs[0]`) as the deck's primary — the second of two
primary-selection strategies this repo carried. The owner's vibe-ic#193 decision
keeps the device-defining rank as the single strategy, so the farm went with it:
without the primary redirect, the farm built symlinks that nothing ever loaded.

The strategy's epitaph — what it did, why it went, and the concrete steps to
bring it back — lives in
`analog_pdk_deck_context.RETIRED_PRIMARY_STRATEGIES["resolver-entry-lib"]`, and
`test_issue193_custom_pdk_primary_selection_ngspice.py` asserts that record is
present and substantive, keeps the ngspice measurements that informed the
decision, and guards against the strategy returning unannounced.

Nine tests were deleted here, all of them exercising the retired path:
`test_split_staged_libs_are_colocated_for_the_shim`,
`test_known_open_pdk_never_farms`, `test_farm_excludes_itself_from_git`,
`test_sim_cwd_is_the_farm`, `test_missing_include_target_fails_loudly`,
`test_ambiguous_include_target_is_never_guessed`,
`test_same_directory_target_wins_over_a_remote_namesake`,
`test_two_root_sets_get_separate_farms`, `test_farm_is_idempotent`. They are
recoverable verbatim from vibe-ic v1.7.69, which is what the restore
instructions point at.

WHAT SURVIVES, AND WHY IT IS NOT FARM-SPECIFIC
==============================================
* the opt-in contract test, rewritten: the elected lib is a RAW staged path.
  Under one strategy this is no longer a statement about opting out of
  anything — it is the plain assertion that the resolver returns a path the
  caller staged, not a path it manufactured.
* `_norm_host_path`'s symlinked-LEAF behaviour. The farm is what SURFACED that
  defect (resolving a symlinked leaf silently relocates every bare-name include
  it carries), but the defect is in the sweep's host-path normalisation and
  applies to any PDK that stages a lib as a symlink — which is common. Deleting
  these with the farm would be over-deletion.

NDA hygiene: SYNTHETIC family names only (MyFoundry X180) — no NDA token.
"""
from __future__ import annotations

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
    """Stage a shim and its device lib in DIFFERENT directories and return
    (res, shim, device)."""
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


def test_the_elected_lib_is_always_a_raw_staged_path(tmp_path):
    """The resolver hands back a lib the CALLER staged — never one it built.

    This is what is left of `test_no_farm_dir_keeps_the_raw_path` once there is
    no farm to opt out of. It deliberately says nothing about WHICH staged lib
    is elected; that is the #193 file's subject.

    MUTATION THIS CATCHES: any future re-introduction of a manufactured path
    (a symlink farm, a copy, a rewritten lib) as the elected primary without
    the caller being told — the elected lib would stop being a member of
    `spice_libs`, and stop being a real file.
    """
    res, _shim, _dev = _stage_split(tmp_path)
    ctx = APDC.custom_family_context(res)
    assert ctx.model_lib in res["spice_libs"], (
        "the elected lib must be one of the RAW staged paths; "
        f"got {ctx.model_lib} for staged {res['spice_libs']}")
    assert not Path(ctx.model_lib).is_symlink()
    # and the retired strategy's schema field is really gone from the artefact
    assert "include_farm" not in ctx.as_json()


# ── the leaf-dereference defect (NOT farm-specific — see the module docstring) ─

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
