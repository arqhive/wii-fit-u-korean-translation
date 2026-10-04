"""번역 묶음 자체 검사: python tl_check.py NN
translation/work/in_NN.json 과 out_NN_p*.json 을 비교해 누락·태그·아이콘·가나·줄 수 문제를 출력
"""
import os, sys, json, glob
from tl_split import WORK, check

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

n = sys.argv[1]
src = json.load(open(os.path.join(WORK, f'in_{n}.json'), encoding='utf-8'))
got = {}
bad_files = []
for p in sorted(glob.glob(os.path.join(WORK, f'out_{n}_p*.json'))):
    try:
        for k, v in json.load(open(p, encoding='utf-8')).items():
            got[int(k)] = v
    except Exception as e:
        bad_files.append(f'{os.path.basename(p)}: {e}')
missing = [x['i'] for x in src if x['i'] not in got]
extra = [i for i in got if i not in {x['i'] for x in src}]
problems = []
for x in src:
    if x['i'] in got:
        e = check(x['jp'], got[x['i']])
        if e:
            problems.append((x['i'], e, x['jp'], got[x['i']]))
print(f'묶음 {n}: 원문 {len(src)}, 번역 {len(got)}, 누락 {len(missing)}, 잘못된 번호 {len(extra)}, 문제 {len(problems)}, JSON 오류 파일 {len(bad_files)}')
for b in bad_files:
    print('  JSON 오류:', b)
if missing:
    print('  누락 번호:', missing[:200], '...' if len(missing) > 200 else '')
if extra:
    print('  원문에 없는 번호:', extra[:50])
for i, e, jp, ko in problems[:80]:
    print(f'  #{i}: {"; ".join(e)}\n     JP: {json.dumps(jp, ensure_ascii=True)}\n     KO: {json.dumps(ko, ensure_ascii=True)}')
if not (missing or extra or problems or bad_files):
    print('  이상 없음')
