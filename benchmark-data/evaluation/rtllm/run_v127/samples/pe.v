// pe — 32-bit multiply-accumulate processing element.
// Each cycle accumulates a*b into c; c is the running partial sum.
module pe (
    input  wire        clk,
    input  wire        rst,        // active-high reset
    input  wire [31:0] a,
    input  wire [31:0] b,
    output reg  [31:0] c
);

    always @(posedge clk or posedge rst) begin
        if (rst)
            c <= 32'd0;
        else
            c <= c + a * b;
    end

endmodule
