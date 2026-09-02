"""ROUND-3 (subservient x gf180mcuD, 2026-09-02): a fill that stays below the
foundry floor must say whether ANY legal fill could have reached it.

MEASURED on the round-2 candidate GDS (416x416 um, gf180mcuD deck, 2 um
dummy-to-circuit clearance): metal2 drawn 8.85%, room for dummy 29.78% of
the die, fill achieved 22.59% against a 30% rule; the widest configured
shape (3.37 um at 0.98 um spacing) packs at most (3.37/4.35)^2 = 60% of a
region, so the lattice ceiling is 8.85 + 0.60 x 29.78 = 26.7% < 30%. The
PDK's own fill recipe reaches 19-20%. The rule is out of reach of fill on
that layout, and the report now says so instead of "target NOT reached".

FALSIFICATION (two-tree): `_metal_fill_capacity`, `capacity_summary_lines`
and the `capacity` key do not exist on the pre-fix tree.

chip-AGNOSTIC: the numbers below are the arithmetic's own fixture, not a PDK.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _metal_fill_capacity as C  # noqa: E402
import metal_fill_emit as E  # noqa: E402


def test_lattice_ceiling_arithmetic():
    lc = C.lattice_ceiling(0.0885, 0.2978, 3.37, 0.98)
    assert abs(lc["packing"] - (3.37 / 4.35) ** 2) < 1e-9
    assert abs(lc["ceiling"] - (0.0885 + 0.2978 * lc["packing"])) < 1e-9
    assert lc["ceiling"] < 0.30                      # the measured case
    assert C.lattice_ceiling(0.1, 0.5, 0, 1.0) is None
    assert C.lattice_ceiling(0.1, 0.5, "x", 1.0) is None
    # widening the shape can only raise the ceiling
    assert (C.lattice_ceiling(0.1, 0.5, 5.0, 0.98)["ceiling"]
            > C.lattice_ceiling(0.1, 0.5, 2.0, 0.98)["ceiling"])


def test_floor_from_config_derivation():
    assert C._floor_frac({"_derivation": {"density_floor_pct": 30}}) == 0.30
    assert C._floor_frac({"_derivation": {"density_floor_pct": True}}) is None
    assert C._floor_frac({}) is None


def _report(after, ceiling, floor=0.30):
    return {
        "verdict": "PARTIAL",
        "layers": [{"name": "m2", "density_after": after,
                    "worst_window_after": after}],
        "capacity": {"layers": [{
            "name": "m2", "floor": floor, "lattice_ceiling": ceiling,
            "drawn_frac": 0.0885, "free_frac": 0.2978,
            "space_to_metal_um": 2.0, "packing_achieved": 0.46}]},
    }


def test_summary_names_unreachable_layers_only():
    lines = E.capacity_summary_lines(_report(after=0.2259, ceiling=0.267))
    assert len(lines) == 1
    assert "UNREACHABLE" in lines[0] and "m2" in lines[0]
    assert "26.7%" in lines[0] and "30%" in lines[0]
    # reachable-in-principle wording when the ceiling clears the floor
    lines = E.capacity_summary_lines(_report(after=0.2259, ceiling=0.35))
    assert len(lines) == 1 and "reachable in principle" in lines[0]
    # a layer that already clears the floor is not listed
    assert E.capacity_summary_lines(_report(after=0.31, ceiling=0.35)) == []
    # no capacity block -> nothing to say
    assert E.capacity_summary_lines({"verdict": "PARTIAL", "layers": []}) == []


def test_capacity_probe_never_raises(tmp_path):
    class _R:
        kind = "none"

        def covers(self, p):
            return False

        def run(self, *a, **k):
            raise OSError("no klayout here")

    res = E._capacity_probe(_R(), tmp_path, tmp_path / "x.gds",
                            tmp_path / "c.json", None)
    assert "error" in res
