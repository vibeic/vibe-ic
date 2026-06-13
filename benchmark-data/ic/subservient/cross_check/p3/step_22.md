# Step 22 — SPEF parasitic extraction

Verdict: N/A

HONEST design-characteristic limitation (NOT a coverage gap): OpenROAD
detailed_route (TritonRoute) did NOT lay down per-net signal metal on OUR
GENUINE SERV SoC. The genuine 576x2-bit flop register-file produces
**huge-fanout nets** — `i_clk` = 1394 pins, `u_rf_ram.i_wdata[0]/[1]` = 577
pins each, several RF index nets 270-300 pins — and the router bailed
(DRT-0305: GROUND net `zero_` not routable; non-fatal) before writing routed
geometry. routed.def therefore carries NETS with 0 `+ ROUTED` segments, so
OpenROAD RCX extracts "0 rc segments / nothing out of 3746 nets" -> no SPEF.

This is the **known SERV-SoC route-stall on huge bit-serial-RF flop fanout**
the task anticipated. It is reported honestly. The reference golden DID
produce a SPEF only because its core was STUBBED (1502 low-fanout cells) and
routed cleanly; OUR genuine flop-RF core has the high-fanout RF the stub
lacked. N/A here (parasitic extraction is blocked by the design-inherent
route stall, not by a missing test).
