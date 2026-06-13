module TopModule (
    input  clk,
    input  reset,
    input  data,
    input  done_counting,
    input  ack,
    output shift_ena,
    output counting,
    output done
);
    // Detect 1101 then shift_ena x4 then counting then done.
    localparam S     = 4'd0;  // searching, last bits none / matched nothing
    localparam S1    = 4'd1;  // got "1"
    localparam S11   = 4'd2;  // got "11"
    localparam S110  = 4'd3;  // got "110"
    localparam B0    = 4'd4;  // 1101 matched -> shift_ena cycle 1
    localparam B1    = 4'd5;
    localparam B2    = 4'd6;
    localparam B3    = 4'd7;  // shift_ena cycle 4
    localparam COUNT = 4'd8;  // counting
    localparam WAITS = 4'd9;  // done, wait ack

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S:     next = data ? S1   : S;
            S1:    next = data ? S11  : S;
            S11:   next = data ? S11  : S110;
            S110:  next = data ? B0   : S;
            B0:    next = B1;
            B1:    next = B2;
            B2:    next = B3;
            B3:    next = COUNT;
            COUNT: next = done_counting ? WAITS : COUNT;
            WAITS: next = ack ? S : WAITS;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= S;
        else       state <= next;
    end

    assign shift_ena = (state == B0) || (state == B1) ||
                       (state == B2) || (state == B3);
    assign counting  = (state == COUNT);
    assign done      = (state == WAITS);
endmodule
