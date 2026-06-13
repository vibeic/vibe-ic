module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);

    localparam IDLE = 2'd0,  // waiting for start bit (in==0)
               DATA = 2'd1,  // receiving 8 data bits
               STOP = 2'd2,  // expecting stop bit (in==1)
               WAIT = 2'd3;  // bad stop: wait for line to return to 1
                              // DONE is signalled via Moore output in a dedicated path

    reg [1:0] state;
    reg [3:0] cnt;        // counts data bits received
    reg       done_r;

    always @(posedge clk) begin
        if (reset) begin
            state  <= IDLE;
            cnt    <= 4'd0;
            done_r <= 1'b0;
        end else begin
            done_r <= 1'b0;   // default
            case (state)
                IDLE: begin
                    if (in == 1'b0) begin   // start bit
                        state <= DATA;
                        cnt   <= 4'd0;
                    end
                end
                DATA: begin
                    if (cnt == 4'd7) begin
                        state <= STOP;
                    end else begin
                        cnt <= cnt + 4'd1;
                    end
                end
                STOP: begin
                    if (in == 1'b1) begin   // valid stop bit
                        done_r <= 1'b1;     // signal done next cycle
                        state  <= IDLE;
                    end else begin          // framing error
                        state <= WAIT;
                    end
                end
                WAIT: begin
                    if (in == 1'b1)         // found a stop (line idle)
                        state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end

    assign done = done_r;

endmodule
