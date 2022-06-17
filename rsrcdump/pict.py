from typing import Dict, List, Tuple, Union

from ctypes import ArgumentError
import io
from dataclasses import dataclass
import struct

from rsrcdump.packutils import Unpacker


class PICTError(Exception):
    pass

class Xmap:
    __slots__ = ('frame_r', 'frame_l', 'frame_b', 'frame_t',
                 'rowbytes', 'pixelsize')
    @property
    def frame_w(self) -> int:
        return self.frame_r - self.frame_l# type: ignore

    @property
    def frame_h(self) -> int:
        return self.frame_b - self.frame_t# type: ignore

    @property
    def frame_rect(self) -> Tuple[int, int, int, int]:
        return (self.frame_t, self.frame_l, self.frame_b, self.frame_r)# type: ignore

    @property
    def pixelsperrow(self) -> int:
        return 8 * self.rowbytes // self.pixelsize# type: ignore

    @property
    def excesscolumns(self) -> int:
        return self.pixelsperrow - self.frame_w

@dataclass
class Bitmap(Xmap):
    rowbytes: int
    frame_t: int
    frame_l: int
    frame_b: int
    frame_r: int

    @property
    def pixelsize(self) -> int:
        return 1

@dataclass
class Pixmap(Xmap):
    rowbytes: int
    frame_t: int
    frame_l: int
    frame_b: int
    frame_r: int
    pmversion: int
    packtype: int
    packsize: int
    hres_fixed: int
    vres_fixed: int
    pixeltype: int
    pixelsize: int
    cmpcount: int
    cmpsize: int
    planebytes: int
    pmtable: int

def rect_dims(rect_tuple: Tuple[int, int, int, int]) -> Tuple[int, int]:
    t, l, b, r = rect_tuple
    return r-l, b-t

def unpack_bits(slice: bytes, packfmt: str, rowbytes: int) -> List[int]:
    unpacked = []

    u = Unpacker(slice)
    while not u.eof():
        flag = u.unpack(">B")[0]

        if flag == 128:  # Apple says ignore
            pass
        elif flag > 128:  # packed data
            stride = 1 + 256-flag
            item = u.unpack(packfmt)[0]
            unpacked.extend([item] * stride)
        else:  # unpacked data
            stride = flag + 1
            for _ in range(stride):
                item = u.unpack(packfmt)[0]
                unpacked.append(item)

    return unpacked

def unpack_all_rows(u: Unpacker, packfmt: str, numrows: int, rowbytes: int) -> List[int]:
    assert rowbytes >= 8, "data is unpacked if rowbytes < 8; handle this case"

    data = []
    for y in range(numrows):
        # unpack scanline (IM:QD, page A-5)
        if rowbytes > 250:
            packed_rowbytes = u.unpack(">H")[0]
        else:
            packed_rowbytes = u.unpack(">B")[0]
        rowpixels = unpack_bits(u.read(packed_rowbytes), packfmt, rowbytes)
        data.extend(rowpixels)
    return data

def unpackbw(u: Unpacker, bm: Bitmap) -> bytes:
    unpacked = unpack_all_rows(u, ">B", numrows=bm.frame_h, rowbytes=bm.rowbytes)
    dst = io.BytesIO()
    for y in range(bm.frame_h):
        for x in range(bm.frame_w):
            byteno = y*bm.rowbytes + x//8
            bitno = 7 - (x % 8)
            black = 0 != (((unpacked[byteno]) >> bitno) & 1)
            if black:
                dst.write(b'\x00\x00\x00\xFF')
            else:
                dst.write(b'\xFF\xFF\xFF\xFF')
    return dst.getvalue()

