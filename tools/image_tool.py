"""글자가 들어간 텍스처(jIMG/GTX) 한글화

  python image_tool.py dump        대상 텍스처 -> translation/images/<묶음>/<이름>.png
  python image_tool.py grid        좌표 격자 버전 -> translation/images/_grid/
  python image_tool.py render      translation/image_text.json 대로 글자 교체 -> translation/images_ko/
  python image_tool.py roundtrip   묶음 재포장·텍스처 재삽입(원본 이미지) 바이트 일치 검증
  python image_tool.py build       images_ko PNG -> BC 인코딩 -> build/content/... 묶음 파일
"""
import os, sys, struct, zlib, json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from wfu_lib import *
from gtx_lib import gtx_parse, decode_surface, deswizzle, swizzle, bc4_encode_blocks, bc1_decode_blocks
from wfu_pack import jarc_read, jarc_write, jcmp_compress, archive_align

IMG_DIR = os.path.join(ROOT, 'translation', 'images')
KO_DIR = os.path.join(ROOT, 'translation', 'images_ko')
SPEC = os.path.join(ROOT, 'translation', 'image_text.json')
# 텍스처 묶음: 항목 이름 필터(None = 전체)
TEX_ARCHIVES = {
    r'JP\ui\wev_tex.jarc': None,
    r'ui\mme_jpn_tex.jarc': None,
    r'ui\aot_tex.jarc': ['aot_stamp001_jpn.jtex'],
}
# 모델(jMDL) 안에 들어 있는 텍스처
MODEL_ARCHIVES = {
    r'ui\models_data.jarc': ['training_obj001_txt_jpn.jmdl'],
}
ARCHIVES = list(TEX_ARCHIVES) + list(MODEL_ARCHIVES)
# 묶음 안의 묶음: 달력 도장 (ui_fb_tex.jarc > com_tex.jarc)
_STAMP_NUMS = ('01', '11', '12', '13')  # 01=済, 11=すみ, 12=犬, 13=猫
NESTED_ARCHIVES = {
    'com_tex': dict(
        outer=r'ui\ui_fb_tex.jarc',
        inner='com_tex.jarc',
        names=[f'cld_te_check{p}_{n}.jtex' for n in _STAMP_NUMS for p in ('', '_L', '_filter_L')],
        # 글자를 넣지는 않지만 렌더에 필요해서 뽑아 두는 것(도장 잉크 얼룩)
        dump_extra=['cld_stampMura_00.jtex'],
    ),
}
FMT = {0x31: 'BC1', 0x33: 'BC3', 0x34: 'BC4', 0x35: 'BC5'}
KO_FONT_BOLD = r'C:\Windows\Fonts\NotoSansKR-VF.ttf'


# ---------------------------------------------------------------- jIMG
def jimg_gtx_range(d):
    assert d[:4] == b'jIMG'
    go = struct.unpack('>I', d[0x10:0x14])[0] & 0xFFFF  # 상위 바이트들은 플래그(0x11000080, 0x00010080 등)
    gl = struct.unpack('>I', d[0x14:0x18])[0]
    return go, gl


def jimg_gtx(d):
    go, gl = jimg_gtx_range(d)
    return d[go:go + gl]


def is_texture_jimg(d):
    try:
        return jimg_gtx(d)[:4] == b'Gfx2'
    except Exception:
        return False


def jimg_fix_crc(d):
    d = bytearray(d)
    size = struct.unpack('>I', d[4:8])[0]
    keep = d[0x20:0x24]
    d[0x1C:0x24] = b'\0' * 8
    struct.pack_into('>I', d, 0x1C, zlib.crc32(d[:size]))
    d[0x20:0x24] = keep
    return bytes(d)


def load_archive(rel):
    raw = open(src_content(rel), 'rb').read()
    outer_flags = raw[8:12] if raw[:4] == b'jCMP' else None
    d = unpack_any(raw)
    ver, ents = jarc_read(d)
    return raw, d, ver, ents, outer_flags


def arc_dir(rel):
    return os.path.splitext(os.path.basename(rel))[0]


