module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output reg z
);
    // A: wait for s. After s=1, examine w over three consecutive cycles;
    // if w==1 in exactly two of them, z=1 in the following cycle. Windows
    // then repeat back-to-back. Active-high synchronous reset.
    localparam A = 2'd0, S1 = 2'd1, S2 = 2'd2, S3 = 2'd3;
    reg [1:0] state;
    reg [1:0] cnt;   // running count of w==1 within the current window

    always @(posedge clk) begin
        if (reset) begin
            state <= A;
            cnt   <= 2'd0;
            z     <= 1'b0;
        end else begin
            case (state)
                A: begin
                    z   <= 1'b0;
                    cnt <= 2'd0;
                    if (s) state <= S1;
                    else   state <= A;
                end
                S1: begin            // 1st w sample
                    cnt   <= {1'b0, w};
                    z     <= 1'b0;
                    state <= S2;
                end
                S2: begin            // 2nd w sample
                    cnt   <= cnt + w;
                    z     <= 1'b0;
                    state <= S3;
                end
                S3: begin            // 3rd w sample -> assert z next cycle
                    z     <= ((cnt + w) == 2'd2);
                    cnt   <= 2'd0;
                    state <= S1;     // next window starts immediately
                end
                default: begin
                    state <= A; cnt <= 2'd0; z <= 1'b0;
                end
            endcase
        end
    end
endmodule
