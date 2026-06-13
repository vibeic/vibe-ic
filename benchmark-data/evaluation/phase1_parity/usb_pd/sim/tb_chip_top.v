// tb_chip_top.v -- self-authored functional sanity TB for the USB-PD engine.
// NOT a hidden/golden TB; drives the parallel symbol interface to exercise:
//   * RX of a Request (data) message with a valid CRC-32 -> GoodCRC + rdo capture
//   * Source contract FSM: SrcCap -> WaitReq -> Accept -> PS_trans -> PS_RDY
`timescale 1ns/1ps
`default_nettype none

module tb_chip_top;
    reg         clk = 0, rst_n = 0;
    reg         rx_symbol_valid = 0, rx_sop = 0, rx_eop = 0;
    reg  [7:0]  rx_symbol = 0;
    reg  [1:0]  rx_sop_type = 0;
    wire        tx_symbol_valid, tx_sop, tx_eop;
    wire [7:0]  tx_symbol;
    wire [1:0]  tx_sop_type;
    reg         tx_symbol_ready = 1;
    reg         port_power_role = 1, port_data_role = 1, attach = 0, dpm_start = 0;
    reg  [31:0] src_pdo0 = 32'h0001912C;   // a vSafe5V fixed PDO pattern
    wire [3:0]  contract_state;
    wire        explicit_contract, ps_rdy_sent;
    wire [31:0] rdo_received;
    wire        hard_reset_evt, soft_reset_evt, goodcrc_sent, rx_crc_ok;
    wire [2:0]  rx_msg_id;
    wire        protocol_error;

    chip_top dut (
        .clk(clk), .rst_n(rst_n),
        .rx_symbol_valid(rx_symbol_valid), .rx_symbol(rx_symbol),
        .rx_sop(rx_sop), .rx_eop(rx_eop), .rx_sop_type(rx_sop_type),
        .tx_symbol_valid(tx_symbol_valid), .tx_symbol(tx_symbol),
        .tx_sop(tx_sop), .tx_eop(tx_eop), .tx_sop_type(tx_sop_type),
        .tx_symbol_ready(tx_symbol_ready),
        .port_power_role(port_power_role), .port_data_role(port_data_role),
        .attach(attach), .dpm_start(dpm_start), .src_pdo0(src_pdo0),
        .contract_state(contract_state), .explicit_contract(explicit_contract),
        .ps_rdy_sent(ps_rdy_sent), .rdo_received(rdo_received),
        .hard_reset_evt(hard_reset_evt), .soft_reset_evt(soft_reset_evt),
        .goodcrc_sent(goodcrc_sent), .rx_crc_ok(rx_crc_ok),
        .rx_msg_id(rx_msg_id), .protocol_error(protocol_error)
    );

    always #10 clk = ~clk;   // 50 MHz

    // reference CRC-32 (IEEE 802.3, reflected) matching the DUT
    function [31:0] crc_upd; input [31:0] c0; input [7:0] d; integer i; reg [31:0] c;
        begin c = c0 ^ {24'h0,d};
            for (i=0;i<8;i=i+1) c = c[0] ? (c>>1)^32'hEDB88320 : (c>>1);
            crc_upd = c; end
    endfunction

    integer i; reg [31:0] crc;
    // send one byte on the RX symbol bus
    task rx_byte; input [7:0] b; input sop; input eop;
        begin @(posedge clk); rx_symbol<=b; rx_symbol_valid<=1; rx_sop<=sop; rx_eop<=eop;
              @(posedge clk); rx_symbol_valid<=0; rx_sop<=0; rx_eop<=0; end
    endtask

    // RX a Request data message: header(2B) + 1 RDO(4B) + CRC(4B), all CRC-covered
    reg [15:0] hdr; reg [31:0] rdo;
    task rx_request;
        begin
            hdr = {1'b0,3'd1,3'd0,1'b0,2'b01,1'b0,5'h02}; // NDO=1, type=Request(0x02)
            rdo = 32'h13A40FA0;
            crc = 32'hFFFFFFFF;
            crc = crc_upd(crc, hdr[7:0]);  crc = crc_upd(crc, hdr[15:8]);
            crc = crc_upd(crc, rdo[7:0]);  crc = crc_upd(crc, rdo[15:8]);
            crc = crc_upd(crc, rdo[23:16]);crc = crc_upd(crc, rdo[31:24]);
            crc = crc ^ 32'hFFFFFFFF;
            rx_byte(hdr[7:0],1,0); rx_byte(hdr[15:8],0,0);
            rx_byte(rdo[7:0],0,0); rx_byte(rdo[15:8],0,0);
            rx_byte(rdo[23:16],0,0); rx_byte(rdo[31:24],0,0);
            rx_byte(crc[7:0],0,0); rx_byte(crc[15:8],0,0);
            rx_byte(crc[23:16],0,0); rx_byte(crc[31:24],0,1);
        end
    endtask

    integer errors = 0;
    initial begin
        rst_n=0; repeat(4) @(posedge clk); rst_n=1; @(posedge clk);

        // 1) kick off Source advertisement
        attach=1; dpm_start=1; @(posedge clk); dpm_start=0;
        // let SrcCap drain
        repeat(40) @(posedge clk);
        if (contract_state==4'd0) begin $display("FAIL: FSM did not advance from IDLE"); errors=errors+1; end

        // 2) deliver a valid Request
        rx_request();
        repeat(20) @(posedge clk);
        if (!rx_crc_ok)        begin $display("FAIL: RX CRC-32 of valid Request not OK"); errors=errors+1; end
        if (rdo_received!=32'h13A40FA0) begin $display("FAIL: RDO not captured (got %h)", rdo_received); errors=errors+1; end

        // 3) let Accept -> PS transition -> PS_RDY complete
        repeat(400) @(posedge clk);
        if (!ps_rdy_sent)        begin $display("FAIL: PS_RDY never sent"); errors=errors+1; end
        if (!explicit_contract)  begin $display("FAIL: Explicit Contract not established"); errors=errors+1; end

        if (errors==0)
            $display("TB_PASS: contract negotiated, RDO=%h, crc_ok=%b, ps_rdy=%b, contract=%b",
                     rdo_received, rx_crc_ok, ps_rdy_sent, explicit_contract);
        else
            $display("TB_FAIL: %0d check(s) failed", errors);
        $finish;
    end

    // global timeout
    initial begin #200000 $display("TB_TIMEOUT"); $finish; end
endmodule

`default_nettype wire
