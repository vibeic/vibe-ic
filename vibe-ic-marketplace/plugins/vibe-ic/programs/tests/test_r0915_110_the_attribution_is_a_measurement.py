"""Which stage takes a pin's last access point is MEASURED, not reconstructed.

R-0915-110. MEASURED on subservient x gf180mcuD as a DIE (int4 arm,
2026-09-21, image 0.3.67): the SDR candidate check answered 0 inaccessible
pins -- truthfully, for the context it was asked in -- and the adopt path's PG
re-route then died on

    [ERROR DRT-1231] Pin u_core/_3245_/ZN does not have access point   (x6)

FIVE stages run between those two points (postroute_spef_extract,
postroute_antenna_repair which inserts diodes, postroute_drv_reconverge,
postroute_antenna_reconverge, postroute_fill), and an offline probe of
`antenna_pre_repair.odb` found the design still CLEAN there -- 0 of 14374
signal ITerms without access -- so the loss is in a later stage and nothing in
the run said which.

The probe is that answer, in the run's own log, at every boundary.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))














def test_every_boundary_between_the_check_and_the_reroute_is_probed():
    """The five stages the int4 arm named, plus the PG reconnect that follows
    them -- the last moment before the re-route, so a future regression dies
    legibly with the pin named."""
    src = (Path(__file__).resolve().parents[1]
           / "phase3_one_shot_runner.py").read_text()
    for tag in ("after_postroute_spef_extract",
                "after_postroute_antenna_repair",
                "after_postroute_drv_reconverge",
                "after_postroute_antenna_reconverge",
                "after_postroute_fill_before_pg_reconnect",
                "after_pg_connect"):
        assert f'_pin_access_probe_tcl("{tag}")' in src, tag
