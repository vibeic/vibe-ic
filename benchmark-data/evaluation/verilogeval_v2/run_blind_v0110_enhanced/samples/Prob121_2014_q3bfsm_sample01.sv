module TopModule(
    input  clk,
    input  reset,
    input  x,
    output z
);
    reg [2:0] state;
    reg [2:0] next;

    localparam S000 = 3'b000,
               S001 = 3'b001,
               S010 = 3'b010,
               S011 = 3'b011,
               S100 = 3'b100;

    always @(*) begin
        case (state)
            S000: next = x ? S001 : S000;
            S001: next = x ? S100 : S001;
            S010: next = x ? S001 : S010;
            S011: next = x ? S010 : S001;
            S100: next = x ? S100 : S011;
            default: next = S000;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S000;
        else
            state <= next;
    end

    assign z = (state == S011) || (state == S100);
endmodule
