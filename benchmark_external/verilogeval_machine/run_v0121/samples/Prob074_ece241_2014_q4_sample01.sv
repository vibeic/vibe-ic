module TopModule (
  input clk,
  input x,
  output z
);
  reg [2:0] s = 3'b0;

  always @(posedge clk) begin
    s[2] <= s[2] ^ x;   // MSB: x XOR s[2]
    s[1] <= ~s[1] & x;  // mid: x AND (NOT s[1])
    s[0] <= ~s[0] | x;  // LSB: x OR  (NOT s[0])
  end

  assign z = ~(s[2] | s[1] | s[0]);  // NOR of all state bits
endmodule
