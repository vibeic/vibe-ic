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
#   VIBEIC_FILL_SKIP     comma-separated sibling script names the generator
#                        `require_relative`s and this caller is providing
#                        itself (see below). Empty by default: the PDK's whole
#                        generator runs.
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

# SKIPPING A PASS THE CALLER DOES NOT WANT, WITHOUT TOUCHING THE PDK'S FILES.
#
# The PDK's top-level generator is a list of `require_relative` calls, one per
# layer family (`fill_comp.rb`, `fill_poly2.rb`, `fill_metal.rb`). A caller that
# already has a filler for one of those families must not run a SECOND one over
# it: two generators writing the same dummy layer produce fill that neither of
# them checked against the other's, and the merged result violates the
# foundry's own metal rules. MEASURED, gf180mcuD, one die filled by both: 234437
# KLayout DRC errors (min-space and min-width on the merged metal), where each
# filler ALONE was DRC-clean. Neither filler is wrong; running both is.
#
# So the caller names the sibling passes it is providing itself, and Ruby's own
# `require_relative` bookkeeping does the rest: a path already in
# `$LOADED_FEATURES` is not loaded again. The PDK's files are read exactly as
# shipped and none of them is edited, copied or re-implemented -- the passes the
# caller DID ask for run verbatim, and the report records which were skipped and
# why.
skip = (ENV["VIBEIC_FILL_SKIP"] || "").split(",").map { |s| s.strip }.reject { |s| s.empty? }
if !skip.empty?
  base = File.dirname(File.expand_path(ENV["VIBEIC_FILL_SCRIPT"].to_s))
  skip.each do |name|
    path = File.expand_path(name, base)
    raise "VIBEIC_FILL_SKIP names #{path}, which the PDK does not ship" unless File.exist?(path)
    $LOADED_FEATURES << path
    puts "SKIPPED_PASS: #{path}"
  end
end

script = ENV["VIBEIC_FILL_SCRIPT"]
raise "VIBEIC_FILL_SCRIPT is unset" if script.nil? || script.empty?
raise "VIBEIC_FILL_IN is unset"     if $input.nil?  || $input.empty?
raise "VIBEIC_FILL_OUT is unset"    if $output.nil? || $output.empty?

load script
