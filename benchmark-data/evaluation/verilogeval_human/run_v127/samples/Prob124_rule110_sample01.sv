module TopModule (
    input clk,
    input load,
    input [511:0] data,
    output reg [511:0] q
);

    wire [511:0] l = {1'b0, q[511:1]};   // left  = q[i+1], q[512]=0
    wire [511:0] c = q;                 // center = q[i]
    wire [511:0] r = {q[510:0], 1'b0};   // right = q[i-1], q[-1]=0
    wire [511:0] nxt = (~l & ~c & r) | (~l & c & ~r) | (~l & c & r) | (l & ~c & r) | (l & c & ~r);

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= nxt;
    end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
