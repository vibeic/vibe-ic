"""An A3 deck baked the emitting host's ABSOLUTE path into its `.lib` line.

MEASURED 2026-09-06 on 8hd-3: every `.sp` under `phase3/analog/*/` in a real
run carried lines like

    .lib /home/<user>/<lane>/proj/input/pdk/models/cornerCAP.lib cap_typ

Copy the project anywhere — another lane, another host, a container with a
different mount — and every deck in it names a file that is not there. The
probe that hit this died with ngspice's own
`Could not find library file .../cornerCAP.lib`, 200 lines into a sweep log,
which reads as "this design has no models" rather than "this path was baked
in at emission time on another machine".

MEASURED the same day, ngspice-47 inside image 0.3.46: a RELATIVE `.lib`
path is resolved against the directory of the FILE that carries the
directive, NOT the process CWD. `ngspice -b /abs/path/deck.sp` invoked with
cwd `/tmp` resolved `../models/tiny.lib` and completed (`v(d) = 1.0`,
rc 0). That measurement is what makes a deck-relative path correct here; it
is not an assumption about ngspice.

Both directions, per the acceptance standard:
  * a copied project resolves its library  -> the relative form
  * a library that is genuinely absent is refused BY NAME at emission,
    instead of being written into a deck that can only fail later
  * a library OUTSIDE the project keeps its absolute path (a host install is
    not part of the design)
"""
from __future__ import annotations

import inspect
import os
import shutil
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import analog_a3_netlist_emit as A3  # noqa: E402


# ── shims, so the BASE ARM can RUN this file ───────────────────────────────
#
# A control arm that raises AttributeError observes NOTHING: it reports a red
# about a missing name, not about the behaviour. Both entry points below fall
# back to the PRE-FIX behaviour when the tree does not have the fixed one, so
# the base answers wrongly and the direction of every row is real.

def _lib_path(lib, deck_dir):
    fn = getattr(A3, "_portable_lib_path", None)
    if fn is None:
        return lib          # pre-fix: the resolver's path, written verbatim
    return fn(lib, deck_dir)


def _validate(ir, ctx, project):
    fn = A3._validate_ir
    if "project" in inspect.signature(fn).parameters:
        return fn(ir, ctx, project)
    return fn(ir, ctx)      # pre-fix: no project, so no absence question


def _render(ir, ctx, prov, overrides, deck_dir):
    fn = A3.render_netlist
    if "deck_dir" in inspect.signature(fn).parameters:
        return fn(ir, ctx, prov, overrides, deck_dir)
    return fn(ir, ctx, prov, overrides)



def _project(tmp_path: Path, name: str = "proj") -> Path:
    p = tmp_path / name
    (p / "input" / "pdk" / "models").mkdir(parents=True, exist_ok=True)
    (p / "phase3" / "analog" / "ldo").mkdir(parents=True, exist_ok=True)
    (p / "input" / "pdk" / "models" / "cornerMOS.lib").write_text(
        ".lib mos_tt\n.model nch nmos level=1\n.endl mos_tt\n")
    return p


# ── the path that goes into the deck ───────────────────────────────────────

def test_a_project_internal_library_is_named_relatively(tmp_path):
    proj = _project(tmp_path)
    deck_dir = proj / "phase3" / "analog" / "ldo"
    lib = proj / "input" / "pdk" / "models" / "cornerMOS.lib"
    got = _lib_path(str(lib), deck_dir)
    assert not os.path.isabs(got), got
    assert (deck_dir / got).resolve() == lib.resolve()


def test_the_deck_still_resolves_after_the_project_is_copied(tmp_path):
    """The whole point. The path is computed once, in project A, and must
    still name the library after the project is copied to B — WITHOUT
    re-emitting."""
    a = _project(tmp_path, "A")
    deck_dir_a = a / "phase3" / "analog" / "ldo"
    got = _lib_path(
        str(a / "input" / "pdk" / "models" / "cornerMOS.lib"), deck_dir_a)
    b = tmp_path / "B"
    shutil.copytree(a, b)
    deck_dir_b = b / "phase3" / "analog" / "ldo"
    assert (deck_dir_b / got).is_file(), (
        f"the copied project cannot resolve `{got}` from {deck_dir_b}")
    # and the resolved file is B's own copy, not A's
    assert (deck_dir_b / got).resolve().is_relative_to(b.resolve())


def test_the_absolute_form_is_what_breaks_under_a_copy(tmp_path):
    """Negative control for the test above: the pre-fix form, checked the
    same way, resolves into project A from inside project B. If this test
    ever passes, the one above proves nothing."""
    a = _project(tmp_path, "A")
    b = tmp_path / "B"
    shutil.copytree(a, b)
    baked = str(a / "input" / "pdk" / "models" / "cornerMOS.lib")
    assert os.path.isabs(baked)
    assert not Path(baked).resolve().is_relative_to(b.resolve())


def test_a_library_outside_the_project_keeps_its_absolute_path(tmp_path):
    """A host installation is not part of the design; relativising it would
    make the deck depend on where the project sits relative to the install
    root — the same defect pointed the other way."""
    proj = _project(tmp_path)
    outside = tmp_path / "foss" / "pdks" / "x" / "corner.lib"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("* installed\n")
    got = _lib_path(
        str(outside), proj / "phase3" / "analog" / "ldo")
    assert got == str(outside)


