"""A project's staged models must not hide the declared family's installed kit from die rows."""
import hashlib

import pytest

import analog_pdk_availability as resolver
import declared_pdk_is_the_pdk_used_check as declared

DEF_TEXT = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN neutral_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 1000 1000 ) ;
PINS 1 ;
 - a + NET a + DIRECTION INPUT ;
END PINS
END DESIGN
"""


def _ref(project, relative, text):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {'path': relative, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
















@pytest.fixture
def project(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    for relative in ('input/pdk/models/neutral.lib', 'input/pdk/klayout/tech/drc/neutral.drc',
                     'input/pdk/klayout/tech/lvs/neutral.lvs'):
        _ref(project, relative, '* staged\n')
    _ref(project, 'input/project.json', '{}')
    monkeypatch.setattr(declared, 'declared_target', lambda p: ('neutral', 'input/project.json:pdk'))
    return project




def test_project_rung_still_owns_project_scoped_resolution(project):
    assert resolver.resolve_pdk('neutral', project=project)['source'] == 'project_custom_pdk'
