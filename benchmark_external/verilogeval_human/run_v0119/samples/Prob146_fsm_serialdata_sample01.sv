module TopModule (
  input clk,
  input in,
  input reset,
  output [7:0] out_byte,
  output done
);
    localparam IDLE = 4'd0,
               B0   = 4'd1,
               B1   = 4'd2,
               B2   = 4'd3,
               B3   = 4'd4,
               B4   = 4'd5,
               B5   = 4'd6,
               B6   = 4'd7,
               B7   = 4'd8,
               STOP = 4'd9,
               DONE = 4'd10,
               WAIT = 4'd11;

    reg [3:0] state, next;
    reg [7:0] shft;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? B0 : IDLE;     // start bit
            B0:   next = B1;
            B1:   next = B2;
            B2:   next = B3;
            B3:   next = B4;
            B4:   next = B5;
            B5:   next = B6;
            B6:   next = B7;
            B7:   next = STOP;
            STOP: next = (in == 1'b1) ? DONE : WAIT;   // verify stop bit
            DONE: next = (in == 1'b0) ? B0 : IDLE;     // next start bit?
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;   // wait for a stop(1)
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= IDLE;
        else       state <= next;
        // capture data bits during B0..B7 (LSB first -> shift into MSB)
        if (state >= B0 && state <= B7)
            shft <= {in, shft[7:1]};
    end

    assign out_byte = shft;
    assign done = (state == DONE);
endmodule
