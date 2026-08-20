# pdk_fill_driver.rb — run the PDK's OWN density-fill generator, unmodified.
#
# The generators PDKs ship for dummy fill (gf180mcu's `fill_all.rb` and the
# `fill_comp.rb` / `fill_poly2.rb` / `fill_metal.rb` it requires) are KLayout
# Ruby batch scripts that read their inputs from GLOBALS -- `$input`,
# `$output`, `$threads` -- rather than from a command line. KLayout's own
# `-rd name=value` sets those globals to STRINGS, and the scripts assign
# `tp.threads = $threads`, which needs an Integer. So `-rd threads=8` raises
# inside the PDK's script.
#
# This driver exists only to bridge that: it reads the environment, sets the
# globals with their correct TYPES, and `load`s the PDK's script. It contains
# no fill geometry, no layer number, no spacing and no density target -- all of
# those are foundry data and stay in the PDK's own file, which is loaded as
# shipped. `load` (not `require`) is deliberate: the PDK scripts use
# `require_relative` for their siblings, which resolves against the LOADED
# file's own directory, so the PDK's own sibling scripts are the ones that run.
#
# Environment:
#   VIBEIC_FILL_SCRIPT   absolute path of the PDK generator to load
#   VIBEIC_FILL_IN       input layout
#   VIBEIC_FILL_OUT      output layout
#   VIBEIC_FILL_THREADS  integer; defaults to KLayout's own default when unset
#   VIBEIC_FILL_IGNORE_ACTIVE  "1" sets the generator's own
#                        `$Metal<N>_ignore_active` opt-outs (a switch the PDK
#                        script itself declares); anything else leaves them nil,
#                        which is the PDK's stricter default.

$input  = ENV["VIBEIC_FILL_IN"]
$output = ENV["VIBEIC_FILL_OUT"]

if ENV["VIBEIC_FILL_THREADS"] && !ENV["VIBEIC_FILL_THREADS"].empty?
  $threads = ENV["VIBEIC_FILL_THREADS"].to_i
end

if ENV["VIBEIC_FILL_IGNORE_ACTIVE"] == "1"
  # The PDK's fill_metal.rb reads one global per metal layer. Setting them is
  # using a switch the PDK declares, not overriding a PDK rule: the guarded
  # branch drops only DM.4-DM.7 (fill-to-previous/subsequent-metal spacing),
  # which the PDK's own comment says makes a digital design "almost impossible
  # to fill". OFF by default here, so the strict branch is what runs unless a
  # caller asks otherwise and says why.
  (1..5).each { |n| eval("$Metal#{n}_ignore_active = true") }
end

script = ENV["VIBEIC_FILL_SCRIPT"]
raise "VIBEIC_FILL_SCRIPT is unset" if script.nil? || script.empty?
raise "VIBEIC_FILL_IN is unset"     if $input.nil?  || $input.empty?
raise "VIBEIC_FILL_OUT is unset"    if $output.nil? || $output.empty?

load script
