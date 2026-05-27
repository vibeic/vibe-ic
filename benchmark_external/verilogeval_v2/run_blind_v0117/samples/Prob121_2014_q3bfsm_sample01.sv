module TopModule (
    input  clk,
    input  reset,
    input  x,
    output z
);
    reg [2:0] y;
    reg [2:0] ynext;

    always @(*) begin
        case (y)
            3'b000: ynext = x ? 3'b001 : 3'b000;
            3'b001: ynext = x ? 3'b100 : 3'b001;
            3'b010: ynext = x ? 3'b001 : 3'b010;
            3'b011: ynext = x ? 3'b010 : 3'b001;
            3'b100: ynext = x ? 3'b100 : 3'b011;
            default: ynext = 3'b000;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            y <= 3'b000;
        else
            y <= ynext;
    end

    // Moore output: function of present state only.
    assign z = (y == 3'b011) || (y == 3'b100);
endmodule
