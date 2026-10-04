"""JFNT 한글 폰트 빌드

  python font_tool.py roundtrip             원본 그대로 재구성 -> 바이트 일치 확인 (JFNT/jIMG/CRC/jARC 구조 검증)
  python font_tool.py calibrate             원본 글리프로 외곽선 반경 추정
  python font_tool.py build [문자목록.txt]   원본 글리프 + 추가 문자 -> build/content/fonts/*.jfnt, font_data.jarc
                                            (기본 문자목록: build/used_chars.txt)
"""
import os, sys, struct, zlib, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from wfu_lib import *
from gtx_lib import *
from wfu_pack import jarc_read, jarc_write, jcmp_compress

KO_FONT = r'C:\Windows\Fonts\NotoSansKR-VF.ttf'
FONTS_REL = 'fonts'
OUT_DIR = os.path.join(BUILD, 'content', 'fonts')
OUTLINE_RADIUS = 3  # calibrate 결과로 조정
SS = 4  # 슈퍼샘플링 배율


# ---------------------------------------------------------------- 파일 구조
def jimg_bytes(orig, gtx, tex_h):
    d = orig.raw; j = orig.jimg_off
    h = bytearray(d[j:j + 0x80])
    total = 0x80 + len(gtx); total += (-total) % 0x100
    struct.pack_into('>I', h, 4, total)
    struct.pack_into('>H', h, 0x0A, tex_h)
    struct.pack_into('>I', h, 0x14, len(gtx))
    out = bytearray(h) + gtx + b'\0' * (total - 0x80 - len(gtx))
    out[0x1C:0x24] = b'\0' * 8
    struct.pack_into('>I', out, 0x1C, zlib.crc32(out))
    out[0x20:0x24] = d[j + 0x20:j + 0x24]  # 미확인 필드: 원본 유지
    return bytes(out)


def jfnt_bytes(orig, codes, widths, gtx, tex_h, ranges=None):
    if ranges is None:
        ranges = []
        for gi, c in enumerate(codes):
            if ranges and c == ranges[-1][1] + 1:
                ranges[-1][1] = c
            else:
                ranges.append([c, c, gi])
    body = bytearray(orig.raw[:0x0C]) + struct.pack('>H', len(ranges))
    for s, e, g in ranges:
        body += struct.pack('>HHH', s, e, g)
    body += struct.pack('>H', len(codes)) + bytes(widths)
    body += b'\0' * ((-len(body)) % 0x80)
    return bytes(body) + jimg_bytes(orig, gtx, tex_h)


def gtx_rebuild(g, tex_h, image_bytes):
    info = gtx_parse(g)
    sb = info['surf_blk']['data']; ib = info['img_blk']
    out = bytearray(g[:ib['data']])
    struct.pack_into('>I', out, sb + 0x08, tex_h)                 # height
    struct.pack_into('>I', out, sb + 0x20, len(image_bytes))      # imageSize
    reg1 = struct.unpack_from('>I', out, sb + 0x8C)[0]
    struct.pack_into('>I', out, sb + 0x8C, (reg1 & ~0x1FFF) | ((tex_h - 1) & 0x1FFF))
    struct.pack_into('>I', out, ib['hdr'] + 0x14, len(image_bytes))
    return bytes(out) + image_bytes + g[ib['data'] + ib['size']:]


# ---------------------------------------------------------------- 아틀라스
def encode_atlas(ch0, ch1, pitch):
    H, W = ch0.shape
    bh = -(-H // 4); rows = -(-bh // 16) * 16
    pad = lambda a: np.pad(a, ((0, rows * 4 - H), (0, pitch * 4 - W)))
    b0 = bc4_encode_blocks(pad(ch0)); b1 = bc4_encode_blocks(pad(ch1))
    return swizzle(np.concatenate([b0, b1], axis=-1))


def dilate(img, r):
    out = img.copy()
    ys, xs = np.mgrid[-r:r + 1, -r:r + 1]
    for dy, dx in zip(ys.ravel(), xs.ravel()):
        if dy * dy + dx * dx > r * r + r:
            continue
        sh = np.roll(np.roll(img, dy, 0), dx, 1)
        if dy > 0: sh[:dy] = 0
        if dy < 0: sh[dy:] = 0
        if dx > 0: sh[:, :dx] = 0
        if dx < 0: sh[:, dx:] = 0
        np.maximum(out, sh, out=out)
    return out


def glyph_cells(f):
    chans, info = decode_surface(f.gtx)
    ch0, ch1 = chans[0], chans[1]
    cells = {}
    for code, g in f.charmap.items():
        x, y, w, h = f.cell_box(g)
        cells[code] = (ch0[y:y + h, x:x + w].copy(), ch1[y:y + h, x:x + w].copy(), f.widths[g])
    return cells, info


def ink_box(a, th=128):
    ys, xs = np.nonzero(a > th)
    return (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())) if len(xs) else None


