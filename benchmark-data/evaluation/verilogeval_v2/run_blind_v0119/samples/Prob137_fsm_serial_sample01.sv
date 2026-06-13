module TopModule(
    input  clk,
    input  reset,
    input  in,
    output done
);
    // Line idle = 1. Start bit = 0. 8 data bits. Stop bit = 1.
    localparam IDLE = 3'd0; // waiting for start bit (in==0)
    localparam DATA = 3'd1; // receiving 8 data bits
    localparam STOP = 3'd2; // checking stop bit
    localparam DONE = 3'd3; // byte received correctly (done=1)
    localparam WAIT = 3'd4; // bad stop bit: wait for a 1 before next byte
    reg [2:0] state, next;
    reg [3:0] cnt;          // data-bit counter

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;
            DATA: next = (cnt == 4'd7) ? STOP : DATA;
            STOP: next = (in == 1'b1) ? DONE : WAIT;
            DONE: next = (in == 1'b0) ? DATA : IDLE; // done cycle is also idle line
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            state <= next;
            if (state == DATA)
                cnt <= cnt + 4'd1;
            else
                cnt <= 4'd0;
        end
    end

    assign done = (state == DONE);
endmodule
