export const meta = {
  name: 'cvdp-distill-lessons',
  description: 'Distill one reusable, design-CLASS-level IC lesson from each of the 94 proven-correct solved designs (RTL + spec). The lesson is grounded in a scored-PASS solution, generalizable to future designs of the same class — written back into the solved-design knowledge DB.',
  phases: [{ title: 'Distill' }],
}

const DB = '/home/reyerchu/vibe-ic/benchmark_external/cvdp/solved_design_db'
const DS = '/home/reyerchu/AI_IC_design/_extbench/cvdp_open_v110/cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl'
const IDS = ["cvdp_copilot_64b66b_decoder_0011", "cvdp_copilot_apb_history_shift_register_0001", "cvdp_copilot_axi_alu_0001", "cvdp_copilot_bus_arbiter_0001", "cvdp_copilot_cont_adder_0045", "cvdp_copilot_gaussian_rounding_div_0003", "cvdp_copilot_interrupt_controller_0017", "cvdp_copilot_perceptron_0006", "cvdp_copilot_run_length_0007", "cvdp_copilot_vending_machine_0001", "cvdp_copilot_64b66b_encoder_0022", "cvdp_copilot_cache_lru_0001", "cvdp_copilot_cache_lru_0019", "cvdp_copilot_data_bus_controller_0001", "cvdp_copilot_gcd_0040", "cvdp_copilot_interrupt_controller_0019", "cvdp_copilot_perceptron_0013", "cvdp_copilot_scrambler_0018", "cvdp_copilot_sorter_0031", "cvdp_copilot_virtual2physical_tlb_0001", "cvdp_copilot_GFCM_0001", "cvdp_copilot_axi_stream_downscale_0001", "cvdp_copilot_clock_jitter_detection_module_0003", "cvdp_copilot_digital_stopwatch_0012", "cvdp_copilot_halfband_fir_0005", "cvdp_copilot_line_buffer_0003", "cvdp_copilot_ping_pong_buffer_0001", "cvdp_copilot_sdram_controller_0001", "cvdp_copilot_sorter_0057", "cvdp_copilot_wb2ahb_0001", "cvdp_copilot_IIR_filter_0019", "cvdp_copilot_axi_stream_upscale_0001", "cvdp_copilot_coffee_machine_0001", "cvdp_copilot_dot_product_0005", "cvdp_copilot_hebbian_rule_0012", "cvdp_copilot_load_store_unit_0009", "cvdp_copilot_pipeline_mac_0017", "cvdp_copilot_secure_ALU_0001", "cvdp_copilot_sound_generator_0001", "cvdp_copilot_word_change_detector_0001", "cvdp_copilot_Serial_Line_Converter_0011", "cvdp_copilot_axi_tap_0009", "cvdp_copilot_elevator_control_0009", "cvdp_copilot_hebbian_rule_0017", "cvdp_copilot_microcode_sequencer_0001", "cvdp_copilot_prbs_gen_0003", "cvdp_copilot_reed_solomon_encoder_and_decoder_0005", "cvdp_copilot_secure_read_write_register_bank_0001", "cvdp_copilot_serial_in_parallel_out_0014", "cvdp_copilot_sprite_0004", "cvdp_copilot_ahb_clk_counter_0001", "cvdp_copilot_apb_dsp_op_0002", "cvdp_copilot_axis_border_gen_0014", "cvdp_copilot_concatenate_0001", "cvdp_copilot_fan_controller_0008", "cvdp_copilot_hill_cipher_0015", "cvdp_copilot_register_file_2R1W_0006", "cvdp_copilot_sigma_delta_audio_0007", "cvdp_copilot_sync_lifo_0010", "cvdp_copilot_sync_serial_communication_0001", "cvdp_copilot_apb_dsp_unit_0001", "cvdp_copilot_binary_search_tree_sorting_0001", "cvdp_copilot_configurable_digital_low_pass_filter_0004", "cvdp_copilot_configurable_digital_low_pass_filter_0011", "cvdp_copilot_fifo_async_0001", "cvdp_copilot_fifo_to_axis_0001", "cvdp_copilot_hmac_register_0001", "cvdp_copilot_mux_synch_0011", "cvdp_copilot_simple_spi_0001", "cvdp_copilot_sync_serial_communication_0014", "cvdp_copilot_apb_gpio_0005", "cvdp_copilot_binary_search_tree_sorting_0014", "cvdp_copilot_cont_adder_0042", "cvdp_copilot_image_rotate_0001", "cvdp_copilot_interrupt_controller_0014", "cvdp_copilot_nbit_swizzling_0020", "cvdp_copilot_neuromorphic_array_0001", "cvdp_copilot_rounding_0001", "cvdp_copilot_skid_buffer_0001", "cvdp_copilot_sync_serial_communication_0052", "cvdp_copilot_sorter_0003", "cvdp_copilot_32_bit_Brent_Kung_PP_adder_0001", "cvdp_copilot_axi_register_0001", "cvdp_copilot_binary_multiplier_0012", "cvdp_copilot_compression_engine_0001", "cvdp_copilot_events_to_apb_0001", "cvdp_copilot_galois_encryption_0001", "cvdp_copilot_hill_cipher_0001", "cvdp_copilot_manchester_enc_0005", "cvdp_copilot_modified_booth_mul_0005", "cvdp_copilot_restoring_division_0001", "cvdp_copilot_run_length_0001", "cvdp_copilot_sorter_0009", "cvdp_copilot_ttc_lite_0001"]

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['id', 'ic_class', 'lesson'],
  properties: {
    id: { type: 'string' },
    ic_class: { type: 'string', description: 'design-class label (e.g. divider, axi-stream, fsm-controller, cache, fir-filter)' },
    lesson: { type: 'string', description: '1-3 sentences: the REUSABLE design-class insight a future author of a SIMILAR design must know — algorithm correctness point, interface convention, latency/reset rule, or the specific trap this correct solution avoids. NOT design-specific trivia; NOT a restatement of the prompt.' },
  },
}

