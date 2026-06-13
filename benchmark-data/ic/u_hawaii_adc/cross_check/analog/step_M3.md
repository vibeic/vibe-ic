# Step M3 — mixed-signal timing / interface check  ·  Verdict: IN-RANGE
OURS: modulator clock fclk=1 MHz (CK4/5/6), 1-bit serial output per channel; OTA GBW (27-67 MHz across corners) >> 5*fclk so SC settling is met within a clock phase. Interface (CLK/INP/INN/VREF/BS) matches the hardmacro LEF pins.
REF: golden top pins CK4/5/6 + OUT1-6 + dout confirm the same clocked-serial interface.
