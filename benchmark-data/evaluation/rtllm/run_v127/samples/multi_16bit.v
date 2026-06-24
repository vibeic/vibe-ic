// multi_16bit: unsigned 16-bit shift-and-accumulate multiplier.
// Faithful to the spec's stated control sequence:
//   - shift count register i: 0 on reset; while start && i<17, i++; if !start, i=0.
//   - done_r: 0 on reset; 1 when i==16; 0 when i==17.
//   - areg/breg loaded from ain/bin when i==0; for 0<i<17, if areg[i-1] then
//     yout_r += breg << (i-1).
module multi_16bit (
    input              clk,
    input              rst_n,
    input              start,
    input      [15:0]  ain,
    input      [15:0]  bin,
    output     [31:0]  yout,
    output             done
);

    reg [4:0]  i;        // shift count register (0..17 needs 5 bits)
    reg        done_r;
    reg [15:0] areg;
    reg [15:0] breg;
    reg [31:0] yout_r;

    // Shift count register
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            i <= 5'd0;
        else if (start) begin
            if (i < 5'd17)
                i <= i + 5'd1;
        end
        else
            i <= 5'd0;
    end

    // Completion flag
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            done_r <= 1'b0;
        else if (i == 5'd16)
            done_r <= 1'b1;
        else if (i == 5'd17)
            done_r <= 1'b0;
    end

    // Shift-and-accumulate datapath
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            areg   <= 16'd0;
            breg   <= 16'd0;
            yout_r <= 32'd0;
        end
        else if (start) begin
            if (i == 5'd0) begin
                areg <= ain;
                breg <= bin;
            end
            else if (i > 5'd0 && i < 5'd17) begin
                if (areg[i - 5'd1])
                    yout_r <= yout_r + ({16'd0, breg} << (i - 5'd1));
            end
        end
    end

    assign yout = yout_r;
    assign done = done_r;

endmodule
