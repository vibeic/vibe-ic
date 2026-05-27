module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S     = 3'd0,  // search: matched none
               S1    = 3'd1,  // matched "1"
               S11   = 3'd2,  // matched "11"
               S110  = 3'd3,  // matched "110"
               SHIFT = 3'd4,  // shifting in 4 delay bits (MSB first)
               COUNT = 3'd5,  // counting down
               DONE  = 3'd6;  // done, wait for ack

    reg [2:0] state, next;
    reg [3:0] delay;          // remaining whole-units, also used as down-counter
    reg [1:0] shift_cnt;      // counts the 4 delay bits 0..3
    reg [9:0] sub;            // 0..999 sub-cycle counter

    // ---- next-state ----
    always @(*) begin
        case (state)
            S:     next = data ? S1   : S;
            S1:    next = data ? S11  : S;
            S11:   next = data ? S11  : S110;
            S110:  next = data ? SHIFT: S;          // 1101 detected
            SHIFT: next = (shift_cnt == 2'd3) ? COUNT : SHIFT;
            COUNT: next = (delay == 4'd0 && sub == 10'd999) ? DONE : COUNT;
            DONE:  next = ack ? S : DONE;
            default: next = S;
        endcase
    end

    // ---- datapath / state register ----
    always @(posedge clk) begin
        if (reset) begin
            state     <= S;
            shift_cnt <= 2'd0;
            delay     <= 4'd0;
            sub       <= 10'd0;
        end else begin
            state <= next;

            // shift in 4 delay bits, MSB first
            if (state == S110 && data) begin
                // first delay bit captured on entry to SHIFT next cycle; init counters
                shift_cnt <= 2'd0;
            end
            if (state == SHIFT) begin
                delay     <= {delay[2:0], data};   // MSB-first shift
                shift_cnt <= shift_cnt + 2'd1;
            end

            // initialize sub-counter when entering COUNT
            if (state == SHIFT && shift_cnt == 2'd3)
                sub <= 10'd0;
            else if (state == COUNT) begin
                if (sub == 10'd999) begin
                    sub <= 10'd0;
                    if (delay != 4'd0)
                        delay <= delay - 4'd1;     // decrement remaining units
                end else begin
                    sub <= sub + 10'd1;
                end
            end
        end
    end

    assign counting = (state == COUNT);
    assign done     = (state == DONE);
    assign count    = delay;     // remaining time (don't-care when not counting)
endmodule
