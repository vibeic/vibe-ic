# SYNTHESIS STRATEGY declared by the CROSS-LAYER SEARCH, not by the design.
#
# `synthesis_strategy` is admitted by crosslayer_search_space with
# justification_kind = no_design_change: it RE-MAPS the same RTL and changes no
# design behaviour, so no specification permission is required and none is
# claimed.  The shipped phase-3 runner exposes no first-class synthesis-strategy
# flag; `input/reference_flow` is the only actuator it reads, so that is where
# this arm writes.  RTL / SDC / L19 bytes are unchanged and their digests are
# published with every trial.
#
# ADDER_MAP_FILE stages a $lcu techmap so the carry chain is realised as a
# han-carlson parallel-prefix network instead of a ripple chain.  The map is
# yosys's OWN shipped choice file, copied out of the pinned EDA image
# unmodified; SWAP_ARITH_OPERATORS (`alumacc`) is the structural enabler the
# runner documents the techmap as requiring.
SWAP_ARITH_OPERATORS = 1
ADDER_MAP_FILE = han-carlson.v
REMOVE_ABC_BUFFERS = 1
