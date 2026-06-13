module TopModule (
    input  clk,
    input  areset,
    input  j,
    input  k,
    output out
);
    localparam OFF = 1'b0, ON = 1'b1;
    reg state;

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= OFF;        // asynchronous active-high reset to OFF
        else begin
            case (state)
                OFF:     state <= j ? ON  : OFF;
                ON:      state <= k ? OFF : ON;
                default: state <= OFF;
            endcase
        end
    end

    // Moore output: function of state only (ON->1, OFF->0)
    assign out = (state == ON);
endmodule
