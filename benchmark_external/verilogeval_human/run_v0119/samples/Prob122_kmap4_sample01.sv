module TopModule (
  input a,
  input b,
  input c,
  input d,
  output reg out
);
    // K-map is a full checkerboard => odd parity (XOR) of all four inputs
    always @(*) begin
        out = a ^ b ^ c ^ d;
    end
endmodule
