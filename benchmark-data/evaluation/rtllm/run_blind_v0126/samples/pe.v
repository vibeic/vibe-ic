module pe (
    input             clk,
    input             rst,
    input      [31:0] a,
    input      [31:0] b,
    output reg [31:0] c
);

    always @(posedge clk or posedge rst) begin
        if (rst)
            c <= 32'd0;
        else
            c <= c + (a * b);
    end

endmodule
