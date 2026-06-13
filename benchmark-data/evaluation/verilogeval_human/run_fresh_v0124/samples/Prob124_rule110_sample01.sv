module TopModule (
  input clk,
  input load,
  input [511:0] data,
  output reg [511:0] q
);

  integer i;
  reg [511:0] next_q;

  always @(*) begin
    for (i = 0; i < 512; i = i + 1) begin : gen_next
      // left = q[i+1], center = q[i], right = q[i-1]; boundaries are 0
      reg lft, ctr, rgt;
      ctr = q[i];
      rgt = (i == 0)   ? 1'b0 : q[i-1];
      lft = (i == 511) ? 1'b0 : q[i+1];
      // Rule 110: next is 0 only for patterns 111, 100, 000
      next_q[i] = (ctr & ~lft) | (ctr & ~rgt) | (~ctr & rgt);
    end
  end

  always @(posedge clk) begin
    if (load)
      q <= data;
    else
      q <= next_q;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
