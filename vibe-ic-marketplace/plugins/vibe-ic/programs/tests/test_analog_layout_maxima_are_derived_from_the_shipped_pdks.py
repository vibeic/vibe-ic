"""The maxima record's families ARE the families whose gencell states one.

The registry entry is DATA, and data goes stale silently. This module derives
the same answer from the shipped PDKs themselves and compares the two sets
BOTH WAYS, so neither a family added to the image without a record nor a
record kept after its PDK stopped stating the number can survive.

It reads the PDKs through the flow's OWN reader
(`analog_a5_pdk_device_limits.gencell_defaults`), which is the same parse the
producer uses — a second, private parse here could agree with the registry and
disagree with the flow.

NOT_VERIFIED, never a pass, where the PDKs are out of reach: this is a
statement about the shipped PDKs and a host without them cannot make it.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

from not_verified_tier import not_verified_reason  # noqa: E402

import analog_a5_pdk_device_limits as LIM
import pdk_analog_layout_minima as M

PDK_ROOT = Path("/foss/pdks")
CAP_CLASS = "capacitor"

# The sentinel is BUILT, not typed. The reason below said `NOT_VERIFIED: ... —
# remedy: ...` by hand, which reads as declared and is not: the tier's detector
# asks for a CALL to a declarer, precisely so the format cannot drift away from
# the reader that parses it. Measured on 9cf22c191c, this was the one file
# `test_no_new_undeclared_infrastructure_skip_appears` named, and it has been
# named since v1.17.98 (18cb660e3b) — the text is unchanged, only its author is.
pytestmark = pytest.mark.skipif(
    not PDK_ROOT.is_dir(),
    reason=not_verified_reason(
        "the shipped PDKs are not on this host, so what each family's gencell "
        "states cannot be read",
        remedy="run inside the shipped EDA image"))


def _capacitor_maxima(family: str):
    """{gencell model: (lmax, wmax)} for every capacitor gencell the family
    declares one for, read out of its own tcl."""
    magic = PDK_ROOT / family / "libs.tech" / "magic"
    out = {}
    if not magic.is_dir():
        return out
    for path in sorted(glob.glob(str(magic / "*.tcl"))):
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            continue
        for model, rec in LIM.gencell_defaults(text, path).items():
            if rec.get("class") != CAP_CLASS:
                continue
            if rec.get("lmax") is None and rec.get("wmax") is None:
                continue
            out[model] = (rec.get("lmax"), rec.get("wmax"))
    return out


def _registry_families():
    """Every family the registry declares, and its recorded cap maxima."""
    out = {}
    for name in ("sky130A", "gf180mcuD", "ihp-sg13g2", "nangate45", "asap7",
                 "custom_auto_detect"):
        fam, roles = M.layout_maxima(name)
        if fam is None:
            continue
        out[name] = roles
    return out


def test_a_family_whose_gencell_states_a_capacitor_maximum_has_a_record():
    """FORWARD. A family the image ships with a capacitor maximum in its own
    tcl must carry one in the registry — otherwise the split that the maximum
    exists to drive is dark on that family and nothing says so."""
    missing = []
    for family, roles in _registry_families().items():
        stated = _capacitor_maxima(family)
        if stated and "cap" not in roles:
            missing.append((family, sorted(stated)))
    assert missing == [], (
        f"these families' own gencells state a capacitor maximum and the "
        f"registry records none: {missing}")


def test_a_recorded_capacitor_maximum_is_one_its_own_pdk_states():
    """BACKWARD, and the half that catches a stale number or a borrowed one.
    Every recorded value must be a value that family's OWN tcl states, for the
    device the record names."""
    checked = 0
    for family, roles in _registry_families().items():
        rec = roles.get("cap")
        if not rec:
            continue
        stated = _capacitor_maxima(family)
        device = rec.get("device")
        assert device in stated, (
            f"{family} records `{device}`, which its own tcl does not state a "
            f"capacitor maximum for; stated: {sorted(stated)}")
        lmax, wmax = stated[device]
        assert M.max_length_um(roles, "cap") == lmax, (family, device)
        assert M.max_width_um(roles, "cap") == wmax, (family, device)
        checked += 1
    assert checked >= 1, "no family carried a capacitor maximum to check"


def test_a_family_with_no_pdk_on_this_host_records_nothing():
    """The third direction: a registry family the image does not ship must
    carry no maximum, because there is nothing to have read it from."""
    for family, roles in _registry_families().items():
        if (PDK_ROOT / family / "libs.tech" / "magic").is_dir():
            continue
        assert roles == {}, (
            f"{family} carries a maxima record and ships no gencell tcl on "
            f"this host — a number with no source is a number nobody can "
            f"re-derive")


def test_the_record_cites_a_line_of_its_own_pdks_tcl():
    for family, roles in _registry_families().items():
        if not roles:
            continue
        src = M.maxima_source(family) or ""
        assert "libs.tech/magic/" in src, (family, src)
        rel = src.split()[0].rstrip(":").split(":")[0]
        assert (PDK_ROOT / family / rel).is_file(), (
            f"{family}'s record cites `{rel}`, which is not a file of its own "
            f"PDK on this host")


def test_the_reader_still_names_no_family():
    """The property the minima reader has always had, re-asserted for the
    maxima it now also serves: every family-specific fact is DATA."""
    reader = Path(M.__file__).read_text(errors="replace").lower()
    for family in _registry_families():
        assert family.lower() not in reader, (
            f"`{Path(M.__file__).name}` names the PDK family `{family}`")


def test_a_recorded_maximum_is_a_CEILING_and_not_a_fixed_width():
    """The arm that would have caught the reason I nearly recorded.

    A gencell can state `wmax` equal to its own `wmin` — sky130A's ten
    poly-resistor flavours all do, 0.35/0.35 through 5.73/5.73 — and that is
    not a ceiling a role can be bounded by: it is a FIXED drawn width, the
    flavour name IS the width, and a split solver handed it would divide a
    device that has no freedom to be divided. A recorded maximum must be
    strictly above the same device's minimum, on the same axis.
    """
    for family, roles in _registry_families().items():
        rec = roles.get("cap")
        if not rec:
            continue
        magic = PDK_ROOT / family / "libs.tech" / "magic"
        found = None
        for path in sorted(glob.glob(str(magic / "*.tcl"))):
            got = LIM.gencell_defaults(
                Path(path).read_text(errors="replace"), path)
            if rec["device"] in got:
                found = got[rec["device"]]
                break
        assert found is not None, (family, rec["device"])
        for lo, hi in (("lmin", "max_length_um"), ("wmin", "max_width_um")):
            floor, ceiling = found.get(lo), rec.get(hi)
            if floor is None or ceiling is None:
                continue
            assert ceiling > floor, (
                f"{family}/{rec['device']}: {hi} {ceiling} is not above its "
                f"own {lo} {floor} — that is a FIXED size, not a ceiling, "
                f"and recording it as one would hand the split solver a "
                f"device with no freedom to divide")


def test_the_absence_notes_are_measured_over_every_gencell_not_sampled():
    """Each family's record explains its ABSENT roles. That prose is a claim
    about the whole file, and a claim about a whole file has to have read the
    whole file — this asserts the counts it quotes."""
    import re
    counts = {}
    for family in _registry_families():
        magic = PDK_ROOT / family / "libs.tech" / "magic"
        if not magic.is_dir():
            continue
        per_class = {}
        for path in sorted(glob.glob(str(magic / "*.tcl"))):
            for _m, rec in LIM.gencell_defaults(
                    Path(path).read_text(errors="replace"), path).items():
                per_class.setdefault(rec.get("class"), []).append(rec)
        counts[family] = per_class
    _fam, ent = M.resolve_family("sky130A")
    note = (ent.get("analog_device_layout_maxima") or {}).get("_note", "")
    if note and "sky130A" in counts:
        n = len(counts["sky130A"].get("resistor", []))
        assert f"of {n} resistor gencells" in note, (n, note[:200])
    _fam, ent = M.resolve_family("gf180mcuD")
    note = (ent.get("analog_device_layout_maxima") or {}).get("_note", "")
    if note and "gf180mcuD" in counts:
        n = len(counts["gf180mcuD"].get("mosfet", []))
        assert f"of {n} mosfet gencells" in note, (n, note[:200])


def test_the_recorded_device_is_one_that_can_actually_BE_sized():
    """The other side of the ceiling arm.

    A capacitor gencell can be FIXED GEOMETRY — sky130A ships four
    `cap_vpp_*` cells whose size is in the cell name and which state no lmin,
    wmin, lmax or wmax at all. A ceiling recorded against one of those would
    bound a device that has no length to solve for, and the unit-split would
    be handed something it cannot divide. The device a maximum is recorded
    for must be PARAMETERISED: it must state its own minimum too.
    """
    for family, roles in _registry_families().items():
        rec = roles.get("cap")
        if not rec:
            continue
        magic = PDK_ROOT / family / "libs.tech" / "magic"
        found = None
        for path in sorted(glob.glob(str(magic / "*.tcl"))):
            got = LIM.gencell_defaults(
                Path(path).read_text(errors="replace"), path)
            if rec["device"] in got:
                found = got[rec["device"]]
                break
        assert found is not None, (family, rec["device"])
        assert found.get("lmin") is not None, (
            f"{family}/{rec['device']} states no lmin — it is a FIXED-geometry "
            f"cell, and a ceiling on a device with no length to solve for "
            f"bounds nothing and misleads the split")
        assert found.get("wmin") is not None, (family, rec["device"])


def test_the_citation_counts_every_capacitor_gencell_not_just_the_bounded_ones():
    """A citation that says "the only one" or "of six" is a claim about the
    WHOLE file, and a claim about a whole file has to have counted the whole
    file — including the gencells that state no maximum, which is the class I
    first missed."""
    for family, roles in _registry_families().items():
        if not roles.get("cap"):
            continue
        magic = PDK_ROOT / family / "libs.tech" / "magic"
        n = 0
        for path in sorted(glob.glob(str(magic / "*.tcl"))):
            for _m, r in LIM.gencell_defaults(
                    Path(path).read_text(errors="replace"), path).items():
                if r.get("class") == CAP_CLASS:
                    n += 1
        src = M.maxima_source(family) or ""
        if n == 1:
            assert "ONLY one" in src or "only capacitor gencell" in src, (
                family, n, src)
        else:
            assert str(n) in src or _WORDS.get(n, "\0") in src.upper(), (
                f"{family} has {n} capacitor gencells and its citation does "
                f"not say so: {src}")


_WORDS = {2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX", 7: "SEVEN"}


def test_every_maximum_a_family_states_is_ACCOUNTED_FOR():
    """The general property behind every other arm in this module.

    A family's record must ACCOUNT for every maximum that family's gencells
    state — either by recording it under a role, or by NAMING it as something
    no role resolves to. Neither is optional: a maximum that appears in
    neither place reads as "this family states nothing else", which is how a
    record written from a filtered scan goes wrong. It is the property that
    would have caught, in one arm, the three separate citations this module's
    history had to correct one at a time.
    """
    for family, roles in _registry_families().items():
        magic = PDK_ROOT / family / "libs.tech" / "magic"
        if not magic.is_dir():
            continue
        _fam, ent = M.resolve_family(family)
        rec = ent.get("analog_device_layout_maxima") or {}
        prose = " ".join(str(rec.get(k, "")) for k in
                         ("_comment", "_measured_from", "_note")).lower()
        by_class = {}
        for path in sorted(glob.glob(str(magic / "*.tcl"))):
            for model, r in LIM.gencell_defaults(
                    Path(path).read_text(errors="replace"), path).items():
                if r.get("lmax") is None and r.get("wmax") is None:
                    continue
                by_class.setdefault(r.get("class"), []).append(model)
        for cls, models in sorted(by_class.items()):
            if cls == CAP_CLASS and roles.get("cap"):
                continue                      # recorded under a role
            named = any(m.lower() in prose for m in models)
            assert named, (
                f"{family} states a maximum for {len(models)} `{cls}` "
                f"gencell(s) {sorted(models)[:4]} and its record neither "
                f"records nor names any of them — a reader takes the record "
                f"as this family's whole answer")
