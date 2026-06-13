module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE = 4'd0;  // waiting for start bit (line idles at 1)
    localparam D0   = 4'd1;  // collecting data bit 0..7
    localparam D1   = 4'd2;
    localparam D2   = 4'd3;
    localparam D3   = 4'd4;
    localparam D4   = 4'd5;
    localparam D5   = 4'd6;
    localparam D6   = 4'd7;
    localparam D7   = 4'd8;
    localparam STOP = 4'd9;  // expect stop bit (1)
    localparam DONE = 4'd10; // good stop -> assert done one cycle
    localparam WAIT = 4'd11; // bad stop -> wait for line=1

    reg [3:0] state, next;
    reg [7:0] shifter;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? D0 : IDLE; // start bit detected
            D0:   next = D1;
            D1:   next = D2;
            D2:   next = D3;
            D3:   next = D4;
            D4:   next = D5;
            D5:   next = D6;
            D6:   next = D7;
            D7:   next = STOP;
            STOP: next = (in == 1'b1) ? DONE : WAIT;
            DONE: next = (in == 1'b0) ? D0 : IDLE; // can start next byte
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= IDLE;
        else       state <= next;
    end

    // shift in LSB first: each data bit goes to bit 7, shifting right,
    // so after 8 bits bit0 ends in [0].
    always @(posedge clk) begin
        if (state >= D0 && state <= D7)
            shifter <= {in, shifter[7:1]};
    end

    assign done     = (state == DONE);
    assign out_byte = shifter;
endmodule
