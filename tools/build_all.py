"""전체 빌드 한 번에: 텍스트 -> 폰트 -> 패키징 -> (선택) SD카드 복사

  python build_all.py            빌드 + 패키징
  python build_all.py --sd D:    빌드 + 패키징 + SD카드 D: 의 KoreanTranslation 모드팩에 복사
"""
import os, sys, subprocess, shutil, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TITLE = '0005000010102200'
MODPACK = 'KoreanTranslation'


def run(*args):
    print(f'\n$ {" ".join(args)}')
    r = subprocess.run([PY, *args], cwd=HERE)
    if r.returncode != 0:
        raise SystemExit(f'실패: {args}')


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def copy_sd(drive):
    from wfu_lib import BUILD
    src = os.path.join(BUILD, 'sdcafiine', TITLE, 'Korean', 'content')
    dst = os.path.join(drive + os.sep, 'wiiu', 'sdcafiine', TITLE, MODPACK, 'content')
    if not os.path.isdir(os.path.join(drive + os.sep, 'wiiu')):
        raise SystemExit(f'{drive} 에 wiiu 폴더가 없습니다 (SD카드 확인)')
    ok = True
    for root, _, files in os.walk(src):
        for fn in files:
            s = os.path.join(root, fn)
            d = os.path.join(dst, os.path.relpath(s, src))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(s, d)
            same = md5(s) == md5(d)
            ok &= same
            print(f'   {"OK " if same else "불일치"} {os.path.relpath(d, drive + os.sep)}')
    print(f'SD 복사 {"완료" if ok else "중 오류"}: {dst}')


if __name__ == '__main__':
    run('bmg_tool.py', 'build')
    run('font_tool.py', 'build')
    run('image_tool.py', 'render')
    run('image_tool.py', 'build')
    run('make_pack.py')
    if '--sd' in sys.argv:
        copy_sd(sys.argv[sys.argv.index('--sd') + 1].rstrip('\\/'))
