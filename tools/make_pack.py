"""build/content 를 테스트/배포용 폴더로 패키징

  python make_pack.py
    -> build/cemu_graphicpack/WiiFitU_Korean/   (Cemu graphicPacks 폴더에 복사)
    -> build/sdcafiine/0005000010102200/content/ (실기 SD: sd:/wiiu/sdcafiine/ 아래에 복사)
"""
import os, shutil
from wfu_lib import BUILD

TITLE_BASE = '0005000010102200'
SRC = os.path.join(BUILD, 'content')

RULES = f"""[Definition]
titleIds = {TITLE_BASE}
name = Korean Translation (test)
path = "Wii Fit U/Mods/Korean Translation"
description = Wii Fit U 일본판 한글화 테스트 빌드
version = 7
"""


def main():
    if not os.path.isdir(SRC):
        raise SystemExit(f'빌드 결과 없음: {SRC}')
    files = [os.path.relpath(os.path.join(r, f), SRC) for r, _, fs in os.walk(SRC) for f in fs]
    gp = os.path.join(BUILD, 'cemu_graphicpack', 'WiiFitU_Korean')
    # Aroma SDCafiine: sd:/wiiu/sdcafiine/[TitleID]/[모드팩 이름]/content/
    sd = os.path.join(BUILD, 'sdcafiine', TITLE_BASE, 'Korean', 'content')
    for dst in (gp, os.path.join(BUILD, 'sdcafiine', TITLE_BASE)):
        if os.path.isdir(dst):
            shutil.rmtree(dst)
    shutil.copytree(SRC, os.path.join(gp, 'content'))
    with open(os.path.join(gp, 'rules.txt'), 'w', encoding='utf-8') as f:
        f.write(RULES)
    shutil.copytree(SRC, sd)
    print(f'패키징 완료: 파일 {len(files)}개')
    for p in files:
        print('   content/' + p.replace(os.sep, '/'))
    print(f'Cemu : {gp}  -> Cemu\\graphicPacks\\ 에 폴더째 복사 후 게임 프로필의 그래픽팩에서 활성화')
    print(f'실기 : {os.path.dirname(sd)} -> SD카드 wiiu\\sdcafiine\\ 아래에 복사')


if __name__ == '__main__':
    main()
