module TopModule (
    input  clk,
    input  areset,
    input  j,
    input  k,
    output out
);
    localparam OFF = 1'b0, ON = 1'b1;
    reg state, next;

    always @(*) begin
        case (state)
            OFF: next = j ? ON  : OFF;
            ON:  next = k ? OFF : ON;
            default: next = OFF;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= OFF;        // asynchronous active-high reset to OFF
        else
            state <= next;
    end

    assign out = (state == ON);  // Moore: ON=>1, OFF=>0
endmodule
