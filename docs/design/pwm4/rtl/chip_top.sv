// Interface and timing contract: ../design_description.md.
module chip_top (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       spi_sclk,
    input  logic       spi_cs_n,
    input  logic       spi_mosi,
    output logic       spi_miso,
    output logic [3:0] pwm_out
);

    (* async_reg = "true" *) logic [1:0] sclk_sync, cs_sync, mosi_sync;
    logic sclk_seen, cs_seen;
    logic [23:0] spi_shift, captured_frame;
    logic [4:0] spi_bit_count;
    logic frame_valid;

    logic [15:0] active_period [0:3];
    logic [15:0] active_duty   [0:3];
    logic        active_enable [0:3];
    logic [15:0] pending_period[0:3];
    logic [15:0] pending_duty  [0:3];
    logic        pending_enable[0:3];
    logic [2:0]  pending_mask  [0:3];
    logic [15:0] pwm_count     [0:3];
    integer i;

    assign spi_miso = 1'b0;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sclk_sync <= 2'b00;
            cs_sync <= 2'b11;
            mosi_sync <= 2'b00;
            sclk_seen <= 1'b0;
            cs_seen <= 1'b1;
            spi_shift <= '0;
            spi_bit_count <= '0;
            captured_frame <= '0;
            frame_valid <= 1'b0;
        end else begin
            sclk_sync <= {sclk_sync[0], spi_sclk};
            cs_sync <= {cs_sync[0], spi_cs_n};
            mosi_sync <= {mosi_sync[0], spi_mosi};
            sclk_seen <= sclk_sync[1];
            cs_seen <= cs_sync[1];
            frame_valid <= 1'b0;
            if (!cs_sync[1] && cs_seen) begin
                spi_shift <= '0;
                spi_bit_count <= '0;
            end else if (!cs_sync[1] && sclk_sync[1] && !sclk_seen) begin
                spi_shift <= {spi_shift[22:0], mosi_sync[1]};
                if (spi_bit_count < 5'd25)
                    spi_bit_count <= spi_bit_count + 1'b1;
            end
            if (cs_sync[1] && !cs_seen && spi_bit_count == 5'd24) begin
                captured_frame <= spi_shift;
                frame_valid <= 1'b1;
            end
        end
    end

    // PWM state changes only from a frame captured in the system domain.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < 4; i = i + 1) begin
                active_period[i]  <= '0;
                active_duty[i]    <= '0;
                active_enable[i]  <= 1'b0;
                pending_period[i] <= '0;
                pending_duty[i]   <= '0;
                pending_enable[i] <= 1'b0;
                pending_mask[i]   <= '0;
                pwm_count[i]      <= '0;
            end
        end else begin
            for (i = 0; i < 4; i = i + 1) begin
                if (active_period[i] == 16'd0) begin
                    pwm_count[i] <= '0;
                    if (pending_mask[i] != 3'b000) begin
                        if (pending_mask[i][0]) active_period[i] <= pending_period[i];
                        if (pending_mask[i][1]) active_duty[i] <= pending_duty[i];
                        if (pending_mask[i][2]) active_enable[i] <= pending_enable[i];
                        pending_mask[i] <= '0;
                    end
                end else if (pwm_count[i] >= active_period[i] - 1'b1) begin
                    pwm_count[i] <= '0;
                    if (pending_mask[i] != 3'b000) begin
                        if (pending_mask[i][0]) active_period[i] <= pending_period[i];
                        if (pending_mask[i][1]) active_duty[i] <= pending_duty[i];
                        if (pending_mask[i][2]) active_enable[i] <= pending_enable[i];
                        pending_mask[i] <= '0;
                    end
                end else begin
                    pwm_count[i] <= pwm_count[i] + 1'b1;
                end
            end

            if (frame_valid && captured_frame[23]) begin
                if (captured_frame[22:16] <= 7'h03) begin
                    pending_period[captured_frame[17:16]] <= captured_frame[15:0];
                    pending_mask[captured_frame[17:16]][0] <= 1'b1;
                end else if (captured_frame[22:16] >= 7'h04 && captured_frame[22:16] <= 7'h07) begin
                    pending_duty[captured_frame[17:16]] <= captured_frame[15:0];
                    pending_mask[captured_frame[17:16]][1] <= 1'b1;
                end else if (captured_frame[22:16] == 7'h08) begin
                    for (i = 0; i < 4; i = i + 1) begin
                        pending_enable[i] <= captured_frame[i];
                        pending_mask[i][2] <= 1'b1;
                    end
                end
            end
        end
    end

    genvar ch;
    generate
        for (ch = 0; ch < 4; ch = ch + 1) begin : gen_pwm_outputs
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n)
                    pwm_out[ch] <= 1'b0;
                else
                    pwm_out[ch] <= active_enable[ch] &&
                                   (active_period[ch] != 16'd0) &&
                                   (pwm_count[ch] < active_duty[ch]);
            end
        end
    endgenerate

endmodule
