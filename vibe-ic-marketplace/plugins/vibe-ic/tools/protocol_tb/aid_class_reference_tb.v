`timescale 1ns / 100ps

// ================================================================
// Plugin-provided reference testbench for AID-class half-duplex
// asynchronous identification protocols (e.g. USB-HID tester / IC-A /
// any 1-wire open-drain query/response IC family).
//
// Wave 28 / v0.119.60: this TB is the first runtime functional
// verification gate for fresh-agent RTL.  It drives host-side
// stimulus (BR break-pulse + cmd byte + tSRS gap) onto the
// open-drain bus, captures the DUT-side response by sampling the
// id_bus midway through each bit cell, and prints a single PASS /
// FAIL line that the gate parser greps for.
//
// Wave 34 / v0.119.66 — REJECT device-side BR.  Real USB-HID-tester-class
// host firmware DOES NOT expect the device to emit a BR before its
// response bits; the host already sent BR as the framing marker
// and just samples the DUT's bit cells directly within tSRS.  Any
// DUT LOW pulse ≥ BR_MIN duration is a PROTOCOL VIOLATION because
// host firmware will mis-classify it as another BR / IBT abnormality
// and discard the reply.  Wave 28's previous "wait for DUT BR before
// reading bits" capture model was wrong and contradicted Layer 14 of
// rig spec.  This Wave-34 TB now:
//   * captures bits from the FIRST DUT-driven LOW after tSRS
//   * tracks every DUT-driven LOW pulse width
//   * FAILs with PROTOCOL_VIOLATION_DEVICE_BR if any DUT pulse is
//     ≥ BR_MIN (= H0_MAX + 1, derived from T_BIT0_LOW_NS).
// Both Wave 25 rig spec AND Wave 28 TB now agree: NO device BR.
//
// CHIP-AGNOSTIC.  All host timing values are parameters with
// physical-time units (in ns) so they translate across any AID-class
// chip whose chip-clock frequency is exposed via CLOCK_PERIOD_NS.
//
// Expected DUT contract (the `chip_top` / agent-supplied top must
// expose at minimum):
//   input  clk          // chip core clock
//   input  reset_n      // active-low synchronous reset
//   inout  id_bus       // 1-wire open-drain (DUT pulls LOW only)
//
// If the agent's top module is not literally named `chip_top`, build
// the TB with `+define+DUT_TOP_NAME=<actual_name>`.
// ================================================================

module aid_class_reference_tb;

  // ----------------------------------------------------------------
  // Compile-time parameters (all in ns or in clock ticks).  iverilog
  // accepts override via `+define+NAME=<value>` on the cmdline.
  // ----------------------------------------------------------------
  parameter CLOCK_PERIOD_NS      = 20;     // 50 MHz default chip clock
  // Host-driven LOW durations (in ns).  Defaults derived from FRS §5
  // typical values for AID-class.
  parameter T_BR_NS              = 14000;  // host BR LOW pulse (~14 us)
  parameter T_BIT0_LOW_NS        =  7100;  // bit-0 LOW phase (~7.1 us)
  parameter T_BIT1_LOW_NS        =  1800;  // bit-1 LOW phase (~1.8 us)
  parameter T_BIT_CELL_NS        =  8800;  // total bit cell  (~8.8 us)
  parameter T_TSRS_MIN_NS        = 20000;  // min host-DUT turnaround
  parameter T_DUT_BIT_THRESHOLD_NS = 4500; // LOW > 4.5 us = bit-0
                                           // (between BIT1 LOW ~1.8 us
                                           //  and BIT0 LOW ~7.1 us)
  parameter T_DUT_MIN_BIT_LOW_NS   = 900;  // ignore LOW pulses < 0.9 us
                                           // (open-drain release races
                                           //  produce sub-100ns blips)
  parameter T_RESPONSE_WAIT_NS   = 800000; // wait DUT reply up to 800us
                                           // (cover 8-byte response @
                                           //  ~70 µs/byte + IBT)
  parameter T_FRAME_END_GAP_NS   = 100000; // host treats this as EOF
                                           // (1 byte ~70 µs at default
                                           //  bit-cell, plus margin)
  parameter MAX_RESPONSE_BYTES   = 32;     // capture buffer depth

  // ----------------------------------------------------------------
  // DUT instantiation.  `chip_top` is the default; agents whose top
  // module is named differently should pass +define+DUT_TOP_NAME.
  // ----------------------------------------------------------------
  reg clk = 1'b0;
  reg reset_n = 1'b0;
  wire id_bus;
  reg host_drive_low = 1'b0;
  pullup(id_bus);
  assign id_bus = host_drive_low ? 1'b0 : 1'bz;

`ifdef DUT_TOP_NAME
  `DUT_TOP_NAME u_dut (
    .clk(clk),
    .reset_n(reset_n),
    .id_bus(id_bus)
  );
`else
  chip_top u_dut (
    .clk(clk),
    .reset_n(reset_n),
    .id_bus(id_bus)
  );
