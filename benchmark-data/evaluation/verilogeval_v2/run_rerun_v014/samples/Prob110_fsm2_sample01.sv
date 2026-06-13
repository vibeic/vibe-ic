module TopModule (
    input  clk,
    input  areset,
    input  j,
    input  k,
    output out
);

    localparam OFF = 1'b0, ON = 1'b1;
    reg state, next_state;

    always @(*) begin
        case (state)
            OFF: next_state = j ? ON : OFF;
            ON:  next_state = k ? OFF : ON;
            default: next_state = OFF;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= OFF;
        else
            state <= next_state;
    end

    assign out = (state == ON);

endmodule
