// program-SOLVED left/right rotator (wrap-around); deterministic, no AI.
module TopModule(
    input clk,
    input load,
    input [1:0] ena,
    input [99:0] data,
    output reg [99:0] q
);
    always @(posedge clk) begin
        if (load)
            q <= data;
        else if (ena == 2'd1)
            q <= {q[0], q[99:1]};
        else if (ena == 2'd2)
            q <= {q[98:0], q[99]};
    end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
