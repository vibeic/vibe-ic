module multi_16bit (
    input             clk,
    input             rst_n,
    input             start,
    input      [15:0] ain,
    input      [15:0] bin,
    output     [31:0] yout,
    output            done
);

    reg [4:0]  i;
    reg        done_r;
    reg [15:0] areg;
    reg [15:0] breg;
    reg [31:0] yout_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            i <= 5'd0;
        end else if (start) begin
            if (i < 17)
                i <= i + 1'b1;
        end else begin
            i <= 5'd0;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            done_r <= 1'b0;
        end else if (i == 16) begin
            done_r <= 1'b1;
        end else if (i == 17) begin
            done_r <= 1'b0;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            areg    <= 16'd0;
            breg    <= 16'd0;
            yout_r  <= 32'd0;
        end else if (start) begin
            if (i == 0) begin
                areg <= ain;
                breg <= bin;
                yout_r <= 32'd0;
            end else if (i > 0 && i < 17) begin
                if (areg[i-1])
                    yout_r <= yout_r + ({16'd0, breg} << (i-1));
            end
        end
    end

    assign yout = yout_r;
    assign done = done_r;

endmodule
