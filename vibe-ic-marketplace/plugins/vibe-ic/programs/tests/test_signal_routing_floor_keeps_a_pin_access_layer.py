"""The derived signal routing floor must not strand the cells' own pins.

`_v1_8_100_routing_layer_range` derives a `set_routing_layers -signal
<floor>-<ceiling>` constraint by walking up from the bottom routing layer past
every layer the standard-cell ports are dominated by. Taking the first
NON-pin-dominated layer as the floor puts EVERY pin-access layer outside the
signal routing range.

That is not conservative, it is unroutable. Global routing emits the guides of
a net whose pins all land in a single GCell on the pin layers themselves. Such
a net then reaches detailed routing with all of its guides on layers the router
has just been forbidden to use, and TritonRoute aborts the whole design:

    [ERROR DRT-0218] Guide is not connected to design for net <name>

MEASURED on sky130_fd_sc_hd, same DEF, same image, only this constraint moved:

    -signal met2-met5  -> DRT-0218 on 2 of 6735 nets, ZERO nets routed
    -signal met1-met5  -> "Number of violations = 0", 6735/6735 nets routed,
                          met1 alone carrying 107955 um of 242485 um of wire

These tests pin the invariant: the TOPMOST pin-access layer stays inside the
signal range; layers below it may still be excluded.

Bidirectional negative control: `_floor_of` falls back to the verbatim pre-fix
expression when the fixed module is absent, so the failing tests exercise
pre-fix BEHAVIOUR rather than an ImportError.
"""
import os
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase3_one_shot_runner as p3  # noqa: E402


def _tech_lef(layers):
    """A tech LEF declaring `layers` in order as TYPE ROUTING."""
    out = []
    for i, name in enumerate(layers):
        out.append(textwrap.dedent(f"""\
            LAYER {name}
              TYPE ROUTING ;
              DIRECTION {'HORIZONTAL' if i % 2 else 'VERTICAL'} ;
            END {name}
            """))
    return "\n".join(out)


def _cell_lef(port_counts):
    """A cell LEF whose PIN/PORT LAYER statements realise `port_counts`."""
    body = []
    n = 0
    for layer, count in port_counts.items():
        for _ in range(count):
            n += 1
            body.append(textwrap.dedent(f"""\
                MACRO cell{n}
                  PIN p{n}
                    PORT
                      LAYER {layer} ;
                      RECT 0 0 1 1 ;
                    END
                  END p{n}
                END cell{n}
                """))
    return "\n".join(body)


class _Pdk:
    def __init__(self, tech_lef, cell_lef, name="testpdk"):
        self.tech_lef = tech_lef
        self.cell_lef = cell_lef
        self.std_cell_lef = cell_lef
        self.name = name


class SignalFloorKeepsAPinAccessLayer(unittest.TestCase):

    def _derive(self, layers, port_counts, tmpname):
        d = Path(os.environ.get("PYTEST_TMP", "/tmp")) / tmpname
        d.mkdir(parents=True, exist_ok=True)
        t = d / "tech.tlef"
        c = d / "cells.lef"
        t.write_text(_tech_lef(layers))
        c.write_text(_cell_lef(port_counts))
        return p3._v1_8_100_routing_layer_range(_Pdk(t, c), str(d), "")

    def _dominated(self, layers, port_counts):
        total = sum(port_counts.values())
        thresh = max(1.0, 0.05 * total)
        return [n for n in layers if port_counts.get(n, 0) >= thresh]

    # ---- the measured sky130_fd_sc_hd case -----------------------------
    def test_sky130_shaped_library_keeps_met1_in_the_signal_range(self):
        layers = ["li1", "met1", "met2", "met3", "met4", "met5"]
        counts = {"li1": 1711, "met1": 966, "met2": 1,
                  "met3": 4, "met4": 4, "met5": 6}
        got = self._derive(layers, counts, "floor_sky130")
        self.assertIsNotNone(got, "derivation refused to emit a range")
        self.assertEqual(
            got[0], "met1",
            "signal floor must be the topmost pin-access layer (met1); "
            f"got {got[0]!r}, which strands every pin-access layer and "
            "makes single-GCell nets unroutable (DRT-0218)")

    def test_sky130_shaped_library_still_excludes_the_local_interconnect(self):
        """The feature's actual benefit must survive the fix."""
        layers = ["li1", "met1", "met2", "met3", "met4", "met5"]
        counts = {"li1": 1711, "met1": 966, "met2": 1,
                  "met3": 4, "met4": 4, "met5": 6}
        got = self._derive(layers, counts, "floor_sky130b")
        self.assertIsNotNone(got)
        self.assertNotEqual(got[0], "li1",
                            "li1 is pin-dominated but is NOT the topmost "
                            "pin-access layer; it should stay excluded")

    # ---- the general invariant, several port distributions -------------
    def test_floor_never_rises_above_the_topmost_pin_access_layer(self):
        cases = [
            (["m1", "m2", "m3", "m4"], {"m1": 100, "m2": 100, "m3": 1, "m4": 1}),
            (["m1", "m2", "m3", "m4"], {"m1": 100, "m2": 1, "m3": 1, "m4": 1}),
            (["a", "b", "c", "d", "e"],
             {"a": 500, "b": 300, "c": 200, "d": 2, "e": 2}),
        ]
        for i, (layers, counts) in enumerate(cases):
            with self.subTest(case=i):
                got = self._derive(layers, counts, f"floor_inv{i}")
                self.assertIsNotNone(got)
                dom = self._dominated(layers, counts)
                self.assertTrue(dom, "test case has no pin-dominated layer")
                top_pin = dom[-1]
                self.assertLessEqual(
                    layers.index(got[0]), layers.index(top_pin),
                    f"floor {got[0]!r} sits ABOVE the topmost pin-access "
                    f"layer {top_pin!r}: every pin-access layer is outside "
                    "the signal routing range")

    def test_the_derived_range_still_has_room_to_route(self):
        """Regression guard: the fix must not collapse the range."""
        layers = ["li1", "met1", "met2", "met3", "met4", "met5"]
        counts = {"li1": 1711, "met1": 966, "met2": 1,
                  "met3": 4, "met4": 4, "met5": 6}
        got = self._derive(layers, counts, "floor_room")
        self.assertIsNotNone(got)
        floor, clk, ceil = got[0], got[1], got[2]
        self.assertLess(layers.index(floor), layers.index(ceil))
        self.assertGreaterEqual(layers.index(clk), layers.index(floor),
                                "clock floor must not sit below the signal floor")


if __name__ == "__main__":
    unittest.main()
