* deterministic_stub extraction_strategy=deterministic_stub low_confidence=true
* ldo — SPICE netlist (stub)
.subckt ldo vdd vss vin vout
* replace with extracted netlist when analog-netlist-gen skill runs
r_stub vin vout 1k
.ends ldo
