# Alternating controller

The controller includes a register, state, used to control the waveform.
On reset, the state register is cleared to 0.
If the state is 0, the output is incremented.
If the output reaches 7, the state is transitioned to 1.
If the state is 1, the output is decremented.
If the output reaches 0, the state is transitioned back to 0.
