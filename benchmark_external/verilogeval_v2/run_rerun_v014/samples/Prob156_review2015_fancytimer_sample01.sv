module TopModule (
    input            clk,
    input            reset,
    input            data,
    output reg [3:0] count,
    output           counting,
    output           done,
    input            ack
);

    localparam S     = 4'd0;
    localparam S1    = 4'd1;
    localparam S11   = 4'd2;
    localparam S110  = 4'd3;
    localparam SHIFT = 4'd4;  // shifting in 4 delay bits
    localparam COUNT = 4'd5;  // counting down
    localparam DONE  = 4'd6;  // timed out, wait for ack

    reg [3:0] state, next;

    reg [3:0] delay;         // captured delay value (and current remaining)
    reg [1:0] shift_cnt;     // counts the 4 shifted-in bits
    reg [9:0] sub_cnt;       // 0..999 within each "second"

    wire sub_done = (sub_cnt == 10'd999);

    always @(*) begin
        case (state)
            S:     next = data ? S1   : S;
            S1:    next = data ? S11  : S;
            S11:   next = data ? S11  : S110;
            S110:  next = data ? SHIFT: S;
            SHIFT: next = (shift_cnt == 2'd3) ? COUNT : SHIFT;
            COUNT: next = (sub_done && delay == 4'd0) ? DONE : COUNT;
            DONE:  next = ack ? S : DONE;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= S;
        end else begin
            state <= next;
        end
    end

    // shift in the 4 delay bits, MSB first
    always @(posedge clk) begin
        if (reset) begin
            shift_cnt <= 2'd0;
        end else if (state == SHIFT) begin
            shift_cnt <= shift_cnt + 2'd1;
        end else begin
            shift_cnt <= 2'd0;
        end
    end

    always @(posedge clk) begin
        if (state == SHIFT) begin
            delay <= {delay[2:0], data};
        end else if (state == COUNT) begin
            if (sub_done && delay != 4'd0)
                delay <= delay - 4'd1;
        end
    end

    // sub-counter 0..999 during counting
    always @(posedge clk) begin
        if (reset) begin
            sub_cnt <= 10'd0;
        end else if (state == COUNT) begin
            if (sub_done)
                sub_cnt <= 10'd0;
            else
                sub_cnt <= sub_cnt + 10'd1;
        end else begin
            sub_cnt <= 10'd0;
        end
    end

    // outputs
    assign counting = (state == COUNT);
    assign done     = (state == DONE);

    // count output reflects current remaining delay while counting
    always @(*) begin
        count = delay;
    end

endmodule
