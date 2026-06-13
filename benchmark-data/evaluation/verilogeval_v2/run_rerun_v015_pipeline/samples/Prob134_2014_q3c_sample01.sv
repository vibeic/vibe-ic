module TopModule (
    input  clk,
    input  x,
    input  [2:0] y,
    output Y0,
    output z
);

    // Combinational next-state logic from the table; Y0 = bit0 of next state.
    //   state | x=0 | x=1
    //   000   | 000 | 001
    //   001   | 001 | 100
    //   010   | 010 | 001
    //   011   | 001 | 010
    //   100   | 011 | 100
    reg [2:0] next;

    always @(*) begin
        case (y)
            3'b000: next = x ? 3'b001 : 3'b000;
            3'b001: next = x ? 3'b100 : 3'b001;
            3'b010: next = x ? 3'b001 : 3'b010;
            3'b011: next = x ? 3'b010 : 3'b001;
            3'b100: next = x ? 3'b100 : 3'b011;
            default: next = 3'b000;
        endcase
    end

    assign Y0 = next[0];

    // Moore output z: 1 in present states 011 and 100
    assign z = (y == 3'b011) || (y == 3'b100);

endmodule
