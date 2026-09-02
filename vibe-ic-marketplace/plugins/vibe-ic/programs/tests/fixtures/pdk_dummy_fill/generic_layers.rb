# VERBATIM excerpts of gf180mcuD's own KLayout deck (image
# ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e057..., PDK tree sha256 8342c17b...),
# reduced to the lines pdk_dummy_fill_spec parses. No value altered.
      extract_single_layer_from_design.call(:fusetop, 75, 0)
      extract_single_layer_from_design.call(:fusewindow_d, 96, 1)
      extract_single_layer_from_design.call(:polyfuse, 220, 0)
      extract_single_layer_from_design.call(:otp_mk, 173, 5)
      extract_single_layer_from_design.call(:pmndmy, 152, 5)
      extract_single_layer_from_design.call(:metal1_drawn, 34, 0)
      extract_single_layer_from_design.call(:metal1_dummy, 34, 4)
      extract_single_layer_from_design.call(:metal2_drawn, 36, 0)
      extract_single_layer_from_design.call(:metal2_dummy, 36, 4)
        extract_single_layer_from_design.call(:metal3_drawn, 42, 0)
        extract_single_layer_from_design.call(:metal3_dummy, 42, 4)
        extract_single_layer_from_design.call(:metal4_drawn, 46, 0)
        extract_single_layer_from_design.call(:metal4_dummy, 46, 4)
        extract_single_layer_from_design.call(:metal5_drawn, 81, 0)
        extract_single_layer_from_design.call(:metal5_dummy, 81, 4)

    METAL_NAMES = {
      1 => { metal_drawn: :metal1_drawn, metal_dummy: :metal1_dummy, metal_result: :metal1 },
      2 => { metal_drawn: :metal2_drawn, metal_dummy: :metal2_dummy, metal_result: :metal2 },
      3 => { metal_drawn: :metal3_drawn, metal_dummy: :metal3_dummy, metal_result: :metal3 },
      4 => { metal_drawn: :metal4_drawn, metal_dummy: :metal4_dummy, metal_result: :metal4 },
      5 => { metal_drawn: :metal5_drawn, metal_dummy: :metal5_dummy, metal_result: :metal5 },
      6 => { metal_drawn: :metaltop_drawn, metal_dummy: :metaltop_dummy, metal_result: :metaltop }
    }.freeze

        ctx.register_layer(names[:metal_result]) { ctx[names[:metal_drawn]] + ctx[names[:metal_dummy]] }
