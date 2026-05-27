module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE = 3'd0;  // wait for start bit (0)
    localparam DATA = 3'd1;  // shifting in 8 data bits
    localparam STOP = 3'd2;  // expect stop bit (1)
    localparam DONE = 3'd3;  // assert done one cycle
    localparam WAIT = 3'd4;  // error: wait for line idle (1)

    reg [2:0] state, next;
    reg [3:0] cnt;          // counts data bits 0..8
    reg [7:0] shifter;      // collects data bits (LSB first)

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;        // start bit
            DATA: next = (cnt == 4'd7) ? STOP : DATA;       // after 8th data bit go check stop
            STOP: next = (in == 1'b1) ? DONE : WAIT;        // valid stop -> done; else error
            DONE: next = (in == 1'b0) ? DATA : IDLE;        // line can immediately start next byte
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;        // wait until line returns to idle
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
            shifter <= 8'd0;
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

    assign done     = (state == DONE);
    assign out_byte = shifter;
endmodule
