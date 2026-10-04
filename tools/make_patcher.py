# -*- coding: utf-8 -*-
"""배포용 패처 꾸리기 — 빌드 결과와 원본을 견주어 바뀐 안쪽 파일만 담는다.

  python tools/build_all.py                      먼저 전체 빌드
  python tools/make_patcher.py v0.1 [--python <내장 파이썬 폴더>]

출력: work/release/WiiFitU_KO_<버전>/        패처 폴더(패치하기.bat · python · patcher)
      work/release/WiiFitU_KO_<버전>.zip     배포용 압축 파일

패치 데이터에는 원본 게임 데이터를 담지 않는다. 묶음은 안쪽에서 바뀐 항목만 담고,
패처가 사용자의 원본 묶음을 다시 꾸려 한글판을 만든다. 글꼴 묶음(font_data.jarc)은
낱개 글꼴 파일과 바이트까지 같으므로 낱개 쪽만 담고 패처가 묶는다.
"""
import os, sys, json, shutil, hashlib, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wfu_lib import GAME, UPD, BUILD, ROOT
import wfu_pack

BUILT = os.path.join(BUILD, 'content')
REL = os.path.join(ROOT, 'work', 'release')
PY_DEFAULT = os.path.join(ROOT, 'work', 'python_embed')
# 묶음 > 안 묶음 구조인 것(겉만 보면 바뀐 항목을 알 수 없다)
NESTED = {os.path.join('ui', 'ui_fb_tex.jarc'): 'com_tex.jarc'}
# 낱개 결과 파일을 모아 만드는 묶음
FROM_FILES = {os.path.join('fonts', 'font_data.jarc'): 'fonts'}


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def read(p):
    with open(p, 'rb') as f:
        return f.read()


def src_path(rel):
    """원본 파일이 업데이트에 있으면 업데이트, 없으면 본편 — 어느 쪽인지도 함께 돌려준다"""
    u = os.path.join(UPD, rel)
    return (u, 'update') if os.path.exists(u) else (os.path.join(GAME, rel), 'game')


def arc_entries(raw):
    """묶음 바이트 -> {이름: 저장 바이트}, 묶음이 아니면 None"""
    inner = wfu_pack.jcmp_decompress(raw) if raw[:4] == b'jCMP' else raw
    if inner[:4] != b'jARC':
        return None
    return dict(wfu_pack.jarc_read(inner)[1])


def built_files():
    out = []
    for dp, _, ns in os.walk(BUILT):
        for n in ns:
            out.append(os.path.relpath(os.path.join(dp, n), BUILT))
    return sorted(out)


