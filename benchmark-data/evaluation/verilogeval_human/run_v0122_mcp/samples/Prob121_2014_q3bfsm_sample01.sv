module TopModule (
    input  clk,
    input  reset,
    input  x,
    output reg z
);

    reg [2:0] y, ny;

    // Next-state logic from the state-assigned table.
    always @(*) begin
        case (y)
            3'b000: ny = x ? 3'b001 : 3'b000;
            3'b001: ny = x ? 3'b100 : 3'b001;
            3'b010: ny = x ? 3'b001 : 3'b010;
            3'b011: ny = x ? 3'b010 : 3'b001;
            3'b100: ny = x ? 3'b100 : 3'b011;
            default: ny = 3'b000;
        endcase
    end

    // Moore output: z = 1 in states 011 and 100.
    always @(*)
        z = (y == 3'b011) || (y == 3'b100);

    always @(posedge clk) begin
        if (reset)
            y <= 3'b000;
        else
            y <= ny;
    end

endmodule
