module TopModule(
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE = 3'd0;  // waiting for start bit (line=0)
    localparam DATA = 3'd1;  // collecting 8 data bits
    localparam STOP = 3'd2;  // expect stop bit (line=1)
    localparam DONE = 3'd3;  // assert done one cycle
    localparam WAITE= 3'd4;  // error: wait for line=1 before resuming

    reg [2:0] state;
    reg [3:0] cnt;        // 0..7 data bit index
    reg [7:0] shft;       // received bits, LSB first
    reg [7:0] out_r;

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
            shft  <= 8'd0;
            out_r <= 8'd0;
        end else begin
            case (state)
                IDLE: begin
                    if (in == 1'b0) begin   // start bit
                        cnt   <= 4'd0;
                        state <= DATA;
                    end
                end
                DATA: begin
                    shft <= {in, shft[7:1]};  // LSB first -> shift in from MSB side
                    if (cnt == 4'd7) state <= STOP;
                    else             cnt   <= cnt + 4'd1;
                end
                STOP: begin
                    if (in == 1'b1) begin
                        out_r <= shft;
                        state <= DONE;
                    end else begin
                        state <= WAITE;       // bad stop bit
                    end
                end
                DONE: begin
                    // done asserted this cycle; decide next from current line
                    if (in == 1'b0) begin     // immediate next start bit
                        cnt   <= 4'd0;
                        state <= DATA;
                    end else begin
                        state <= IDLE;
                    end
                end
                WAITE: begin
                    if (in == 1'b1) state <= IDLE;  // found stop, resume search
                end
                default: state <= IDLE;
            endcase
        end
    end

    assign out_byte = out_r;
    assign done     = (state == DONE);
endmodule
