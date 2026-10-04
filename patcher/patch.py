# -*- coding: utf-8 -*-
"""Wii Fit U 한글 패치 적용기 — 일본판 복호화 폴더로 한글판 파일을 만든다.

  패치하기.bat 에 게임 폴더를 끌어다 놓거나, 실행한 뒤 경로를 입력한다.
  python patch.py <본편·업데이트가 들어 있는 폴더>

원본 파일은 건드리지 않는다. 결과:
  출력\\sdcafiine\\0005000010102200\\WiiFitU_Korean\\content\\...   SD 카드에 복사할 파일
"""
import os, sys, json, time, hashlib, traceback

try:  # 콘솔 글자표가 무엇이든 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'lib'))
import wfu_pack

PAYLOAD = os.path.join(HERE, 'payload')
OUT = os.path.join(TOP, '출력')
TID = '0005000010102200'
MODPACK = 'WiiFitU_Korean'
# 본편·업데이트를 가려내는 실마리(폴더 이름이 무엇이든 찾는다)
MARK = os.path.join('content', 'JP', 'Message', 'message.carc')


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def find_titles(arg):
    """주어진 경로 아래에서 본편·업데이트의 content 폴더를 찾는다.

    - 본편·업데이트가 나란히 든 상위 폴더를 주는 것이 보통이다.
    - 둘 중 하나만 주거나 content 폴더를 바로 줘도 그것만 인식한다.
    """
    arg = arg.strip().strip('"').rstrip(os.sep)
    found = {}

    def look(d):
        """content 폴더 하나를 보고 본편인지 업데이트인지 가른다"""
        if not os.path.isfile(os.path.join(d, MARK)):
            return
        content = os.path.join(d, 'content')
        # 업데이트에는 ui\ui_fb_tex.jarc 가 있고 본편에는 ui\aot_tex.jarc 가 있다
        kind = 'update' if os.path.isfile(os.path.join(content, 'ui', 'ui_fb_tex.jarc')) else 'game'
        # 본편에도 ui_fb_tex.jarc 가 있으므로 폴더 이름으로 한 번 더 가린다
        low = os.path.basename(d).lower()
        if 'update' in low or '0005000e' in low:
            kind = 'update'
        elif 'game' in low or '00050000' in low:
            kind = 'game'
        found.setdefault(kind, content)

    if os.path.isdir(arg):
        base = os.path.dirname(arg) if os.path.basename(arg) == 'content' else arg
        look(base)
        for n in sorted(os.listdir(base)):
            d = os.path.join(base, n)
            if os.path.isdir(d):
                look(d)
    return found


def resolve(titles, rel, side):
    """payload 가 적어 둔 쪽(본편/업데이트)의 원본 파일 경로"""
    c = titles.get(side)
    return os.path.join(c, rel) if c else None


def main():
    man = json.load(open(os.path.join(PAYLOAD, 'manifest.json'), encoding='utf-8'))
    print('Wii Fit U 한글 패치 %s\n' % man['version'])
    arg = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].strip() else None
    if not arg:
        print('복호화한 일본판 「Wii Fit U」 폴더 경로를 입력하세요.')
        print('본편과 업데이트가 나란히 들어 있는 폴더를 이 창에 끌어다 놓으면 됩니다.')
        arg = input('> ')
    titles = find_titles(arg)
    need = sorted({f['side'] for f in man['files']})
    label = {'game': '본편', 'update': '업데이트'}
    for side in need:
        if side not in titles:
            print('[오류] %s 폴더를 찾지 못했습니다: %s' % (label[side], arg))
            print('       복호화한 폴더(안에 content 폴더가 있는 것)를 지정해 주세요.')
            print('       본편과 업데이트가 둘 다 필요합니다.')
            return 1
        print('%s: %s' % (label[side], titles[side]))
    print()

    # 1) 원본이 일본판 그대로인지 확인
    print('[1/3] 원본 확인')
    src = {}
    for f in man['files']:
        p = resolve(titles, f['rel'], f['side'])
        if not os.path.isfile(p):
            print('[오류] 원본에 %s 가 없습니다.' % f['rel']); return 1
        d = read(p)
        if len(d) != f['src_size'] or sha1(d) != f['src_sha1']:
            print('[오류] %s 가 일본판 원본과 다릅니다(이미 패치했거나 다른 판본).' % f['rel'])
            return 1
        src[f['rel']] = d
    print('  %d개 모두 일치' % len(man['files']))

    # 2) 한글판 만들기
    print('\n[2/3] 한글판 만들기')
    blob = read(os.path.join(PAYLOAD, 'data.bin'))
    part = lambda k: blob[man['parts'][k][0]:man['parts'][k][0] + man['parts'][k][1]]
    outdir = os.path.join(OUT, 'sdcafiine', TID, MODPACK, 'content')
    made = {}
    t0 = time.time()
    for f in man['files']:
        how = f['how']
        if how == 'whole':                       # 파일을 통째로 담아 둔 것
            out = part(f['parts'][0])
        elif how == 'arc':                       # 묶음 안의 항목만 갈아끼우기
            out = wfu_pack.rebuild(src[f['rel']], {n: part(k) for n, k in f['parts'].items()})
        elif how == 'nested':                    # 묶음 > 묶음 안의 항목 갈아끼우기
            out = wfu_pack.rebuild_nested(src[f['rel']], f['inner'],
                                          {n: part(k) for n, k in f['parts'].items()})
        elif how == 'arc_from':                  # 다른 결과 파일들을 모아 묶음 만들기
            out = wfu_pack.rebuild_keep_packing(src[f['rel']],
                                                {n: made[r] for n, r in f['from'].items()})
        else:
            print('[오류] 알 수 없는 방식: %s' % how); return 1
        if sha1(out) != f['out_sha1']:
            print('[오류] %s 결과가 기준과 다릅니다. 패치 파일이 손상됐을 수 있습니다.' % f['rel'])
            return 1
        made[f['rel']] = out
        dst = os.path.join(outdir, f['rel'])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as fp:
            fp.write(out)
        print('  %-34s %7.2fMB 확인 일치' % (f['rel'], len(out) / 1048576))
    print('  %d개 · %.1f초' % (len(made), time.time() - t0))

    # 3) 안내
    print('\n[3/3] 다 됐습니다')
    print('  만든 곳: %s' % os.path.join(OUT, 'sdcafiine'))
    print('\n넣는 방법 (둘 중 하나만 하면 됩니다)')
    print('  (1) SDCafiine: 만들어진 sdcafiine 폴더의 내용을 SD 카드의 wiiu\\sdcafiine\\ 아래에 복사합니다.')
    print('      SD 카드가 wiiu\\sdcafiine\\%s\\%s\\content\\... 모양이 되면 됩니다.' % (TID, MODPACK))
    print('  (2) FTP: content 아래 파일들을 본체에 설치된 게임의 같은 경로에 덮어씁니다.')
    print('      되돌리기 어려우므로 (1) 을 권합니다.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n중단했습니다.'); sys.exit(1)
    except Exception:
        traceback.print_exc(); print('[오류] 예상하지 못한 문제가 생겼습니다.'); sys.exit(1)
