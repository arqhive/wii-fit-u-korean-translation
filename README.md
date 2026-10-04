# Wii Fit U (Wii U) 한글 패치

「Wii Fit U」(Wii U, 일본판 `0005000010102200`) 비공식 한국어 팬 패치입니다.
대사는 일본어판 원문을 기준으로 번역했습니다.

**제작: arqhive** · **최신 버전: [v1.0f](../../releases/tag/v1.0f)**

- 대사 7,821개를 한글화했습니다(안내·메뉴·트레이너 대사·기록·측정 결과 등. 전체 8,665개 중 기호·문자표 제외).
- 게임 글꼴 6종에 한글 1,051자를 새로 그려 넣었습니다.
- 글씨가 그려진 그림 32장을 한글화했습니다(튜토리얼 그림, 기록·메뉴 패널, 3D 메뉴 로고, 완료 도장, 달력 도장 12장).
- **가지고 있는 일본판 게임 파일로 한글판을 만드는 패처로 배포합니다.** 결과는 Wii U 실기(SDCafiine)에서 바로 쓸 수 있습니다.

> 이 저장소에는 게임 데이터가 들어 있지 않습니다.
> 패치를 적용하려면 본인이 소유한 게임에서 직접 덤프한 원본이 필요합니다.

## 사용자용: 패치 적용

### 준비물

- 일본판 「Wii Fit U」의 복호화된 게임 파일. **본편과 업데이트가 둘 다** 필요합니다.
  - 본편 `0005000010102200`, 업데이트 `0005000E10102200`. 각 폴더 안에 `code`·`content`·`meta`가 있어야 합니다.
  - 본체에서 dumpling 으로 덤프하면 복호화된 상태로 나옵니다. WUP 설치 파일은 CDecrypt 로 복호화합니다.
- Windows 10 이상. 패처에 파이썬이 들어 있어 따로 설치할 것이 없습니다.
- 빈 공간 약 250MB(결과 파일).
- Wii U 실기와 Aroma 등 CFW, SDCafiine 플러그인, SD 카드.
  - 이 게임은 Cemu 에서 실행되지 않아 실기가 필요합니다.
- 게임을 하려면 Wii 밸런스 보드가 필요합니다(원래 게임의 조건입니다).

### 적용 방법

1. [배포 페이지](../../releases/latest)에서 `WiiFitU_KO_v1.0f.zip`을 받아 압축을 풉니다.
2. 본편과 업데이트 폴더가 나란히 들어 있는 폴더를 `패치하기.bat` 위에 끌어다 놓습니다.
   그냥 실행하면 경로를 물어봅니다.

   ```
   내 게임
    +- Wii Fit U [Game] [0005000010102200]
    +- Wii Fit U [Update] [0005000e10102200]
   ```

   이때 `내 게임` 폴더를 지정합니다. 폴더 이름은 무엇이든 상관없습니다.
3. 원본 확인 → 한글판 만들기 → 결과 확인이 차례로 끝납니다(몇 초). 원본 파일은 바뀌지 않습니다.
4. `WiiFitU_KO_v1.0f\출력` 폴더에 결과가 생깁니다.

### Wii U 실기 (SDCafiine)

