module TopModule (
  input [7:0] in,
  output [31:0] out
);
  // Sign-extend semantics: replicate the MSB (bit 7) 24 times, then the byte.
  assign out = {{24{in[7]}}, in};
endmodule
