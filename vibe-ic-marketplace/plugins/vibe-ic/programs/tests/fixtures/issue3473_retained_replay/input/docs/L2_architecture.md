# Architecture

`spm` is a parameterized unsigned serial-parallel multiplier.  Parameter
`size` defaults to 32.  Input `x[size-1:0]` is the parallel operand and input
`y` supplies one serial multiplier bit per rising edge of `clk`.  Output `p`
emits one product bit per cycle.  Internal sum, carry, retained multiplier bit,
and product-bit state update only on the rising edge of `clk`.

`rst` is synchronous and active high.  On a rising edge with `rst == 1`, every
internal state bit and `p` are cleared to zero.  Reset has priority over normal
arithmetic work.  There are no asynchronous controls, FSM, software registers,
memories, analog blocks, clocks other than `clk`, or power-domain crossings.