def iter_targets(rel, ents):
    """-> (항목 이름, 이미지 키, 항목 안 jIMG 오프셋 또는 None)"""
    if rel in TEX_ARCHIVES:
        filt = TEX_ARCHIVES[rel]
        for name, data in ents:
            if (filt is None or name in filt) and data[:4] == b'jIMG':
                yield name, os.path.splitext(name)[0], None
    if rel in MODEL_ARCHIVES:
        for name, data in ents:
            if name not in MODEL_ARCHIVES[rel]:
                continue
            i = data.find(b'jIMG'); k = 0
            while i >= 0:
                size = struct.unpack('>I', data[i + 4:i + 8])[0]
                if is_texture_jimg(data[i:i + size]):
                    yield name, f'{os.path.splitext(name)[0]}__tex{k}', i
                    k += 1
                    i = data.find(b'jIMG', i + size)
                else:
                    i = data.find(b'jIMG', i + 4)


def load_nested(key):
    """-> (outer_raw, outer_ver, outer_ents, outer_flags, inner_ver, inner_ents)"""
    cfg = NESTED_ARCHIVES[key]
    raw, d, ver, ents, flags = load_archive(cfg['outer'])
    inner_raw = dict(ents)[cfg['inner']]
    iver, ients = jarc_read(unpack_any(inner_raw))
    return raw, ver, ents, flags, iver, ients


def rebuild_nested(key, replace):
    """중첩 묶음 재포장 -> 바깥 묶음 파일 bytes"""
    cfg = NESTED_ARCHIVES[key]
    raw, ver, ents, flags, iver, ients = load_nested(key)
    inner_new = [[n, replace.get(n, data)] for n, data in ients]
    inner_raw = dict(ents)[cfg['inner']]
    inner_bytes = jarc_write(iver, inner_new, align=archive_align(unpack_any(inner_raw)))
    if inner_raw[:4] == b'jCMP':  # 원본이 압축되어 있으면 같은 방식으로 다시 압축
        inner_bytes = jcmp_compress(inner_bytes, inner_raw[8:12])
    outer_new = [[n, inner_bytes if n == cfg['inner'] else data] for n, data in ents]
    arc = jarc_write(ver, outer_new, align=archive_align(unpack_any(raw)))
    return (jcmp_compress(arc, flags) if flags is not None else arc), raw, arc


def target_jimg(data, off):
    if off is None:
        return data
    size = struct.unpack('>I', data[off + 4:off + 8])[0]
    return data[off:off + size]


# ---------------------------------------------------------------- BC 인코더
def bc1_encode_blocks(rgb):
    """rgb: (H, W, 3) uint8, H/W 4의 배수 -> (H/4, W/4, 8), 항상 4색 모드(c0 > c1)"""
    H, W, _ = rgb.shape
    bh, bw = H // 4, W // 4
    px = rgb.reshape(bh, 4, bw, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh, bw, 16, 3).astype(np.float32)
    mean = px.mean(2, keepdims=True)
    cen = px - mean
    cov = np.einsum('abki,abkj->abij', cen, cen)
    axis = np.ones((bh, bw, 3), np.float32)
    for _ in range(6):
        axis = np.einsum('abij,abj->abi', cov, axis)
        axis /= np.linalg.norm(axis, axis=-1, keepdims=True) + 1e-6
    proj = np.einsum('abki,abi->abk', cen, axis)
    e0 = mean[:, :, 0] + axis * proj.max(2)[..., None]
    e1 = mean[:, :, 0] + axis * proj.min(2)[..., None]

    def to565(c):
        c = np.clip(np.rint(c), 0, 255).astype(np.int32)
        return ((c[..., 0] * 31 + 127) // 255 << 11) | ((c[..., 1] * 63 + 127) // 255 << 5) | ((c[..., 2] * 31 + 127) // 255)

    c0 = to565(e0); c1 = to565(e1)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    eq = c0 == c1
    c0 = np.where(eq & (c0 < 0xFFFF), c0 + 1, c0)
    c1 = np.where(eq & (c0 == 0xFFFF), c1 - 1, c1)
    blk = np.zeros((bh, bw, 8), np.uint8)
    blk[..., 0] = c0 & 0xFF; blk[..., 1] = c0 >> 8; blk[..., 2] = c1 & 0xFF; blk[..., 3] = c1 >> 8

    def rgb888(c):
        r = (c >> 11) & 31; g = (c >> 5) & 63; b = c & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.float32)

    p0, p1 = rgb888(c0), rgb888(c1)
    pal = np.stack([p0, p1, np.floor((2 * p0 + p1) / 3), np.floor((p0 + 2 * p1) / 3)], 2)
    dist = ((px[:, :, :, None, :] - pal[:, :, None, :, :]) ** 2).sum(-1)
    idx = dist.argmin(-1).astype(np.int64)
    bits = np.zeros((bh, bw), np.int64)
    for k in range(16):
        bits |= idx[..., k] << (2 * k)
    for i in range(4):
        blk[..., 4 + i] = (bits >> (8 * i)) & 0xFF
    return blk


