module TopModule (
  input ring,
  input vibrate_mode,
  output ringer,
  output motor
);

  // Ring only acts when an incoming call is present; vibrate routes it to motor.
  assign motor  = ring & vibrate_mode;
  assign ringer = ring & ~vibrate_mode;

endmodule
