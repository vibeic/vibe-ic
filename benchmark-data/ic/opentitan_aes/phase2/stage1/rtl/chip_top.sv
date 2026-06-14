// chip_top — GENERATED integration wrapper for OpenTitan AES (REUSED-IP).
//
// Authored from L1-L23 spec + input/docs (aes_README.md, aes_interfaces.md,
// aes_theory_of_operation.md) + input/vendor_rtl. This is the GENERATED glue;
// the AES IP itself (aes, aes_core, aes_cipher_core, prim_*, tlul_*) is
// REUSED-IP staged as-is from input/vendor_rtl/ (see SOURCE_MANIFEST.md).
//
// Design intent:
//   The OpenTitan `aes` top exposes struct-typed comportable ports (TL-UL bus,
//   EDN req/rsp, keymgr sideload, life-cycle, alert rx/tx). For a stand-alone
//   ASIC/FPGA integration with a flat scalar interface, OpenTitan ships the
//   synthesizable `aes_wrap` module (input/vendor_rtl/aes/aes_wrap.sv) which
//   instantiates `aes`, drives the full TL-UL register programming sequence
//   (CTRL/AUX/KEY/IV/DATA) via an internal FSM, and exposes a flat
//   {clk, rst, key, input, output, alert, done} interface. chip_top wraps
//   aes_wrap so the deterministic runner's downstream gates (lint / yosys
//   synth / LEC) operate on a single, fully-synthesizable scalar-port top.
//
// S-Box / masking configuration:
//   The DOM masked S-Box source (aes_sbox_dom.sv) is provided in the dataset
//   tagged `.unused-masked-scan-excluded` and is therefore NOT part of the
//   staged synthesis set. Per aes_README.md (Features), DOM masking is an
//   OPTIONAL compile-time parameter and can be disabled to save area. chip_top
//   therefore selects the unmasked LUT S-Box (SecMasking=0, SBoxImplLut),
//   which is fully covered by the staged RTL and keeps the cipher datapath
//   functionally identical (FIPS-197 AES) — masking only affects SCA hardening,
//   not the encrypt/decrypt result.

module chip_top
  import aes_pkg::*;
(
  input  logic         clk_i,
  input  logic         rst_ni,

  // Flat AES data/key interface (matches aes_wrap)
  input  logic [127:0] aes_input,
  input  logic [255:0] aes_key,
  output logic [127:0] aes_output,

  // Alert / status
  output logic         alert_recov_o,
  output logic         alert_fatal_o,
  output logic         test_done_o
);

  // REUSED-IP: input/vendor_rtl/aes/aes_wrap.sv (instantiates the full aes IP).
  // Unmasked LUT S-Box (synthesizable with the staged RTL set); AES-192 kept
  // enabled to retain full key-length support per spec.
  aes_wrap #(
    .AES192Enable (1'b1),
    .SecMasking   (1'b0),           // optional masking disabled (DOM src excluded)
    .SecSBoxImpl  (SBoxImplLut)     // unmasked LUT S-Box, fully synthesizable
  ) u_aes_wrap (
    .clk_i         (clk_i),
    .rst_ni        (rst_ni),
    .aes_input     (aes_input),
    .aes_key       (aes_key),
    .aes_output    (aes_output),
    .alert_recov_o (alert_recov_o),
    .alert_fatal_o (alert_fatal_o),
    .test_done_o   (test_done_o)
  );

endmodule
