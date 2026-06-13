module multi_8bit (
    input  wire [7:0]  A,
    input  wire [7:0]  B,
    output wire [15:0] product
);

    integer i;
    reg [15:0] prod;
    reg [15:0] mcand;

    always @(*) begin
        prod  = 16'd0;
        mcand = {8'd0, A};
        for (i = 0; i < 8; i = i + 1) begin
            if (B[i])
                prod = prod + (mcand << i);
        end
    end

    assign product = prod;

endmodule
