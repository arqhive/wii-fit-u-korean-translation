"""Wii U GTX 텍스처 + JFNT 폰트 라이브러리

- GTX(Gfx2) 파싱, 표면 정보
- tileMode 4 (2D tiled thin1) swizzle/deswizzle: 매크로타일 32x16 블록, 내부 저장 인덱스 비트
  [y0, x0, x1, x2, x3^y3, x3^y5, x4^y4, y1, y2]  (블록 좌표 기준, 원본 폰트 아틀라스로 검증)
- BC4 / BC5 디코드·인코드 (numpy)
- JFNT 파싱: 문자 범위표, 폭표, 셀 그리드(열 수·패딩), 내장 jIMG(GTX)
"""
import struct
import numpy as np

GTX_FIELDS = ['dim', 'width', 'height', 'depth', 'numMips', 'format', 'aa', 'use', 'imageSize', 'imagePtr',
              'mipSize', 'mipPtr', 'tileMode', 'swizzle', 'alignment', 'pitch']
FMT_BC4, FMT_BC5 = 0x34, 0x35


# ---------------------------------------------------------------- GTX
def gtx_parse(g):
    assert g[:4] == b'Gfx2', 'not GTX'
    hs = struct.unpack('>I', g[4:8])[0]
    pos = hs; blocks = []
    while pos + 0x20 <= len(g):
        mg, bhs, _, _, typ, dsz, _, _ = struct.unpack('>4s7I', g[pos:pos + 0x20])
        if mg != b'BLK{':
            break
        blocks.append(dict(type=typ, hdr=pos, data=pos + bhs, size=dsz))
        pos += bhs + dsz
    surf_blk = next(b for b in blocks if b['type'] == 0x0B)
    surf = dict(zip(GTX_FIELDS, struct.unpack('>16I', g[surf_blk['data']:surf_blk['data'] + 64])))
    img_blk = next(b for b in blocks if b['type'] == 0x0C)
    return dict(blocks=blocks, surf=surf, surf_blk=surf_blk, img_blk=img_blk)


def bytes_per_block(fmt):
    return {FMT_BC4: 8, FMT_BC5: 16}[fmt]


# ---------------------------------------------------------------- tileMode 4 swizzle
def _storage_index_rgba8(xb, yb):
    """32bpp(픽셀당 4바이트) tileMode4: [x0,x1,y0,x2,y1,y2, pipe, bank0, bank1] (달력 텍스처로 검증)"""
    b = lambda v, i: (v >> i) & 1
    order = [b(xb, 0), b(xb, 1), b(yb, 0), b(xb, 2), b(yb, 1), b(yb, 2),
             b(xb, 3) ^ b(yb, 3), b(xb, 3) ^ b(yb, 5), b(xb, 4) ^ b(yb, 4)]
    idx = np.zeros_like(xb)
    for pos, bit in enumerate(order):
        idx |= bit << pos
    return idx


def _storage_index(xb, yb, bpb):
    """블록 좌표 -> 매크로타일 내 저장 인덱스(9비트). pipe/bank 3비트는 바이트 주소 256 위치에 삽입되므로
    16바이트 블록(BC3/BC5)은 4번째, 8바이트 블록(BC1/BC4)은 5번째 비트에 들어감 (원본 텍스처로 검증)"""
    b = lambda v, i: (v >> i) & 1
    pipe_bank = [b(xb, 3) ^ b(yb, 3), b(xb, 3) ^ b(yb, 5), b(xb, 4) ^ b(yb, 4)]
    if bpb == 4:
        return _storage_index_rgba8(xb, yb)
    if bpb == 16:
        order = [b(yb, 0), b(xb, 0), b(xb, 1), b(xb, 2)] + pipe_bank + [b(yb, 1), b(yb, 2)]
    elif bpb == 8:
        order = [b(xb, 0), b(yb, 0), b(xb, 1), b(xb, 2), b(yb, 1)] + pipe_bank + [b(yb, 2)]
    else:
        raise NotImplementedError(f'block size {bpb}')
    idx = np.zeros_like(xb)
    for pos, bit in enumerate(order):
        idx |= bit << pos
    return idx


