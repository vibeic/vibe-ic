def dummy_metal_rules(idx:)
  #================================================
  #----------------- Dummy METAL ------------------
  #================================================

  metal_dummy = ctx[METAL_MAP_DUMMY[idx][:metal_dummy]]
  metal_drawn = ctx[METAL_MAP_DUMMY[idx][:metal_drawn]]

  # Rule DM.2b: Min Dummy metal line space (for DRC): 0.98
  logger.info("Executing rule DM#{idx}.2b")
  dm_2b_l1 = metal_dummy.space(0.98.um, euclidian)
  dm_2b_l1.output("DM#{idx}.2b", "DM#{idx}.2b : Min Dummy metal line space (for DRC): 0.98")
  dm_2b_l1.forget

  # Rule DM.3: Minimum space between dummy metal and circuit Metal line: 2
  logger.info("Executing rule DM#{idx}.3")
  dm_3_l1 = metal_dummy.separation(metal_drawn, 2.um, euclidian)
  dm_3_l1.output("DM#{idx}.3", "DM#{idx}.3 : Minimum space between dummy metal and circuit Metal line: 2")
  dm_3_l1.forget

  # if DUMMY_SUB_PREV
  #
  #  # Rule DM.4_DM.6: Dummy Metal space (no overlap) to Subsequent Metal layer: 1
  #  logger.info("Executing rule DM#{idx}.4_DM#{idx}.6")
  #  dm_4_dm_6_l1 = metal_dummy.separation(metal2_drawn, 1.um, euclidian)
  #  dm_4_dm_6_l1.output("DM#{idx}.4_DM#{idx}.6", "DM#{idx}.4_DM#{idx}.6 : Dummy Metal space (no overlap) to Subsequent Metal layer: 1")
  #  dm_4_dm_6_l1.forget
  #
  #  # Rule DM.5_DM.7: Dummy Metal space (no overlap) to Previous Metal layer: 1
  #  logger.info("Executing rule DM#{idx}.5_DM#{idx}.7")
  #  dm_5_dm_7_l1 = metal_dummy.separation(poly2, 1.um, euclidian)
  #  dm_5_dm_7_l1.output("DM#{idx}.5_DM#{idx}.7", "DM#{idx}.5_DM#{idx}.7 : Dummy Metal space (no overlap) to Previous Metal layer: 1")
  #  dm_5_dm_7_l1.forget
  #
  # end

  # Rule DM.8: Minimum space between dummy metal and FuseTop, POLYFUSE, FUSEWINDOW_D, PMNDMY, MTPMK, OTP_MK: 6
  logger.info("Executing rule DM#{idx}.8")
  dm_8_l1 = metal_dummy.separation(fusetop, 6.um, euclidian)
  dm_8_l1 += metal_dummy.separation(polyfuse, 6.um, euclidian)
  dm_8_l1 += metal_dummy.separation(fusewindow_d, 6.um, euclidian)
  dm_8_l1 += metal_dummy.separation(pmndmy, 6.um, euclidian)
  dm_8_l1 += metal_dummy.separation(mtpmark, 6.um, euclidian)
  dm_8_l1 += metal_dummy.separation(otp_mk, 6.um, euclidian)
  dm_8_l1.output("DM#{idx}.8",
                 "DM#{idx}.8 : Minimum space between dummy metal and FuseTop, POLYFUSE, FUSEWINDOW_D, PMNDMY, MTPMK, OTP_MK: 6")
  dm_8_l1.forget