function p(id) {
  return `Distill ONE reusable IC-design lesson from a PROVEN-CORRECT (officially-scored PASS) solution.

## Inputs
- The proven-correct RTL: \`${DB}/rtl/${id}.sv\`
- The spec (read the matching id from the dataset \`${DS}\` — grep for "${id}" and read its input.prompt).

## Task
Read the correct RTL + spec. Extract the ONE most valuable REUSABLE lesson a future engineer authoring a SIMILAR design (same class) should know — the insight that makes this class of design correct and that a naive author gets wrong. Prefer:
- algorithm correctness (e.g. "non-restoring division needs a (W+1)-bit partial-remainder register and a final +divisor correction when the sign bit is set"),
- interface/handshake convention (e.g. "AXI-Stream: assert tready combinationally from downstream-ready; hold tdata/tlast stable while tvalid && !tready"),
- latency/reset discipline (e.g. "registered-output DUTs must present the result the SAME cycle 'done' asserts, else the checker samples stale data"),
- the specific trap avoided (width truncation, off-by-one index, Moore-vs-Mealy, blocking-in-sequential).
Make it design-CLASS-level and generalizable — NOT this problem's specific vectors, NOT a prompt restatement.

Return structured {id, ic_class, lesson}.`
}

phase('Distill')
const results = (await parallel(IDS.map(id => () =>
  agent(p(id), { schema: SCHEMA, label: `lesson:${id.replace('cvdp_copilot_', '')}`, phase: 'Distill', effort: 'low' })
))).filter(Boolean)

// write lessons to a sidecar the builder merges into the index
const map = {}
for (const r of results) map[r.id] = { ic_class: r.ic_class, lesson: r.lesson }
return { distilled: results.length, lessons: map }
