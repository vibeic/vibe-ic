// Prob036_ringer — ring routed to ringer (normal) or motor (vibrate mode).
module TopModule (
  input ring,
  input vibrate_mode,
  output ringer,
  output motor
);

  assign ringer = ring & ~vibrate_mode;
  assign motor  = ring & vibrate_mode;

endmodule
