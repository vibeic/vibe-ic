module TopModule (
    input  clk,
    input  x,
    input  [2:0] y,
    output reg Y0,
    output reg z
);

    // Next-state bit 0 from the state-assigned table.
    always @(*) begin
        case (y)
            3'b000: Y0 = x ? 1'b1 : 1'b0;
            3'b001: Y0 = x ? 1'b0 : 1'b1;
            3'b010: Y0 = x ? 1'b1 : 1'b0;
            3'b011: Y0 = x ? 1'b0 : 1'b1;
            3'b100: Y0 = x ? 1'b0 : 1'b1;
            default: Y0 = 1'b0;
        endcase
    end

    // Moore output z = 1 in states 011 and 100.
    always @(*)
        z = (y == 3'b011) || (y == 3'b100);

endmodule
