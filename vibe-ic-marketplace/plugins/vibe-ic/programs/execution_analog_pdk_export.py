"""Export a bounded, resolver-declared container PDK population to a project.

This is an input copier, not an execution authority or a native-verdict gate.
Only paths named by ``analog_pdk_availability.resolve_pdk`` are seeds; the
container follows literal file references reachable from those seeds.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import ctypes
from typing import Mapping

import execution_modes as em
import librelane_contract as lc
import _docker_memory as _dmem


SCHEMA = "vibeic.analog-pdk-export.v1"
OUTPUT_BASE = Path("reports/execution/analog-pdk-export")

# Executed only in the pinned EDA image, with no network and the project-owned
# scratch directory as its sole writable mount. The seed list is resolver data,
# not a user-authored digest manifest. Never print file contents.
_CONTAINER_COPY = r'''import hashlib,json,os,pathlib,re,shlex,stat,sys
logical_path=pathlib.Path(sys.argv[1]); out=pathlib.Path(sys.argv[2]); request=json.loads(sys.argv[3])
guest_root=pathlib.PurePosixPath(request['pdk_root'])
max_files,max_bytes=request['max_files'],request['max_bytes']
def bad(code):
    print(json.dumps({'status':'NOT_MEASURED','reason':code},sort_keys=True)); raise SystemExit(0)
def under(path, base):
    try: return path.relative_to(base)
    except ValueError: bad('PDK_PATH_ESCAPE')
def measured_root_binding():
    if not guest_root.is_absolute() or '..' in guest_root.parts:
        bad('PDK_ROOT_ALIAS_UNBOUND')
    authority=logical_path.parent
    authority_guest=guest_root.parent
    cursor=pathlib.Path('/')
    for part in authority.parts[1:]:
        cursor=cursor/part
        try: mode=cursor.lstat().st_mode
        except OSError: bad('PDK_ROOT_AUTHORITY_UNAVAILABLE')
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode): bad('PDK_ROOT_AUTHORITY_REFUSED')
    try: leaf_mode=logical_path.lstat().st_mode
    except OSError: bad('PDK_ROOT_UNAVAILABLE')
    link_text=os.readlink(logical_path) if stat.S_ISLNK(leaf_mode) else None
    if link_text is None and not stat.S_ISDIR(leaf_mode): bad('PDK_ROOT_UNAVAILABLE')
    if link_text is not None:
        raw_target=pathlib.PurePosixPath(link_text)
        lexical_physical=(raw_target if raw_target.is_absolute() else
                          pathlib.PurePosixPath(os.path.normpath(str(authority/raw_target))))
        if (not lexical_physical.is_absolute() or '..' in lexical_physical.parts
                or not lexical_physical.is_relative_to(authority)):
            bad('PDK_ROOT_ALIAS_ESCAPE')
        lexical_relative=lexical_physical.relative_to(authority)
        lexical_guest=authority_guest.joinpath(*lexical_relative.parts)
    try: canonical=logical_path.resolve(strict=True)
    except (OSError,RuntimeError): bad('PDK_ROOT_ALIAS_REFUSED')
    try: canonical_relative=canonical.relative_to(authority)
    except ValueError: bad('PDK_ROOT_ALIAS_ESCAPE')
    canonical_guest=authority_guest.joinpath(*canonical_relative.parts)
    if (not canonical.is_dir() or not canonical_guest.is_relative_to(authority_guest)
            or canonical_guest.name!=guest_root.name):
        bad('PDK_ROOT_ALIAS_ESCAPE')
    if link_text is None and canonical!=logical_path:
        bad('PDK_ROOT_ALIAS_UNBOUND')
    if link_text is not None and lexical_guest!=canonical_guest:
        bad('PDK_ROOT_ALIAS_CHANGED')
    cursor=pathlib.Path('/')
    for index,part in enumerate(canonical.parts[1:]):
        cursor=cursor/part
        try: mode=cursor.lstat().st_mode
        except OSError: bad('PDK_ROOT_UNAVAILABLE')
        if stat.S_ISLNK(mode) or (index<len(canonical.parts[1:])-1 and not stat.S_ISDIR(mode)):
            bad('PDK_ROOT_ALIAS_REFUSED')
    return {'logical_root':guest_root.as_posix(),'link_text':link_text,
            'canonical_root':canonical_guest.as_posix()}, canonical
if str(guest_root.parent)!='/foss/pdks': bad('PDK_ROOT_AUTHORITY_REFUSED')
root_binding,root=measured_root_binding()
def checked(guest):
    try: rel=under(guest,guest_root)
    except Exception: raise
    cursor=root
    for part in ('.',*rel.parts):
        if part in ('','.') : continue
        cursor=cursor/part
        try: mode=cursor.lstat().st_mode
        except OSError: bad('PDK_FILE_MISSING')
        if stat.S_ISLNK(mode): bad('PDK_SYMLINK_REFUSED')
    if not stat.S_ISREG(cursor.lstat().st_mode): bad('PDK_NONREGULAR_REFUSED')
    return rel,cursor
def reject_existing_symlink_prefix(guest):
    rel=under(guest,guest_root); cursor=root
    for part in rel.parts:
        cursor=cursor/part
        try: mode=cursor.lstat().st_mode
        except (FileNotFoundError,NotADirectoryError): return
        if stat.S_ISLNK(mode): bad('PDK_SYMLINK_REFUSED')
def resolve_include(guest, name):
    child=pathlib.PurePosixPath(name)
    if child.is_absolute():
        if not child.is_relative_to(guest_root): bad('PDK_PATH_ESCAPE')
        cursor=guest_root; parts=child.relative_to(guest_root).parts
    else:
        cursor=guest.parent; parts=child.parts
    parts=tuple(part for part in parts if part not in ('','/','.'))
    for index,part in enumerate(parts):
        if part=='..':
            if cursor==guest_root: bad('PDK_PATH_ESCAPE')
            cursor=cursor.parent
            continue
        cursor=cursor/part
        # Existing symlinks redirect real consumers before a later '..'.
        # Missing or non-directory prefixes are not rejected here: accepted
        # consumers may lexically erase them before opening the final target.
        reject_existing_symlink_prefix(cursor)
    return cursor
def command_parts(line, slash_comments=True):
    parts=[]; start=0; quote=None; escaped=False
    for i,c in enumerate(line):
        if escaped: escaped=False; continue
        if c=='\\': escaped=True; continue
        if quote:
            if c==quote: quote=None
            continue
        if c in ('"',"'"): quote=c; continue
        if c=='#' or (slash_comments and line[i:i+2]=='//'):
            parts.append(line[start:i]); return parts
        if c==';': parts.append(line[start:i]); start=i+1
    parts.append(line[start:]); return parts
def includes(path, raw, config_mode=False):
    suffix=path.suffix.lower(); found=[]
    klayout=suffix in ('.drc','.lydrc','.lvs','.lylvs')
    slash_comments=suffix not in ('.tcl','.magic','.tech')
    for line in raw.decode('utf-8',errors='replace').splitlines():
        statements=command_parts(line,slash_comments=slash_comments) if config_mode else [line]
        for statement in statements:
            s=statement.strip()
            if not s or s.startswith(('*','#','//',';')): continue
            if klayout and re.fullmatch(r'source\s*\(\s*\$input(?:\s*,\s*\$top_cell)?\s*\)\s*;?',s):
                # KLayout's source() supplies the layout input (and optional
                # top cell); it is not a PDK include edge.
                continue
            if klayout and re.match(r'^source\s*\(',s): bad('PDK_DYNAMIC_INCLUDE_REFUSED')
            if klayout and re.match(r'^(require|require_relative|load)\b',s):
                ruby_import=re.fullmatch(
                    r"(?:require|require_relative|load)\s*(?:\(\s*(?:\"([^\"\n]+)\"|'([^'\n]+)')\s*\)|(?:\"([^\"\n]+)\"|'([^'\n]+)'))\s*;?",s)
                if not ruby_import: bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                import_kind=re.match(r'^(require|require_relative|load)\b',s).group(1)
                child=next(value for value in ruby_import.groups() if value is not None)
                if any(x in child for x in ('$','`','*','?','[',']','{','}')): bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                if (import_kind=='require' and child not in ('.','..')
                        and not child.startswith('.') and '/' not in child and '\\' not in child):
                    # Bare Ruby require names resolve in the pinned runtime's
                    # $LOAD_PATH and are not PDK-relative file edges.
                    continue
                found.append(child); continue
            spice=suffix in ('.sp','.spi','.spice','.cir','.lib','.mod','.pm')
            tcl=suffix in ('.tcl','.magic','.tech') or config_mode
            verilog=suffix in ('.v','.vh','.sv','.svh')
            if spice and re.match(r'^\.(include|inc|lib)\b',s,re.I):
                op,tail=s[1:].split(None,1); tail=tail.strip()
                if op.lower()=='lib' and not tail.startswith(('"',"'")) and '/' not in tail and '\\\\' not in tail and not tail.startswith('.'):
                    continue
                try: words=shlex.split(tail,comments=True,posix=True)
                except ValueError: bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                if not words or len(words)>2 or any(x in words[0] for x in ('$','`','*','?','[',']','{','}')): bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                if op.lower()=='lib' and len(words)>1 and any(x in words[1] for x in ('$','`','*','?')): bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                found.append(words[0]); continue
            if tcl and re.match(r'^(source|load)\b',s,re.I):
                try: words=shlex.split(s,comments=True,posix=True)
                except ValueError: bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                if len(words)!=2 or any(x in words[1] for x in ('$','`','*','?','[',']','{','}')): bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                found.append(words[1]); continue
            if verilog and re.match(r'^`include\b',s):
                try: words=shlex.split(s[len('`include'):].strip(),comments=True,posix=True)
                except ValueError: bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                if len(words)!=1 or any(x in words[0] for x in ('$','`','*','?','[',']','{','}')): bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                found.append(words[0]); continue
            command=re.fullmatch(r"\s*(?:%?INCLUDE|source|require_relative|load)\s*\(?\s*(['\"])([^'\"]+)\1\s*\)?\s*;?",s,re.I)
            if not command:
                command=re.fullmatch(r"\s*(?:%?INCLUDE|source)\s+([^\s;]+)\s*;?",s,re.I)
            if command:
                child=command.group(2) if command.lastindex == 2 else command.group(1)
                if any(x in child for x in ('$','`','*','?','[',']','{','}')): bad('PDK_DYNAMIC_INCLUDE_REFUSED')
                found.append(child); continue
            if (spice and re.match(r'^\.(include|inc|lib)\b',s,re.I)
                or tcl and re.match(r'^(source|load)\b',s,re.I)
                or verilog and re.match(r'^`include\b',s)):
                bad('PDK_DYNAMIC_INCLUDE_REFUSED')
            if config_mode:
                code=re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", '""', s)
                if re.search(r'(?i)\b(?:%?include|source|require_relative|load)\s*(?=\(|["\']|[A-Za-z_$])',code):
                    bad('PDK_DYNAMIC_INCLUDE_REFUSED')
    return found
config_seed_set=set(request.get('config_seeds',[]))
todo=[]
for seed in request['seeds']:
    p=pathlib.PurePosixPath(seed)
    if not p.is_absolute() or '..' in p.parts: bad('PDK_SEED_INVALID')
    under(p,guest_root)
    todo.append((p,seed in config_seed_set))
seen={}; parsed=set(); total=0
while todo:
    guest,config_mode=todo.pop(0)
    rel,src=checked(guest)
    key=rel.as_posix()
    if (key,config_mode) in parsed: continue
    if key not in seen and len(seen)>=max_files: bad('PDK_EXPORT_MAX_FILES')
    before=src.stat()
    if before.st_size<0 or (key not in seen and total+before.st_size>max_bytes): bad('PDK_EXPORT_MAX_BYTES')
    try: raw=src.read_bytes()
    except OSError: bad('PDK_FILE_READ_FAILED')
    after=src.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or len(raw)!=before.st_size: bad('PDK_FILE_CHANGED_DURING_EXPORT')
    digest=hashlib.sha256(raw).hexdigest()
    if key in seen and seen[key]['sha256']!=digest: bad('PDK_FILE_CHANGED_DURING_EXPORT')
    children=[]
    next_config=config_mode or src.suffix.lower() in ('.tcl','.magic','.tech')
    for name in includes(src,raw,next_config):
        # Resolve component-by-component before normalization. This preserves
        # safe in-root '..' while refusing existing symlink prefixes that a
        # real consumer would traverse before reaching '..'.
        normalized=resolve_include(guest,name)
        children.append((normalized,next_config))
    if key not in seen:
        relout=pathlib.Path(key)
        dest=out/relout
        dest.parent.mkdir(parents=True,exist_ok=True)
        try:
            fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        except OSError: bad('PDK_EXPORT_WRITE_FAILED')
        seen[key]={'guest_path':guest.as_posix(),'relative_path':key,'size':len(raw),'sha256':digest}
        total+=len(raw)
    parsed.add((key,config_mode)); todo.extend(children)
if measured_root_binding()[0]!=root_binding: bad('PDK_ROOT_ALIAS_CHANGED')
print(json.dumps({'status':'MEASURED','pdk_root_binding':root_binding,
                  'files':[seen[k] for k in sorted(seen)],'total_bytes':total},sort_keys=True,separators=(',',':')))
'''


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Publish a complete directory atomically without replacing any entry."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        _refuse('ANALOG_PDK_EXPORT_ATOMIC_NOREPLACE_UNAVAILABLE')
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        if error in (17, 39):
            _refuse('ANALOG_PDK_EXPORT_STALE_OUTPUT')
        _refuse('ANALOG_PDK_EXPORT_ATOMIC_PUBLISH_FAILED', str(error))


def _refuse(code: str, detail: str = '') -> None:
    raise em.Refusal(code, detail)


def _resolver_seeds(target: str, facts: Mapping[str, object]) -> tuple[str, str, list[str], dict[str, list[str]]]:
    if not isinstance(facts, Mapping):
        _refuse('ANALOG_PDK_EXPORT_RESOLVER_INVALID')
    if facts.get('available') is not True or facts.get('probe_ok') is not True or facts.get('source') != 'container_installed' or facts.get('rung') != 2:
        _refuse('ANALOG_PDK_EXPORT_NOT_MEASURED', 'resolver did not measure one installed PDK')
    family, matched, root = facts.get('family'), facts.get('matched_dir'), facts.get('pdk_root')
    if (not isinstance(family, str) or not family or not isinstance(matched, str) or not matched
            or not isinstance(root, str) or not root.startswith('/') or '\x00' in root):
        _refuse('ANALOG_PDK_EXPORT_RESOLVER_INVALID', 'family/root absent')
    root_path = PurePosixPath(root)
    if str(root_path) != root.rstrip('/') or '..' in root_path.parts or root_path.name != matched:
        _refuse('ANALOG_PDK_EXPORT_RESOLVER_INVALID', 'root/matched_dir disagreement')
    if facts.get('target') not in (None, target):
        _refuse('ANALOG_PDK_EXPORT_RESOLVER_INVALID', 'target disagreement')
    fields: dict[str, list[str]] = {}
    libs = facts.get('spice_libs')
    if libs is None:
        libs = [facts['spice_lib']] if isinstance(facts.get('spice_lib'), str) else []
    if not isinstance(libs, (list, tuple)) or any(not isinstance(x, str) for x in libs):
        _refuse('ANALOG_PDK_EXPORT_RESOLVER_INVALID', 'spice_libs must be exact paths')
    if libs:
        fields['spice_libs'] = list(libs)
    for key in ('drc_deck', 'lvs_deck'):
        value = facts.get(key)
        if value is not None:
            if not isinstance(value, str):
                _refuse('ANALOG_PDK_EXPORT_RESOLVER_INVALID', key)
            fields[key] = [value]
    if not fields:
        _refuse('ANALOG_PDK_EXPORT_NOT_MEASURED', 'resolver named no file seeds')
    seeds = []
    for values in fields.values():
        for value in values:
            p = PurePosixPath(value)
            if not p.is_absolute() or '..' in p.parts or not value.startswith(root.rstrip('/') + '/'):
                _refuse('ANALOG_PDK_EXPORT_SEED_OUTSIDE_ROOT', value)
            normalized = p.as_posix()
            if normalized not in seeds:
                seeds.append(normalized)
    return family, root, seeds, fields


def _validate_population(directory: Path, rows: list[dict], pdk_root: str,
                         max_files: int, max_bytes: int) -> tuple[list[dict], int]:
    if not isinstance(rows, list) or not rows or len(rows) > max_files:
        _refuse('ANALOG_PDK_EXPORT_POPULATION_INVALID')
    normalized = []
    expected_paths = set()
    expected_guests = {}
    total = 0
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'guest_path', 'relative_path', 'size', 'sha256'}
                or not isinstance(row['guest_path'], str) or not isinstance(row['relative_path'], str)
                or type(row['size']) is not int or row['size'] < 0
                or not re.fullmatch(r'[0-9a-f]{64}', str(row['sha256']))):
            _refuse('ANALOG_PDK_EXPORT_POPULATION_INVALID')
        rel = PurePosixPath(row['relative_path'])
        guest = PurePosixPath(row['guest_path'])
        if (rel.is_absolute() or '..' in rel.parts or rel.as_posix() != row['relative_path']
                or not guest.is_absolute() or guest.name in ('', '.', '..')):
            _refuse('ANALOG_PDK_EXPORT_POPULATION_INVALID')
        try:
            guest_rel = guest.relative_to(PurePosixPath(pdk_root))
        except ValueError:
            _refuse('ANALOG_PDK_EXPORT_GUEST_PATH_OUTSIDE_ROOT')
        if guest_rel.as_posix() != row['relative_path']:
            _refuse('ANALOG_PDK_EXPORT_GUEST_MAPPING_MISMATCH')
        if row['relative_path'] in expected_paths:
            _refuse('ANALOG_PDK_EXPORT_DUPLICATE_PATH')
        if row['guest_path'] in expected_guests and expected_guests[row['guest_path']] != row['relative_path']:
            _refuse('ANALOG_PDK_EXPORT_DUPLICATE_PATH_CONTRADICTION')
        expected_paths.add(row['relative_path'])
        expected_guests[row['guest_path']] = row['relative_path']
        path = directory.joinpath(*rel.parts)
        cursor = directory
        for part in rel.parts[:-1]:
            cursor = cursor / part
            if cursor.is_symlink():
                _refuse('ANALOG_PDK_EXPORT_SYMLINK_REFUSED', row['relative_path'])
        try:
            st = path.lstat()
        except OSError:
            _refuse('ANALOG_PDK_EXPORT_OUTPUT_MISSING', row['relative_path'])
        if not stat.S_ISREG(st.st_mode) or path.is_symlink() or st.st_size != row['size'] or _sha256(path) != row['sha256']:
            _refuse('ANALOG_PDK_EXPORT_OUTPUT_CHANGED', row['relative_path'])
        total += st.st_size
        normalized.append(dict(guest_path=row['guest_path'], relative_path=row['relative_path'],
                               size=st.st_size, sha256=row['sha256']))
    if total > max_bytes:
        _refuse('ANALOG_PDK_EXPORT_MAX_BYTES')
    observed = set()
    for parent, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs:
            if (Path(parent) / name).is_symlink():
                _refuse('ANALOG_PDK_EXPORT_SYMLINK_REFUSED')
        for name in files:
            path = Path(parent) / name
            relative = path.relative_to(directory).as_posix()
            if relative != '_receipt.json' and path.is_file():
                observed.add(relative)
            elif relative != '_receipt.json':
                _refuse('ANALOG_PDK_EXPORT_NONREGULAR_REFUSED')
    if observed != expected_paths:
        _refuse('ANALOG_PDK_EXPORT_POPULATION_CHANGED')
    return sorted(normalized, key=lambda x: x['relative_path']), total


def _result_from_receipt(receipt: dict, project: Path, reused: bool) -> dict:
    root = project / receipt['output_root']
    mapping = {row['guest_path']: (Path(receipt['output_root']) / row['relative_path']).as_posix()
               for row in receipt['files']}
    rewritten = {}
    for field, values in receipt['resolver_fields'].items():
        local = [mapping[value] for value in values]
        rewritten[field] = local if field == 'spice_libs' else local[0]
    if 'spice_libs' in rewritten:
        rewritten['spice_lib'] = rewritten['spice_libs'][0]
    return dict(schema=SCHEMA, status='MEASURED', image_ref=receipt['image_ref'],
                image_id=receipt['image_id'], image_manifest_digest=receipt['image_manifest_digest'],
                image_repo_digests=receipt['image_repo_digests'], target=receipt['target'],
                pdk_family=receipt['pdk_family'], pdk_root=receipt['pdk_root'],
                pdk_root_binding=receipt['pdk_root_binding'],
                output_root=receipt['output_root'], files=receipt['files'],
                guest_to_project=mapping, resolver_fields=rewritten,
                limits=receipt['limits'], not_measured=[], refusal_reasons=[],
                receipt_digest=receipt['receipt_digest'], reused=reused)


def export_bounded_pdk(project: Path, *, target: str, image_ref: str,
                       image_id: str, resolver_facts: Mapping[str, object],
                       docker: str = 'docker', max_files: int = 512,
                       max_bytes: int = 67_108_864) -> dict:
    """Copy resolver-named PDK files and literal include closure atomically.

    A successful result means only that bounded inputs were copied and bound;
    it does not qualify an analog tool, execute a design, or confer PASS.
    """
    if (not isinstance(project, Path) or not project.is_absolute() or project.is_symlink()
            or type(max_files) is not int or not 1 <= max_files <= 512
            or type(max_bytes) is not int or not 1 <= max_bytes <= 67_108_864
            or not isinstance(target, str) or not target or not isinstance(docker, str) or not docker):
        _refuse('ANALOG_PDK_EXPORT_REQUEST_INVALID')
    project = project.resolve(strict=True)
    if not project.is_dir():
        _refuse('ANALOG_PDK_EXPORT_PROJECT_INVALID')
    family, pdk_root, seeds, fields = _resolver_seeds(target, resolver_facts)
    import execution_analog_installation as installation
    try:
        image = installation.inspect_image(image_ref, docker=docker)
    except (em.Refusal, OSError, subprocess.SubprocessError) as exc:
        return dict(schema=SCHEMA, status='NOT_MEASURED', image_ref=image_ref, image_id=image_id,
                    pdk_family=family, pdk_root=pdk_root, output_root=None, files=[],
                    guest_to_project={}, resolver_fields={}, limits={'max_files': max_files, 'max_bytes': max_bytes},
                    not_measured=['IMAGE_INSPECTION_UNAVAILABLE:' + getattr(exc, 'code', type(exc).__name__)],
                    refusal_reasons=[], receipt_digest=None)
    if image.get('image_ref') != image_ref or image.get('image_id') != image_id:
        _refuse('ANALOG_PDK_EXPORT_IMAGE_UNBOUND', 'image ref or local image id differs')
    if image_ref not in image.get('image_repo_digests', ()):
        _refuse('ANALOG_PDK_EXPORT_IMAGE_UNBOUND', 'pinned ref absent from RepoDigests')
    base = project
    for part in OUTPUT_BASE.parts:
        base = base / part
        if base.is_symlink():
            _refuse('ANALOG_PDK_EXPORT_OUTPUT_PATH_INVALID')
        try:
            base.mkdir(exist_ok=True)
        except OSError:
            _refuse('ANALOG_PDK_EXPORT_OUTPUT_PATH_INVALID')
        if not base.is_dir():
            _refuse('ANALOG_PDK_EXPORT_OUTPUT_PATH_INVALID')
    if not base.resolve().is_relative_to(project):
        _refuse('ANALOG_PDK_EXPORT_OUTPUT_PATH_INVALID')
    request = dict(target=target, pdk_family=family, pdk_root=pdk_root, seeds=seeds,
                   resolver_fields=fields, image_ref=image_ref, image_id=image_id,
                   image_manifest_digest=image['image_manifest_digest'],
                   image_repo_digests=image['image_repo_digests'],
                   limits={'max_files': max_files, 'max_bytes': max_bytes})
    scratch = Path(tempfile.mkdtemp(prefix='.analog-pdk-export-', dir=base))
    try:
        argv = [docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network', 'none', '--cpus', '1',
                '-v', f'{scratch}:/vibeic-pdk-export:rw', image_ref,
                '--skip', 'python3', '-c', _CONTAINER_COPY, pdk_root,
                '/vibeic-pdk-export', json.dumps({'pdk_root': pdk_root, 'seeds': seeds,
                                                   'config_seeds': fields.get('drc_deck', []) + fields.get('lvs_deck', []),
                                                   'max_files': max_files,
                                                   'max_bytes': max_bytes}, sort_keys=True)]
        safe_env = {k: v for k, v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')}
        done = lc.run_container(argv, probe_deadline_s=120, env=safe_env)
        if done.returncode != 0:
            return dict(schema=SCHEMA, status='NOT_MEASURED', image_ref=image_ref, image_id=image_id,
                        pdk_family=family, pdk_root=pdk_root, output_root=None, files=[],
                        guest_to_project={}, resolver_fields={}, limits=request['limits'],
                        not_measured=['PDK_EXPORT_PROCESS_NONZERO'], refusal_reasons=[], receipt_digest=None)
        try:
            observed = json.loads((done.stdout or '').strip().splitlines()[-1])
        except (ValueError, IndexError):
            return dict(schema=SCHEMA, status='NOT_MEASURED', image_ref=image_ref, image_id=image_id,
                        pdk_family=family, pdk_root=pdk_root, output_root=None, files=[],
                        guest_to_project={}, resolver_fields={}, limits=request['limits'],
                        not_measured=['PDK_EXPORT_RECEIPT_UNREADABLE'], refusal_reasons=[], receipt_digest=None)
        if observed.get('status') != 'MEASURED':
            return dict(schema=SCHEMA, status='NOT_MEASURED', image_ref=image_ref, image_id=image_id,
                        pdk_family=family, pdk_root=pdk_root, output_root=None, files=[],
                        guest_to_project={}, resolver_fields={}, limits=request['limits'],
                        not_measured=[str(observed.get('reason', 'PDK_EXPORT_INCOMPLETE'))],
                        refusal_reasons=[], receipt_digest=None)
        root_binding = observed.get('pdk_root_binding')
        logical = PurePosixPath(pdk_root)
        if (not isinstance(root_binding, dict)
                or set(root_binding) != {'logical_root', 'link_text', 'canonical_root'}
                or root_binding.get('logical_root') != pdk_root
                or not isinstance(root_binding.get('canonical_root'), str)
                or '\x00' in root_binding['canonical_root']
                or (root_binding.get('link_text') is not None
                    and (not isinstance(root_binding['link_text'], str)
                         or not root_binding['link_text'] or '\x00' in root_binding['link_text']))):
            _refuse('ANALOG_PDK_EXPORT_ROOT_BINDING_INVALID')
        try:
            canonical = PurePosixPath(root_binding['canonical_root'])
        except (TypeError, ValueError):
            _refuse('ANALOG_PDK_EXPORT_ROOT_BINDING_INVALID')
        authority = PurePosixPath(pdk_root).parent
        link_text = root_binding['link_text']
        if (canonical.as_posix() != root_binding['canonical_root']
                or not canonical.is_absolute() or '..' in canonical.parts
                or not canonical.is_relative_to(authority) or canonical.name != logical.name):
            _refuse('ANALOG_PDK_EXPORT_ROOT_BINDING_INVALID')
        if canonical == logical:
            if link_text is not None:
                _refuse('ANALOG_PDK_EXPORT_ROOT_BINDING_INVALID')
        else:
            if not isinstance(link_text, str) or not link_text or '\x00' in link_text:
                _refuse('ANALOG_PDK_EXPORT_ROOT_BINDING_INVALID')
            try:
                raw_target = PurePosixPath(link_text)
                lexical_target = (raw_target if raw_target.is_absolute() else
                    PurePosixPath(os.path.normpath(str(logical.parent / raw_target))))
            except (TypeError, ValueError):
                _refuse('ANALOG_PDK_EXPORT_ROOT_BINDING_INVALID')
            if lexical_target != canonical or not lexical_target.is_relative_to(authority):
                _refuse('ANALOG_PDK_EXPORT_ROOT_BINDING_INVALID')
        files, total = _validate_population(scratch, observed.get('files'), pdk_root, max_files, max_bytes)
        if type(observed.get('total_bytes')) is not int or observed['total_bytes'] != total:
            _refuse('ANALOG_PDK_EXPORT_BYTE_COUNT_MISMATCH')
        seeds_set = set(seeds)
        if not seeds_set.issubset({row['guest_path'] for row in files}):
            _refuse('ANALOG_PDK_EXPORT_SEED_OMITTED')
        body = dict(schema=SCHEMA, target=target, pdk_family=family, pdk_root=pdk_root,
                    pdk_root_binding=root_binding,
                    image_ref=image_ref, image_id=image_id,
                    image_manifest_digest=image['image_manifest_digest'],
                    image_repo_digests=image['image_repo_digests'], resolver_fields=fields,
                    files=files, limits=request['limits'], total_bytes=total)
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        output_rel = (OUTPUT_BASE / digest).as_posix()
        final = project / output_rel
        receipt = {**body, 'receipt_digest': digest, 'output_root': output_rel}
        if final.exists() or final.is_symlink():
            if final.is_symlink() or not final.is_dir():
                _refuse('ANALOG_PDK_EXPORT_STALE_OUTPUT')
            try:
                old = json.loads((final / '_receipt.json').read_text())
                if (old != receipt or (final / '_receipt.json').read_bytes() != _canonical(receipt) + b'\n'):
                    _refuse('ANALOG_PDK_EXPORT_STALE_OUTPUT')
                _validate_population(final, files, pdk_root, max_files, max_bytes)
            except (OSError, ValueError):
                _refuse('ANALOG_PDK_EXPORT_STALE_OUTPUT')
            return _result_from_receipt(receipt, project, True)
        receipt_path = scratch / '_receipt.json'
        receipt_path.write_bytes(_canonical(receipt) + b'\n')
        # Same-filesystem rename publishes only a fully checked population.
        _rename_noreplace(scratch, final)
        return _result_from_receipt(receipt, project, False)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
