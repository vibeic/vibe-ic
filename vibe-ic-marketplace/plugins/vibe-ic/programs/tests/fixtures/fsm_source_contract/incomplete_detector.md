# Detector

The detector recognizes a binary sequence using the following FSM states:
REST: Waiting for the first bit.
Q1: The first bit was received.
Q2: The final bit was received and the output is asserted.

The FSM transitions according to the input bitstream.
No mismatch or restart transition is specified here.