def unpack0(u: Unpacker, pmh: Pixmap, palette: List[bytes]) -> bytes: # w: int, h: int, rowbytes: bytes, palette: List[bytes]) -> bytes:
    unpacked = bytes(unpack_all_rows(u, ">B", numrows=pmh.frame_h, rowbytes=pmh.rowbytes))

    assert len(unpacked) == pmh.rowbytes * pmh.frame_h

    pixels8 = convert_to_8bit(unpacked, pmh.pixelsize)
    pixels8 = trim_excess_columns_8bit(pixels8, pmh)

    dst = io.BytesIO()
    for px in pixels8:
        color = palette[px]
        assert len(color) == 4
        dst.write(color)
    return dst.getvalue()

# Unpack pixel type 3 (16 bits, chunky)
def unpack3(u: Unpacker, w: int, h: int, rowbytes: int) -> bytes:
    unpacked = unpack_all_rows(u, ">H", h, rowbytes)
    if len(unpacked) != w*h:
        raise PICTError("unpack3: unexpected item count")
    dst = io.BytesIO()
    for px in unpacked:
        a = 0xFF
        r = int( ((px >> 10) & 0b11111) * (255.0/31.0) )
        g = int( ((px >>  5) & 0b11111) * (255.0/31.0) )
        b = int( ((px >>  0) & 0b11111) * (255.0/31.0) )
        dst.write(struct.pack(">4B", b,g,r,a))
    return dst.getvalue()

# Unpack pixel type 4 (24 or 32 bits, planar)
def unpack4(u: Unpacker, w: int, h: int, rowbytes: int, numplanes: int) -> bytes:
    unpacked = unpack_all_rows(u, ">B", h, rowbytes)
    if len(unpacked) != numplanes*w*h:
        raise PICTError("unpack4: unexpected item count")
    dst = io.BytesIO()
    if numplanes == 3:
        for y in range(h):
            for x in range(w):
                a = 0xFF
                r = unpacked[y*w*3 + x + w*0]
                g = unpacked[y*w*3 + x + w*1]
                b = unpacked[y*w*3 + x + w*2]
                dst.write(struct.pack(">BBBB", b,g,r,a))
    else:
        for y in range(h):
            for x in range(w):
                a = unpacked[y*w*3 + x + w*0]
                r = unpacked[y*w*3 + x + w*1]
                g = unpacked[y*w*3 + x + w*2]
                b = unpacked[y*w*3 + x + w*3]
                dst.write(struct.pack(">BBBB", b,g,r,a))
    return dst.getvalue()

def read_bitmap_or_pixmap(u: Unpacker) -> Union[Pixmap, Bitmap]:
    rowbytes_flag = u.unpack(">H")[0]
    rowbytes = rowbytes_flag & 0x7FFF
    is_pixmap = 0 != (rowbytes_flag & 0x8000)
    if is_pixmap:
        return Pixmap(rowbytes, *u.unpack("> 4h hh i ii hhhh i i 4x"))
    return Bitmap(rowbytes, *u.unpack("> 4h"))

def read_colortable(u: Unpacker) -> List[bytes]:
    seed, flags, numcolors = u.unpack(">LHH")
    numcolors += 1
    #print(F"Seed: {seed:08x}", "NColors:", numcolors)

    if numcolors <= 0 or numcolors > 256:
        raise PICTError(F"unsupported palette size {numcolors}")

    palette = [ b'\xFF\x00\xFF\xFF' ] * 256
    alreadyset = [False] * 256
    illegalcolors = set()

    for i in range(numcolors):
        colorindex = u.unpack(">H")[0]
        if colorindex >= 256:
            if colorindex not in illegalcolors:
                print(F"!!! illegal color index ${colorindex:04x} in palette definition")  
                illegalcolors.add(colorindex)
            colorindex = 0
        if colorindex == 0:
            colorindex = i
        if alreadyset[colorindex]:
            print(F"!!! warning: color {colorindex} overwritten")
        alreadyset[colorindex] = True
        r,g,b = u.unpack(">HHH")
        r >>= 8
        g >>= 8
        b >>= 8
        a = 0xFF
        palette[colorindex] = struct.pack(">BBBB", b,g,r,a)
    
    return palette

