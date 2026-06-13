module TopModule(
    input  clk,
    input  reset,
    input  data,
    output start_shifting
);
    // Detect sequence 1101 (MSB first in time order 1,1,0,1).
    // States track progress; DONE is sticky until reset.
    localparam S_IDLE = 3'd0,  // no progress
               S_1    = 3'd1,  // seen "1"
               S_11   = 3'd2,  // seen "11"
               S_110  = 3'd3,  // seen "110"
               S_DONE = 3'd4;  // seen "1101" -> latched
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
                default:state <= S_IDLE;
            endcase
        end
    end

    // Moore output.
    assign start_shifting = (state == S_DONE);
endmodule
