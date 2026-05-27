module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE = 2'd0;  // waiting for start bit (0)
    localparam DATA = 2'd1;  // collecting 8 data bits
    localparam STOP = 2'd2;  // expecting stop bit (1)
    localparam WAITS= 2'd3;  // error: wait for a stop (1) bit

    reg [1:0] state, next;
    reg [3:0] cnt;          // counts data bits collected (0..8)
    reg [7:0] sh;           // shift register (LSB first)
    reg [7:0] byte_q;       // latched byte for output

    always @(*) begin
        case (state)
            IDLE:  next = in ? IDLE : DATA;         // start bit = 0
            DATA:  next = (cnt == 4'd7) ? STOP : DATA;
            STOP:  next = in ? IDLE : WAITS;        // stop=1 ok else wait
            WAITS: next = in ? IDLE : WAITS;        // wait until a 1
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state  <= IDLE;
            cnt    <= 4'd0;
            sh     <= 8'd0;
            byte_q <= 8'd0;
        end else begin
            state <= next;
            if (state == DATA) begin
                sh  <= {in, sh[7:1]};  // LSB first -> shift in from MSB position
                cnt <= cnt + 4'd1;
            end else begin
                cnt <= 4'd0;
            end
            if (state == DATA && cnt == 4'd7)
                byte_q <= {in, sh[7:1]};  // capture full byte on last data bit
        end
    end

    assign done     = (state == STOP) && in;  // stop bit correct this cycle
    assign out_byte = byte_q;

endmodule
