module TopModule (
    input            clk,
    input            reset,
    input            data,
    output reg [3:0] count,
    output           counting,
    output           done,
    input            ack
);
    // Pattern-detect states for 1101
    localparam S     = 3'd0;  // searching, start
    localparam S1    = 3'd1;  // got 1
    localparam S11   = 3'd2;  // got 11
    localparam S110  = 3'd3;  // got 110
    localparam SHIFT = 3'd4;  // shifting in 4 delay bits (MSB first)
    localparam CNT   = 3'd5;  // counting down
    localparam DONE  = 3'd6;  // timed out, wait for ack

    reg [2:0] state, next;
    reg [1:0] shift_cnt;      // counts the 4 delay bits (0..3)
    reg [3:0] delay;          // remaining delay value (drives count)
    reg [9:0] sub;            // 0..999 sub-cycle counter

    always @(*) begin
        case (state)
            S:     next = data ? S1    : S;
            S1:    next = data ? S11   : S;
            S11:   next = data ? S11   : S110;
            S110:  next = data ? SHIFT : S;
            SHIFT: next = (shift_cnt == 2'd3) ? CNT : SHIFT;
            CNT:   next = (sub == 10'd999 && delay == 4'd0) ? DONE : CNT;
            DONE:  next = ack ? S : DONE;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state     <= S;
            shift_cnt <= 2'd0;
            sub       <= 10'd0;
            delay     <= 4'd0;
        end else begin
            state <= next;

            // Entering SHIFT: reset the bit counter
            if (state == S110 && data) begin
                shift_cnt <= 2'd0;
            end

            // Shift 4 delay bits MSB-first while in SHIFT
            if (state == SHIFT) begin
                delay     <= {delay[2:0], data};
                shift_cnt <= shift_cnt + 2'd1;
            end

            // Counting: 1000 cycles per delay value, decrement after each 1000
            if (state == CNT) begin
                if (sub == 10'd999) begin
                    sub <= 10'd0;
                    if (delay != 4'd0) delay <= delay - 4'd1;
                end else begin
                    sub <= sub + 10'd1;
                end
            end else if (state != SHIFT) begin
                sub <= 10'd0;
            end
        end
    end

    always @(*) count = delay;
    assign counting = (state == CNT);
    assign done     = (state == DONE);
endmodule