class HangulRenderer:
    REF = '한국어글뷁빼앎'

    def __init__(self, f, cells, weight):
        self.f = f
        ref = None
        cand = [ord(c) for c in '国会あア'] + [c for c in sorted(cells) if 0x4E00 <= c <= 0x9FFF] + \
               [c for c in sorted(cells) if 0x3041 <= c <= 0x30FF and chr(c) not in 'ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮー゛゜・']
        for code in cand:
            if code in cells and ink_box(cells[code][0]) is not None:
                ref = ink_box(cells[code][0]); self.ref_width = cells[code][2]; break
        if ref is None:
            raise ValueError('기준 글리프(국/あ) 없음')
        self.box = ref  # x0, x1, y0, y1 (셀 좌표)
        tgt_h = ref[3] - ref[2] + 1
        size = tgt_h * SS
        for _ in range(3):
            font = ImageFont.truetype(KO_FONT, size)
            try:
                font.set_variation_by_axes([weight])
            except Exception:
                pass
            bb = self._union_bbox(font)
            size = max(8, int(round(size * tgt_h * SS / (bb[3] - bb[1]))))
        self.font = ImageFont.truetype(KO_FONT, size)
        try:
            self.font.set_variation_by_axes([weight])
        except Exception:
            pass
        bb = self._union_bbox(self.font)
        cx = (ref[0] + ref[1] + 1) / 2 * SS; top = ref[2] * SS
        self.ox = cx - (bb[0] + bb[2]) / 2
        self.oy = top - bb[1]

    def _union_bbox(self, font):
        bbs = [font.getbbox(c) for c in self.REF]
        return (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))

    def render(self, ch, shear=0.0):
        f = self.f
        W, H = f.cell_w * SS, f.cell_h * SS
        im = Image.new('L', (W, H), 0)
        ImageDraw.Draw(im).text((self.ox, self.oy), ch, fill=255, font=self.font)
        if shear:  # 기울임체 폰트(_I): 위쪽이 오른쪽으로 기울도록
            im = im.transform((W, H), Image.AFFINE, (1, shear, -shear * H / 2, 0, 1, 0), resample=Image.BICUBIC)
        small = np.asarray(im.resize((f.cell_w, f.cell_h), Image.LANCZOS))
        return small.astype(np.uint8)


