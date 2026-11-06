"""Native LEF roles bound the tap-spacing population on the fallback path."""
from pathlib import Path








def test_real_corner_fixture_declares_the_excluded_class():
    from _pad_ring import parse_lef_macro_classes
    data = (Path(__file__).parent / 'fixtures/perc_native_corner.lef').read_text()
    assert list(parse_lef_macro_classes(data).values()) == ['ENDCAP BOTTOMLEFT']
