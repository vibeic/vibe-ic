"""R-0915-128: a SPEF cannot annotate a driver outside the die, so stop asking.

THE MEASUREMENT THAT EARNED THE RULING. spm run20 produced a complete SPEF-based
multi-corner STA -- an 8.5 MB transient carrying all six (corner, role) sections
with finite MET slacks (FF 14.31/0.51, SS 6.48/1.55, TT 11.87/0.83) -- and
`_emit_declared_process_sta` refused to promote it, because
`_sta_native_census_complete` was False for every SETUP section. From the run's
own population.json for FF: 3131 drivers, 3084 EXPLICIT_PG_NOT_SIGNAL_PARASITICS,
36 REQUIRED_OR_UNKNOWN -- of which 35 are top-level DEF PINS (the design declares
38) and the 36th is `u_pad_p/PAD`. Every one faces OFF the die, and a SPEF
extracted from the routed die cannot carry it. Step 23 therefore FAILed
`required_outputs missing: ['reports/phase3/sta_spef_based.rpt']` over a
measurement the run had made and thrown away.

The ruling grants a typed class for exactly that, with four conditions, each
pinned below:
  (a) the judgement is DERIVED from the DEF -- the PINS section for a top-level
      pin, COMPONENTS plus the run's LEF IO inventory for a pad terminal -- and
      never from a name pattern;
  (b) the class is DISCLOSED by name and count, in population.json and in the
      promoted report's header;
  (c) the census keeps its teeth: an INTERNAL unannotated driver still refuses,
      and an off-die driver never masks one on the same net;
  (d) the six sections promote unchanged -- no slack is touched.
"""
from __future__ import annotations


IO_MASTER = "fixture_io__bi_t"
PAD_INST = "u_pad_p"


def report(drivers, partial=0):
    """The OpenSTA fragment `classify` reads: its own unannotated-driver list."""
    return ("STA_LINK_CENSUS total=2 linked=2 missing=0\n"
            "STA_LINK_INSTANCE u_core RESOLVED\n"
            f"STA_LINK_INSTANCE {PAD_INST} RESOLVED\n"
            f"Found {len(drivers)} unannotated drivers.\n"
            + "".join(f"{d}\n" for d in drivers)
            + f"Found {partial} partially unannotated drivers.\n")


def deffile(tmp_path, *, pins=("p",), nets=None, components=None):
    """A DEF stating its own ports, instances and net topology."""
    nets = nets if nets is not None else [
        ("p", "SIGNAL", [("PIN", "p"), (PAD_INST, "PAD")]),
    ]
    components = components if components is not None else [
        ("u_core", "fixture_std__inv"), (PAD_INST, IO_MASTER),
    ]
    out = ["VERSION 5.8 ;", "DESIGN chip_top ;", "UNITS DISTANCE MICRONS 1000 ;",
           "DIEAREA ( 0 0 ) ( 1000 1000 ) ;",
           f"COMPONENTS {len(components)} ;"]
    out += [f"- {i} {m} + PLACED ( 0 0 ) N ;" for i, m in components]
    out.append("END COMPONENTS")
    out.append(f"PINS {len(pins)} ;")
    out += [f"- {p} + NET {p} + DIRECTION INPUT + USE SIGNAL ;" for p in pins]
    out.append("END PINS")
    out.append(f"NETS {len(nets)} ;")
    for name, use, conns in nets:
        joined = " ".join(f"( {i} {pin} )" for i, pin in conns)
        out.append(f"- {name} {joined} + USE {use} ;")
    out.append("END NETS")
    out.append("END DESIGN")
    path = tmp_path / "chip_top.def"
    path.write_text("\n".join(out) + "\n")
    return path


# ── (a) derived from the DEF, never from a name ─────────────────────────────








# ── (c) the census keeps its teeth ──────────────────────────────────────────






# ── (b) disclosure by name and count ───────────────────────────────────────




# ── the RUNNER side: the promotion predicate, and (d) sections untouched ────
def test_the_promotion_predicate_forwards_the_inventory(tmp_path):
    """`_sta_native_census_complete` is what gates the rename, so the inventory
    has to reach IT -- fixing only `classify` would leave the report unpromoted,
    which is how run20 looked with a correct classifier."""
    import phase3_one_shot_runner as R
    d = deffile(tmp_path)
    # the PAD terminal is the discriminating shape: a top-level PIN is off-die
    # from the DEF's PINS section alone and needs no inventory, so it could not
    # show whether the inventory reached the predicate.
    body = report([f"{PAD_INST}/PAD"])
    assert R._sta_native_census_complete(body, d) is False
    assert R._sta_native_census_complete(body, d, io_masters={IO_MASTER}) is True
    # and the pin-only shape passes either way, which is the DEF-alone basis
    assert R._sta_native_census_complete(report(["p"]), d) is True


def test_the_inventory_resolver_fails_closed(tmp_path):
    """No record, no inventory -- and therefore no off-die class."""
    import phase3_one_shot_runner as R
    assert R._io_masters_for(tmp_path) == set()


def test_a_leading_disclosure_leaves_every_section_and_slack_untouched(tmp_path):
    """CONDITION (d). The header is a comment block; the six sections and their
    numbers must survive it byte-for-byte."""
    import sta_corner_record_completeness_check as native
    rpt = "\n".join(
        f"=== {role} corner: process={corner} ===\n"
        f"STA_BASIS: POST_ROUTE_SPEF\nworst slack "
        f"{'max' if role == 'SETUP' else 'min'} {value}\n"
        for corner, role, value in (("FF", "SETUP", "14.31"), ("FF", "HOLD", "0.51"),
                                    ("SS", "SETUP", "6.48"), ("SS", "HOLD", "1.55"),
                                    ("TT", "SETUP", "11.87"), ("TT", "HOLD", "0.83")))
    before = native._split_sections(rpt)
    disclosed = ("# STA_ANNOTATION_OFF_DIE FF: 36 off-die driver(s)\n"
                 "# STA_ANNOTATION_OFF_DIE basis: the DEF PINS section\n" + rpt)
    after = native._split_sections(disclosed)
    assert len(after) == len(before) == 6
    assert [(c, k) for k, c, _b in after] == [(c, k) for k, c, _b in before]
    assert ([native.extract_slacks(b) for _k, _c, b in after]
            == [native.extract_slacks(b) for _k, _c, b in before])
