# L6 — Calibration / Analog Trim

Not applicable. `user_proj_example` is a purely digital block (a counter). The
wrapper exposes `analog_io[28:0]` from the Caravel harness but this design does
not connect to it. No trim, no OTP, no calibration constants.
