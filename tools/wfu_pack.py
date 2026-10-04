"""jARC 묶음 · jCMP 압축만 다루는 최소 모듈 — 파이썬 기본 기능만 쓴다.

배포용 패처(patcher/lib/)가 이 파일을 그대로 복사해 쓴다. 그래서 numpy·PIL 같은
외부 라이브러리를 들이지 않고, 게임 폴더 위치도 알지 않는다(wfu_lib 와 다른 점).
"""
import struct, zlib


# ---------------------------------------------------------------- jCMP (zlib 묶음 포장)
def jcmp_decompress(d):
    assert d[:4] == b'jCMP'
    fsize, flags, csize, dsize = struct.unpack('>I4sII', d[4:0x14])
    u = zlib.decompress(d[0x14:0x14 + csize])
    assert len(u) == dsize
    return u


def jcmp_compress(raw, flags):
    level = flags[0] if 1 <= flags[0] <= 9 else 6
    c = zlib.compress(raw, level)
    return b'jCMP' + struct.pack('>I', 0x14 + len(c)) + flags + struct.pack('>II', len(c), len(raw)) + c


def jcmp_flags(d):
    """jCMP 로 포장돼 있으면 그 flags, 아니면 None"""
    return d[8:12] if d[:4] == b'jCMP' else None


# ---------------------------------------------------------------- jARC (묶음)
def jarc_read(d):
    assert d[:4] == b'jARC'
    size, ver, cnt = struct.unpack('>III', d[4:0x10])
    ents = []
    for i in range(cnt):
        off, sz, noff, h = struct.unpack('>IIII', d[0x10 + i * 16:0x20 + i * 16])
        ents.append([d[noff:d.index(b'\0', noff)].decode(), d[off:off + sz]])
    return ver, ents


def jarc_write(ver, ents, align=0x20):
    cnt = len(ents)
    names = bytearray(); noffs = []
    base = 0x10 + cnt * 16
    for n, _ in ents:
        noffs.append(base + len(names)); names += n.encode() + b'\0'
    pos = base + len(names); pos += (-pos) % align
    table = bytearray(); blob = bytearray(); offs = []
    for (n, data), no in zip(ents, noffs):
        offs.append(pos + len(blob))
        blob += data
        if n != ents[-1][0]:
            blob += b'\0' * ((-(pos + len(blob))) % align)
    for (n, data), no, off in zip(ents, noffs, offs):
        table += struct.pack('>IIII', off, len(data), no, zlib.crc32(n.encode()))
    head = bytearray(b'jARC' + struct.pack('>III', 0, ver, cnt)) + table + names
    head += b'\0' * (pos - len(head))
    out = head + blob
    struct.pack_into('>I', out, 4, len(out))
    return bytes(out)


def archive_align(d):
    """묶음이 항목을 몇 바이트 단위로 맞춰 두었는지 되읽는다(묶음마다 다르다)"""
    cnt = struct.unpack('>I', d[0x0C:0x10])[0]
    offs = [struct.unpack('>I', d[0x10 + i * 16:0x14 + i * 16])[0] for i in range(cnt)]
    a = 1 << 16
    while a > 1 and any(o % a for o in offs):
        a >>= 1
    return a


# ---------------------------------------------------------------- 묶음 다시 꾸리기
def rebuild(raw, replace):
    """묶음 바이트(jARC 또는 jCMP(jARC)) 안의 항목을 replace({이름: 새 바이트}) 로 갈아끼운다.

    값이 None 인 이름은 중첩 묶음 안을 고쳐야 한다는 뜻이 아니라 그대로 두라는 뜻이다.
    원래 jCMP 였으면 같은 flags 로 다시 압축한다(안 하면 파일이 몇 배로 부푼다).
    """
    flags = jcmp_flags(raw)
    inner = jcmp_decompress(raw) if flags is not None else raw
    ver, ents = jarc_read(inner)
    new = [[n, replace.get(n, data)] for n, data in ents]
    arc = jarc_write(ver, new, align=archive_align(inner))
    return jcmp_compress(arc, flags) if flags is not None else arc


def rebuild_keep_packing(raw, replace):
    """rebuild 와 같지만, 원래 항목이 jCMP 로 압축돼 있었으면 새 바이트도 같은 flags 로 압축한다.

    글꼴 묶음(font_data.jarc)은 안쪽 글꼴이 압축된 채 들어 있어서, 낱개 글꼴 파일을
    그대로 끼우면 안 된다.
    """
    inner = jcmp_decompress(raw) if raw[:4] == b'jCMP' else raw
    cur = dict(jarc_read(inner)[1])
    packed = {}
    for name, data in replace.items():
        flags = jcmp_flags(cur[name])
        packed[name] = jcmp_compress(data, flags) if flags is not None else data
    return rebuild(raw, packed)


def entry_raw(stored):
    """묶음 항목의 저장 바이트 -> 압축을 풀어 놓은 바이트"""
    return jcmp_decompress(stored) if stored[:4] == b'jCMP' else stored


def rebuild_nested(raw, inner_name, replace):
    """겉 묶음 > 안 묶음 > 항목 을 갈아끼운다(달력 도장이 이 구조)"""
    flags = jcmp_flags(raw)
    outer = jcmp_decompress(raw) if flags is not None else raw
    ver, ents = jarc_read(outer)
    inner_raw = dict(ents)[inner_name]
    inner_new = rebuild(inner_raw, replace)
    arc = jarc_write(ver, [[n, inner_new if n == inner_name else d] for n, d in ents],
                     align=archive_align(outer))
    return jcmp_compress(arc, flags) if flags is not None else arc
