module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE  = 3'd0; // waiting for start bit (0)
    localparam DATA  = 3'd1; // collecting 8 data bits
    localparam STOP  = 3'd2; // checking stop bit
    localparam DONE  = 3'd3; // done asserted for one cycle
    localparam WAIT  = 3'd4; // stop bit wrong: wait for a 1 (stop) before idle

    reg [2:0] state, next;
    reg [3:0] cnt;          // counts data bits 0..7
    reg [7:0] shifter;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;          // start bit
            DATA: next = (cnt == 4'd7) ? STOP : DATA;
            STOP: next = (in == 1'b1) ? DONE : WAIT;          // stop bit must be 1
            DONE: next = (in == 1'b0) ? DATA : IDLE;          // can immediately start next
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;          // wait until a stop (1) seen
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state   <= IDLE;
            cnt     <= 4'd0;
            shifter <= 8'd0;
        end else begin
            state <= next;
            if (state == DATA) begin
                shifter <= {in, shifter[7:1]}; // LSB first
                cnt     <= cnt + 4'd1;
            end else begin
                cnt <= 4'd0;
            end
        end
    end

    assign out_byte = shifter;
    assign done     = (state == DONE);
endmodule
