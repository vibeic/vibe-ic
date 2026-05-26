module TopModule (
    input  clk,
    input  reset,
    input  x,
    output z
);

    reg [2:0] state, next;

    always @(*) begin
        case (state)
            3'b000: next = x ? 3'b001 : 3'b000;
            3'b001: next = x ? 3'b100 : 3'b001;
            3'b010: next = x ? 3'b001 : 3'b010;
            3'b011: next = x ? 3'b010 : 3'b001;
            3'b100: next = x ? 3'b100 : 3'b011;
            default: next = 3'b000;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= 3'b000;
        else
            state <= next;
    end

    assign z = (state == 3'b011) || (state == 3'b100);

endmodule
