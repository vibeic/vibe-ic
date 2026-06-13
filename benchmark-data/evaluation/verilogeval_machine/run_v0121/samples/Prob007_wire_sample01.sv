module TopModule (
  input  in,
  output out
);
  // Header exposes only {in, out}; prose's FSM ports do not exist. Pass-through.
  assign out = in;
endmodule
