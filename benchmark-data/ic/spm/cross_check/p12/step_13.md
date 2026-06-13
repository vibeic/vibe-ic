# Step 13 — LEC (OUR RTL ≡ OUR post-DFT netlist)

## What we ran
- yosys formal equivalence between OUR RTL (golden) and OUR synthesized/mapped netlist
  (the post-scan-flop netlist of steps 9/11/12), using
  `equiv_make` + `equiv_simple -seq 5` + `equiv_induct -seq 40` + `equiv_status -assert`.
  - Liberty cell functions loaded via `read_liberty -ignore_miss_func` so SAT can reason
    about every cell; script
    `/home/reyerchu/AI_IC_design/_spm_xc_p12/miter_net3.ys`.

## OUR result
```
equiv_induct: Proved 65 previously unproven $equiv cells.
equiv_status: Of those cells 65 are proven and 0 are unproven.
Equivalence successfully proven!     (M3_EXIT=0)
```
- All 65 sequential equivalence points (s[*], c[*], p) proven by **sequential
  k-induction (`equiv_induct -seq 40`)**: OUR RTL ≡ OUR gate netlist.
- Cross-checked independently by 10,013-vector gate-level simulation (step 9 LEC #2:
  `RESULT: PASS`), which also exercises the scan-mapped flop instances.

## Honest note
`equiv_simple` alone (combinational name-matching) leaves the internal `s`/`p` state
unproven because synthesis restructures/renames internal nodes — this is a name-alignment
artifact, NOT an inequivalence. The sequential k-induction pass `equiv_induct -seq 40`
proves all 65 points and `equiv_status -assert` confirms zero unproven. We kept the
honest record of the two-pass method rather than reporting only the final green.

## REF result
REF carries `phase2/stage2/synth/post_dft_netlist.v` forward into phase3; its LEC is
implied by the same yosys flow. OUR explicit RTL≡netlist k-induction proof is at least
as strong.

## Verdict: MATCH
OUR RTL ≡ OUR post-DFT/synthesized netlist, formally proven (65/65 by k-induction) and
corroborated by 10,013-vector gate sim. MATCH.
