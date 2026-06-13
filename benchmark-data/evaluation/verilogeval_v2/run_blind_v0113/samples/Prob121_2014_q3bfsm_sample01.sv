module TopModule (
    input  clk,
    input  reset,
    input  x,
    output z
);
    reg [2:0] y;

    always @(posedge clk) begin
        if (reset)
            y <= 3'b000;
        else begin
            case (y)
                3'b000: y <= x ? 3'b001 : 3'b000;
                3'b001: y <= x ? 3'b100 : 3'b001;
                3'b010: y <= x ? 3'b001 : 3'b010;
                3'b011: y <= x ? 3'b010 : 3'b001;
                3'b100: y <= x ? 3'b100 : 3'b011;
                default: y <= 3'b000;
            endcase
        end
    end

    // Moore output: function of current state only
    assign z = (y == 3'b011) || (y == 3'b100);
endmodule
