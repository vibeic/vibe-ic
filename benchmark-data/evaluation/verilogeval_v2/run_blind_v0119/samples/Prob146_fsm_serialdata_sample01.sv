module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE = 2'd0,  // wait for start bit (0)
               DATA = 2'd1,  // shifting 8 data bits
               STOP = 2'd2,  // check stop bit
               WAIT = 2'd3;  // error: wait for a 1 to resync

    reg [1:0] state, next;
    reg [2:0] cnt;          // counts data bits 0..7
    reg [7:0] shifter;
    reg       done_r;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;
            DATA: next = (cnt == 3'd7) ? STOP : DATA;
            STOP: next = (in == 1'b1) ? IDLE : WAIT;   // valid stop -> idle, else recover
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 3'd0;
            done_r <= 1'b0;
        end else begin
            state <= next;
            // data bit counter
            if (state == DATA)
                cnt <= cnt + 3'd1;
            else
                cnt <= 3'd0;
            // assert done one cycle when a valid stop bit was seen
            done_r <= (state == STOP) && (in == 1'b1);
        end
    end

    // shift register: capture data bits LSB-first during DATA state
    always @(posedge clk) begin
        if (state == DATA)
            shifter <= {in, shifter[7:1]};
    end

    assign out_byte = shifter;
    assign done     = done_r;
endmodule
