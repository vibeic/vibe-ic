module TopModule (
    input            clk,
    input            in,
    input            reset,
    output reg [7:0] out_byte,
    output           done
);
    // Serial frame: 1 start bit (0), 8 data bits (LSB first), 1 stop bit (1).
    // Idle line is 1. done is asserted (Moore) one cycle after a valid stop
    // bit is verified. On a bad stop bit, wait for the line to return to 1
    // (a stop bit) before attempting the next frame.
    localparam IDLE = 3'd0;  // line idle / waiting for start bit (0)
    localparam DATA = 3'd1;  // shifting in the 8 data bits, LSB first
    localparam STOP = 3'd2;  // check the stop bit
    localparam DONE = 3'd3;  // Moore: done=1 here, out_byte valid
    localparam WAIT = 3'd4;  // error recovery: wait for line to return to 1

    reg [2:0] state, next;
    reg [3:0] cnt;       // number of data bits received so far (0..8)
    reg [7:0] shifter;   // received bits, LSB first

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;        // start bit (0)
            DATA: next = (cnt == 4'd7) ? STOP : DATA;       // after 8th bit
            STOP: next = (in == 1'b1) ? DONE : WAIT;        // verify stop bit
            DONE: next = (in == 1'b0) ? DATA : IDLE;        // next start bit?
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;        // wait for stop bit
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            state <= next;
            if (state == DATA) begin
                shifter <= {in, shifter[7:1]};  // LSB first
                cnt <= cnt + 4'd1;
            end else begin
                cnt <= 4'd0;
            end
        end
    end

    // Moore done: asserted in the DONE state, one cycle after the valid stop bit.
    assign done = (state == DONE);

    // out_byte holds the last fully received byte; valid when done is high.
    always @(*) out_byte = shifter;
endmodule