def plan():
    """담을 것을 정한다 -> (files, blobs)  blobs = {조각 이름: 바이트}"""
    files, blobs = [], {}
    rels = built_files()
    loose = {r for r in rels if os.path.dirname(r) == 'fonts' and r.endswith('.jfnt')}

    for rel in rels:
        sp, side = src_path(rel)
        old, new = read(sp), read(os.path.join(BUILT, rel))
        rec = dict(rel=rel, side=side, src_size=len(old), src_sha1=sha1(old), out_sha1=sha1(new))

        # (1) 낱개 글꼴 파일을 모아 만드는 묶음: 데이터를 다시 담지 않는다
        if rel in FROM_FILES:
            oe, ne = arc_entries(old), arc_entries(new)
            frm = {}
            for name, data in ne.items():
                if oe.get(name) == data:
                    continue
                cand = os.path.join(FROM_FILES[rel], name)
                # 묶음 안에서는 압축된 채 들어 있으므로 풀어서 낱개 파일과 견준다
                if cand not in loose or read(os.path.join(BUILT, cand)) != wfu_pack.entry_raw(data):
                    raise SystemExit(f'{rel} 의 {name} 은 낱개 파일과 달라서 따로 담아야 합니다')
                frm[name] = cand
            rec.update(how='arc_from', **{'from': frm})
            files.append(rec)
            continue

        # (2) 묶음 > 안 묶음
        if rel in NESTED:
            iname = NESTED[rel]

            def inner_entries(raw):
                """겉 묶음에서 안 묶음을 꺼내 그 안의 항목 목록을 돌려준다"""
                return arc_entries(arc_entries(raw)[iname])

            oe, ne = inner_entries(old), inner_entries(new)
            parts = {}
            for name, data in ne.items():
                if oe.get(name) == data:
                    continue
                key = f'{rel}|{iname}|{name}'.replace('\\', '/')
                blobs[key] = data; parts[name] = key
            rec.update(how='nested', inner=iname, parts=parts)
            files.append(rec)
            continue

        # (3) 보통 묶음
        oe = arc_entries(old)
        if oe is not None:
            ne = arc_entries(new)
            parts = {}
            for name, data in ne.items():
                if oe.get(name) == data:
                    continue
                key = f'{rel}|{name}'.replace('\\', '/')
                blobs[key] = data; parts[name] = key
            rec.update(how='arc', parts=parts)
            files.append(rec)
            continue

        # (4) 묶음이 아닌 것(낱개 글꼴·대사)은 통째로
        key = rel.replace('\\', '/')
        blobs[key] = new
        rec.update(how='whole', parts=[key])
        files.append(rec)

    # 묶음을 만들 때 재료가 먼저 만들어져 있어야 한다
    files.sort(key=lambda f: f['how'] == 'arc_from')
    return files, blobs


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 'v0.1'
    pydir = PY_DEFAULT
    if '--python' in sys.argv:
        pydir = sys.argv[sys.argv.index('--python') + 1]
    if not os.path.isdir(BUILT):
        raise SystemExit('먼저 python tools/build_all.py 로 빌드하세요')

    files, blobs = plan()
    # 조각들을 한 파일로 이어 붙인다(작은 파일 수백 개보다 다루기 쉽다)
    parts, data = {}, bytearray()
    for k, v in blobs.items():
        parts[k] = [len(data), len(v)]; data += v
    man = dict(version=ver, title=TID_NAME, files=files, parts=parts)

    name = f'WiiFitU_KO_{ver}'
    dst = os.path.join(REL, name)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.join(dst, 'patcher', 'payload'), exist_ok=True)
    os.makedirs(os.path.join(dst, 'patcher', 'lib'), exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))
    shutil.copyfile(os.path.join(ROOT, 'patcher', 'patch.py'), os.path.join(dst, 'patcher', 'patch.py'))
    shutil.copyfile(os.path.join(here, 'wfu_pack.py'), os.path.join(dst, 'patcher', 'lib', 'wfu_pack.py'))
    shutil.copyfile(os.path.join(ROOT, 'patcher', '패치하기.bat'), os.path.join(dst, '패치하기.bat'))
    shutil.copyfile(os.path.join(ROOT, 'patcher', 'README_KO.txt'), os.path.join(dst, 'README_KO.txt'))
    shutil.copytree(os.path.join(ROOT, 'licenses'), os.path.join(dst, 'licenses'))
    with open(os.path.join(dst, 'patcher', 'payload', 'data.bin'), 'wb') as f:
        f.write(data)
    with open(os.path.join(dst, 'patcher', 'payload', 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    if os.path.isdir(pydir):
        shutil.copytree(pydir, os.path.join(dst, 'python'))
        print('내장 파이썬 포함:', pydir)
    else:
        print('[주의] 내장 파이썬 폴더가 없어 넣지 않았습니다:', pydir)

    print(f'\n패치 데이터 {len(data)/1048576:.2f}MB (조각 {len(parts)}개, 파일 {len(files)}개)')
    for f in files:
        n = len(f.get('parts', [])) if f['how'] != 'arc_from' else len(f['from'])
        print(f"  {f['rel']:34s} {f['how']:9s} {f['side']:6s} 항목 {n}개")

    zp = os.path.join(REL, name + '.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dp, _, ns in os.walk(dst):
            for n in ns:
                p = os.path.join(dp, n)
                z.write(p, os.path.join(name, os.path.relpath(p, dst)))
    print(f'\n{zp}  ({os.path.getsize(zp)/1048576:.2f}MB)')


TID_NAME = 'Wii Fit U (JP) 0005000010102200'

if __name__ == '__main__':
    main()
