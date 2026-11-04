import json

import pytest

import ic_class_profile as profile


@pytest.mark.parametrize(('description', 'expected'), [
    ('RISC-V CPU with an instruction fetch bus, program counter, register file '
     'and load/store ALU. SECDED ECC protects instruction memory. Verification '
     'checks memory integrity using a testbench signature address.', 'processor_cpu'),
    ('APB subordinate with a memory-mapped register map, register bank, '
     'read-only status register and address decode. SECDED ECC protects '
     'the registers. Verification checks corrected data.', 'bus_peripheral'),
])
def test_error_correcting_ecc_does_not_select_crypto(tmp_path, description, expected):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'description': description}))
    assert profile.infer_ic_class_uncached(tmp_path)['ic_class'] == expected


@pytest.mark.parametrize('description', [
    'ECC public-key signature verification accelerator.',
    'ECC accelerator with key material for signature verification.',
])
def test_cryptographic_ecc_keeps_its_class(tmp_path, description):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'description': description}))
    assert profile.infer_ic_class_uncached(tmp_path)['ic_class'] == 'crypto_accelerator'
