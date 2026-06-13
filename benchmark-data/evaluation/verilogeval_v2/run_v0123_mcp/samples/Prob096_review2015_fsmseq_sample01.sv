module TopModule (
    input  clk,
    input  reset,
    input  data,
    output start_shifting
);
    // Sequence detector for 1101 (overlapping not required after detect:
    // once found, latch start_shifting forever until reset).
    localparam S_IDLE = 3'd0,  // nothing matched
               S_1    = 3'd1,  // saw 1
               S_11   = 3'd2,  // saw 11
               S_110  = 3'd3,  // saw 110
               S_DONE = 3'd4;  // saw 1101 -> done
    reg [2:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= S_IDLE;
        else begin
            case (state)
                S_IDLE: state <= data ? S_1   : S_IDLE;
                S_1:    state <= data ? S_11  : S_IDLE;
                S_11:   state <= data ? S_11  : S_110;
                S_110:  state <= data ? S_DONE: S_IDLE;
                S_DONE: state <= S_DONE;
                default: state <= S_IDLE;
            endcase
        end
    end

    assign start_shifting = (state == S_DONE);
endmodule
