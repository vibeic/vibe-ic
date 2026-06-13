module clkgenerator #(
    parameter PERIOD = 10
)(
    output reg clk
);

    // Initialize the clock low; toggle every half PERIOD so the full clock
    // period equals PERIOD (frequency = 1/PERIOD).
    initial clk = 1'b0;

    always #(PERIOD/2) clk = ~clk;

endmodule