def tm4_addr(pitch, rows, bpb):
    yb, xb = np.mgrid[0:rows, 0:pitch]
    return ((xb // 32) + (pitch // 32) * (yb // 16)) * 512 + _storage_index(xb, yb, bpb)


def deswizzle(data, pitch, bpb):
    rows = len(data) // bpb // pitch
    blocks = np.frombuffer(data[:rows * pitch * bpb], np.uint8).reshape(-1, bpb)
    return blocks[tm4_addr(pitch, rows, bpb).reshape(-1)].reshape(rows, pitch, bpb)


def swizzle(linear):
    """linear: (rows, pitch, bpb) -> bytes (저장 순서)"""
    rows, pitch, bpb = linear.shape
    out = np.zeros((rows * pitch, bpb), np.uint8)
    out[tm4_addr(pitch, rows, bpb).reshape(-1)] = linear.reshape(-1, bpb)
    return out.tobytes()


# ---------------------------------------------------------------- BC4 / BC5
def _bc4_palette(r0, r1):
    r0 = r0.astype(np.int32); r1 = r1.astype(np.int32)
    pal = np.zeros(r0.shape + (8,), np.int32)
    pal[..., 0] = r0; pal[..., 1] = r1
    big = r0 > r1
    for k in range(2, 8):
        pal[..., k] = np.where(big, ((8 - k) * r0 + (k - 1) * r1) // 7, 0)
    for k in range(2, 6):
        pal[..., k] = np.where(big, pal[..., k], ((6 - k) * r0 + (k - 1) * r1) // 5)
    pal[..., 6] = np.where(big, pal[..., 6], 0)
    pal[..., 7] = np.where(big, pal[..., 7], 255)
    return pal


def bc4_decode_blocks(blk):
    """blk: (bh, bw, 8) uint8 -> (bh*4, bw*4) uint8"""
    bh, bw, _ = blk.shape
    out = np.zeros((bh * 4, bw * 4), np.uint8)
    step = 256
    for r in range(0, bh, step):
        b = blk[r:r + step].astype(np.int64)
        n = b.shape[0]
        pal = _bc4_palette(b[..., 0], b[..., 1])
        allbits = np.zeros(b.shape[:2], np.int64)
        for i in range(6):
            allbits |= b[..., 2 + i] << (8 * i)
        idx = np.stack([(allbits >> (3 * k)) & 7 for k in range(16)], axis=-1)
        px = np.take_along_axis(pal, idx, axis=2).reshape(n, bw, 4, 4).transpose(0, 2, 1, 3).reshape(n * 4, bw * 4)
        out[r * 4:(r + n) * 4] = px.astype(np.uint8)
    return out


def bc4_encode_blocks(img):
    """img: (H, W) uint8, H/W 는 4의 배수 -> (H/4, W/4, 8) uint8"""
    H, W = img.shape
    bh, bw = H // 4, W // 4
    out = np.zeros((bh, bw, 8), np.uint8)
    step = 256
    for r in range(0, bh, step):
        n = min(step, bh - r)
        px = img[r * 4:(r + n) * 4].reshape(n, 4, bw, 4).transpose(0, 2, 1, 3).reshape(n, bw, 16).astype(np.int32)
        hi = px.max(-1); lo = px.min(-1)
        r0 = hi.copy(); r1 = lo.copy()
        flat = r0 == r1
        r1 = np.where(flat & (r0 > 0), r0 - 1, r1)
        r0 = np.where(flat & (r0 == 0), 1, r0)  # r0 > r1 보장 (8단계 모드)
        pal = _bc4_palette(r0, r1)
        dist = np.abs(px[..., :, None] - pal[..., None, :])
        idx = dist.argmin(-1).astype(np.int64)
        allbits = np.zeros((n, bw), np.int64)
        for k in range(16):
            allbits |= idx[..., k] << (3 * k)
        out[r:r + n, :, 0] = r0; out[r:r + n, :, 1] = r1
        for i in range(6):
            out[r:r + n, :, 2 + i] = (allbits >> (8 * i)) & 0xFF
    return out


def bc1_decode_blocks(blk):
    """blk: (bh, bw, 8) BC1 컬러 블록 -> (bh*4, bw*4, 3) RGB uint8 (BC3용: 항상 4색 모드)"""
    bh, bw, _ = blk.shape
    b = blk.astype(np.int32)
    c0 = b[..., 0] | (b[..., 1] << 8); c1 = b[..., 2] | (b[..., 3] << 8)
    def rgb(c):
        r = (c >> 11) & 31; g = (c >> 5) & 63; bl = c & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (bl << 3) | (bl >> 2)], -1)
    p0, p1 = rgb(c0), rgb(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], axis=2)  # (bh,bw,4,3)
    bits = b[..., 4] | (b[..., 5] << 8) | (b[..., 6] << 16) | (b[..., 7] << 24)
    idx = np.stack([(bits >> (2 * k)) & 3 for k in range(16)], -1)  # (bh,bw,16)
    px = np.take_along_axis(pal, idx[..., None].repeat(3, -1), axis=2)  # (bh,bw,16,3)
    return px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 3).astype(np.uint8)


