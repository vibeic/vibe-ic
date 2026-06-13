module TopModule (
  input a,
  input b,
  input c,
  input d,
  output reg out
);
    // Minimal SOP absorbing don't-cares {4,9,13}: out = a | (~b & c)
    always @(*) begin
        out = a | (~b & c);
    end
endmodule
