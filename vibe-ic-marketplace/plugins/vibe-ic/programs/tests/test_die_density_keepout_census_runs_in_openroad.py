"""The density top-up keep-out census is EXECUTED by real OpenROAD/OpenDB.

WHY THIS FILE EXISTS. Every control in test_die_density_finish.py mocks
`run_container` and writes canned `BOX PAD ...` lines, so the Tcl that decides
which placed instances are protected, and the bbox it reads, never runs there.
Review wave 57 replaced that Tcl's classification with a bare `continue` (an
empty protected set: no pad boxes, no edge band, top-up promoted) and 112 of
those tests still passed.

Here the branch's own `_placed_keepout_boxes` writes its own Tcl and its own
`docker run`, and OpenDB reads synthetic LEFs and a one-line-COMPONENTS DEF.
Only the fill ENGINE (a separate container) is faked, and only for its file
writes. Nothing about the census is canned.

Route, the way `_tcl_walk` resolves tclsh: the program's own `docker run` of
the image named by `VIBEIC_EDA_CONTAINER` (else the plugin's pinned image);
otherwise `openroad` on PATH (inside the image, where docker is absent), with
the command's `-v host:guest` mounts applied to the script's paths. If neither
route exists on this host the test reports NOT_VERIFIED (owner R-0927: a tool
or image the host lacks is reported, in the run, as not verified -- never a
FAIL), naming the host and every route tried; a docker probe that never
answered says so rather than claiming the image is absent. Where a route
exists every assertion runs exactly as before.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import librelane_fill_dfm as fill                              # noqa: E402
from librelane_contract import Refusal                         # noqa: E402
import _tool_probes as _nv                                # noqa: E402
import _outcome_states as states                               # noqa: E402

PDK = 'processA'

TECH_LEF = '''VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS
  DATABASE MICRONS 2000 ;
END UNITS
MANUFACTURINGGRID 0.005 ;
SITE coreSite
  CLASS CORE ;
  SYMMETRY Y ;
  SIZE 0.5 BY 5 ;
END coreSite
LAYER Metal1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.5 ;
  WIDTH 0.2 ;
  SPACING 0.3 ;
END Metal1
END LIBRARY
'''


def _macro(name, cls, w, h, site=None):
    return (f'MACRO {name}\n' + (f' CLASS {cls} ;\n' if cls else '')
            + f' ORIGIN 0 0 ;\n SIZE {w} BY {h} ;\n'
            + (f' SITE {site} ;\n' if site else '') + f'END {name}\n')


def _lib(*macros):
    return 'VERSION 5.8 ;\n' + ''.join(macros) + 'END LIBRARY\n'


#: (instance, master, x, y, orient) in DEF units (1000/um, LEF DBU is 2000).
PLACED = [
    ('PAD_S', 'PADCELL', 100000, 0, 'N'),
    ('PAD_W', 'PADCELL', 0, 100000, 'W'),
    ('PAD_E', 'PADCELL', 170000, 50000, 'FS'),
    ('PAD_IN', 'PADCELL', 80000, 80000, 'N'),        # a pad inside the core
    ('MAC0', 'BLOCKCELL', 30000, 140000, 'FS'),
    ('CORE0', 'CORECELL', 60000, 60000, 'N'),        # never protected
    ('ECAP0', 'ENDCAPCELL', 61000, 60000, 'N'),      # std-cell endcap: never
]

#: What OpenDB must report, in microns: getBBox honours orientation and DBU.
EXPECTED_UM = [
    ('BLOCK', 'BLOCKCELL', (30.0, 140.0, 70.0, 165.0)),
    ('PAD', 'PADCELL', (0.0, 100.0, 30.0, 120.0)),   # W: 20x30 -> 30x20
    ('PAD', 'PADCELL', (80.0, 80.0, 100.0, 110.0)),
    ('PAD', 'PADCELL', (100.0, 0.0, 120.0, 30.0)),
    ('PAD', 'PADCELL', (170.0, 50.0, 190.0, 80.0)),
]


def _stage(tmp_path, placed=PLACED, pad_macros=()):
    pdk_root = tmp_path / 'pdks'
    tech = pdk_root / PDK / 'tech'
    tech.mkdir(parents=True)
    (tech / 'tech.tlef').write_text(TECH_LEF)
    (tech / 'cells.lef').write_text(_lib(
        _macro('CORECELL', 'CORE', 1, 5, 'coreSite'),
        _macro('ENDCAPCELL', 'ENDCAP PRE', 0.5, 5, 'coreSite')))
    (tech / 'pad.lef').write_text(_lib(
        _macro('PADCELL', 'PAD INOUT', 20, 30), *pad_macros))
    project = tmp_path / 'project'
    macros = project / 'macros'
    macros.mkdir(parents=True)
    (macros / 'block.lef').write_text(_lib(_macro('BLOCKCELL', 'BLOCK', 40, 25)))
    routed = project / 'phase3/stage3/pnr/routed.def'
    routed.parent.mkdir(parents=True)
    line = ' '.join(f'- {n} {m} + FIXED ( {x} {y} ) {o} ;'
                    for n, m, x, y, o in placed)
    routed.write_text(
        'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\nDESIGN top ;\n'
        'UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 200000 200000 ) ;\n'
        f'COMPONENTS {len(placed)} ; {line} END COMPONENTS\nEND DESIGN\n')
    cfg = {'TECH_LEFS': {'nom_*': f'/pdk/{PDK}/tech/tech.tlef'},
           'CELL_LEFS': [f'/pdk/{PDK}/tech/cells.lef'],
           'PAD_LEFS': [f'/pdk/{PDK}/tech/pad.lef'],
           'MACROS': {'blk': {'lef': [str(macros / 'block.lef')],
                              'halo_um': 1.0}},
           'DESIGN_NAME': 'top', 'DIE_AREA': [0, 0, 200, 200]}
    return project, pdk_root, cfg


def _image():
    container = os.environ.get('VIBEIC_EDA_CONTAINER')
    if container and shutil.which('docker'):
        r = subprocess.run(['docker', 'inspect', '--format',
                            '{{.Config.Image}}', container],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    import _eda_pin                                            # noqa: PLC0415
    return _eda_pin.image_reference()


def _route(monkeypatch):
    """Return the image to hand the program; install the in-image route when
    only a local `openroad` exists. Report NOT_VERIFIED when neither exists.

    Only the two ways the image question goes unanswered are caught -- no held
    identity (`ImageNotResolvable`, incl. `ImageNotHeld`) and a `docker
    inspect` that timed out -- where a bare `except Exception` used to fold
    every error, a timeout included, into "not held". The held check goes
    through `not_verified_tier.probe`, which keeps PRESENT / ABSENT / UNANSWERED
    apart."""
    import _eda_pin                                            # noqa: PLC0415
    tried = []
    unanswered = ''
    if shutil.which('docker'):
        try:
            image = _image()
        except _eda_pin.ImageNotResolvable as exc:
            tried.append(f'no held vibeic-eda image ({exc})')
        except subprocess.TimeoutExpired as exc:
            unanswered = (f"`{' '.join(map(str, exc.cmd))}` did not answer in "
                          f"{exc.timeout}s")
            tried.append(unanswered)
        else:
            state, detail = _nv.probe(['docker', 'image', 'inspect', image])
            if state == _nv.PROBE_PRESENT:
                return image, 'docker-run'
            if state == _nv.PROBE_UNANSWERED:
                unanswered = detail
            tried.append(f'docker image {image!r} not held ({detail})')
    else:
        tried.append("docker (shutil.which('docker') -> None)")
    local = shutil.which('openroad')
    if local:
        real = fill.run_container

        def in_image(cmd, **kwargs):
            if 'openroad' not in cmd:
                return real(cmd, **kwargs)
            mounts = [cmd[i + 1].split(':')[:2] for i, a in enumerate(cmd)
                      if a == '-v']
            script = Path(cmd[-1])
            text = script.read_text()
            for host, guest in mounts:
                if host != guest:
                    text = re.sub(r'\{' + re.escape(guest) + r'(?=[/}])',
                                  '{' + host, text)
            local_script = script.with_suffix('.local.tcl')
            local_script.write_text(text)
            return subprocess.run([local, '-exit', str(local_script)],
                                  capture_output=True, text=True, timeout=600)

        monkeypatch.setattr(fill, 'run_container', in_image)
        return 'in-image', f'local:{local}'
    tried.append("host PATH (shutil.which('openroad') -> None)")
    where = f'host {states.host()}'
    pytest.skip(_nv.probe_skip_reason(
        _nv.PROBE_UNANSWERED if unanswered else _nv.PROBE_ABSENT,
        f'{where}: {unanswered}',
        f'{where}: the OpenDB keep-out census needs OpenROAD and neither '
        f'route exists here -- ' + '; '.join(tried),
        f'pull the pinned vibeic-eda image on this host, or run inside it '
        f'with {states.IMAGE_HARNESS} (openroad on PATH)'))


def _um(placed):
    dbu = placed['dbu']
    return sorted((kind, master, tuple(c / dbu for c in box))
                  for kind, master, box in placed['boxes'])


def test_opendb_census_reads_every_placed_pad_and_block_footprint(tmp_path,
                                                                 monkeypatch):
    image, _ = _route(monkeypatch)
    project, pdk_root, cfg = _stage(tmp_path)
    placed = fill._placed_keepout_boxes(project, image, pdk_root, PDK, cfg,
                                        project / 'phase3/librelane/census')
    assert placed['dbu'] == 2000, 'the block DBU is the LEF database unit'
    assert placed['total'] == len(PLACED)
    # The compact one-line COMPONENTS section, the interior pad, the W and FS
    # orientations and the FS block all arrive with their exact footprints;
    # the CORE cell and the std-cell ENDCAP are not protected.
    assert _um(placed) == EXPECTED_UM


def test_top_up_masks_the_real_census_and_bands_the_pad_ring(tmp_path,
                                                             monkeypatch):
    image, _ = _route(monkeypatch)
    project, pdk_root, cfg = _stage(tmp_path)
    (pdk_root / PDK / 'tech/layers.map').write_text('Metal1 NET 61 0\n')
    (pdk_root / PDK / 'tech/density.drc').write_text(
        'chip_area = extent.sized(0.0).area\n'
        'extract_single_layer_from_design.call(:metal1_drawn, 61, 0)\n'
        'extract_single_layer_from_design.call(:metal1_dummy, 61, 7)\n'
        '# Rule M1.4: Metal1 coverage over the entire die shall be >30%\n'
        'if (metal1.area / chip_area) * 100 < 30\n'
        " extent.output('M1.4', '30%')\nend\n")
    cfg.update({'KLAYOUT_DEF_LAYER_MAP': f'/pdk/{PDK}/tech/layers.map',
                'KLAYOUT_DENSITY_RUNSET': f'/pdk/{PDK}/tech/density.drc'})
    config = tmp_path / 'density.json'
    config.write_text(json.dumps(cfg))
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    monkeypatch.setattr(fill, 'declaration_config', lambda project: (
        {'CORE_AREA': [35, 32, 165, 168]}, {'CORE_AREA': 'reviewed core'}))
    census = fill.run_container

    def engine_or_census(cmd, **kwargs):
        if 'openroad' in cmd:
            return census(cmd, **kwargs)
        # The fill ENGINE is a different tool: fake only its file writes.
        Path(cmd[cmd.index('--out') + 1]).write_bytes(b'protected fill')
        Path(cmd[cmd.index('--report') + 1]).write_text(json.dumps(
            {'verdict': 'PASS', 'layers': [{'name': 'metal1',
                                           'density_before': .28,
                                           'density_after': .34}]}))
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(fill, 'run_container', engine_or_census)
    result = fill.top_up_density(project, image, pdk_root, PDK, gds, config,
                                 '37-real-census')
    derived = json.loads(Path(result['config']).read_text())
    spacing = 0.3
    assert derived['keepout_boxes_um'] == sorted(
        [x1 - spacing, y1 - spacing, x2 + spacing, y2 + spacing]
        for _, _, (x1, y1, x2, y2) in EXPECTED_UM)
    assert derived['keepout_edge_um'] == 35
    assert derived['_derivation']['pad_ring_exclusion']['placed_pad_masters'] \
        == ['PADCELL']
    assert derived['_derivation']['placed_instance_keepout'][
        'protected_count'] == len(EXPECTED_UM)


@pytest.mark.parametrize('bad, reason', [
    (('PAD_X', 'NO_SUCH_MASTER', 100000, 0, 'N'), 'NO_SUCH_MASTER'),
    (('PAD_U', 'PADCELL', 100000, 0, 'N'), 'unplaced protected instance: PAD_U'),
], ids=['unknown-master', 'unplaced-pad'])
def test_a_refused_census_keeps_openroads_reason_in_the_log_it_names(
        tmp_path, monkeypatch, bad, reason):
    image, _ = _route(monkeypatch)
    project, pdk_root, cfg = _stage(tmp_path, placed=[*PLACED[1:], bad])
    if bad[0] == 'PAD_U':
        routed = project / 'phase3/stage3/pnr/routed.def'
        routed.write_text(routed.read_text().replace(
            '- PAD_U PADCELL + FIXED ( 100000 0 ) N ;', '- PAD_U PADCELL ;'))
    with pytest.raises(Refusal, match='LL_DENSITY_FILL_PLACEMENT_UNREADABLE') \
            as refused:
        fill._placed_keepout_boxes(project, image, pdk_root, PDK, cfg,
                                   project / 'phase3/librelane/census')
    log = project / 'phase3/librelane/census/placed_keepouts.log'
    assert str(log) in str(refused.value)
    assert log.is_file(), 'the refusal names a log that was never written'
    assert reason in log.read_text()


def test_a_failed_fill_engine_keeps_its_reason_in_fill_log(tmp_path,
                                                          monkeypatch):
    image, _ = _route(monkeypatch)
    project, pdk_root, cfg = _stage(tmp_path)
    (pdk_root / PDK / 'tech/layers.map').write_text('Metal1 NET 61 0\n')
    (pdk_root / PDK / 'tech/density.drc').write_text(
        'chip_area = extent.sized(0.0).area\n'
        'extract_single_layer_from_design.call(:metal1_drawn, 61, 0)\n'
        'extract_single_layer_from_design.call(:metal1_dummy, 61, 7)\n'
        '# Rule M1.4: Metal1 coverage over the entire die shall be >30%\n'
        'if (metal1.area / chip_area) * 100 < 30\n'
        " extent.output('M1.4', '30%')\nend\n")
    cfg.update({'KLAYOUT_DEF_LAYER_MAP': f'/pdk/{PDK}/tech/layers.map',
                'KLAYOUT_DENSITY_RUNSET': f'/pdk/{PDK}/tech/density.drc'})
    config = tmp_path / 'density.json'
    config.write_text(json.dumps(cfg))
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    monkeypatch.setattr(fill, 'declaration_config', lambda project: (
        {'CORE_AREA': [35, 32, 165, 168]}, {'CORE_AREA': 'reviewed core'}))
    census = fill.run_container

    def engine_or_census(cmd, **kwargs):
        if 'openroad' in cmd:
            return census(cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 1, 'engine started\n',
                                           'engine: layer 61/7 unwritable\n')

    monkeypatch.setattr(fill, 'run_container', engine_or_census)
    with pytest.raises(Refusal, match='LL_DENSITY_FILL_FAILED') as refused:
        fill.top_up_density(project, image, pdk_root, PDK, gds, config,
                            '37-engine-fails')
    log = project / 'phase3/librelane/37-engine-fails/fill.log'
    assert str(log) in str(refused.value)
    assert 'layer 61/7 unwritable' in log.read_text()


def test_every_master_a_pad_or_macro_view_declares_is_protected_whatever_its_class(
        tmp_path, monkeypatch):
    """Review wave 57: OpenDB classifies by LEF CLASS, so a PAD_LEFS master
    with no CLASS, or a corner declared CLASS ENDCAP, or a macro view's RING,
    was read as an unprotected core cell and filled over. The view that
    declared the master names its role; the std-cell ENDCAP still does not."""
    image, _ = _route(monkeypatch)
    placed = [*PLACED,
              ('NC0', 'NOCLASSPAD', 140000, 160000, 'N'),
              ('CORNER0', 'CORNERCELL', 0, 0, 'N'),
              ('RING0', 'RINGCELL', 150000, 20000, 'N')]
    project, pdk_root, cfg = _stage(tmp_path, placed=placed, pad_macros=(
        _macro('NOCLASSPAD', None, 10, 10),
        _macro('CORNERCELL', 'ENDCAP BOTTOMLEFT', 30, 30)))
    block = project / 'macros/block.lef'
    block.write_text(block.read_text().replace(
        'END LIBRARY', _macro('RINGCELL', 'RING', 12, 6) + 'END LIBRARY'))
    census = fill._placed_keepout_boxes(project, image, pdk_root, PDK, cfg,
                                        project / 'phase3/librelane/census')
    assert census['total'] == len(placed)
    assert _um(census) == sorted(EXPECTED_UM + [
        ('BLOCK', 'RINGCELL', (150.0, 20.0, 162.0, 26.0)),
        ('PAD', 'CORNERCELL', (0.0, 0.0, 30.0, 30.0)),
        ('PAD', 'NOCLASSPAD', (140.0, 160.0, 150.0, 170.0)),
    ])


@pytest.mark.parametrize('text, code, reason', [
    (None, 'LL_DENSITY_FILL_CORE_UNDECLARED', 'FileNotFoundError'),
    ('{"answers": ', 'LL_DENSITY_FILL_CORE_UNDECLARED', 'JSONDecodeError'),
    ('[]', 'LL_INVALID_JSON_OBJECT', ''),
    ('{"answers": {}}', 'LL_DENSITY_FILL_CORE_UNDECLARED', 'core_area_um'),
], ids=['absent', 'malformed', 'not-an-object', 'no-core'])
def test_a_placed_pad_without_a_readable_core_names_the_declaration(
        tmp_path, monkeypatch, text, code, reason):
    """Review wave 57: a declaration error was swallowed into `{}` and the
    refusal cited the density step config, which is not where CORE_AREA
    comes from. It must name the tape-out declaration and the reader's reason
    (a declaration Refusal keeps its own code)."""
    from librelane_contract import DECLARATION_REL           # noqa: PLC0415
    image, _ = _route(monkeypatch)
    project, pdk_root, cfg = _stage(tmp_path)
    (pdk_root / PDK / 'tech/layers.map').write_text('Metal1 NET 61 0\n')
    (pdk_root / PDK / 'tech/density.drc').write_text(
        'extract_single_layer_from_design.call(:metal1_drawn, 61, 0)\n'
        'extract_single_layer_from_design.call(:metal1_dummy, 61, 7)\n'
        '# Rule M1.4: Metal1 coverage over the entire die shall be >30%\n'
        'if (metal1.area / chip_area) * 100 < 30\n'
        " extent.output('M1.4', '30%')\nend\n")
    cfg.update({'KLAYOUT_DEF_LAYER_MAP': f'/pdk/{PDK}/tech/layers.map',
                'KLAYOUT_DENSITY_RUNSET': f'/pdk/{PDK}/tech/density.drc'})
    config = tmp_path / 'density.json'
    config.write_text(json.dumps(cfg))
    declaration = project / DECLARATION_REL
    if text is not None:
        declaration.parent.mkdir(parents=True)
        declaration.write_text(text)
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    with pytest.raises(Refusal, match=code) as refused:
        fill.top_up_density(project, image, pdk_root, PDK, gds, config,
                            '37-core-source')
    assert str(declaration) in str(refused.value)
    assert reason in str(refused.value)
    assert str(config) not in str(refused.value)
