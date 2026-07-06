module clkgenerator(
    output reg clk
);

parameter PERIOD = 10;

initial begin
    clk = 1'b0;
end

always #(PERIOD/2) clk <= ~clk;

endmodule
