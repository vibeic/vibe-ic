  priority: 0,
  tags: %w[all density]
) do
  chip_area = extent.sized(0.0).area

  # Rule PL.8: Poly2 coverage over the entire die shall be 14%.
  ## Dummy poly2 lines must be added to meet the minimum poly2 density requirement.
  logger.info('Executing rule PL.8')
  if (poly2.area / chip_area) * 100 < 14
    extent.output('PL.8',
                  'PL.8 : Poly2 coverage over the entire die shall be 14%.
                  Dummy poly2 lines must be added to meet the minimum poly2 density requirement. : 14%')
  end

  # Rule M1.4: Metal1 coverage over the entire die shall be >30%
  ## (Refer to section 13.0 for Dummy Metal fill guidelines.
  ## Customer needs to ensure enough dummy metal to satisfy Metal1 coverage)
  logger.info('Executing rule M1.4')
  if (metal1.area / chip_area) * 100 < 30
    extent.output('M1.4',
                  'M1.4 : Metal1 coverage over the entire die shall be >30%
                  (Refer to section 13.0 for Dummy Metal fill guidelines.
                   Customer needs to ensure enough dummy metal to satisfy Metal1 coverage) : 30%')
  end

  # Rule M2.4: Metal2 coverage over the entire die shall be >30%
  ## (Refer to section 13.0 for Dummy Metal fill guidelines.
  ## Customer needs to ensure enough dummy metal to satisfy Metal2 coverage)
  logger.info('Executing rule M2.4')
  if (metal2.area / chip_area) * 100 < 30
    extent.output('M2.4',
                  'M2.4 : Metal2 coverage over the entire die shall be >30%
                  (Refer to section 13.0 for Dummy Metal fill guidelines.
                   Customer needs to ensure enough dummy metal to satisfy Metal2 coverage) : 30%')
  end

  if ctx.metal_level_numerical >= 3
    # Rule M3.4: metal3 coverage over the entire die shall be >30%
    ## (Refer to section 13.0 for Dummy Metal fill guidelines.
    ## Customer needs to ensure enough dummy metal to satisfy metal3 coverage)
    logger.info('Executing rule M3.4')
    if (metal3.area / chip_area) * 100 < 30
      extent.output('M3.4',
                    'M3.4 : metal3 coverage over the entire die shall be >30%
                      (Refer to section 13.0 for Dummy Metal fill guidelines.
                      Customer needs to ensure enough dummy metal to satisfy metal3 coverage) : 30%')
    end
  end

  if ctx.metal_level_numerical >= 4
    # Rule M4.4: metal4 coverage over the entire die shall be >30%