`출력\sdcafiine` 안의 내용을 SD 카드의 `wiiu\sdcafiine\`에 복사하고, SDCafiine 플러그인을 켠 채로
게임을 실행합니다.

```
sd:/wiiu/sdcafiine/0005000010102200/WiiFitU_Korean/content/...
```

본편과 업데이트에서 가져온 파일이 한 폴더에 함께 들어갑니다. 그대로 두면 됩니다.
패치를 빼려면 SD 카드에서 `WiiFitU_Korean` 폴더를 지웁니다.

### 오류가 날 때

| 메시지 | 원인·해결 |
|---|---|
| 본편/업데이트 폴더를 찾지 못했습니다 | 복호화한 폴더(안에 `content`가 있는 것)를 지정하세요. 암호화된 상태(`.app`)로는 안 됩니다. 본편과 업데이트가 둘 다 필요합니다. |
| …가 일본판 원본과 다릅니다 | 이미 패치한 파일이거나 다른 판본입니다. 원본 일본판 파일을 넣으세요. |
| 결과가 기준과 다릅니다 | 패치 파일이 손상됐을 수 있습니다. zip 을 다시 받아 주세요. |

패처는 원본 13개의 해시를 확인한 뒤 바뀐 부분만 갈아끼워 파일을 다시 만들고, 결과가 제작 환경에서
확인한 빌드와 해시까지 같은지 검사합니다.
자세한 방법은 패처에 들어 있는 `README_KO.txt`를 참고하세요.

### 실행 환경

- **확인함**: Wii U 실기(Aroma + SDCafiine).

### 한글로 바뀌지 않는 곳

- 이름을 넣는 화면의 문자표는 일본어·영문 그대로입니다. 한글 이름은 넣을 수 없습니다.
- 사진·일러스트에 원래부터 그려져 있는 작은 글자 일부는 그대로입니다.

## 개발자용: 도구

번역 원본(대사 시트·번역 묶음 JSON·용어집)에는 게임의 일본어 원문이 함께 들어 있어
**공개 저장소에는 넣지 않았습니다.** 이 저장소의 도구는 파일 형식과 빌드 방식을 참고하는 용도이며,
번역 원본 없이는 한글판을 빌드할 수 없습니다. 패치 적용은 위의 패처를 쓰세요.

### 요구 사항

- Python 3.11 이상. `pip install -r requirements.txt` (numpy, Pillow, openpyxl, opencv-python-headless).
- 일본판 게임 덤프(복호화된 `code`·`content`·`meta`)를 저장소 루트에 둡니다. 폴더 이름은 상관없이
  본편·업데이트를 알아서 찾습니다.
- 한글 글꼴: Noto Sans KR (`C:/Windows/Fonts/NotoSansKR-VF.ttf`).

### 빌드

```bash
python tools/build_all.py                  # 대사·글꼴·그림 → build/
python tools/build_all.py --sd D:          # + SD 카드로 복사(MD5 검증)
python tools/make_patcher.py v1.0f         # 배포용 패처 zip (work/release/)
```

같은 입력이면 결과는 바이트 단위로 같습니다.

### 검증

고치지 않고 다시 꾸몄을 때 원본과 바이트 단위로 같아지는지 확인합니다. 도구를 손본 뒤에는 먼저
이걸 돌려 보세요. 모두 "일치 True"가 나와야 정상입니다.

```bash
python tools/bmg_tool.py roundtrip     # 대사: BMG / U8 / Yaz0
python tools/font_tool.py roundtrip    # 글꼴 9종, GTX, 타일 배열, jARC, jCMP
python tools/image_tool.py roundtrip   # 텍스처 묶음 5개 재포장·재인코딩
```

### 폴더 구조

```
patcher/           사용자용 패처 (패치하기.bat, patch.py, README_KO.txt)
tools/             빌드·패처·조사 도구
docs/              기술 문서
licenses/          글꼴 라이선스
```

### 기술 문서

파일 형식, 한글화 방식, 밟아 본 함정은 [`docs/TECHNICAL.md`](docs/TECHNICAL.md)에 정리했습니다.

## 변경 내역

전체 내역은 [`CHANGELOG.md`](CHANGELOG.md)에 있습니다.

## 크레딧·라이선스

- 이 저장소의 도구 코드와 문서: [MIT License](LICENSE) (© 2026 arqhive).
- 게임 글꼴의 한글 글자는 [Noto Sans KR](https://fonts.google.com/noto/specimen/Noto+Sans+KR)로 그렸습니다. SIL Open Font License 1.1 ([`licenses/OFL_NotoSansKR.txt`](licenses/OFL_NotoSansKR.txt)).
- 패처에 동봉하는 Python 은 PSF License 입니다.

## 면책

비공식 팬 번역이며 Nintendo 와 관련이 없습니다. 「Wii Fit U」 관련 상표·저작권은 Nintendo 에 있습니다.
패치를 적용한 게임 파일의 배포를 금지합니다.