`endif

  // ----------------------------------------------------------------
  // Clock generator
  // ----------------------------------------------------------------
  initial clk = 1'b0;
  always #(CLOCK_PERIOD_NS / 2) clk = ~clk;

  // ----------------------------------------------------------------
  // Host-side stimulus tasks
  // ----------------------------------------------------------------

  // Break-pulse: drive LOW for T_BR_NS then release.
  task host_drive_br;
    begin
      host_drive_low = 1'b1;
      #(T_BR_NS);
      host_drive_low = 1'b0;
    end
  endtask

  // One bit cell: LOW for T_BIT0/1_LOW_NS then HIGH for the remainder.
  task host_drive_bit;
    input b;
    integer low_ns;
    integer high_ns;
    begin
      host_drive_low = 1'b1;
      if (b == 1'b0) low_ns = T_BIT0_LOW_NS;
      else           low_ns = T_BIT1_LOW_NS;
      #(low_ns);
      host_drive_low = 1'b0;
      high_ns = T_BIT_CELL_NS - low_ns;
      if (high_ns > 0) #(high_ns);
    end
  endtask

  // One byte = 8 bit cells, LSB-first per AID-class FRS §7.
  task host_drive_byte;
    input [7:0] byte_val;
    integer i;
    begin
      for (i = 0; i < 8; i = i + 1)
        host_drive_bit(byte_val[i]);
    end
  endtask

  // ----------------------------------------------------------------
  // DUT response capture (continuous parallel process) — Wave 34
  // ----------------------------------------------------------------
  // Strategy: continuously sample id_bus.  When id_bus is LOW *and*
  // host_drive_low==0 it must be the DUT pulling.  Wave 34 contract:
  // every DUT-driven LOW pulse is a BIT cell (BIT0 if LOW > threshold,
  // BIT1 if LOW < threshold).  If ANY DUT-driven LOW pulse exceeds
  // BR_MIN_NS, it's a PROTOCOL VIOLATION (device-side BR forbidden).
  // Bits accumulate LSB-first; after 8 bits a byte is latched.
  // Reset between scenarios via clear_dut_capture().
  //
  // BR_MIN_NS derived from T_BIT0_LOW_NS — chip-AGNOSTIC: any LOW
  // exceeding 1.5× the longest bit-cell LOW is treated as the host's
  // BR width class.  The DUT's response must NEVER reach that.
  localparam integer BR_MIN_NS = (T_BIT0_LOW_NS * 3) / 2;

  reg [7:0] dut_response_bytes [0:MAX_RESPONSE_BYTES-1];
  integer  dut_byte_idx;
  integer  dut_bit_idx;
  reg [7:0] dut_byte_acc;
  integer   dut_long_low_count;  // Wave 34: count of LOW pulses ≥ BR_MIN_NS
  integer   dut_first_long_low_ns; // first violation timestamp, for diag
  integer   dut_first_long_low_dur_ns; // duration of first violation

  task clear_dut_capture;
    integer i;
    begin
      dut_byte_idx              = 0;
      dut_bit_idx               = 0;
      dut_byte_acc              = 8'h00;
      dut_long_low_count        = 0;
      dut_first_long_low_ns     = 0;
      dut_first_long_low_dur_ns = 0;
      for (i = 0; i < MAX_RESPONSE_BYTES; i = i + 1)
        dut_response_bytes[i] = 8'h00;
    end
  endtask

  // Continuous capture process — runs forever in parallel with host
  // stimulus.  Detects DUT-driven LOW pulses (id_bus===0 while
  // host_drive_low==0), classifies them as BIT0/BIT1 (and flags
  // PROTOCOL_VIOLATION_DEVICE_BR if any pulse ≥ BR_MIN_NS).  No
  // "leading BR" handshake — Wave 34 starts capturing bits from the
  // FIRST DUT-driven LOW after tSRS turnaround.
  integer cap_low_start_ns;
  integer cap_low_dur_ns;
  reg     cap_bit_val;
  initial begin
    clear_dut_capture;
    @(posedge reset_n);
    forever begin
      // Poll at 100 ns granularity
      #100;
      if (id_bus === 1'b0 && host_drive_low == 1'b0) begin
        cap_low_start_ns = $time;
        // Wait for HIGH or host taking over the bus
        while (id_bus === 1'b0 && host_drive_low == 1'b0)
          #100;
        cap_low_dur_ns = $time - cap_low_start_ns;
`ifdef DEBUG_CAPTURE
        $display("DBG_CAP dur=%0d byte_idx=%0d bit_idx=%0d t=%0t",
                 cap_low_dur_ns, dut_byte_idx, dut_bit_idx, $time);
