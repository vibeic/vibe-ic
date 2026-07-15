# ldo — topology (analog-topology-select)

Topology family: **PMOS-pass low-dropout regulator with a single-stage NMOS-input differential error amplifier** (R3: designer's choice per L5).

Device-level primitives:
- **PMOS pass device** (`xmp_pass`): large-W p-channel series pass transistor from IOVDD (1.8V) to CORE (1.2V); low dropout, high current.
- **NMOS-input differential pair** (`xmn1`/`xmn2`): error amplifier comparing Vref against the resistive feedback tap.
- **PMOS current-mirror active load** (`xmp1`/`xmp2`): differential-to-single-ended conversion for the error amp.
- **NMOS tail current source** (`xmn_tail`) + **NMOS bias mirror** (`xmn_b`): sets the error-amp bias current.
- **Miller compensation cap** (`cc`) across the pass-device gate for stability.
- **Feedback divider** (`r1`/`r2`): sets Vout = Vref * (1 + r1/r2).

Rationale: PMOS pass gives the 0.6 V headroom LDO the lowest dropout; NMOS-input diff-pair is adequate for the 1.2 V regulated output sense node.
