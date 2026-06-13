// Prob021_mux256to1v — 4-bit-block selector from a 1024-bit vector.
//
// The 1024-bit input is 256 contiguous 4-bit blocks. The 8-bit sel picks the
// block index; the starting bit index is sel*4. Use the indexed part-select
// (+:) so sel is variable. Combinational.
module TopModule (
  input [1023:0] in,
  input [7:0] sel,
  output [3:0] out
);

  assign out = in[sel*4 +: 4];

endmodule