def unpack_maskrgn(mask: bytes, w: int, h: int) -> bytes:
    out = io.BytesIO()

    u = Unpacker(mask)

    lastrow = 0

    scanline = [0] * w

    while not u.eof():
        row = u.unpack(">H")[0]

        if row == 0x7FFF:
            break

        for repeat in range(row-lastrow):
            out.write(bytes(scanline))

        while True:
            left = u.unpack(">H")[0]
            if left == 0x7FFF:
                break
            right = u.unpack(">H")[0]
            assert right != 0x7FFF
            for x in range(left, right):
                scanline[x] ^= 1
        
        lastrow = row
    
    buf = out.getvalue()
    assert len(buf) == w*h
    return buf

def read_pict_bits(u: Unpacker, opcode: int) -> Tuple[Tuple[int, int, int, int], bytes]:
    direct_bits_opcode = opcode in [0x009A, 0x009B]
    region_opcode = opcode in [0x0091, 0x0099]

    if direct_bits_opcode:
        u.read(4)  # skip junk
    else:
        pass #print("Not direct bits!")

    pmh = read_bitmap_or_pixmap(u)
    #print(pmh, pmh.frame_w, pmh.frame_h)
    
    palette = None
    if not direct_bits_opcode and not isinstance(pmh, Bitmap):
        palette = read_colortable(u)
    
    src_rect = u.unpack(">4h")
    dst_rect = u.unpack(">4h")
    #if src_rect != dst_rect or src_rect != pmh.frame_rect:
    #    raise PICTError(F"unsupported src/dst rects; s={src_rect} d={dst_rect} f={pmh.frame_rect}")
    tm = u.read(2) # transfer mode

    mask = None
    if region_opcode:
        # IM:QD, page 2-7
        maskrgn_size = u.unpack(">H")[0]
        maskrgn_rect = u.unpack(">4h")
        mask_w = maskrgn_rect[3]-maskrgn_rect[1]
        mask_h = maskrgn_rect[2]-maskrgn_rect[0]
        maskrgn_bits = u.read(maskrgn_size - 4*2-2)
        if maskrgn_bits:
            mask = unpack_maskrgn(maskrgn_bits, mask_w, mask_h)
            #print(binascii.hexlify(maskrgn_bits, ' ', 2))

    if opcode in [0x0091, 0x009b] or palette is None:
        raise PICTError("read_pict_bits unimplemented opcode")

    bgra = read_pixmap_image_data(u, pmh, palette)

    if mask:
        out = io.BytesIO()
        for b,g,r,maskbit in zip(bgra[0::4], bgra[1::4], bgra[2::4], mask):
            out.write(struct.pack(">BBBB", b,g,r, 0 if maskbit==0 else 0xFF))
        bgra = out.getvalue()

    return pmh.frame_rect, bgra

def read_pixmap_image_data(u: Unpacker, pmh: Union[Bitmap, Pixmap], palette: List[bytes]) -> bytes:
    frame_w, frame_h = pmh.frame_w, pmh.frame_h
    if frame_w < 0 or frame_h < 0:
        raise PICTError(F"illegal canvas dimensions {frame_w} {frame_h}")

    if isinstance(pmh, Bitmap):
        return unpackbw(u, pmh)
    elif pmh.packtype == 0:
        return unpack0(u, pmh, palette)
    elif pmh.packtype == 3:
        return unpack3(u, frame_w, frame_h, pmh.rowbytes)
    elif pmh.packtype == 4:
        return unpack4(u, frame_w, frame_h, pmh.rowbytes, pmh.cmpcount)
    raise PICTError(F"unsupported pack_type {pmh.packtype}")