def test_a_path_that_is_already_relative_is_left_alone(tmp_path):
    proj = _project(tmp_path)
    got = _lib_path(
        "../models/x.lib", proj / "phase3" / "analog" / "ldo")
    assert got == "../models/x.lib"


def test_no_deck_dir_means_no_rewrite(tmp_path):
    """`render_netlist` may be called without a deck directory (its
    `deck_dir` is optional). Rewriting on a guess would be worse than not
    rewriting: the path stays exactly as the resolver gave it."""
    proj = _project(tmp_path)
    lib = str(proj / "input" / "pdk" / "models" / "cornerMOS.lib")
    assert _lib_path(lib, None) == lib


# ── the refusal ────────────────────────────────────────────────────────────

_IR = {
    "block": "ldo", "block_type": "ldo", "topology": "t",
    "ports": [], "rails": {}, "internal_nets": [], "devices": [],
    "role_terminals": {},
}


def _ctx(lib):
    return {"model_lib": lib, "typ_section": "mos_tt", "role_models": {},
            "registry_family": "fam", "device_terminals": {}}


def test_an_absent_library_inside_the_project_is_refused_by_name(tmp_path):
    proj = _project(tmp_path)
    missing = str(proj / "input" / "pdk" / "models" / "not_here.lib")
    problems = _validate(dict(_IR), _ctx(missing), proj)
    hits = [p for p in problems if "MODEL_LIB_ABSENT" in p]
    assert len(hits) == 1, problems
    assert missing in hits[0], hits[0]


def test_a_present_library_is_not_refused(tmp_path):
    proj = _project(tmp_path)
    lib = str(proj / "input" / "pdk" / "models" / "cornerMOS.lib")
    problems = _validate(dict(_IR), _ctx(lib), proj)
    assert not [p for p in problems if "MODEL_LIB_ABSENT" in p], problems


def test_an_installed_pdk_the_host_cannot_see_is_not_refused(tmp_path):
    """THE CONTROL THAT DECIDES THE SCOPE. This producer runs on the HOST;
    the deck runs in a CONTAINER. `/foss/pdks/...` is legitimately absent
    here and present at simulation time, so "I cannot see it" must not be
    reported as "it is not there".

    MEASURED: an absence check that did not make this distinction refused 9
    of the emitter's own fixtures, which name exactly such a path."""
    proj = _project(tmp_path)
    problems = _validate(
        dict(_IR), _ctx("/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models.lib"),
        proj)
    assert not [p for p in problems if "MODEL_LIB_ABSENT" in p], problems


def test_with_no_project_the_absence_question_is_not_asked(tmp_path):
    """Called without a project there is no tree to speak about, so nothing
    is claimed either way — NOT_MEASURED, never a default."""
    missing = str(tmp_path / "proj" / "input" / "pdk" / "nope.lib")
    problems = _validate(dict(_IR), _ctx(missing), None)
    assert not [p for p in problems if "MODEL_LIB_ABSENT" in p], problems


def test_no_library_at_all_still_says_no_model_include(tmp_path):
    """Control: the pre-existing refusal must keep its own wording. `absent`
    and `never resolved` are different facts and must not collapse."""
    proj = _project(tmp_path)
    problems = _validate(dict(_IR), _ctx(None), proj)
    assert [p for p in problems if "NO_MODEL_INCLUDE" in p], problems
    assert not [p for p in problems if "MODEL_LIB_ABSENT" in p], problems


def test_every_split_corner_lib_is_checked_not_just_the_first(tmp_path):
    """A family that splits actives and passives across separate corner libs
    populates `deck_loads`; the absence check must cover each of them, not
    the single `model_lib` line those families never reach."""
    proj = _project(tmp_path)
    good = str(proj / "input" / "pdk" / "models" / "cornerMOS.lib")
    bad = str(proj / "input" / "pdk" / "models" / "cornerCAP.lib")
    ctx = _ctx(good)
    ctx["deck_loads"] = [[good, "mos_tt"], [bad, "cap_typ"]]
    problems = _validate(dict(_IR), ctx, proj)
    hits = [p for p in problems if "MODEL_LIB_ABSENT" in p]
    assert len(hits) == 1 and bad in hits[0], problems


