# SYNTHESIS STRATEGY declared by the CROSS-LAYER SEARCH, not by the design.
#
# The `synthesis_strategy` lever is admitted by crosslayer_search_space with
# justification_kind = no_design_change: it re-maps the same RTL and changes no
# design behaviour, so no specification permission is required and none is
# claimed.  The shipped phase-3 runner exposes NO first-class synthesis-strategy
# flag; `input/reference_flow` is the ONLY actuator it reads, so that is where
# this arm has to write.  The RTL bytes, the SDC and the L19 spec are unchanged
# and their digests are published alongside every trial, so "did the design
# change?" is answered by hash and not by assertion.
#
# REMOVE_ABC_BUFFERS -> yosys `opt_clean -purge` after abc, dropping the
# identity/buffer cells and dangling nets abc introduces before PnR sees them.
REMOVE_ABC_BUFFERS = 1