skip_opcodes = {
    0x0000: (0, "NOP"),
    0x0002: (8, "BkPat"),
    0x0003: (2, "TxFont"),
    0x0004: (1, "TxFace"),
    0x0005: (2, "TxMode"),
    0x0006: (4, "SpExtra"),
    0x0007: (4, "PnSize"),
    0x0008: (2, "PnMode"),
    0x0009: (8, "PnPat"),
    0x000A: (8, "FillPat"),
    0x000B: (4, "OvSize"),
    0x000C: (4, "Origin"),
    0x000D: (2, "TxSize"),
    0x0010: (8, "TxRatio"),
    0x001A: (6, "RGBFgCol"),
    0x001B: (6, "RGBBkCol"),
    0x001E: (0, "DefHilite"),
    0x001F: (6, "OpColor"),
    0x0020: (8, "Line"),
    0x0021: (4, "LineFrom"),
    0x0022: (6, "ShortLine"),
    0x0023: (2, "ShortLineFrom"),
    0x0030: (8, "frameRect"),
    0x0031: (8, "paintRect"),
    0x0032: (8, "eraseRect"),
    0x0033: (8, "invertRect"),
    0x0034: (8, "fillRect"),
    0x0038: (0, "frameSameRect"),
    0x0048: (0, "frameSameRRect"),
    0x0060: (12, "frameArc"),
    0x0061: (12, "paintArc"),
    0x0062: (12, "eraseArc"),
    0x0063: (12, "invertArc"),
    0x0064: (12, "fillArc"),
    0x007C: (0, "fillSamePoly"),
}

def get_reserved_opcode_size(k: int) -> int:
    if 0x0035 <= k <= 0x0037: return 8
    if 0x003D <= k <= 0x003F: return 0
    if 0x0045 <= k <= 0x0047: return 8
    if 0x004D <= k <= 0x004F: return 0
    if 0x0055 <= k <= 0x0057: return 8
    if 0x005D <= k <= 0x005F: return 0
    if 0x0065 <= k <= 0x0067: return 12
    if 0x006D <= k <= 0x006F: return 4
    if 0x007D <= k <= 0x007F: return 0
    if 0x008D <= k <= 0x008F: return 0
    if 0x00B0 <= k <= 0x00CF: return 0
    if 0x0100 <= k <= 0x01FF: return 2
    if k == 0x0200: return 4
    if k == 0x02FF: return 2
    if k == 0x0BFF: return 22
    if 0x0C00 <= k <= 0x7EFF: return 24
    if 0x7F00 <= k <= 0x7FFF: return 254
    if 0x8000 <= k <= 0x80FF: return 0
    return -1

