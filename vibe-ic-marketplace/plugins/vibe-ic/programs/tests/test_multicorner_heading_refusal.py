from test_multicorner_signoff_scope import emit


def test_library_example_heading_cannot_create_requirement(tmp_path):
    _,rows=emit(tmp_path,'# SDC\n## Library examples\nMulti-corner sign-off: each library must pass SS, TT and FF corners.\n')
    assert rows['STA']['stated'] is False and rows['STA']['corners']==[]