def build_font(name, extra_chars, image_override=None):
    src = src_content(os.path.join(FONTS_REL, name))
    f = JFNT(open(src, 'rb').read())
    if image_override is not None:  # roundtrip: 원본 그대로
        info = gtx_parse(f.gtx)
        codes = [c for c, _ in sorted(f.charmap.items(), key=lambda kv: kv[1])]
        return jfnt_bytes(f, codes, f.widths, f.gtx, info['surf']['height'], ranges=[list(r) for r in f.ranges]), 0
    cells, info = glyph_cells(f)
    # 공백류는 원본 폰트에도 없음(엔진이 폭 처리) -> 추가하지 않음
    # 한자·가나는 추가하지 않음(원본 폰트 서브셋 유지, 텍스처 용량 폭증 방지)
    def addable(c):
        o = ord(c)
        return (o not in cells and not c.isspace() and o >= 0x20
                and not (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xE000 <= o <= 0xF8FF or 0xFF65 <= o <= 0xFF9F))
    add = sorted({ord(c) for c in extra_chars if addable(c)})
    if add:
        weight = 800 if '_EB' in name else 700
        rnd = HangulRenderer(f, cells, weight)
        shear = 0.2 if name.endswith('_I.jfnt') else 0.0
        for c in add:
            g0 = rnd.render(chr(c), shear)
            g1 = dilate(g0, OUTLINE_RADIUS)
            cells[c] = (g0, g1, rnd.ref_width)
    codes = sorted(cells)
    n = len(codes); cols = f.cols
    rows = -(-n // cols)
    s = info['surf']
    W = s['width']; H = rows * f.cell_h
    ch0 = np.zeros((H, W), np.uint8); ch1 = np.zeros((H, W), np.uint8)
    widths = []
    for gi, c in enumerate(codes):
        r, cc = divmod(gi, cols)
        x, y = cc * f.cell_w, r * f.cell_h
        a0, a1, wd = cells[c]
        ch0[y:y + f.cell_h, x:x + f.cell_w] = a0
        ch1[y:y + f.cell_h, x:x + f.cell_w] = a1
        widths.append(wd)
    img = encode_atlas(ch0, ch1, s['pitch'])
    gtx = gtx_rebuild(f.gtx, H, img)
    return jfnt_bytes(f, codes, widths, gtx, H), len(add)


def font_names():
    return sorted(n for n in os.listdir(os.path.join(UPD, FONTS_REL)) if n.endswith('.jfnt'))


def has_kana(name):
    f = JFNT(open(src_content(os.path.join(FONTS_REL, name)), 'rb').read())
    return any(0x3040 <= c <= 0x30FF for c in f.charmap)


# ---------------------------------------------------------------- 명령
def roundtrip():
    ok_all = True
    for name in font_names():
        orig = open(src_content(os.path.join(FONTS_REL, name)), 'rb').read()
        rebuilt, _ = build_font(name, '', image_override=True)
        same = rebuilt == orig
        ok_all &= same
        print(f'   {name:28} JFNT 재구성 일치: {same}')
        if not same:
            k = next((i for i in range(min(len(orig), len(rebuilt))) if orig[i] != rebuilt[i]), None)
            print(f'      첫 차이 @ {k:#x} len {len(rebuilt)} vs {len(orig)}')
    # GTX 재조립(같은 이미지) 일치
    f = JFNT(open(src_content(os.path.join(FONTS_REL, 'style_font_DB_3_I.jfnt')), 'rb').read())
    info = gtx_parse(f.gtx)
    img = f.gtx[info['img_blk']['data']:info['img_blk']['data'] + info['img_blk']['size']]
    print('   GTX 재조립 일치:', gtx_rebuild(f.gtx, info['surf']['height'], img) == f.gtx)
    # swizzle 왕복
    lin = deswizzle(img, info['surf']['pitch'], 16)
    print('   swizzle 왕복 일치:', swizzle(lin) == img)
    fd = open(src_content(os.path.join(FONTS_REL, 'font_data.jarc')), 'rb').read()
    ver, ents = jarc_read(fd)
    print('   jARC 재구성 일치:', jarc_write(ver, ents) == fd)
    e = ents[1][1]
    re_c = jcmp_compress(jcmp_decompress(e), e[8:12])
    print(f'   jCMP 재압축 일치: {re_c == e} (다르더라도 해제 결과만 같으면 무방: {jcmp_decompress(re_c) == jcmp_decompress(e)})')


def calibrate():
    f = JFNT(open(src_content(os.path.join(FONTS_REL, 'style_font_DB_3_S.jfnt')), 'rb').read())
    cells, _ = glyph_cells(f)
    sample = [cells[ord(c)] for c in 'あアカ国会話体重測定日本語' if ord(c) in cells]
    for r in range(1, 7):
        err = np.mean([np.abs(dilate(a0, r).astype(int) - a1.astype(int)).mean() for a0, a1, _ in sample])
        print(f'   외곽선 반경 {r}: 평균오차 {err:.2f}')


def build():
    chars_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BUILD, 'used_chars.txt')
    extra = open(chars_path, encoding='utf-8').read()
    os.makedirs(OUT_DIR, exist_ok=True)
    fd = open(src_content(os.path.join(FONTS_REL, 'font_data.jarc')), 'rb').read()
    ver, ents = jarc_read(fd)
    for name in font_names():
        if not has_kana(name):
            print(f'   {name:28} (가나 없음: 건너뜀)'); continue
        data, n_add = build_font(name, extra)
        open(os.path.join(OUT_DIR, name), 'wb').write(data)
        for e in ents:
            if e[0] == name:
                e[1] = jcmp_compress(data, e[1][8:12])
        print(f'   {name:28} 추가 {n_add}자 -> {len(data)} bytes')
    open(os.path.join(OUT_DIR, 'font_data.jarc'), 'wb').write(jarc_write(ver, ents))
    print(f'   font_data.jarc 갱신 -> {OUT_DIR}')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    {'roundtrip': roundtrip, 'calibrate': calibrate, 'build': build}.get(cmd, lambda: print(__doc__))()