def convert_pict_to_image(data: bytes) -> Tuple[int, int, bytes]:
    u = Unpacker(data)
    start_offset = u.offset

    v1_picture_size, = u.unpack(">H")  # Meaningless for "modern" picts that can easily exceed 65,535 bytes.
    #print("v1_picture_size:", v1_picture_size)

    canvas_rect = u.unpack(">4h")

    if 0x0011 != u.unpack(">h")[0]:
        #raise PICTError("no version opcode in PICT header")
        print("!!! no version opcode in PICT header, perhaps this is a very old v1 PICT with single-byte opcodes")
        return 0, 0, b''
    if 0x02 != u.unpack(">B")[0]:
        raise PICTError("unsupported PICT version")
    if 0xFF != u.unpack(">B")[0]:
        raise PICTError("bad PICT header")

    pm = None
    pm_rect = None

    while True:
        # align position to short
        if 1 == (u.offset - start_offset) % 2:
            u.read(1)

        opcode, = u.unpack(">H")
        #print(F"Opcode {opcode:04x} at offset {u.offset}")

        # skip reserved opcodes
        reserved_opcode_size = get_reserved_opcode_size(opcode)
        if reserved_opcode_size >= 0:
            #print(F"PICT: Skipping reserved opcode 0x{opcode:04x} of size {reserved_opcode_size} (offset: {u.offset})")
            u.read(reserved_opcode_size)
            continue

        if opcode in [0x0001]:  # clip
            length, = u.unpack(">H")
            if length != 0x0A:
                u.read(length - 2)
            frame_rect = u.unpack(">4h")
            if frame_rect != canvas_rect:
                print("WARNING: Clip rect different from canvas rect")
        elif opcode in [0x0098, 0x0099, 0x009A]:  # PackBitsRect, PackBitsRgn, DirectBitsRect
            if pm:
                print("!!! multiple raster images in PICT")
            pm_rect, pm = read_pict_bits(u, opcode)
            #if pm_rect != canvas_rect:
            #    print("WARNING: pixmap rect different from canvas rect")
        elif opcode in [0x00A0]:  # short comment
            u.read(2)  # kind
        elif opcode in [0x00A1]:  # long comment
            u.read(2)  # kind
            length, = u.unpack(">H")
            longcomment = u.read(length)
            #print("*** Long Comment:", longcomment.decode('macroman'))
        elif opcode in [0x8200, 0x8201]:  # CompressedQuickTime, UncompressedQuickTime
            length, = u.unpack(">L")
            u.read(length)
        elif opcode in [0x00FF]:  # done
            if not pm or not pm_rect:
                print("!!! exiting PICT without a pixmap")
                return 0, 0, b''
            pm_w, pm_h = rect_dims(pm_rect)
            return pm_w, pm_h, pm
        elif 0x00D0 <= opcode <= 0x00FE:  # reserved
            length, = u.unpack(">H")
            u.read(length)
        elif opcode == 0x0028:  # LongText
            x, y, text_length = u.unpack(">HHB")
            text = u.read(text_length)
            print(F"Skipping LongText: {text.decode('macroman')}")
        elif opcode == 0x0029:  # DHText
            dh, text_length = u.unpack(">BB")
            text = u.read(text_length)
            print(F"Skipping DHText  : {text.decode('macroman')}")
        elif opcode == 0x002A:  # DVText
            dv, text_length = u.unpack(">BB")
            text = u.read(text_length)
            print(F"Skipping DVText  : {text.decode('macroman')}")
        elif opcode == 0x002B:  # DHDVText
            dh, dv, text_length = u.unpack(">BBB")
            text = u.read(text_length)
            print(F"Skipping DHDVText: {text.decode('macroman')}")
        elif opcode == 0x002C:  # fontName
            length, old_font_id, name_length = u.unpack(">HHB")
            font_name = u.read(name_length)
            print(F"Skipping fontName: {font_name.decode('macroman')}")
        elif opcode == 0x002E:  # glyphState
            length, = u.unpack(">H")
            u.read(length)
        elif opcode in skip_opcodes:
            length, opcode_name = skip_opcodes[opcode]
            #print(F"PICT: Skipping opcode 0x{opcode:04x} {opcode_name} of size {length} at offset {u.offset}")
            u.read(length)
        else:
            raise PICTError(F"unsupported PICT opcode 0x{opcode:04x}")

def convert_to_8bit(raw: bytes, pixelsize: int) -> bytes:
    if pixelsize == 8:
        return raw
    
    out = io.BytesIO()

    if pixelsize == 4:
        for byte in raw:
            high = (byte >> 4) & 0b1111
            low = byte & 0b1111
            out.write(struct.pack(">BB", high, low))

    elif pixelsize == 2:
        for byte in raw:
            i = (byte >> 6) & 0b11
            j = (byte >> 4) & 0b11
            k = (byte >> 2) & 0b11
            l = (byte) & 0b11
            out.write(struct.pack(">BBBB", i, j, k, l))

    elif pixelsize == 1:
        for byte in raw:
            for bitno in range(7, -1, -1):
                on = 0 != ((byte >> bitno) & 1)
                out.write(b'\1' if on else b'\0')

    else:
        raise ArgumentError(F"unsupported pixelsize {pixelsize}")

    return out.getvalue()

