// clkgenerator — free-running clock generator, toggles every PERIOD/2.
module clkgenerator #(
    parameter PERIOD = 10
) (
    output reg clk
);

    // start low
    initial clk = 1'b0;

    // toggle every half period (NBA: the post-toggle value is observed in the
    // observed region, so a TB sampling at the same delay sees the pre-toggle
    // value and the stated initial clk=0 holds at the first sample)
    always #(PERIOD/2) clk <= ~clk;

endmodule
