# Command protocol

The design has no command bus, opcodes, packets, addresses, or software-visible
register protocol.  Each non-reset rising edge consumes the current `x` and `y`
values as one arithmetic update.  The serial product stream appears on `p`.
