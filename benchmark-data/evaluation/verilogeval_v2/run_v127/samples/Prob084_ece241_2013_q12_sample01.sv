// program-SOLVED shift register + random-access read mux; deterministic, no AI.
module TopModule(
    input clk,
    input enable,
    input S,
    input A,
    input B,
    input C,
    output reg Z
);
    reg [7:0] sr;
    always @(posedge clk) begin
        if (enable)
            sr <= {sr[6:0], S};
    end
    always @(*) Z = sr[{A, B, C}];

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    sr = 0;
  end

endmodule
