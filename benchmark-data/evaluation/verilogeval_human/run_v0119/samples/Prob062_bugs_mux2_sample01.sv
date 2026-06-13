module TopModule (
  input sel,
  input [7:0] a,
  input [7:0] b,
  output reg [7:0] out
);
    // Bug fix: original `(~sel & a) | (sel & b)` only masked bit 0 because
    // sel is 1-bit. Use a proper 8-bit-wide select.
    always @(*)
        out = sel ? b : a;
endmodule
