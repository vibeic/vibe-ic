module TopModule (
  input clk,
  input load,
  input [511:0] data,
  output reg [511:0] q
);

  // Rule 110: next[i] = f(left=q[i+1], center=q[i], right=q[i-1])
  // Pattern (LCR index): rule byte = 8'b01101110.
  // Boundaries q[-1] and q[512] are 0.
  wire [511:0] left  = {1'b0, q[511:1]};   // left[i]  = q[i+1]
  wire [511:0] right = {q[510:0], 1'b0};   // right[i] = q[i-1]
  reg  [511:0] nq;
  integer i;
  always @(*) begin
    for (i = 0; i < 512; i = i + 1) begin
      nq[i] = (8'b01101110 >> {left[i], q[i], right[i]}) & 1'b1;
    end
  end

  always @(posedge clk) begin
    if (load)
      q <= data;
    else
      q <= nq;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
