module TopModule(
    input  clk,
    input  reset,
    input  data,
    output start_shifting
);
    // Detect 1101. Once seen, latch DONE forever (until reset).
    localparam IDLE = 3'd0, S1 = 3'd1, S11 = 3'd2, S110 = 3'd3, DONE = 3'd4;
    reg [2:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= IDLE;
        else begin
            case (state)
                IDLE: state <= data ? S1   : IDLE;
                S1:   state <= data ? S11  : IDLE;
                S11:  state <= data ? S11  : S110;   // "11" + 1 keeps last two = 11
                S110: state <= data ? DONE : IDLE;
                DONE: state <= DONE;
                default: state <= IDLE;
            endcase
        end
    end

    assign start_shifting = (state == DONE);
endmodule