# ── the staging tree the deck is VERIFIED in — WHY THE REWRITE IS NOT WIRED ──
#
# MEASURED 2026-09-06 on the front door, twice, by wiring `_portable_lib_path`
# into the emitter and running the IC: A3 refused to emit EITHER block
# (`NETLIST_NOT_SIMULATABLE`, ngspice `Could not find library file
# ../../../input/pdk/models/cornerMOShv.lib`) and A4-A7 went BLOCKED behind it
# on both blocks — the whole analog track, lost to a staging tree missing one
# directory. Logs: `logs/run_ic_A3broken.log`, `logs/run_ic_relpath.log`.
#
# The deck is verified in TWO staging locations, and NEITHER carries `input/`:
#   * `verify_with_checkers` — a host TemporaryDirectory holding only the
#     deck, its provenance sidecar and a one-block list;
#   * `verify_with_ngspice`  — a FLAT `/tmp/a3emit_<block>_<ts>` INSIDE the
#     container, into which exactly two files are `docker cp`'d.
# An absolute path resolves from both by accident. So both staging sites have
# been getting the right answer for the wrong reason for as long as the defect
# existed, and neither can detect a defect in HOW the dependency is expressed.
#
# The emitter is therefore left writing the absolute path, the portability
# defect is reported UNFIXED, and the helper below stays tested so the next
# author starts from the measured ngspice behaviour rather than re-deriving
# it. A correct fix must make BOTH staging sites reproduce the directory
# relationship the deck names — larger than this lane, and not half-landed.


# THE MOMENT THE NOTE ABOVE PREDICTED. Both staging sites now reproduce the
# project's own shape (`stage_deck_inputs`), so a deck-relative `.lib` can be
# resolved where the deck is verified, and the rewrite is wired in. The two
# tests below are the same two subjects, now asserting the state that makes
# the deck survive a copy instead of the state that made it unemittable.


def test_the_emitter_writes_a_project_internal_library_relatively(tmp_path):
    """A library the PROJECT carries is named relative to the deck, so the
    deck resolves after the project is copied anywhere."""
    proj = _project(tmp_path)
    deck_dir = proj / "phase3" / "analog" / "ldo"
    lib = str(proj / "input" / "pdk" / "models" / "cornerMOS.lib")
    ir = dict(_IR)
    ir["ports"] = ["vin", "vout", "vss"]
    ctx = _ctx(lib)
    ctx["geometry_units"] = {}
    text = _render(ir, ctx, [], {}, deck_dir)
    card = [ln for ln in text.splitlines() if ln.startswith(".lib ")]
    assert len(card) == 1, text
    got = card[0].split()[1]
    assert not Path(got).is_absolute(), got
    assert (deck_dir / got).resolve() == Path(lib).resolve(), got


def test_a_library_outside_the_project_keeps_its_absolute_path(tmp_path):
    """THE CONTROL. An installed PDK is not part of the design; relativising
    it would make the deck depend on where the project sits relative to the
    install root, which is the same defect pointed the other way."""
    proj = _project(tmp_path)
    deck_dir = proj / "phase3" / "analog" / "ldo"
    lib = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOS.lib"
    ir = dict(_IR)
    ir["ports"] = ["vin", "vout", "vss"]
    ctx = _ctx(lib)
    ctx["geometry_units"] = {}
    text = _render(ir, ctx, [], {}, deck_dir)
    card = [ln for ln in text.splitlines() if ln.startswith(".lib ")]
    assert card[0].split()[1] == lib, card


def test_both_staging_sites_reproduce_the_projects_own_shape(tmp_path):
    """THE FINDING, inverted. Both sites now put the deck where the project
    puts it and carry the libraries the project carries."""
    src = Path(A3.__file__).read_text()
    verify = src[src.index("def verify_with_checkers("):
                 src.index("def _docker_ok(")]
    ngspice = src[src.index("def verify_with_ngspice("):]
    ngspice = ngspice[:ngspice.index("\ndef ", 10)]
    for name, body in (("verify_with_checkers", verify),
                       ("verify_with_ngspice", ngspice)):
        assert "stage_deck_inputs(" in body, (
            f"{name} no longer reproduces the project shape the deck names; "
            f"a deck-relative `.lib` cannot be verified there")


def test_a_deck_relative_library_that_is_not_staged_is_refused_by_name(
        tmp_path):
    """THE MUTATION ARM. A deck naming a library that is NOT under the root
    being staged is refused, with the path in the finding — which is the
    whole point of staging the shape: a site that cannot see the dependency
    cannot find a defect in it."""
    root = tmp_path / "stage"
    (root / "phase3" / "analog" / "ldo").mkdir(parents=True)
    staged, missing = A3.stage_deck_inputs(
        ".lib ../../../input/pdk/models/nowhere.lib mos_tt\n",
        None, root, "phase3/analog/ldo")
    assert staged == []
    assert len(missing) == 1
    assert "nowhere.lib" in missing[0]["lib"]
    assert "does not resolve" in missing[0]["why"]


def test_a_project_internal_library_is_materialised_at_its_own_relpath(
        tmp_path):
    """GREEN, and the reason the mutation above can fail: the same call with
    the project's library present stages it at the SAME relative path, which
    is what makes `input/` exist in the staging tree."""
    proj = _project(tmp_path)
    lib = proj / "input" / "pdk" / "models" / "cornerMOS.lib"
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.write_text("* a library\n")
    root = tmp_path / "stage"
    (root / "phase3" / "analog" / "ldo").mkdir(parents=True)
    staged, missing = A3.stage_deck_inputs(
        f".lib {lib} mos_tt\n", proj, root, "phase3/analog/ldo")
    assert missing == []
    assert staged == ["input/pdk/models/cornerMOS.lib"]
    assert (root / "input" / "pdk" / "models" / "cornerMOS.lib").is_file()
