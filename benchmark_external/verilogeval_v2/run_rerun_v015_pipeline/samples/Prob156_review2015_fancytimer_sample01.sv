module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S     = 3'd0; // searching for 1101
    localparam S1    = 3'd1;
    localparam S11   = 3'd2;
    localparam S110  = 3'd3;
    localparam SHIFT = 3'd4; // shifting in 4 delay bits, MSB first
    localparam COUNT = 3'd5; // counting down
    localparam DONE  = 3'd6; // done, wait ack

    reg [2:0]  state, next;
    reg [3:0]  delay;        // remaining whole-units (the count output)
    reg [1:0]  shift_cnt;    // counts the 4 shifted bits
    reg [9:0]  subcnt;       // 0..999 sub-counter per unit

    wire sub_last  = (subcnt == 10'd999);
    wire shift_last = (shift_cnt == 2'd3);

    always @(*) begin
        case (state)
            S:     next = data ? S1   : S;
            S1:    next = data ? S11  : S;
            S11:   next = data ? S11  : S110;
            S110:  next = data ? SHIFT: S;       // 1101 detected; this bit is MSB of delay
            SHIFT: next = shift_last ? COUNT : SHIFT;
            COUNT: next = (sub_last && delay == 4'd0) ? DONE : COUNT;
            DONE:  next = ack ? S : DONE;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state     <= S;
            delay     <= 4'd0;
            shift_cnt <= 2'd0;
            subcnt    <= 10'd0;
        end else begin
            state <= next;

            // Shift in 4 delay bits MSB first, over the 4 cycles spent in SHIFT.
            // The 1101 ends with the S110->SHIFT transition; delay bits follow.
            if (state == S110 && data) begin
                shift_cnt <= 2'd0;       // arm for first delay bit next cycle
            end else if (state == SHIFT) begin
                delay     <= {delay[2:0], data}; // MSB first
                shift_cnt <= shift_cnt + 2'd1;
            end

            // sub-counter and unit countdown during COUNT
            if (next == COUNT && state != COUNT) begin
                subcnt <= 10'd0; // first count cycle
            end else if (state == COUNT) begin
                if (sub_last) begin
                    subcnt <= 10'd0;
                    if (delay != 4'd0) delay <= delay - 4'd1;
                end else begin
                    subcnt <= subcnt + 10'd1;
                end
            end
        end
    end

    assign counting = (state == COUNT);
    assign done     = (state == DONE);
    assign count    = delay;
endmodule
