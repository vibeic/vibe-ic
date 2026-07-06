module multi_8bit (
    input      [7:0]  A,
    input      [7:0]  B,
    output     [15:0] product
);

    integer i;
    reg [15:0] acc;
    reg [15:0] a_shift;

    always @(*) begin
        acc     = 16'd0;
        a_shift = {8'd0, A};
        for (i = 0; i < 8; i = i + 1) begin
            if (B[i])
                acc = acc + (a_shift << i);
        end
    end

    assign product = acc;

endmodule
