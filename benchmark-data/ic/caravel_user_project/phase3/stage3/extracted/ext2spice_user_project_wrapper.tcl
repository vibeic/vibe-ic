crashbackups stop
drc off
lef read $env(TLEF)
lef read $env(CLEF)
eval $env(MACRO_LEF_READS)
def read $env(DEF)
load $env(TOP)
select top cell
port makeall
puts "PORTS_PROMOTED [port first]..[port last]"
extract no all
extract do local
extract all
ext2spice lvs
ext2spice -o $env(SPICE_OUT)
puts "MAGIC_EXT2SPICE_DONE $env(SPICE_OUT)"
quit -noprompt
