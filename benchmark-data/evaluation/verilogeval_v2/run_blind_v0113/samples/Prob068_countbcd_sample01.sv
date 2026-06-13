module TopModule (
    input         clk,
    input         reset,
    output  [2:0] ena,
    output [15:0] q
);
    reg [3:0] d0, d1, d2, d3;

    wire roll0 = (d0 == 4'd9);
    wire roll1 = roll0 && (d1 == 4'd9);
    wire roll2 = roll1 && (d2 == 4'd9);

    assign ena = {roll2, roll1, roll0};
    assign q   = {d3, d2, d1, d0};

    always @(posedge clk) begin
        if (reset) begin
            d0 <= 4'd0; d1 <= 4'd0; d2 <= 4'd0; d3 <= 4'd0;
        end else begin
            d0 <= roll0 ? 4'd0 : d0 + 4'd1;
            if (roll0) d1 <= roll1 ? 4'd0 : d1 + 4'd1;
            if (roll1) d2 <= roll2 ? 4'd0 : d2 + 4'd1;
            if (roll2) d3 <= (d3 == 4'd9) ? 4'd0 : d3 + 4'd1;
        end
    end
endmodule
