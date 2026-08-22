"""Shared cut rule.  J73 caught a table that split the placement stage at
`PNR_STAGE: cts` and so swept up the tapcell-prune / spare-tieoff / before-CTS blocks
that run AFTER the initial verdict.  J75 then reintroduced the identical defect in a
different script within the same hour.  So the rule lives in ONE place."""
import re
_V = re.compile(r"INITIAL_DPL_LEGALIZE_(OK|FAILED)[^\n]*")

def initial_ladder(txt):
    """Everything up to and including the initial-placement verdict line."""
    pre = txt.split("PNR_STAGE: cts")[0]
    m = _V.search(pre)
    return pre[:m.end()] if m else pre

def post_hold(txt):
    """Everything after the hold_repair stage marker."""
    return txt.split("PNR_STAGE: hold_repair")[-1]