def encode_texture_into(jimg, img):
    """jimg: 원본 jIMG bytes, img: RGB/RGBA ndarray (원본과 같은 크기) -> 새 jIMG bytes (같은 길이)"""
    go, gl = jimg_gtx_range(jimg)
    g = jimg[go:go + gl]
    info = gtx_parse(g)
    s = info['surf']; ib = info['img_blk']
    fmt = s['format'] & 0xFF
    bpb = 8 if fmt == 0x31 else 16
    data = g[ib['data']:ib['data'] + ib['size']]
    lin = deswizzle(data, s['pitch'], bpb).copy()
    W, H = s['width'], s['height']
    assert img.shape[0] == H and img.shape[1] == W, f'크기 불일치 {img.shape} vs {W}x{H}'
    bw, bh = -(-W // 4), -(-H // 4)
    pad = np.pad(img, ((0, bh * 4 - H), (0, bw * 4 - W), (0, 0)), mode='edge')
    if fmt == 0x31:
        lin[:bh, :bw, 0:8] = bc1_encode_blocks(pad[..., :3])
    elif fmt == 0x33:
        alpha = pad[..., 3] if pad.shape[2] == 4 else np.full(pad.shape[:2], 255, np.uint8)
        lin[:bh, :bw, 0:8] = bc4_encode_blocks(np.ascontiguousarray(alpha))
        lin[:bh, :bw, 8:16] = bc1_encode_blocks(np.ascontiguousarray(pad[..., :3]))
    elif fmt == 0x32:  # BC2: 알파 4비트 묶음 8바이트 + 컬러(BC1) 8바이트
        alpha = pad[..., 3] if pad.shape[2] == 4 else np.full(pad.shape[:2], 255, np.uint8)
        a4 = (alpha.astype(np.uint16) * 15 + 127) // 255
        a4 = a4.reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh, bw, 16).astype(np.uint8)
        packed = np.zeros((bh, bw, 8), np.uint8)
        for k in range(8):
            packed[..., k] = a4[..., 2 * k] | (a4[..., 2 * k + 1] << 4)
        lin[:bh, :bw, 0:8] = packed
        lin[:bh, :bw, 8:16] = bc1_encode_blocks(np.ascontiguousarray(pad[..., :3]))
    else:
        raise NotImplementedError(FMT.get(fmt, hex(fmt)))
    new_data = swizzle(lin)
    assert len(new_data) == len(data)
    abs_img = go + ib['data']
    out = bytearray(jimg)
    out[abs_img:abs_img + len(new_data)] = new_data
    return jimg_fix_crc(out)


# ---------------------------------------------------------------- 명령: dump / grid
def dump():
    for rel in ARCHIVES:
        _, _, ver, ents, _ = load_archive(rel)
        E = dict(ents)
        odir = os.path.join(IMG_DIR, arc_dir(rel)); os.makedirs(odir, exist_ok=True)
        for name, key, off in iter_targets(rel, ents):
            g = jimg_gtx(target_jimg(E[name], off))
            s = gtx_parse(g)['surf']
            img = decode_surface(g)[0][0]
            mode = {4: 'RGBA', 3: 'RGB'}[img.shape[2]]
            Image.fromarray(img, mode).save(os.path.join(odir, key + '.png'))
            print(f'   {arc_dir(rel)}/{key:40} {s["width"]}x{s["height"]} {FMT.get(s["format"] & 0xFF)}')
    for nkey, cfg in NESTED_ARCHIVES.items():
        odir = os.path.join(IMG_DIR, nkey); os.makedirs(odir, exist_ok=True)
        want = list(cfg['names']) + list(cfg.get('dump_extra', []))
        for name, data in load_nested(nkey)[5]:
            if name not in want:
                continue
            g = jimg_gtx(data)
            s = gtx_parse(g)['surf']
            chans, _ = decode_surface(g)
            base = os.path.splitext(name)[0]
            for i, img in enumerate(chans):
                # BC4/BC5 는 채널마다 따로 뽑는다(채널이 하나뿐이면 접미사 없이)
                mode = {4: 'RGBA', 3: 'RGB'}[img.shape[2]] if img.ndim == 3 else 'L'
                suffix = f'__ch{i}' if len(chans) > 1 else ''
                Image.fromarray(img, mode).save(os.path.join(odir, base + suffix + '.png'))
            print(f'   {nkey}/{name:40} {s["width"]}x{s["height"]} {FMT.get(s["format"] & 0xFF)}'
                  f'{" 채널 %d개" % len(chans) if len(chans) > 1 else ""}')


