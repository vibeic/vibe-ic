module TopModule (
  input  [7:0]  in,
  output [31:0] out
);
  // Width-consistency arithmetic (hold the stated replication count FIXED):
  //   out_width == N * operand_width + other_parts_width
  //   prose states N = 24 ("replicated 24 times"); other part = original 8-bit in (8 bits)
  //   32 == 24 * operand_width + 8  ->  24*operand_width == 24  ->  operand_width == 1
  //   operand_width (1) < in_width (8)  => the replicated operand is a SINGLE BIT,
  //   i.e. the sign/MSB in[7]. This is SIGN-EXTENSION, not whole-vector replication.
  //   (Whole-vector replicate would need 32 == k*8 -> k=4, contradicting the stated N=24.)
  assign out = { {24{in[7]}}, in };
endmodule
