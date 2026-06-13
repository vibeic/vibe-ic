module TopModule(
    input      clk,
    input      reset,
    input      data,
    output     start_shifting
);
    // Detect serial sequence 1101. Once matched, latch DONE forever.
    localparam S0   = 3'd0,  // no match
               S1   = 3'd1,  // saw 1
               S11  = 3'd2,  // saw 11
               S110 = 3'd3,  // saw 110
               DONE = 3'd4;  // saw 1101 -> stay
    reg [2:0] state = S0;

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else begin
            case (state)
                S0:   state <= data ? S1   : S0;
                S1:   state <= data ? S11  : S0;
                S11:  state <= data ? S11  : S110;
                S110: state <= data ? DONE : S0;
                DONE: state <= DONE;
                default: state <= S0;
            endcase
        end
    end

    assign start_shifting = (state == DONE);
endmodule