def grid():
    gdir = os.path.join(IMG_DIR, '_grid'); os.makedirs(gdir, exist_ok=True)
    font = ImageFont.truetype(r'C:\Windows\Fonts\malgun.ttf', 11)
    for rel in ARCHIVES:
        sub = os.path.join(IMG_DIR, arc_dir(rel))
        if not os.path.isdir(sub):
            continue
        for fn in sorted(os.listdir(sub)):
            im = Image.open(os.path.join(sub, fn)).convert('RGBA')
            bg = Image.new('RGBA', im.size, (128, 128, 128, 255)); bg.alpha_composite(im)
            dr = ImageDraw.Draw(bg)
            for x in range(0, im.width, 25):
                dr.line([(x, 0), (x, im.height)], fill=(255, 0, 0, 90 if x % 100 else 200), width=1)
                if x % 100 == 0:
                    dr.text((x + 2, 2), str(x), fill=(255, 0, 0, 255), font=font)
            for y in range(0, im.height, 25):
                dr.line([(0, y), (im.width, y)], fill=(0, 0, 255, 90 if y % 100 else 200), width=1)
                if y % 100 == 0:
                    dr.text((2, y + 2), str(y), fill=(0, 0, 255, 255), font=font)
            bg.convert('RGB').save(os.path.join(gdir, f'{arc_dir(rel)}__{fn}'))
    print('격자 이미지 저장:', gdir)


