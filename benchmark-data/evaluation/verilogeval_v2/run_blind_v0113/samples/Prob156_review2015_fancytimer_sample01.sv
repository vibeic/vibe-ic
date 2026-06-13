module TopModule(
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S     = 3'd0;  // search start: have nothing
    localparam S1    = 3'd1;  // saw 1
    localparam S11   = 3'd2;  // saw 11
    localparam S110  = 3'd3;  // saw 110
    localparam SHIFT = 3'd4;  // shifting in 4 delay bits (MSB first)
    localparam COUNT = 3'd5;  // counting down
    localparam DONE  = 3'd6;  // timed out, wait for ack

    reg [2:0] state;
    reg [3:0] delay;     // remaining delay value (count output)
    reg [1:0] sh_cnt;    // 0..3 bits shifted
    reg [9:0] milli;     // 0..999 sub-counter for each delay step

    always @(posedge clk) begin
        if (reset) begin
            state  <= S;
            delay  <= 4'd0;
            sh_cnt <= 2'd0;
            milli  <= 10'd0;
        end else begin
            case (state)
                S:    state <= data ? S1  : S;
                S1:   state <= data ? S11 : S;
                S11:  state <= data ? S11 : S110;
                S110: begin
                    if (data) begin
                        state  <= SHIFT;   // 1101 complete; next 4 bits = delay
                        sh_cnt <= 2'd0;
                    end else
                        state  <= S;
                end
                SHIFT: begin
                    delay <= {delay[2:0], data};   // MSB first
                    if (sh_cnt == 2'd3) begin
                        state <= COUNT;
                        milli <= 10'd999;
                    end else begin
                        sh_cnt <= sh_cnt + 2'd1;
                    end
                end
                COUNT: begin
                    if (milli == 10'd0) begin
                        if (delay == 4'd0) begin
                            state <= DONE;
                        end else begin
                            delay <= delay - 4'd1;
                            milli <= 10'd999;
                        end
                    end else begin
                        milli <= milli - 10'd1;
                    end
                end
                DONE: begin
                    if (ack) state <= S;
                end
                default: state <= S;
            endcase
        end
    end

    assign count    = delay;
    assign counting = (state == COUNT);
    assign done     = (state == DONE);
endmodule
