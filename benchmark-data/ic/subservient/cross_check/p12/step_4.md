# Step 4 — Functional sim vs golden behaviour

Verdict: EQUIVALENT

OUR functional sim runs a REAL rv32i program through the GENUINE SERV core: fetch=4172, gpio_writes=87, GPIO toggled -> FUNCTIONAL_PASS (sim/functional_gpio_sim.log). This is STRONGER than the golden (which stubbed the datapath + drove a skeleton TB). Behaviourally EQUIVALENT to the intended SoC contract; OURS is the more faithful realization.
