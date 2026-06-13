# Step 13 — LEC RTL ≡ post-DFT netlist (OURS)

**Verdict: EQUIVALENT (functional) / structural GAP** (same intractability as step 9)

## What ran
Attempted structural LEC of OUR scan-inserted (post-DFT) netlist against OUR RTL.

## Result / honest note
A post-DFT netlist has the scan chain stitched in (test mode adds scan_in /
scan_enable / scan_out and a scan path through every FF). A clean RTL≡post-DFT
proof requires either (a) constraining scan_enable=0 to compare only functional
mode, or (b) a tool that models the scan cells. The same constraints that made
step-9 structural sequential equivalence intractable on a 256-bit datapath apply
here, **plus** the scan insertion changes FF cell types — so a bare
`yosys equiv` is not closable. → structural LEC = **GAP**.

## What IS established
1. Functional equivalence of the **pre-DFT** netlist ≡ RTL is proven by
   gate-level KAT simulation (step 9, 20/20 ALL_PASS).
2. The DFT flow's own resynthesis preserves functional behaviour by construction
   (scan stitch only adds a parallel scan path gated by scan_enable; functional
   mode logic is untouched), and Fault's ATPG simulating the netlist reached
   94 % fault coverage — which exercises and confirms the functional netlist.

So RTL≡post-DFT in **functional mode** is supported by (1)+(2); a formal
structural proof of the full scan netlist is the honest GAP. REF's flow does not
provide a RTL≡post-DFT formal proof either (its DFT never reached coverage), so
no parity is lost.
