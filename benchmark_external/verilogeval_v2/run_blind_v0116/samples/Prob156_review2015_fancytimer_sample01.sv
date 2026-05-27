module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S=3'd0, S1=3'd1, S11=3'd2, S110=3'd3,
               SHIFT=3'd4, COUNT=3'd5, DONE=3'd6;

    reg [2:0] state, next;
    reg [3:0] delay;       // shifted-in delay value, also used as remaining count
    reg [1:0] shift_cnt;   // counts the 4 shifted bits (0..3)
    reg [9:0] sub;         // 0..999 sub-cycle counter

    // detect end-of-1000 window
    wire sub_done = (sub == 10'd999);

    always @(*) begin
        case (state)
            S:    next = data ? S1   : S;
            S1:   next = data ? S11  : S;
            S11:  next = data ? S11  : S110;
            S110: next = data ? SHIFT : S;       // 1101 detected; this 'data'=1 is bit? -> see below
            SHIFT: next = (shift_cnt == 2'd3) ? COUNT : SHIFT;
            COUNT: next = (sub_done && delay == 4'd0) ? DONE : COUNT;
            DONE:  next = ack ? S : DONE;
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
            case (state)
                S110: begin
                    if (data) begin
                        // the '1' completing 1101 is the pattern bit, not a delay bit.
                        shift_cnt <= 2'd0;
                    end
                end
                SHIFT: begin
                    delay <= {delay[2:0], data};   // MSB-first shift
                    shift_cnt <= shift_cnt + 2'd1;
                end
                COUNT: begin
                    if (sub_done) begin
                        sub <= 10'd0;
                        if (delay != 4'd0)
                            delay <= delay - 4'd1;  // decrement remaining time each 1000 cycles
                    end else begin
                        sub <= sub + 10'd1;
                    end
                end
                default: ;
            endcase
        end
    end

    assign counting = (state == COUNT);
    assign done     = (state == DONE);
    assign count    = delay;     // remaining time (don't-care when not counting)
endmodule