def decode_surface(gtx_bytes):
    """-> BC4/BC5: 채널 이미지 리스트 / BC3: [RGBA 이미지]  (width x height)"""
    info = gtx_parse(gtx_bytes)
    s = info['surf']
    data = gtx_bytes[info['img_blk']['data']:info['img_blk']['data'] + info['img_blk']['size']]
    if s['tileMode'] != 4:
        raise NotImplementedError(f"tileMode {s['tileMode']}")
    fmt = s['format'] & 0xFF
    bw, bh = (s['width'] + 3) // 4, (s['height'] + 3) // 4
    if fmt == 0x1A:  # RGBA8: 블록 압축 아님, 픽셀 단위 4바이트
        lin = deswizzle(data, s['pitch'], 4)
        return [np.ascontiguousarray(lin[:s['height'], :s['width'], :])], info
    if fmt == 0x31:  # BC1: 컬러 8바이트 (알파 없음으로 취급)
        lin = deswizzle(data, s['pitch'], 8)
        rgb = bc1_decode_blocks(np.ascontiguousarray(lin[:bh, :bw, 0:8]))[:s['height'], :s['width']]
        return [rgb], info
    if fmt == 0x32:  # BC2: 알파 4비트(8바이트) + 컬러(BC1) 8바이트
        lin = deswizzle(data, s['pitch'], 16)
        blk = np.ascontiguousarray(lin[:bh, :bw, 0:8]).astype(np.uint16)
        bits = np.zeros((bh, bw, 16), np.uint8)
        for k in range(16):
            byte = blk[..., k // 2]
            bits[..., k] = np.where(k % 2 == 0, byte & 0xF, byte >> 4).astype(np.uint8)
        a = (bits * 17).reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
        rgb = bc1_decode_blocks(np.ascontiguousarray(lin[:bh, :bw, 8:16]))
        return [np.dstack([rgb, a])[:s['height'], :s['width']]], info
    if fmt == 0x33:  # BC3: 알파(BC4식) 8바이트 + 컬러(BC1) 8바이트
        lin = deswizzle(data, s['pitch'], 16)
        a = bc4_decode_blocks(np.ascontiguousarray(lin[:bh, :bw, 0:8]))
        rgb = bc1_decode_blocks(np.ascontiguousarray(lin[:bh, :bw, 8:16]))
        rgba = np.dstack([rgb, a])[:s['height'], :s['width']]
        return [rgba], info
    bpb = bytes_per_block(s['format'])
    lin = deswizzle(data, s['pitch'], bpb)
    chans = []
    for c in range(bpb // 8):
        img = bc4_decode_blocks(np.ascontiguousarray(lin[:bh, :bw, 8 * c:8 * (c + 1)]))
        chans.append(img[:s['height'], :s['width']])
    return chans, info


# ---------------------------------------------------------------- JFNT
class JFNT:
    def __init__(self, d):
        assert d[:4] == b'JFNT'
        self.raw = d
        self.magic2 = d[4:8]                     # 00 8b 54 42 (모든 폰트 공통)
        self.max_w, self.height, self.cols, self.pad = d[8], d[9], d[10], d[11]
        n = struct.unpack('>H', d[0x0C:0x0E])[0]
        self.ranges = [struct.unpack('>HHH', d[0x0E + i * 6:0x14 + i * 6]) for i in range(n)]
        end = 0x0E + n * 6
        self.count = struct.unpack('>H', d[end:end + 2])[0]
        self.widths = list(d[end + 2:end + 2 + self.count])
        self.jimg_off = d.find(b'jIMG', end + 2 + self.count)
        j = self.jimg_off
        self.gtx_off = j + struct.unpack('>I', d[j + 0x10:j + 0x14])[0]
        self.gtx_len = struct.unpack('>I', d[j + 0x14:j + 0x18])[0]
        self.gtx = d[self.gtx_off:self.gtx_off + self.gtx_len]
        self.cell_w = self.max_w + self.pad
        self.cell_h = self.height + self.pad
        self.charmap = {}
        for s, e, g in self.ranges:
            for c in range(s, e + 1):
                self.charmap[c] = g + (c - s)

    def cell_box(self, glyph):
        r, c = divmod(glyph, self.cols)
        return c * self.cell_w, r * self.cell_h, self.cell_w, self.cell_h