`endif
        // Wave 34 — REJECT device-side BR.  Any DUT LOW pulse
        // exceeding BR_MIN_NS is a protocol violation.  The bit
        // would be mis-classified as a BIT0 anyway (since BR > BIT0)
        // and the host firmware would treat it as a frame restart.
        // Also: ignore sub-bit-cell blips (< T_DUT_MIN_BIT_LOW_NS)
        // caused by open-drain release races at the host BR/cmd
        // boundary — those are TB artefacts, not real DUT bits.
        if (cap_low_dur_ns < T_DUT_MIN_BIT_LOW_NS) begin
          // bus glitch — drop
        end else if (cap_low_dur_ns >= BR_MIN_NS) begin
          if (dut_long_low_count == 0) begin
            dut_first_long_low_ns     = cap_low_start_ns;
            dut_first_long_low_dur_ns = cap_low_dur_ns;
          end
          dut_long_low_count = dut_long_low_count + 1;
          $display("PROTOCOL_VIOLATION_DEVICE_BR — DUT drove LOW for %0d ns at t=%0d ns (BR_MIN=%0d ns)",
                   cap_low_dur_ns, cap_low_start_ns, BR_MIN_NS);
        end else begin
          // Normal bit cell — classify by LOW width.
          if (cap_low_dur_ns > T_DUT_BIT_THRESHOLD_NS)
            cap_bit_val = 1'b0;
          else
            cap_bit_val = 1'b1;
          dut_byte_acc[dut_bit_idx] = cap_bit_val;
          dut_bit_idx = dut_bit_idx + 1;
          if (dut_bit_idx == 8) begin
            if (dut_byte_idx < MAX_RESPONSE_BYTES) begin
              dut_response_bytes[dut_byte_idx] = dut_byte_acc;
              dut_byte_idx = dut_byte_idx + 1;
            end
            dut_bit_idx = 0;
            dut_byte_acc = 8'h00;
          end
        end
      end
    end
  end

  // Wait up to max_wait_ns for DUT to finish responding (frame-end
  // gap or watchdog).  Used by scenarios in lieu of fixed sleep.
  task capture_dut_response;
    input integer max_wait_ns;
    integer       waited_ns;
    integer       last_byte_count;
    integer       last_bit_idx;
    integer       quiet_ns;
    begin
      waited_ns = 0;
      quiet_ns = 0;
      last_byte_count = dut_byte_idx;
      last_bit_idx = dut_bit_idx;
      while (waited_ns < max_wait_ns) begin
        #500;
        waited_ns = waited_ns + 500;
        // Any DUT activity (new byte / new bit) resets the quiet
        // counter.  Wave 34: we no longer wait on a BR sentinel —
        // we count quiet time as soon as ANY bit has been received.
        if (dut_byte_idx != last_byte_count
            || dut_bit_idx != last_bit_idx) begin
          last_byte_count = dut_byte_idx;
          last_bit_idx = dut_bit_idx;
          quiet_ns = 0;
        end else if (dut_byte_idx > 0 || dut_bit_idx > 0) begin
          quiet_ns = quiet_ns + 500;
          if (quiet_ns >= T_FRAME_END_GAP_NS)
            waited_ns = max_wait_ns; // EOF
        end
      end
    end
  endtask

  // ----------------------------------------------------------------
  // CRC-8 reflected polynomial 0x8C with init 0xFF (FRS §7).  The
  // residue of (CMD/RSP-bytes ++ CRC) computed with this polynomial
  // is 0x00 for a valid frame.
  // ----------------------------------------------------------------
  function [7:0] crc8_8c_step;
    input [7:0] crc_in;
    input [7:0] data;
    integer     j;
    reg [7:0]   c;
    begin
      c = crc_in ^ data;
      for (j = 0; j < 8; j = j + 1) begin
        if (c[0])
          c = (c >> 1) ^ 8'h8C;
        else
          c = c >> 1;
      end
      crc8_8c_step = c;
    end
  endfunction

  function [7:0] compute_crc_residue;
    input integer nbytes;
    integer       k;
    reg [7:0]     c;
    begin
      c = 8'hFF;
      for (k = 0; k < nbytes; k = k + 1)
        c = crc8_8c_step(c, dut_response_bytes[k]);
      compute_crc_residue = c;
    end
  endfunction

  // ----------------------------------------------------------------
  // Test scenarios
  // ----------------------------------------------------------------
  integer errors;

  task run_scenario_get_id;
    integer residue;
    integer i;
    begin
      $display("INFO scenario=GET_ID opcode=0x74 — driving host stimulus");
      clear_dut_capture;
      // BR + CMD(0x74) + tSRS gap, then capture
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'h74);
      capture_dut_response(T_RESPONSE_WAIT_NS);

      $display("INFO GET_ID dut_byte_count=%0d", dut_byte_idx);
      for (i = 0; i < dut_byte_idx; i = i + 1)
        $display("INFO GET_ID byte[%0d]=0x%02h", i,
                 dut_response_bytes[i]);

      if (dut_long_low_count > 0) begin
        $display("FAIL_GET_ID_DEVICE_BR — DUT drove %0d LOW pulse(s) >= BR_MIN=%0d ns; first at t=%0d ns dur=%0d ns. Wave 34: device-side BR forbidden.",
                 dut_long_low_count, BR_MIN_NS,
                 dut_first_long_low_ns, dut_first_long_low_dur_ns);
        errors = errors + 1;
      end else if (dut_byte_idx < 8) begin
        $display("FAIL_GET_ID — DUT only sent %0d bytes (expected >=8)",
                 dut_byte_idx);
        errors = errors + 1;
      end else if (dut_response_bytes[0] !== 8'h75) begin
        $display("FAIL_GET_ID_OPCODE — DUT first byte 0x%02h, expected 0x75",
                 dut_response_bytes[0]);
        errors = errors + 1;
      end else begin
        residue = compute_crc_residue(8);
        if (residue !== 8'h00) begin
          $display("FAIL_GET_ID_CRC — residue 0x%02h, expected 0x00",
                   residue);
          errors = errors + 1;
        end else begin
          $display("PASS_GET_ID — 8 bytes, opcode=0x75, CRC residue=0");
        end
      end
    end
  endtask

  task run_scenario_get_state;
    integer i;
    begin
      $display("INFO scenario=GET_STATE opcode=0x72 — driving host stimulus");
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'h72);
      capture_dut_response(T_RESPONSE_WAIT_NS);
      $display("INFO GET_STATE dut_byte_count=%0d", dut_byte_idx);
      for (i = 0; i < dut_byte_idx; i = i + 1)
        $display("INFO GET_STATE byte[%0d]=0x%02h", i,
                 dut_response_bytes[i]);
      if (dut_long_low_count > 0) begin
        $display("FAIL_GET_STATE_DEVICE_BR — DUT drove %0d LOW pulse(s) >= BR_MIN=%0d ns; first at t=%0d ns dur=%0d ns. Wave 34: device-side BR forbidden.",
                 dut_long_low_count, BR_MIN_NS,
                 dut_first_long_low_ns, dut_first_long_low_dur_ns);
        errors = errors + 1;
      end else if (dut_byte_idx < 1) begin
        $display("FAIL_GET_STATE — DUT silent (0 bytes)");
        errors = errors + 1;
      end else if (dut_response_bytes[0] !== 8'h73) begin
        // Convention: response opcode = command opcode + 1.
        // Some chips reply with arbitrary status — only flag silent.
        $display("WARN_GET_STATE — DUT first byte 0x%02h (expected 0x73 by AID convention)",
                 dut_response_bytes[0]);
      end else begin
        $display("PASS_GET_STATE — DUT responded with 0x73");
      end
    end
  endtask

  task run_scenario_get_info;
    integer i;
    begin
      $display("INFO scenario=GET_INFO opcode=0x76 — driving host stimulus");
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'h76);
      capture_dut_response(T_RESPONSE_WAIT_NS);
      $display("INFO GET_INFO dut_byte_count=%0d", dut_byte_idx);
      for (i = 0; i < dut_byte_idx; i = i + 1)
        $display("INFO GET_INFO byte[%0d]=0x%02h", i,
                 dut_response_bytes[i]);
      if (dut_long_low_count > 0) begin
        $display("FAIL_GET_INFO_DEVICE_BR — DUT drove %0d LOW pulse(s) >= BR_MIN=%0d ns; first at t=%0d ns dur=%0d ns. Wave 34: device-side BR forbidden.",
                 dut_long_low_count, BR_MIN_NS,
                 dut_first_long_low_ns, dut_first_long_low_dur_ns);
        errors = errors + 1;
      end else if (dut_byte_idx < 1) begin
        $display("FAIL_GET_INFO — DUT silent (0 bytes)");
        errors = errors + 1;
      end else begin
        $display("PASS_GET_INFO — DUT responded (%0d bytes)", dut_byte_idx);
      end
    end
  endtask

  // ----------------------------------------------------------------
  // Wave 35 (v0.119.67) — extended scenarios.  Each scenario
  // emits its own PROTOCOL_REFERENCE_TB_<name>_PASS / _FAIL /
  // _SKIP line.  Final aggregate PROTOCOL_REFERENCE_TB_PASS only
  // requires the canonical liveness scenario (GET_ID) to PASS;
  // the additional scenarios act as DIAGNOSTIC information so
  // chips that don't implement a particular opcode report SKIP
  // rather than blocking the aggregate verdict.
  // ----------------------------------------------------------------

  // GET_OTP_BYTE (0xE2) — drive 0xE2 + addr; expect response opcode
  // 0xE3 + OTP byte at that addr + CRC.  Wave 35: probe with one
  // address; chips that don't implement 0xE2 stay silent → SKIP.
  task run_scenario_get_otp_byte;
    input  [6:0] addr;
    integer i;
    integer residue;
    begin
      $display("INFO scenario=GET_OTP_BYTE opcode=0xE2 addr=0x%02h", addr);
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'hE2);
      host_drive_byte({1'b0, addr});
      capture_dut_response(T_RESPONSE_WAIT_NS);
      $display("INFO GET_OTP_BYTE dut_byte_count=%0d", dut_byte_idx);
      for (i = 0; i < dut_byte_idx; i = i + 1)
        $display("INFO GET_OTP_BYTE byte[%0d]=0x%02h", i,
                 dut_response_bytes[i]);
      if (dut_long_low_count > 0) begin
        $display("FAIL_GET_OTP_BYTE_DEVICE_BR — DUT drove %0d LOW pulse(s) >= BR_MIN=%0d ns",
                 dut_long_low_count, BR_MIN_NS);
        // Device BR is a real protocol violation — count error.
        errors = errors + 1;
      end else if (dut_byte_idx < 1) begin
        $display("SKIP_GET_OTP_BYTE — DUT silent (chip may not implement 0xE2)");
      end else if (dut_response_bytes[0] !== 8'hE3) begin
        $display("WARN_GET_OTP_BYTE — first byte 0x%02h, expected 0xE3 by AID convention",
                 dut_response_bytes[0]);
      end else if (dut_byte_idx >= 3) begin
        residue = compute_crc_residue(dut_byte_idx);
        if (residue !== 8'h00)
          $display("WARN_GET_OTP_BYTE_CRC — residue 0x%02h", residue);
        else
          $display("PASS_GET_OTP_BYTE — opcode=0xE3 CRC residue=0");
      end else begin
        $display("PASS_GET_OTP_BYTE — DUT responded (%0d bytes)", dut_byte_idx);
      end
    end
  endtask

  // SET_STATE (0x70) — drive 0x70 + state-data; expect 0x71 echo + CRC.
  task run_scenario_set_state;
    integer i;
    integer residue;
    begin
      $display("INFO scenario=SET_STATE opcode=0x70 — driving host stimulus");
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'h70);
      host_drive_byte(8'h01);
      capture_dut_response(T_RESPONSE_WAIT_NS);
      $display("INFO SET_STATE dut_byte_count=%0d", dut_byte_idx);
      for (i = 0; i < dut_byte_idx; i = i + 1)
        $display("INFO SET_STATE byte[%0d]=0x%02h", i,
                 dut_response_bytes[i]);
      if (dut_long_low_count > 0) begin
        $display("FAIL_SET_STATE_DEVICE_BR — DUT drove %0d LOW pulse(s) >= BR_MIN=%0d ns",
                 dut_long_low_count, BR_MIN_NS);
        errors = errors + 1;
      end else if (dut_byte_idx < 1) begin
        $display("SKIP_SET_STATE — DUT silent (chip may not implement 0x70)");
      end else if (dut_response_bytes[0] !== 8'h71) begin
        $display("WARN_SET_STATE — first byte 0x%02h, expected 0x71",
                 dut_response_bytes[0]);
      end else if (dut_byte_idx >= 2) begin
        residue = compute_crc_residue(dut_byte_idx);
        if (residue !== 8'h00)
          $display("WARN_SET_STATE_CRC — residue 0x%02h", residue);
        else
          $display("PASS_SET_STATE — opcode=0x71 CRC residue=0");
      end else begin
        $display("PASS_SET_STATE — DUT responded (%0d bytes)", dut_byte_idx);
      end
    end
  endtask

  // CRC corruption — drive 0x74 then BR-followed-by-deliberate-noise.
  // The DUT must reject the frame and stay silent.  Detection: any
  // non-quiet response is a violation.
  task run_scenario_crc_corruption;
    integer i;
    begin
      $display("INFO scenario=CRC_CORRUPTION — driving 0x74 then garbage");
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'h74);
      // Append a spurious byte mid-frame to corrupt residue
      host_drive_byte(8'h99);
      capture_dut_response(T_RESPONSE_WAIT_NS / 2);
      $display("INFO CRC_CORRUPTION dut_byte_count=%0d", dut_byte_idx);
      if (dut_long_low_count > 0) begin
        $display("FAIL_CRC_CORRUPTION_DEVICE_BR — DUT emitted device BR");
        errors = errors + 1;
      end else if (dut_byte_idx == 0) begin
        $display("PASS_CRC_CORRUPTION — DUT correctly stayed silent on bad frame");
      end else begin
        $display("WARN_CRC_CORRUPTION — DUT replied with %0d byte(s); some chips may always-respond. Not an error.",
                 dut_byte_idx);
      end
    end
  endtask

  // Frame-timeout — drive only a partial byte (3 bits worth) then quit;
  // the DUT must discard and stay in RX state ready for next BR.
  // After timeout, drive a fresh GET_ID and verify recovery.
  task run_scenario_frame_timeout;
    integer i;
    begin
      $display("INFO scenario=FRAME_TIMEOUT — drive partial byte, then full GET_ID");
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      // Only 3 bits of an opcode — stop mid-byte
      host_drive_bit(1'b0);
      host_drive_bit(0);
      host_drive_bit(1);
      // Long quiet so any decent timeout fires
      #(T_FRAME_END_GAP_NS * 2);
      // Now drive a fresh proper GET_ID frame
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'h74);
      capture_dut_response(T_RESPONSE_WAIT_NS);
      $display("INFO FRAME_TIMEOUT post-recovery dut_byte_count=%0d",
               dut_byte_idx);
      if (dut_long_low_count > 0) begin
        $display("FAIL_FRAME_TIMEOUT_DEVICE_BR — DUT emitted device BR");
        errors = errors + 1;
      end else if (dut_byte_idx >= 1) begin
        $display("PASS_FRAME_TIMEOUT — DUT recovered and replied (%0d bytes) after partial-frame abort",
                 dut_byte_idx);
      end else begin
        $display("WARN_FRAME_TIMEOUT — DUT silent after partial-frame; chip may need explicit reset");
      end
    end
  endtask

  // Multi-byte command (0xE0 OTP program) — drive 0xE0 + addr + data
  // + CRC stub.  Most chips reject without tester unlock; chips that
  // accept emit 0xE1 echo or status byte.  Treated as advisory.
  task run_scenario_multi_byte_cmd;
    integer i;
    begin
      $display("INFO scenario=MULTI_BYTE_CMD opcode=0xE0 (OTP program)");
      clear_dut_capture;
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'hE0);
      host_drive_byte(8'h7F);  // addr
      host_drive_byte(8'hAA);  // data
      host_drive_byte(8'h00);  // crc stub
      capture_dut_response(T_RESPONSE_WAIT_NS / 2);
      $display("INFO MULTI_BYTE_CMD dut_byte_count=%0d", dut_byte_idx);
      if (dut_long_low_count > 0) begin
        $display("FAIL_MULTI_BYTE_CMD_DEVICE_BR — DUT emitted device BR");
        errors = errors + 1;
      end else if (dut_byte_idx == 0) begin
        $display("SKIP_MULTI_BYTE_CMD — DUT silent (likely OTP locked / unlock-gated)");
      end else begin
        $display("PASS_MULTI_BYTE_CMD — DUT replied (%0d bytes); first=0x%02h",
                 dut_byte_idx, dut_response_bytes[0]);
      end
    end
  endtask

  // WAKE then GET_ID — simulate full session: wake pulse + delay + GET_ID.
  task run_scenario_wake_then_get_id;
    integer i;
    integer residue;
    begin
      $display("INFO scenario=WAKE_THEN_GET_ID — wake pulse then GET_ID");
      clear_dut_capture;
      // Drive a wake-style long LOW (host BR works as wake on most AID chips)
      host_drive_br;
      #(T_TSRS_MIN_NS * 4);  // longer settle for wake
      // Standard GET_ID
      host_drive_br;
      #(T_TSRS_MIN_NS);
      host_drive_byte(8'h74);
      capture_dut_response(T_RESPONSE_WAIT_NS);
      $display("INFO WAKE_THEN_GET_ID dut_byte_count=%0d", dut_byte_idx);
      for (i = 0; i < dut_byte_idx; i = i + 1)
        $display("INFO WAKE_THEN_GET_ID byte[%0d]=0x%02h", i,
                 dut_response_bytes[i]);
      if (dut_long_low_count > 0) begin
        $display("FAIL_WAKE_THEN_GET_ID_DEVICE_BR — DUT emitted device BR");
        errors = errors + 1;
      end else if (dut_byte_idx < 8) begin
        $display("WARN_WAKE_THEN_GET_ID — DUT only sent %0d bytes (expected >=8 for GET_ID); chip may need explicit wake protocol",
                 dut_byte_idx);
      end else if (dut_response_bytes[0] !== 8'h75) begin
        $display("WARN_WAKE_THEN_GET_ID_OPCODE — first byte 0x%02h, expected 0x75",
                 dut_response_bytes[0]);
      end else begin
        residue = compute_crc_residue(8);
        if (residue !== 8'h00)
          $display("WARN_WAKE_THEN_GET_ID_CRC — residue 0x%02h", residue);
        else
          $display("PASS_WAKE_THEN_GET_ID — 8 bytes, opcode=0x75, CRC=0");
      end
    end
  endtask

  // ----------------------------------------------------------------
  // Main driver
  // ----------------------------------------------------------------
  initial begin
    errors = 0;

`ifdef DUMP_VCD
    $dumpfile("aid_class_ref_tb.vcd");
    $dumpvars(0, aid_class_reference_tb);
