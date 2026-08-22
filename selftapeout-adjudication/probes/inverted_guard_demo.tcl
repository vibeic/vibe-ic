# J80 side-finding — the flow's clkbuf-downsize diagnostic fires on SUCCESS and is
# SILENT on FAILURE.  This is plain Tcl semantics, so it runs in any tclsh; no EDA
# tool is needed to see it.  The shape is copied from
# phase3_one_shot_runner.py:16109 / :16125 (identical on origin/main a4caccefe).
puts "--- shipped shape:  if {![catch {BODY} e]} { puts NONFATAL: \$e }"
foreach {label body} {
  "BODY SUCCEEDS" {puts "      body ran: swapped=2089"}
  "BODY FAILS"    {error "findMaster returned NULL"}
} {
  puts "  $label:"
  if {![catch $body e]} { puts "    NONFATAL: $e" }
}
puts ""
puts "--- correct shape:  if {[catch {BODY} e]}  { puts NONFATAL: \$e }"
foreach {label body} {
  "BODY SUCCEEDS" {puts "      body ran: swapped=2089"}
  "BODY FAILS"    {error "findMaster returned NULL"}
} {
  puts "  $label:"
  if {[catch $body e]} { puts "    NONFATAL: $e" }
}
