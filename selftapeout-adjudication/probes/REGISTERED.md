# J80 — predictions registered BEFORE the probe ran

Registered at: (see registered_at.txt, written in the same command that created this file)
Subject: `proj/matmul_d3800/phase3/stage3/pnr/post_cts.def` — die 3800, the arm whose
INITIAL placement legalized OK, written by the runner at 04:30 and closed since.

## What is being probed, and what it is NOT

The report's one OPEN item is the POST-HOLD verdict, and all five arms are inside
rung 5 (full-die displacement), which has not terminated in up to 13 h. J79 registered
P1/P2/P3 about that verdict. **This probe does not answer P1/P2/P3.** It is run on the
POST-CTS state, which is a DIFFERENT state from post-hold (hold repair has not run).
It tests the MECHANISM those predictions rest on — J53's claim that the residual is
created by 2 055 root-sized clock buffers, and that rung 6 (the clkbuf downsize) is
the first rung that changes AREA rather than SEARCH.

## Q1 — how does J51's 7.5-9.1x split between CTS and hold repair?

J51 measured, at die 3800, `before CTS` residual **312** and post-hold **2 352**, and
attributed the growth to "CTS and hold repair" as one term. `post_cts.def` sits exactly
between them and nobody has read its residual.

**PREDICTION Q1: the post-CTS residual is ABOVE 1 500** — i.e. CTS alone accounts for
most of the growth and hold repair for the minority. Reason: J53 measured that CTS's
2 055 root-master clock buffers are 225 337 um^2 = **82.3 %** of everything CTS and
hold repair added together.
FALSIFIER: a post-CTS residual below 1 500 means hold repair, not CTS, is the larger
half, and J53's 82.3 % of AREA does not carry over to COUNT.

## Q2 — is the clkbuf downsize actually the lever?

The flow's rung 6 swaps every `*__clkbuf_*` master wider than `clkbuf_4` down to
`clkbuf_4` (28.000 um -> 7.840 um), then re-runs `detailed_placement` at DEFAULT
displacement. This probe runs the identical code on the post-CTS state.

**PREDICTION Q2: after the swap, `detailed_placement` at default displacement leaves a
residual STRICTLY BELOW 50 % of the pre-swap residual measured in the same run.**
FALSIFIER: a post-swap residual >= 50 % of the pre-swap one means the downsize is not
the lever J53's account makes it, and the report's reason for P1/P2 is weakened even
though P1/P2 themselves are untouched.

## Rules this probe holds to

* It runs rungs 1-4 (default / 5 / 20 / 100) and NEVER the full-die rung, so it cannot
  become another 13-hour arm.
* It reads `post_cts.def` and writes NOTHING into any project directory.
* `docker run` in a fresh container with `--skip` first, never `docker exec`, so it
  cannot disturb the five live arms.
* No hand-placement, no geometry edit, no rule relaxed. The swap is the FLOW'S OWN
  code, copied verbatim from `pnr.tcl:8325-8344`.
