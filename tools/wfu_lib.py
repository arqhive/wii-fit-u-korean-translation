"""Wii Fit U (JP) 한글화 공용 라이브러리: Yaz0 / U8 / jCMP / jARC / BMG"""
import struct, zlib, sys, os
from wfu_pack import jcmp_decompress, jcmp_compress

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_title(kind):
    """폴더 이름이 'Wii Fit U Game' 이든 'Wii Fit U [Game] [0005000010102200]' 이든 찾는다"""
    want = '0005000e' if kind == 'update' else '00050000'
    cands = []
    for name in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, name)
        if not os.path.isdir(d) or not os.path.isdir(os.path.join(d, 'content')):
            continue
        low = name.lower()
        if kind == 'update' and ('update' in low or want in low):
            cands.append(d)
        elif kind == 'game' and 'update' not in low and ('game' in low or want in low):
            cands.append(d)
    if not cands:
        raise SystemExit(f'{kind} 폴더를 찾지 못했습니다. 복호화한 게임 폴더(code/content/meta)를 {ROOT} 아래에 두세요.')
    return os.path.join(cands[0], 'content')


GAME = _find_title('game')
UPD = _find_title('update')
BUILD = os.path.join(ROOT, 'build')


def src_content(rel):
    """업데이트에 있으면 업데이트 파일, 없으면 본편 파일 경로"""
    p = os.path.join(UPD, rel)
    return p if os.path.exists(p) else os.path.join(GAME, rel)


# ---------------------------------------------------------------- Yaz0
def yaz0_decompress(d):
    assert d[:4] == b'Yaz0', 'not Yaz0'
    size = struct.unpack('>I', d[4:8])[0]
    out = bytearray(); src = 16
    while len(out) < size:
        code = d[src]; src += 1
        for i in range(8):
            if len(out) >= size:
                break
            if code & (0x80 >> i):
                out.append(d[src]); src += 1
            else:
                b1, b2 = d[src], d[src + 1]; src += 2
                dist = ((b1 & 0xF) << 8 | b2) + 1
                n = b1 >> 4
                if n == 0:
                    n = d[src] + 0x12; src += 1
                else:
                    n += 2
                for _ in range(n):
                    out.append(out[-dist])
    return bytes(out)


def yaz0_compress(src, max_cands=48):
    n = len(src)
    out = bytearray(b'Yaz0' + struct.pack('>I', n) + b'\0' * 8)
    table = {}

    def add(p):
        if p + 3 <= n:
            lst = table.setdefault(src[p:p + 3], [])
            lst.append(p)
            if len(lst) > max_cands:
                del lst[0]

    pos = 0
    while pos < n:
        code_pos = len(out); out.append(0); code = 0
        for bit in range(8):
            if pos >= n:
                break
            best_len = 0; best_dist = 0
            if pos + 3 <= n:
                cands = table.get(src[pos:pos + 3])
                if cands:
                    maxl = min(0x111, n - pos)
                    for c in reversed(cands):
                        if pos - c > 0x1000:
                            break
                        l = 3
                        while l < maxl and src[c + l] == src[pos + l]:
                            l += 1
                        if l > best_len:
                            best_len, best_dist = l, pos - c
                            if l == maxl:
                                break
            if best_len >= 3:
                dd = best_dist - 1
                if best_len >= 0x12:
                    out += bytes([(dd >> 8) & 0xF, dd & 0xFF, best_len - 0x12])
                else:
                    out += bytes([((best_len - 2) << 4) | ((dd >> 8) & 0xF), dd & 0xFF])
                for k in range(best_len):
                    add(pos + k)
                pos += best_len
            else:
                code |= 0x80 >> bit
                out.append(src[pos]); add(pos); pos += 1
        out[code_pos] = code
    return bytes(out)


# ---------------------------------------------------------------- U8
def u8_read(d):
    """-> list of (path, bytes). 디렉터리는 경로에 포함"""
    assert d[:4] == b'\x55\xAA\x38\x2D', 'not U8'
    root = struct.unpack('>I', d[4:8])[0]
    total = struct.unpack('>I', d[root + 8:root + 12])[0]
    strtab = root + total * 12
    files = []; dirs = []
    for i in range(1, total):
        while dirs and i >= dirs[-1][0]:
            dirs.pop()
        o = root + i * 12
        t = d[o]; no = int.from_bytes(d[o + 1:o + 4], 'big')
        a, b = struct.unpack('>II', d[o + 4:o + 12])
        name = d[strtab + no:d.index(b'\0', strtab + no)].decode('ascii')
        prefix = dirs[-1][1] if dirs else ''
        if t == 1:
            dirs.append((b, prefix + name + '/'))
        else:
            files.append((prefix + name, d[a:a + b]))
    return files


def u8_write(files, align=0x20):
    """files: list of (path, bytes) — 원본 순서 유지"""
    # 트리 구성
    tree = {}
    for path, data in files:
        parts = path.split('/')
        node = tree
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = data
    nodes = []; names = bytearray(b'\0')

    def name_off(s):
        o = len(names); names.extend(s.encode('ascii') + b'\0'); return o

    datas = []

    def walk(node, parent):
        for k, v in node.items():
            if isinstance(v, dict):
                idx = len(nodes); nodes.append(['d', name_off(k), parent, 0])
                walk(v, idx)
                nodes[idx][3] = len(nodes)
            else:
                nodes.append(['f', name_off(k), v]); datas.append(len(nodes) - 1)

    nodes.append(['d', 0, 0, 0])
    walk(tree, 0)
    nodes[0][3] = len(nodes)
    hdr_size = len(nodes) * 12 + len(names)
    data_off = (0x20 + hdr_size + align - 1) // align * align
    blob = bytearray(); offs = {}
    for idx in datas:
        pos = data_off + len(blob)
        offs[idx] = pos
        blob += nodes[idx][2]
        if idx != datas[-1]:
            pad = (-len(blob)) % align
            blob += b'\0' * pad
    nt = bytearray()
    for i, nd in enumerate(nodes):
        if nd[0] == 'd':
            nt += bytes([1]) + nd[1].to_bytes(3, 'big') + struct.pack('>II', nd[2], nd[3])
        else:
            nt += bytes([0]) + nd[1].to_bytes(3, 'big') + struct.pack('>II', offs[i], len(nd[2]))
    head = b'\x55\xAA\x38\x2D' + struct.pack('>III', 0x20, hdr_size, data_off) + b'\0' * 16
    out = head + nt + names
    out += b'\0' * (data_off - len(out))
    return bytes(out + blob)


# ---------------------------------------------------------------- jCMP / jARC
def unpack_any(d):
    if d[:4] == b'Yaz0':
        return yaz0_decompress(d)
    if d[:4] == b'jCMP':
        return jcmp_decompress(d)
    return d
