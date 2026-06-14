crashbackups stop
gds readonly true
gds rescale false
set ::env_lefs [split $env(LEFS) ";"]
foreach lf $::env_lefs {
    if {[string trim $lf] ne ""} { lef read $lf }
}
def read $env(DEF)
load $env(TOP)
select top cell
cellname rename $env(TOP) $env(TOP)
# v0.3.9 — ORGANIC #509: promote the DEF PINS to Magic PORTS so the top
# I/O pin labels are streamed to the GDS on the label-purpose layer.
# Pre-#509 the streamout wrote only the met PORT GEOMETRY (DEF `- clk +
# NET clk + LAYER met3`) with no port TEXT — so when signoff LVS later
# `gds read`s + extracts, the top I/O (clk/rst/x[..]/y) came back as
# internal nets (uppercase), `port makeall` had nothing to promote, and
# every top port extracted as a DISCONNECTED node → a spurious top-level
# 'Netlists do not match.' even when every leaf cell matched. Promoting
# the DEF pins to ports here writes the labels so re-extraction recovers
# named, connected top ports. chip-AGNOSTIC: operates on whatever DEF
# pins exist, no chip-specific port names.
if {[catch {port makeall} _porterr]} {
    puts "PORT_MAKEALL_NONFATAL $_porterr"
}
gds write $env(GDS_OUT)
puts "MAGIC_GDS_WRITTEN $env(GDS_OUT)"
quit -noprompt
