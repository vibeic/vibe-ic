// formal_top.sv — reset-safety proof harness for spm (regenerated evidence, F4)
// Property: one cycle after rst is asserted, p == 0 (unconditional; matches
// L3's "assertion 後一個 cycle 內所有內部狀態歸零" contract).
module formal_top (
    input  wire        clk,
    input  wire        rst,
    input  wire [31:0] x,
    input  wire        y,
    output wire        p
);
    spm #(.size(32)) dut (.clk(clk), .rst(rst), .x(x), .y(y), .p(p));

    reg past_rst = 1'b0;
    always @(posedge clk) past_rst <= rst;

    always @(posedge clk) begin
        if (past_rst) assert(p == 1'b0);
    end
endmodule