# ---------------------------------------------------------------- 명령: render
def _font(size, weight):
    f = ImageFont.truetype(KO_FONT_BOLD, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def _box_mask(shape, box, ellipse):
    x0, y0, x1, y1 = box
    mask = np.zeros(shape[:2], np.uint8)
    if ellipse:
        m = Image.new('L', (shape[1], shape[0]), 0)
        ImageDraw.Draw(m).ellipse([x0, y0, x1 - 1, y1 - 1], fill=255)
        mask = np.array(m)
    else:
        mask[y0:y1, x0:x1] = 255
    return mask


def _fill_box(arr, box, method, ellipse=False):
    x0, y0, x1, y1 = box
    if method == 'none':
        return
    mask = _box_mask(arr.shape, box, ellipse)
    sel = mask > 0
    if isinstance(method, list):  # 단색
        arr[sel, :len(method)] = method
        return
    if method == 'solid':  # 상자 바깥 테두리 2px의 중앙값 색으로 채우기
        ring = np.concatenate([arr[max(0, y0 - 2):y0, x0:x1, :3].reshape(-1, 3), arr[y1:y1 + 2, x0:x1, :3].reshape(-1, 3),
                               arr[y0:y1, max(0, x0 - 2):x0, :3].reshape(-1, 3), arr[y0:y1, x1:x1 + 2, :3].reshape(-1, 3)])
        arr[sel, :3] = np.median(ring, 0).astype(np.uint8)
        return
    import cv2
    rgb = np.ascontiguousarray(arr[..., :3])
    out = cv2.inpaint(rgb, mask, 5, cv2.INPAINT_TELEA)
    arr[sel, :3] = out[sel]


def _auto_colors(arr, box):
    x0, y0, x1, y1 = box
    ring = np.concatenate([arr[max(0, y0 - 2):y0, x0:x1, :3].reshape(-1, 3), arr[y1:y1 + 2, x0:x1, :3].reshape(-1, 3),
                           arr[y0:y1, max(0, x0 - 2):x0, :3].reshape(-1, 3), arr[y0:y1, x1:x1 + 2, :3].reshape(-1, 3)])
    bg = np.median(ring, 0) if len(ring) else np.array([255, 255, 255])
    inner = arr[y0:y1, x0:x1, :3].reshape(-1, 3).astype(int)
    d = np.abs(inner - bg).sum(1)
    fg = inner[d >= np.percentile(d, 97)].mean(0) if len(inner) else np.array([0, 0, 0])
    return tuple(int(v) for v in fg)


def _composite(arr, layer):
    base = Image.fromarray(arr, 'RGBA')
    base.alpha_composite(layer)
    return np.array(base)


def render_one(src_png, regions, dst_png):
    im = Image.open(src_png)
    mode = im.mode
    arr = np.array(im.convert('RGBA'))
    for r in regions:
        box = [int(v) for v in r['box']]
        x0, y0, x1, y1 = box
        if r.get('transparent', False):
            arr[y0:y1, x0:x1] = 0
        else:
            _fill_box(arr, box, r.get('bg', 'inpaint'), ellipse=r.get('shape') == 'ellipse')
        if 'segments' in r:  # 한 줄 여러 색: [[글자, [r,g,b]], ...] 왼쪽 정렬
            f = _font(int(r['size']), r.get('weight', 700))
            layer = Image.new('RGBA', (arr.shape[1], arr.shape[0]), (0, 0, 0, 0))
            dr = ImageDraw.Draw(layer)
            full = ''.join(t for t, _ in r['segments'])
            bb = dr.textbbox((0, 0), full, font=f)
            x = x0 - bb[0]; y = y0 + ((y1 - y0) - (bb[3] - bb[1])) / 2 - bb[1]
            for t, c in r['segments']:
                dr.text((x, y), t, font=f, fill=tuple(c) + (255,))
                x += dr.textlength(t, font=f)
            arr = _composite(arr, layer)
            continue
        text = r.get('text', '')
        if not text:
            continue
        color = tuple(r['color']) if r.get('color') else _auto_colors(arr, box)
        weight = r.get('weight', 700)
        bw, bh = x1 - x0, y1 - y0
        size = int(r.get('size', bh * 0.8))
        stroke = r.get('stroke', 0)
        lines = text.split('\n')
        while True:
            f = _font(size, weight)
            dr = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
            bbs = [dr.textbbox((0, 0), ln, font=f, stroke_width=stroke) for ln in lines]
            tw = max(b[2] - b[0] for b in bbs)
            lh = int(size * r.get('line_height', 1.2))
            th = lh * (len(lines) - 1) + (bbs[-1][3] - bbs[-1][1])
            if (tw <= bw * r.get('max_width', 1.0) and th <= bh * 1.05) or size <= 6:
                break
            size -= 1
        layer = Image.new('RGBA', (arr.shape[1], arr.shape[0]), (0, 0, 0, 0))
        dr = ImageDraw.Draw(layer)
        align = r.get('align', 'center')
        y = y0 + (bh - th) / 2
        for ln, b in zip(lines, bbs):
            w = b[2] - b[0]
            x = x0 - b[0] + (0 if align == 'left' else (bw - w) if align == 'right' else (bw - w) / 2)
            dr.text((x, y - b[1]), ln, font=f, fill=color + (255,), stroke_width=stroke,
                    stroke_fill=tuple(r.get('stroke_color', [255, 255, 255])) + (255,))
            y += lh
        if r.get('mura'):  # 도장 잉크 얼룩: 무라 텍스처를 글자 알파에 곱함
            mura_p = os.path.join(IMG_DIR, 'com_tex', 'cld_stampMura_00__ch1.png')
            m = Image.open(mura_p).convert('L').resize((arr.shape[1], arr.shape[0]), Image.BILINEAR)
            la = np.array(layer)
            ma = np.array(m).astype(np.float32) / 255.0
            ma = np.clip((ma - 0.55) / 0.45, 0, 1)  # 옅은 부분은 완전히 비우고 진한 부분만 남김
            la[..., 3] = (la[..., 3] * ma).astype(np.uint8)
            layer = Image.fromarray(la, 'RGBA')
        arr = _composite(arr, layer)
    out = Image.fromarray(arr, 'RGBA')
    if mode != 'RGBA':
        out = out.convert('RGB')
    os.makedirs(os.path.dirname(dst_png), exist_ok=True)
    out.save(dst_png)


def render():
    spec = json.load(open(SPEC, encoding='utf-8'))
    n = 0
    for key, regions in spec.items():
        if key.startswith('_'):
            continue
        sub, name = key.split('/')
        render_one(os.path.join(IMG_DIR, sub, name + '.png'), regions, os.path.join(KO_DIR, sub, name + '.png'))
        n += 1
    print(f'렌더 {n}장 -> {KO_DIR}')


# ---------------------------------------------------------------- 명령: roundtrip / build
def rebuild_archive(rel, replace):
    raw, d, ver, ents, flags = load_archive(rel)
    align = archive_align(d)
    new_ents = [[n, replace.get(n, data)] for n, data in ents]
    arc = jarc_write(ver, new_ents, align=align)
    return (jcmp_compress(arc, flags) if flags is not None else arc), raw, arc, d


def roundtrip():
    for rel in ARCHIVES:
        out, raw, arc, d = rebuild_archive(rel, {})
        print(f'   {rel}: jARC 재구성 일치 {arc == d}, 최종 파일 일치 {out == raw} (정렬 {archive_align(d):#x})')
        _, _, ver, ents, _ = load_archive(rel)
        E = dict(ents)
        for name, key, off in list(iter_targets(rel, ents))[:1]:
            j = target_jimg(E[name], off)
            img = decode_surface(jimg_gtx(j))[0][0]
            re_j = encode_texture_into(j, img)
            re_img = decode_surface(jimg_gtx(re_j))[0][0]
            err = np.abs(re_img.astype(int) - img.astype(int)).mean()
            print(f'      {key}: 재인코딩 평균오차 {err:.2f}, CRC 검증 {jimg_fix_crc(j) == j}')
    for nkey, cfg in NESTED_ARCHIVES.items():
        out, raw, arc = rebuild_nested(nkey, {})
        print(f'   {cfg["outer"]} > {cfg["inner"]}: 재구성 후 최종 파일 일치 {out == raw}')
        name, data = next((n, d) for n, d in load_nested(nkey)[5] if n in cfg['names'])
        img = decode_surface(jimg_gtx(data))[0][0]
        re_j = encode_texture_into(data, img)
        re_img = decode_surface(jimg_gtx(re_j))[0][0]
        print(f'      {name}: 재인코딩 평균오차 {np.abs(re_img.astype(int) - img.astype(int)).mean():.2f}')


def build():
    total = 0
    for rel in ARCHIVES:
        _, _, ver, ents, _ = load_archive(rel)
        E = dict(ents)
        patched = {}
        for name, key, off in iter_targets(rel, ents):
            p = os.path.join(KO_DIR, arc_dir(rel), key + '.png')
            if not os.path.exists(p):
                continue
            im = Image.open(p)
            arr = np.array(im.convert('RGBA' if im.mode == 'RGBA' else 'RGB'))
            buf = bytearray(patched.get(name, E[name]))
            j = target_jimg(bytes(buf), off)
            new_j = encode_texture_into(j, arr)
            start = 0 if off is None else off
            buf[start:start + len(new_j)] = new_j
            patched[name] = bytes(buf)
            total += 1
        if not patched:
            continue
        out, _, _, _ = rebuild_archive(rel, patched)
        dst = os.path.join(BUILD, 'content', rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, 'wb').write(out)
        print(f'   {rel}: 항목 {len(patched)}개 교체 -> {dst}')
    for nkey, cfg in NESTED_ARCHIVES.items():
        replace = {}
        for name, data in load_nested(nkey)[5]:
            if name not in cfg['names']:
                continue
            p = os.path.join(KO_DIR, nkey, os.path.splitext(name)[0] + '.png')
            if not os.path.exists(p):
                continue
            im = Image.open(p)
            arr = np.array(im.convert('RGBA' if im.mode == 'RGBA' else 'RGB'))
            replace[name] = encode_texture_into(data, arr)
        if not replace:
            continue
        out, _, _ = rebuild_nested(nkey, replace)
        dst = os.path.join(BUILD, 'content', cfg['outer'])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, 'wb').write(out)
        total += len(replace)
        print(f'   {cfg["outer"]} > {cfg["inner"]}: 항목 {len(replace)}개 교체 -> {dst}')
    print(f'텍스처 교체 {total}장')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    {'dump': dump, 'grid': grid, 'render': render, 'roundtrip': roundtrip, 'build': build}.get(cmd, lambda: print(__doc__))()
