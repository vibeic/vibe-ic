# delta_sigma — topology (analog-topology-select)

Topology family: **2nd-order single-loop incremental delta-sigma modulator** (switched-capacitor, R3: SC or CT designer's choice per L5).

Device-level / block primitives:
- **Two cascaded switched-capacitor integrators** built from **NMOS/PMOS OTA differential amplifiers** (folded-cascode OTA) with sampling/integration capacitors.
- **1-bit comparator** (clocked latch, NMOS-input differential preamp + regenerative latch) producing the OUTn/dout bitstream.
- **1-bit feedback DAC** (capacitor + reference switches to Vref = VHI-VLO) subtracting the quantized output from the input.
- **Non-overlapping clock generator** (from CK4/5/6) driving the SC phases.
- Incremental reset switches (NMOS) that clear the integrators each conversion window.

Rationale: 2nd-order + OSR 256 comfortably meets ENOB >= 14; incremental (reset-per-window) matches the per-channel conversion model in L5.
