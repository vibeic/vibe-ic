module TopModule(
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S    = 4'd0,  S1   = 4'd1, S11  = 4'd2, S110 = 4'd3,
               SH   = 4'd4,                              // shifting 4 delay bits
               CNT  = 4'd5,
               DN   = 4'd6;
    reg [3:0] state, next;
    reg [3:0] delay;       // delay[3:0]
    reg [1:0] shcnt;       // counts the 4 shifted bits (0..3)
    reg [3:0] sec;         // remaining seconds (count output)
    reg [9:0] ms;          // sub-second counter 0..999

    // ---- next-state ----
    always @(*) begin
        case (state)
            S:    next = data ? S1   : S;
            S1:   next = data ? S11  : S;
            S11:  next = data ? S11  : S110;
            S110: next = data ? SH   : S;
            SH:   next = (shcnt == 2'd3) ? CNT : SH;
            CNT:  next = (sec == 4'd0 && ms == 10'd0) ? DN : CNT;
            DN:   next = ack ? S : DN;
            default: next = S;
        endcase
    end

    // ---- datapath ----
    always @(posedge clk) begin
        if (reset) begin
            state <= S;
            shcnt <= 2'd0;
            delay <= 4'd0;
            sec   <= 4'd0;
            ms    <= 10'd0;
        end else begin
            state <= next;

            // shift 4 delay bits, MSB first
            if (state == S110 && data) begin
                // entering SH next cycle; nothing shifted yet
                shcnt <= 2'd0;
            end
            if (state == SH) begin
                delay <= {delay[2:0], data};   // MSB-first accumulation
                shcnt <= shcnt + 2'd1;
            end

            // initialise counters when transitioning SH -> CNT
            if (state == SH && shcnt == 2'd3) begin
                sec <= {delay[2:0], data};     // final delay value
                ms  <= 10'd999;
            end else if (state == CNT) begin
                if (ms != 10'd0) begin
                    ms <= ms - 10'd1;
                end else if (sec != 4'd0) begin
                    sec <= sec - 4'd1;
                    ms  <= 10'd999;
                end
            end
        end
    end

    assign count    = sec;
    assign counting = (state == CNT);
    assign done     = (state == DN);
endmodule
