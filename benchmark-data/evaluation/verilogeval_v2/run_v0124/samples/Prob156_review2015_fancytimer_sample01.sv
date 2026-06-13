module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S    = 3'd0,  // searching for 1
               S1   = 3'd1,  // saw 1
               S11  = 3'd2,  // saw 11
               S110 = 3'd3,  // saw 110
               SHIFT= 3'd4,  // shifting in 4 delay bits
               CNT  = 3'd5,  // counting down
               WAITS= 3'd6;  // done, waiting for ack
    reg [2:0] state, next;
    reg [3:0] delay;        // captured delay[3:0]
    reg [1:0] shift_cnt;    // counts the 4 delay bits shifted in
    reg [3:0] rem;          // remaining delay value (count output)
    reg [9:0] sub;          // 0..999 sub-counter for each 1000-cycle window

    // pattern detection / state next-logic
    always @(*) begin
        case (state)
            S    : next = data ? S1   : S;
            S1   : next = data ? S11  : S;
            S11  : next = data ? S11  : S110;
            S110 : next = data ? SHIFT: S;
            SHIFT: next = (shift_cnt == 2'd3) ? CNT : SHIFT;
            CNT  : next = (rem == 4'd0 && sub == 10'd999) ? WAITS : CNT;
            WAITS: next = ack ? S : WAITS;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state     <= S;
            shift_cnt <= 2'd0;
            sub       <= 10'd0;
        end else begin
            state <= next;

            // shift in 4 delay bits, MSB first
            if (state == S110 && data) begin
                shift_cnt <= 2'd0;
            end
            if (state == SHIFT) begin
                delay     <= {delay[2:0], data};
                shift_cnt <= shift_cnt + 2'd1;
            end

            // initialize counter when entering CNT
            if (state == SHIFT && shift_cnt == 2'd3) begin
                rem <= {delay[2:0], data};  // final delay value
                sub <= 10'd0;
            end else if (state == CNT) begin
                if (sub == 10'd999) begin
                    sub <= 10'd0;
                    if (rem != 4'd0) rem <= rem - 4'd1;
                end else begin
                    sub <= sub + 10'd1;
                end
            end
        end
    end

    assign counting = (state == CNT);
    assign done     = (state == WAITS);
    assign count    = rem;
endmodule