def trim_excess_columns_8bit(raw8: bytes, pm: Xmap) -> bytes:
    w = pm.frame_w
    h = pm.frame_h
    excess = pm.excesscolumns
    if excess <= 0:
        return raw8
    out = io.BytesIO()
    for y in range(h):
        out.write(raw8[y*(w+excess) : y*(w+excess) + w])
    return out.getvalue()

def convert_cicn_to_image(data: bytes) -> Tuple[int, int, bytes]:
    u = Unpacker(data)
    
    off = u.offset
    z1 = u.read(4)
    iconpm = read_bitmap_or_pixmap(u)
    assert u.offset - off == 50, F"{u.offset-off} bad offset delta"
    
    off = u.offset
    z2 = u.read(4)
    maskbm = read_bitmap_or_pixmap(u)
    assert u.offset - off == 14, F"{u.offset-off} bad offset delta"

    z3 = u.read(4)
    bwiconbm = read_bitmap_or_pixmap(u)

    icon_data = u.read(4)

    assert isinstance(iconpm, Pixmap)
    assert isinstance(maskbm, Bitmap)
    assert isinstance(bwiconbm, Bitmap)
    maskbits = u.read(maskbm.rowbytes * maskbm.frame_h)
    bwiconbits = u.read(bwiconbm.rowbytes * maskbm.frame_h)

    mask8 = convert_to_8bit(maskbits, 1)
    bwicon8 = convert_to_8bit(bwiconbits, 1)

    palette = read_colortable(u)

    raw = u.read(iconpm.rowbytes * iconpm.frame_h)
    raw = convert_to_8bit(raw, iconpm.pixelsize)

    raw = trim_excess_columns_8bit(raw, iconpm)
    mask8 = trim_excess_columns_8bit(mask8, maskbm)
    bwicon8 = trim_excess_columns_8bit(bwicon8, bwiconbm)

    dst = io.BytesIO()
    for px,mask in zip(raw,mask8):
        color = palette[px]
        assert len(color) == 4
        dst.write(color[:3])
        dst.write(b'\xFF' if mask != 0 else b'\x00')

    return iconpm.frame_w, iconpm.frame_h, dst.getvalue()

def convert_ppat_to_image(data: bytes) -> Tuple[int, int, bytes]:
    # IM:QD page 4-103
    u = Unpacker(data)

    pat_type, pat_map, pat_data = u.unpack(">H i i")  
    u.read(28-2-4-4)  # skip remaining of PixPat record

    # pat_type: 0=bw, 1=color, 2=rgb
    # pat_map: offset to pixmap record in resource
    # pat_data: offset to pixel data in resource

    if pat_type != 1:
        print(F"!!! only 'type 1' indexed-color ppats are supported (this is a type {pat_type} ppat)")
        return 0, 0, b''

    u.read(4)  # Skip junk
    pm = read_bitmap_or_pixmap(u)
    
    if isinstance(pm, Bitmap):
        raise ValueError('Expected Bitmap from read_bitmap_or_pixmap')

    image_data = u.read(pm.pmtable - pat_data)  # pm.pmtable = offset to clut
    palette = read_colortable(u)

    image8 = convert_to_8bit(image_data, pm.pixelsize)

    image8 = trim_excess_columns_8bit(image8, pm)
    
    bgra = io.BytesIO()
    for px in image8:
        bgra.write(palette[px])
    return pm.frame_w, pm.frame_h, bgra.getvalue()

def convert_sicn_to_image(data: bytes) -> Tuple[int, int, bytes]:
    num_icons = len(data) // 32
    image8 = convert_to_8bit(data, 1)
    bgra = io.BytesIO()
    for px in image8:
        if px != 0:
            bgra.write(b'\x00\x00\x00\xFF')
        else:
            bgra.write(b'\xFF\xFF\xFF\xFF')
    return 16, num_icons*16, bgra.getvalue()
