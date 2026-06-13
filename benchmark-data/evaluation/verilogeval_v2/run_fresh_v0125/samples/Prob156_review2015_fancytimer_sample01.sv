module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    // states: search 1101, shift 4 delay bits, count, done
    localparam S    = 3'd0;   // searching
    localparam S1   = 3'd1;   // seen 1
    localparam S11  = 3'd2;   // seen 11
    localparam S110 = 3'd3;   // seen 110
    localparam SHFT = 3'd4;   // shifting 4 delay bits (MSB first)
    localparam CNT  = 3'd5;   // counting down
    localparam DONE = 3'd6;   // done, wait for ack

    reg [2:0]  state, next;
    reg [3:0]  delay;        // remaining whole-units (current count output)
    reg [1:0]  shift_cnt;    // counts the 4 shifted delay bits
    reg [9:0]  sub;          // 0..999 sub-counter within each unit

    always @(*) begin
        case (state)
            S:    next = data ? S1   : S;
            S1:   next = data ? S11  : S;
            S11:  next = data ? S11  : S110;
            S110: next = data ? SHFT : S;     // 1101 detected; next 4 bits are delay
            SHFT: next = (shift_cnt == 2'd3) ? CNT : SHFT;
            CNT:  next = (delay == 4'd0 && sub == 10'd999) ? DONE : CNT;
            DONE: next = ack ? S : DONE;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state     <= S;
            delay     <= 4'd0;
            shift_cnt <= 2'd0;
            sub       <= 10'd0;
        end else begin
            state <= next;
            // shift in 4 delay bits, MSB first, while in SHFT state.
            if (state == S110 && data) begin
                shift_cnt <= 2'd0;
                delay     <= 4'd0;
                sub       <= 10'd0;
            end else if (state == SHFT) begin
                delay     <= {delay[2:0], data};   // MSB first
                shift_cnt <= shift_cnt + 2'd1;
                sub       <= 10'd0;
            end else if (state == CNT) begin
                if (sub == 10'd999) begin
                    sub   <= 10'd0;
                    if (delay != 4'd0)
                        delay <= delay - 4'd1;
                end else begin
                    sub <= sub + 10'd1;
                end
            end
        end
    end

    assign counting = (state == CNT);
    assign done     = (state == DONE);
    assign count    = delay;
endmodule
