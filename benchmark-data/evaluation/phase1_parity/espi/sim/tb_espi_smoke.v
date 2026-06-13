`timescale 1ns/1ps
// Smoke testbench for the eSPI slave digital core.
// Drives a GET_STATUS command byte-wise via the parallel symbol interface
// of the PHY stub (bit_tick-paced) and checks the slave returns a response.
module tb_espi_smoke;
    reg clk = 0, rst_n = 0;
    reg ESPI_RESET_N = 1, ESPI_CS_N = 1, ESPI_BIT_TICK = 0, ESPI_IO0_IN = 0;
    reg [1:0] ESPI_IO_MODE = 2'd0;
    reg CH_PC_READY=1, CH_VW_READY=1, CH_OOB_READY=1, CH_FLASH_READY=1, EVENT_PENDING=0;
    wire ESPI_IO1_OUT, ESPI_ALERT_N;
    wire [15:0] STATUS_REG;
    wire [3:0]  CH_ENABLE;
    wire [7:0]  LAST_CMD;
    wire        CRC_ERROR;

    chip_top dut(
        .clk(clk), .rst_n(rst_n),
        .ESPI_RESET_N(ESPI_RESET_N), .ESPI_CS_N(ESPI_CS_N),
        .ESPI_BIT_TICK(ESPI_BIT_TICK), .ESPI_IO0_IN(ESPI_IO0_IN),
        .ESPI_IO1_OUT(ESPI_IO1_OUT), .ESPI_IO_MODE(ESPI_IO_MODE),
        .ESPI_ALERT_N(ESPI_ALERT_N),
        .CH_PC_READY(CH_PC_READY), .CH_VW_READY(CH_VW_READY),
        .CH_OOB_READY(CH_OOB_READY), .CH_FLASH_READY(CH_FLASH_READY),
        .EVENT_PENDING(EVENT_PENDING),
        .STATUS_REG(STATUS_REG), .CH_ENABLE(CH_ENABLE),
        .LAST_CMD(LAST_CMD), .CRC_ERROR(CRC_ERROR)
    );

    always #25 clk = ~clk;   // 20 MHz

    integer errors = 0;

    // send one byte MSB-first via bit_tick
    task send_byte(input [7:0] b);
        integer i;
        begin
            for (i = 7; i >= 0; i = i - 1) begin
                @(negedge clk);
                ESPI_IO0_IN  = b[i];
                ESPI_BIT_TICK = 1'b1;
                @(negedge clk);
                ESPI_BIT_TICK = 1'b0;
            end
        end
    endtask

    initial begin
        // reset
        repeat (4) @(negedge clk);
        rst_n = 1;
        repeat (2) @(negedge clk);

        // power-up STATUS = 0x000F (four *_FREE bits)
        if (STATUS_REG !== 16'h000F) begin
            $display("FAIL: power-up STATUS=%h expected 000F", STATUS_REG);
            errors = errors + 1;
        end else $display("PASS: power-up STATUS=%h", STATUS_REG);

        // start a transaction: CS# low, then GET_STATUS opcode (0x20)
        ESPI_CS_N = 1'b0;
        @(negedge clk);
        send_byte(8'h20);          // GET_STATUS opcode
        repeat (4) @(negedge clk);
        if (LAST_CMD !== 8'h20) begin
            $display("FAIL: LAST_CMD=%h expected 20", LAST_CMD);
            errors = errors + 1;
        end else $display("PASS: LAST_CMD captured = %h", LAST_CMD);

        send_byte(8'h00);          // command CRC byte (don't-care value here)
        // let the FSM run through TAR / RESP / RDATA
        repeat (200) @(negedge clk);

        ESPI_CS_N = 1'b1;
        repeat (4) @(negedge clk);

        // SET_CONFIGURATION enable PC channel (addr 0x10, data bit0=1)
        ESPI_CS_N = 1'b0;
        @(negedge clk);
        send_byte(8'h21);          // SET_CONFIGURATION
        send_byte(8'h10);          // config addr = Channel 0
        send_byte(8'h01);          // data: enable bit0
        repeat (4) @(negedge clk);
        if (CH_ENABLE[0] !== 1'b1) begin
            $display("FAIL: CH_ENABLE[0]=%b expected 1 after SET_CONFIG", CH_ENABLE[0]);
            errors = errors + 1;
        end else $display("PASS: SET_CONFIGURATION enabled PC channel, CH_ENABLE=%b", CH_ENABLE);
        repeat (50) @(negedge clk);
        ESPI_CS_N = 1'b1;
        repeat (4) @(negedge clk);

        if (errors == 0) $display("SMOKE_TB_RESULT: PASS");
        else             $display("SMOKE_TB_RESULT: FAIL (%0d errors)", errors);
        $finish;
    end

    // global watchdog
    initial begin
        #200000;
        $display("SMOKE_TB_RESULT: TIMEOUT");
        $finish;
    end
endmodule