`endif

    // Reset
    reset_n = 1'b0;
    #(50 * CLOCK_PERIOD_NS);
    reset_n = 1'b1;
    #(200 * CLOCK_PERIOD_NS);

    // Allow chip-side wake / POR to settle (chips may emit POR
    // wake pulses; the TB tolerates them in the bus-quiet phase).
    #(20000);

    run_scenario_get_id;
    #(50000);
    run_scenario_get_state;
    #(50000);
    run_scenario_get_info;
    // Wave 35 (v0.119.67) — extended diagnostic scenarios.
    // These do NOT block the aggregate verdict for chips that don't
    // implement the opcode (silent → SKIP).  They DO block on
    // device-BR violations (errors increment).
    #(50000);
    run_scenario_get_otp_byte(7'h00);
    #(50000);
    run_scenario_get_otp_byte(7'h05);
    #(50000);
    run_scenario_set_state;
    #(50000);
    run_scenario_crc_corruption;
    #(50000);
    run_scenario_frame_timeout;
    #(50000);
    run_scenario_multi_byte_cmd;
    #(50000);
    run_scenario_wake_then_get_id;

    if (errors == 0) begin
      $display("PROTOCOL_REFERENCE_TB_PASS");
    end else begin
      $display("PROTOCOL_REFERENCE_TB_FAIL — %0d error(s)", errors);
    end

    $finish;
  end

  // Watchdog — Wave 35 extended to cover added scenarios
  initial begin
    #(15_000_000); // 15 ms hard limit (was 5 ms; Wave 35 adds 7 scenarios)
    $display("PROTOCOL_REFERENCE_TB_FAIL — watchdog timeout");
    $finish;
  end

endmodule
