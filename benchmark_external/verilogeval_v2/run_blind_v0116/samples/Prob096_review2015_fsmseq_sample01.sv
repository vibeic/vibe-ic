module TopModule (
    input  clk,
    input  reset,
    input  data,
    output start_shifting
);
    // Sequence detector for 1101. Once found, latch DONE forever.
    localparam S0   = 3'd0,  // no match yet
               S1   = 3'd1,  // seen "1"
               S11  = 3'd2,  // seen "11"
               S110 = 3'd3,  // seen "110"
               DONE = 3'd4;  // seen "1101" -> sticky
    reg [2:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = data ? S1   : S0;
            S1:   next = data ? S11  : S0;
            S11:  next = data ? S11  : S110;
            S110: next = data ? DONE : S0;
            DONE: next = DONE;
            default: next = S0;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else
            state <= next;
    end

    assign start_shifting = (state == DONE);
endmodule
