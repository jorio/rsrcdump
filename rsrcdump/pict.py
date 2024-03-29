from __future__ import annotations

import enum
import io
import struct
from ctypes import ArgumentError
from dataclasses import dataclass

from rsrcdump.packutils import Unpacker
from rsrcdump.structtemplate import StructTemplate
from rsrcdump.textio import get_global_encoding


class PICTError(BaseException):
    pass


@dataclass(frozen=True)
class PICTRect:
    top: int
    left: int
    bottom: int
    right: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    def offset(self, dy: int = 0, dx: int = 0) -> PICTRect:
        return PICTRect(self.top + dy, self.left + dx, self.bottom + dy, self.right + dx)

    def intersect(self, r: PICTRect):
        t = max(self.top, r.top)
        l = max(self.left, r.left)
        b = min(self.bottom, r.bottom)
        r = min(self.right, r.right)

        b = max(t, b)
        r = max(l, r)

        return PICTRect(t, l, b, r)

    def __repr__(self) -> str:
        return f"({self.left},{self.top} {self.width}x{self.height})"


# IM:QD Table A-3 "Opcodes for version 1 pictures"
# IM:QD Table A-2 "Opcodes for extended version 2 and version 2 pictures"
class Op(enum.IntEnum):
    NOP                     = 0x00
    ClipRgn                 = 0x01
    BkPat                   = 0x02
    TxFont                  = 0x03
    TxFace                  = 0x04
    TxMode                  = 0x05
    SpExtra                 = 0x06
    PnSize                  = 0x07
    PnMode                  = 0x08
    PnPat                   = 0x09
    FillPat                 = 0x0A
    OvSize                  = 0x0B
    Origin                  = 0x0C
    TxSize                  = 0x0D
    FgColor                 = 0x0E
    BkColor                 = 0x0F

    TxRatio                 = 0x10
    picVersion              = 0x11
    RGBFgCol                = 0x1A  # v2
    RGBBkCol                = 0x1B  # v2
    HiliteMode              = 0x1C  # v2
    HiliteColor             = 0x1D  # v2
    DefHilite               = 0x1E  # v2
    OpColor                 = 0x1F  # v2

    Line                    = 0x20
    LineFrom                = 0x21
    ShortLine               = 0x22
    ShortLineFrom           = 0x23
    LongText                = 0x28
    DHText                  = 0x29
    DVText                  = 0x2A
    DHDVText                = 0x2B
    fontName                = 0x2C  # v2
    lineJustify             = 0x2D  # v2
    glyphState              = 0x2E  # v2

    frameRect               = 0x30
    paintRect               = 0x31
    eraseRect               = 0x32
    invertRect              = 0x33
    fillRect                = 0x34
    frameSameRect           = 0x38
    paintSameRect           = 0x39
    eraseSameRect           = 0x3A
    invertSameRect          = 0x3B
    fillSameRect            = 0x3C

    frameRRect              = 0x40
    paintRRect              = 0x41
    eraseRRect              = 0x42
    invertRRect             = 0x43
    fillRRect               = 0x44
    frameSameRRect          = 0x48
    paintSameRRect          = 0x49
    eraseSameRRect          = 0x4A
    invertSameRRect         = 0x4B
    fillSameRRect           = 0x4C

    frameOval               = 0x50
    paintOval               = 0x51
    eraseOval               = 0x52
    invertOval              = 0x53
    fillOval                = 0x54
    frameSameOval           = 0x58
    paintSameOval           = 0x59
    eraseSameOval           = 0x5A
    invertSameOval          = 0x5B
    fillSameOval            = 0x5C

    frameArc                = 0x60
    paintArc                = 0x61
    eraseArc                = 0x62
    invertArc               = 0x63
    fillArc                 = 0x64
    frameSameArc            = 0x68
    paintSameArc            = 0x69
    eraseSameArc            = 0x6A
    invertSameArc           = 0x6B
    fillSameArc             = 0x6C

    framePoly               = 0x70
    paintPoly               = 0x71
    erasePoly               = 0x72
    invertPoly              = 0x73
    fillPoly                = 0x74
    frameSamePoly           = 0x78
    paintSamePoly           = 0x79
    eraseSamePoly           = 0x7A
    invertSamePoly          = 0x7B
    fillSamePoly            = 0x7C

    frameRgn                = 0x80
    paintRgn                = 0x81
    eraseRgn                = 0x82
    invertRgn               = 0x83
    fillRgn                 = 0x84
    frameSameRgn            = 0x88
    paintSameRgn            = 0x89
    eraseSameRgn            = 0x8A
    invertSameRgn           = 0x8B
    fillSameRgn             = 0x8C

    BitsRect                = 0x90
    BitsRgn                 = 0x91
    PackBitsRect            = 0x98
    PackBitsRgn             = 0x99
    DirectBitsRect          = 0x9A
    DirectBitsRgn           = 0x9B

    ShortComment            = 0xA0
    LongComment             = 0xA1

    EndOfPicture            = 0xFF

    CompressedQuickTime     = 0x8200  # v2
    UncompressedQuickTime   = 0x8201  # v2


# IM:QD Table A-2 "Opcodes for extended version 2 and version 2 pictures"
# "len" is a special field that determines the length of the rest of the record.
# It is used to skip the opcode.
opcode_formats = {
    Op.NOP                      : ">",  # empty
    # Op.ClipRgn
    Op.BkPat                    : ">8B",
    Op.TxFont                   : ">H:font",
    Op.TxFace                   : ">B:face",
    Op.TxMode                   : ">B:mode",
    Op.SpExtra                  : ">L:extraspace_fixed",
    Op.PnSize                   : ">HH:v,h",
    Op.PnMode                   : ">H:mode",
    Op.PnPat                    : ">8B",
    Op.FillPat                  : ">8B",
    Op.OvSize                   : ">HH:v,h",
    Op.Origin                   : ">HH:dh,dv",
    Op.TxSize                   : ">H:size",
    Op.FgColor                  : ">L:color",
    Op.BkColor                  : ">L:color",

    Op.TxRatio                  : ">HHHH:numv,numh,denomv,denomh",
    Op.picVersion               : ">B:version",
    Op.RGBFgCol                 : ">HHH:r,g,b",
    Op.RGBBkCol                 : ">HHH:r,g,b",
    Op.HiliteMode               : ">",  # empty
    Op.HiliteColor              : ">HHH:r,g,b",
    Op.DefHilite                : ">",  # empty
    Op.OpColor                  : ">HHH:r,g,b",

    Op.Line                     : ">HHHH:v1,h1,v2,h2",
    Op.LineFrom                 : ">HH:v,h",
    Op.ShortLine                : ">HHbb:v1,h1,dh,dv",
    Op.ShortLineFrom            : ">bb:dh,dv",
    Op.LongText                 : ">HHB:v,h,len",  # variable length
    Op.DHText                   : ">BB:dh,len",  # variable length
    Op.DVText                   : ">BB:dv,len",  # variable length
    Op.DHDVText                 : ">BBB:dh,dv,len",  # variable length
    Op.fontName                 : ">HHB:datalen,oldfontid,len",  # variable length
    Op.lineJustify              : ">HLL:datalen,interchar_fixed,total_fixed",
    Op.glyphState               : ">HBBBB:datalen,outlinePreferred,preserveGlyph,fractionalWidths,scalingDisabled",

    Op.frameRect                : ">HHHH:t,l,b,r",
    Op.paintRect                : ">HHHH:t,l,b,r",
    Op.eraseRect                : ">HHHH:t,l,b,r",
    Op.invertRect               : ">HHHH:t,l,b,r",
    Op.fillRect                 : ">HHHH:t,l,b,r",
    Op.frameSameRect            : ">",  # empty
    Op.paintSameRect            : ">",  # empty
    Op.eraseSameRect            : ">",  # empty
    Op.invertSameRect           : ">",  # empty
    Op.fillSameRect             : ">",  # empty

    Op.frameRRect               : ">HHHH:t,l,b,r",
    Op.paintRRect               : ">HHHH:t,l,b,r",
    Op.eraseRRect               : ">HHHH:t,l,b,r",
    Op.invertRRect              : ">HHHH:t,l,b,r",
    Op.fillRRect                : ">HHHH:t,l,b,r",
    Op.frameSameRRect           : ">",  # empty
    Op.paintSameRRect           : ">",  # empty
    Op.eraseSameRRect           : ">",  # empty
    Op.invertSameRRect          : ">",  # empty
    Op.fillSameRRect            : ">",  # empty

    Op.frameOval                : ">HHHH:t,l,b,r",
    Op.paintOval                : ">HHHH:t,l,b,r",
    Op.eraseOval                : ">HHHH:t,l,b,r",
    Op.invertOval               : ">HHHH:t,l,b,r",
    Op.fillOval                 : ">HHHH:t,l,b,r",
    Op.frameSameOval            : ">",  # empty
    Op.paintSameOval            : ">",  # empty
    Op.eraseSameOval            : ">",  # empty
    Op.invertSameOval           : ">",  # empty
    Op.fillSameOval             : ">",  # empty

    Op.frameArc                 : ">HHHHHH:t,l,b,r,startAngle,arcAngle",
    Op.paintArc                 : ">HHHHHH:t,l,b,r,startAngle,arcAngle",
    Op.eraseArc                 : ">HHHHHH:t,l,b,r,startAngle,arcAngle",
    Op.invertArc                : ">HHHHHH:t,l,b,r,startAngle,arcAngle",
    Op.fillArc                  : ">HHHHHH:t,l,b,r,startAngle,arcAngle",
    Op.frameSameArc             : ">",  # empty
    Op.paintSameArc             : ">",  # empty
    Op.eraseSameArc             : ">",  # empty
    Op.invertSameArc            : ">",  # empty
    Op.fillSameArc              : ">",  # empty

    Op.framePoly                : ">H:datalen",  # INCOMPLETE struct but just enough to skip it
    Op.paintPoly                : ">H:datalen",
    Op.erasePoly                : ">H:datalen",
    Op.invertPoly               : ">H:datalen",
    Op.fillPoly                 : ">H:datalen",
    Op.frameSamePoly            : ">",  # empty
    Op.paintSamePoly            : ">",  # empty
    Op.eraseSamePoly            : ">",  # empty
    Op.invertSamePoly           : ">",  # empty
    Op.fillSamePoly             : ">",  # empty

    Op.frameRgn                 : ">H:datalen",  # INCOMPLETE struct but just enough to skip it
    Op.paintRgn                 : ">H:datalen",
    Op.eraseRgn                 : ">H:datalen",
    Op.invertRgn                : ">H:datalen",
    Op.fillRgn                  : ">H:datalen",
    Op.frameSameRgn             : ">",  # empty
    Op.paintSameRgn             : ">",  # empty
    Op.eraseSameRgn             : ">",  # empty
    Op.invertSameRgn            : ">",  # empty
    Op.fillSameRgn              : ">",  # empty

    Op.ShortComment             : ">H:kind",
    Op.LongComment              : ">HH:kind,len",  # variable length
    Op.CompressedQuickTime      : ">L:len",  # variable length
    Op.UncompressedQuickTime    : ">L:len",  # variable length
}


opcode_templates: dict[Op, StructTemplate] = {
    k: StructTemplate.from_template_string(v)
    for k, v in opcode_formats.items()
}


class Xmap:
    rowbytes: int
    pixelsize: int
    frame_t: int
    frame_l: int
    frame_b: int
    frame_r: int

    @property
    def frame_rect(self) -> PICTRect:
        return PICTRect(self.frame_t, self.frame_l, self.frame_b, self.frame_r)

    @property
    def width(self) -> int:
        return self.frame_rect.width

    @property
    def height(self) -> int:
        return self.frame_rect.height

    @property
    def pixelsperrow(self) -> int:
        return 8 * self.rowbytes // self.pixelsize

    @property
    def excesscolumns(self) -> int:
        return self.pixelsperrow - self.width


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


def unpack_bits(slice: bytes, packfmt: str, rowbytes: int) -> list[int]:
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


def unpack_all_rows(u: Unpacker, packfmt: str, numrows: int, rowbytes: int) -> list[int]:
    # Data is unpacked if rowbytes < 8 (IM:QD A-15)
    if rowbytes < 8:
        assert packfmt == ">B"
        return list(u.read(rowbytes * numrows))

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
    unpacked = unpack_all_rows(u, ">B", numrows=bm.height, rowbytes=bm.rowbytes)
    dst = io.BytesIO()
    for y in range(bm.height):
        for x in range(bm.width):
            byteno = y*bm.rowbytes + x//8
            bitno = 7 - (x % 8)
            black = 0 != (((unpacked[byteno]) >> bitno) & 1)
            if black:
                dst.write(b'\x00\x00\x00\xFF')
            else:
                dst.write(b'\xFF\xFF\xFF\xFF')
    return dst.getvalue()


def unpack0(u: Unpacker, pm: Pixmap, palette: list[bytes]) -> bytes:
    unpacked = bytes(unpack_all_rows(u, ">B", numrows=pm.height, rowbytes=pm.rowbytes))
    assert len(unpacked) == pm.rowbytes * pm.height

    pixels8 = convert_to_8bit(unpacked, pm.pixelsize)
    pixels8 = trim_excess_columns_8bit(pixels8, pm)
    return convert_indexed_8bit_to_32bit(pixels8, palette)


# Unpack pixel type 1 (8 bits, no packing)
def unpack1(u: Unpacker, pm: Pixmap, palette: list[bytes]) -> bytes:
    unpacked = u.read(pm.rowbytes * pm.height)
    assert len(unpacked) == pm.rowbytes * pm.height

    pixels8 = convert_to_8bit(unpacked, pm.pixelsize)
    pixels8 = trim_excess_columns_8bit(pixels8, pm)
    return convert_indexed_8bit_to_32bit(pixels8, palette)


# Unpack pixel type 3 (16 bits, chunky)
def unpack3(u: Unpacker, w: int, h: int, rowbytes: int) -> bytes:
    assert (rowbytes % 2) == 0
    assert w * 2 <= rowbytes

    unpacked = unpack_all_rows(u, ">H", h, rowbytes)
    if len(unpacked) != h * (rowbytes//2):
        raise PICTError("unpack3: unexpected item count")

    dst = io.BytesIO()
    for y in range(h):
        rowoffset = y * (rowbytes//2)
        for x in range(w):
            p = unpacked[rowoffset + x]
            a = 0xFF
            r = int(((p >> 10) & 0b11111) * (255.0/31.0))
            g = int(((p >>  5) & 0b11111) * (255.0/31.0))
            b = int(((p >>  0) & 0b11111) * (255.0/31.0))
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


def read_bitmap_or_pixmap(u: Unpacker) -> Bitmap | Pixmap:
    rowbytes_flag = u.unpack(">H")[0]
    rowbytes = rowbytes_flag & 0x7FFF
    is_pixmap = 0 != (rowbytes_flag & 0x8000)
    if is_pixmap:
        return Pixmap(rowbytes, *u.unpack("> 4h hh i ii hhhh i i 4x"))
    return Bitmap(rowbytes, *u.unpack("> 4h"))


def read_colortable(u: Unpacker) -> list[bytes]:
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
            print(F"!!! color {colorindex} overwritten")
        alreadyset[colorindex] = True
        r,g,b = u.unpack(">HHH")
        r >>= 8
        g >>= 8
        b >>= 8
        a = 0xFF
        palette[colorindex] = struct.pack(">BBBB", b,g,r,a)
    
    return palette


def unpack_maskrgn(rect: PICTRect, mask: bytes) -> bytes:
    out = io.BytesIO()
    u = Unpacker(mask)

    lastrow = rect.top
    scanline = [0x00] * rect.width

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
                scanline[x - rect.left] ^= 0xFF
        
        lastrow = row
    
    buf = out.getvalue()
    assert len(buf) == rect.width * rect.height
    return buf


def read_pict_bits(u: Unpacker, opcode: int) -> tuple[PICTRect, bytes]:
    direct_bits_opcode = opcode in (Op.DirectBitsRect, Op.DirectBitsRgn)

    # Skip junk pointer at beginning of DirectBitsRect/DirectBitsRgn
    if direct_bits_opcode:
        u.read(4)

    # Read BitMap or PixMap
    raster = read_bitmap_or_pixmap(u)

    # Read palette (if any)
    palette = None
    if not direct_bits_opcode and not isinstance(raster, Bitmap):
        palette = read_colortable(u)

    # Read src/dst rectangles
    src_rect = PICTRect(*u.unpack(">4h"))
    dst_rect = PICTRect(*u.unpack(">4h"))
    if src_rect.width != dst_rect.width or src_rect.height != dst_rect.height:
        print(F"!!! unsupported src/dst rects; s={src_rect} d={dst_rect} f={raster.frame_rect}")

    transfer_mode = u.unpack(">h")[0]  # transfer mode
    transfer_mode &= ~64  # ignore ditherCopy flag (IM:QD 3-10)
    if transfer_mode != 0:
        print(f"!!! unsupported transfer mode {transfer_mode}")

    # Read mask region, if any (xxxRgn opcodes)
    mask_8bit = None
    if opcode in (Op.BitsRgn, Op.PackBitsRgn, Op.DirectBitsRgn):
        # IM:QD, page 2-7
        maskrgn_size = u.unpack(">H")[0]
        maskrgn_rect = PICTRect(*u.unpack(">4h"))
        maskrgn_bits = u.read(maskrgn_size - 4*2-2)
        if maskrgn_bits:
            mask_8bit = unpack_maskrgn(maskrgn_rect, maskrgn_bits)

    bgra = read_pixmap_image_data(u, raster, palette)

    # Apply mask
    if mask_8bit:
        bgra = apply_8bit_mask_on_32bit_image(maskrgn_rect, mask_8bit, raster.frame_rect, bgra)

    # Crop
    if src_rect != raster.frame_rect:
        bgra = crop_32bit(bgra, raster.frame_rect, src_rect)

    return dst_rect, bgra


def read_pixmap_image_data(u: Unpacker, raster: Bitmap | Pixmap, palette: list[bytes]) -> bytes:
    if raster.width < 0 or raster.height < 0:
        raise PICTError(F"illegal bitmap/pixmap dimensions {raster.width} {raster.height}")

    if isinstance(raster, Bitmap):
        return unpackbw(u, raster)
    elif raster.packtype == 1 or raster.rowbytes < 8:
        return unpack1(u, raster, palette)
    elif raster.packtype == 0:
        return unpack0(u, raster, palette)
    elif raster.packtype == 2:
        raise PICTError("Packtype 2 isn't supported yet - it's so rare that I've never seen it in the wild. "
                        "Please open an issue on https://github.com/jorio/rsrcdump and attach the rsrc file. "
                        "Thank you!")
    elif raster.packtype == 3:
        return unpack3(u, raster.width, raster.height, raster.rowbytes)
    elif raster.packtype == 4:
        return unpack4(u, raster.width, raster.height, raster.rowbytes, raster.cmpcount)
    raise PICTError(F"unsupported packtype {raster.packtype}")


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


def crop_32bit(src_data: bytes, src_rect: PICTRect, dst_rect: PICTRect):
    intersection = src_rect.intersect(dst_rect)

    src_io = io.BytesIO(src_data)
    dst_io = io.BytesIO()

    left_offset = intersection.left - src_rect.left
    assert left_offset >= 0, "negative left_offset when cropping!"

    for y in range(intersection.height):
        src_io.seek(4 * (y * src_rect.width + left_offset))
        row_len = 4 * intersection.width
        row = src_io.read(row_len)
        assert len(row) == row_len
        dst_io.write(row)

    return dst_io.getvalue()


def blit_32bit(src_rect: PICTRect, src_data: bytes, dst_rect: PICTRect, dst_data: bytes):
    intersection = src_rect.intersect(dst_rect)

    src_dy, src_dx = intersection.top - src_rect.top, intersection.left - src_rect.left
    dst_dy, dst_dx = intersection.top - dst_rect.top, intersection.left - dst_rect.left
    assert src_dy >= 0 and src_dx >= 0, "blit: negative src offset"
    assert dst_dy >= 0 and dst_dx >= 0, "blit: negative dst offset"

    src_io = io.BytesIO(src_data)
    dst_io = io.BytesIO(dst_data)

    for y in range(intersection.height):
        src_io.seek(4 * ((src_dy + y) * src_rect.width + src_dx))
        dst_io.seek(4 * ((dst_dy + y) * dst_rect.width + dst_dx))

        row_len = 4 * intersection.width
        row = src_io.read(row_len)
        assert len(row) == row_len, "blit: underrun"

        dst_io.write(row)

    return dst_io.getvalue()


def apply_8bit_mask_on_32bit_image(msk_rect: PICTRect, msk_data: bytes, dst_rect: PICTRect, dst_data: bytes):
    intersection = dst_rect.intersect(msk_rect)

    msk_dy, msk_dx = intersection.top - msk_rect.top, intersection.left - msk_rect.left
    dst_dy, dst_dx = intersection.top - dst_rect.top, intersection.left - dst_rect.left
    assert msk_dy >= 0 and msk_dx >= 0, "mask: negative msk offset"
    assert dst_dy >= 0 and dst_dx >= 0, "mask: negative dst offset"

    msk_io = io.BytesIO(msk_data)
    dst_io = io.BytesIO(dst_data)

    for y in range(intersection.height):
        msk_io.seek(1 * ((msk_dy + y) * msk_rect.width + msk_dx))
        dst_io.seek(4 * ((dst_dy + y) * dst_rect.width + dst_dx) + 3)  # +3: jump to alpha component in BGRA stream

        for x in range(intersection.width):
            opacity = msk_io.read(1)
            assert len(opacity) == 1, "mask: underrun"
            assert opacity in b"\x00\xFF"
            dst_io.write(opacity)
            dst_io.seek(3, io.SEEK_CUR)  # jump to alpha component in next pixel

    return dst_io.getvalue()


def convert_pict_to_image(data: bytes) -> tuple[int, int, bytes]:
    u = Unpacker(data)
    start_offset = u.offset

    v1_picture_size, = u.unpack(">H")  # Meaningless for "modern" picts that can easily exceed 65,535 bytes.

    # Get canvas dimensions
    canvas_rect = PICTRect(*u.unpack(">4h"))

    # Initialize canvas pixels
    canvas_32bit = b"\xFF\xFF\xFF\xFF" * (canvas_rect.width * canvas_rect.height)

    # Determine version
    if Op.picVersion == u.unpack(">B")[0]:
        if 0x01 != u.unpack(">B")[0]:
            raise PICTError("unsupported PICT version (expected 1)")
        version = 1
    else:
        u.skip(-1)  # rewind
        if Op.picVersion != u.unpack(">H")[0]:
            raise PICTError("bad v2 PICT header")
        if 0x02 != u.unpack(">B")[0]:
            raise PICTError("unsupported PICT version")
        if 0xFF != u.unpack(">B")[0]:
            raise PICTError("bad PICT header")
        version = 2

    while True:
        # align position to short (v2 PICT only)
        if version == 2 and 1 == (u.offset - start_offset) % 2:
            u.skip(1)

        if version == 1:
            opcode, = u.unpack(">B")
        else:
            opcode, = u.unpack(">H")

        try:
            opcode_name = Op(opcode).name
        except ValueError:
            opcode_name = f"${opcode:04x}"
        # print(F"Opcode {opcode_name} at offset {u.offset}")

        # skip reserved opcodes
        reserved_opcode_size = get_reserved_opcode_size(opcode)
        if reserved_opcode_size >= 0:
            u.read(reserved_opcode_size)
            continue

        if opcode == Op.ClipRgn:
            length, = u.unpack(">H")
            if length != 0x0A:
                u.read(length - 2)
            frame_rect = PICTRect(*u.unpack(">4h"))
            if frame_rect != canvas_rect:
                print(f"!!! clip rect {frame_rect} differs from canvas rect {canvas_rect}")

        elif opcode in (Op.BitsRect, Op.BitsRgn,
                        Op.PackBitsRect, Op.PackBitsRgn,
                        Op.DirectBitsRect, Op.DirectBitsRgn):
            raster_rect, raster_32bit = read_pict_bits(u, opcode)
            canvas_32bit = blit_32bit(raster_rect, raster_32bit, canvas_rect, canvas_32bit)

        elif opcode == Op.EndOfPicture:  # done
            break

        elif 0x00D0 <= opcode <= 0x00FE:  # reserved
            length, = u.unpack(">H")
            u.read(length)

        elif opcode in opcode_templates:
            # Skip opcode
            if opcode not in (Op.LongComment, Op.LongText, Op.ShortComment, Op.DefHilite):
                print(F"!!! skipping PICT opcode {opcode_name} at offset {u.offset}")

            template = opcode_templates[opcode]
            values = u.unpack(template.format)
            annotated = template.tag_values(values)

            # Skip rest of variable-length records
            if "len" in annotated:
                # if opcode in (Op.LongText, Op.LongComment):
                #     text = u.read(annotated["len"]).decode(get_global_encoding(), "replace")
                #     print(F"{opcode_name} text contents: {text}")
                #     continue
                u.skip(annotated["len"])
            elif "datalen" in annotated:
                u.skip(annotated["datalen"] - template.record_length)

        else:
            raise PICTError(F"unsupported PICT opcode {opcode_name}")

    return canvas_rect.width, canvas_rect.height, canvas_32bit


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


def trim_excess_columns_8bit(raw8: bytes, raster: Xmap) -> bytes:
    w = raster.width
    h = raster.height
    excess = raster.excesscolumns
    if excess <= 0:
        return raw8
    out = io.BytesIO()
    for y in range(h):
        out.write(raw8[y*(w+excess) : y*(w+excess) + w])
    return out.getvalue()


def convert_indexed_8bit_to_32bit(pixels8: bytes, palette: list[bytes]) -> bytes:
    out = io.BytesIO()
    for px in pixels8:
        color = palette[px]
        assert len(color) == 4, "each color in the palette should be 4 bytes"
        out.write(color)
    return out.getvalue()


def convert_cicn_to_image(data: bytes) -> tuple[int, int, bytes]:
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
    maskbits = u.read(maskbm.rowbytes * maskbm.height)
    bwiconbits = u.read(bwiconbm.rowbytes * maskbm.height)

    mask8 = convert_to_8bit(maskbits, 1)
    bwicon8 = convert_to_8bit(bwiconbits, 1)

    palette = read_colortable(u)

    raw = u.read(iconpm.rowbytes * iconpm.height)
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

    return iconpm.width, iconpm.height, dst.getvalue()


def convert_ppat_to_image(data: bytes) -> tuple[int, int, bytes]:
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
        raise ValueError('Expected Pixmap from read_bitmap_or_pixmap')

    image_data = u.read(pm.pmtable - pat_data)  # pm.pmtable = offset to clut
    palette = read_colortable(u)

    image8 = convert_to_8bit(image_data, pm.pixelsize)

    image8 = trim_excess_columns_8bit(image8, pm)
    
    bgra = io.BytesIO()
    for px in image8:
        bgra.write(palette[px])
    return pm.width, pm.height, bgra.getvalue()


def convert_sicn_to_image(data: bytes) -> tuple[int, int, bytes]:
    num_icons = len(data) // 32
    image8 = convert_to_8bit(data, 1)
    bgra = io.BytesIO()
    for px in image8:
        if px != 0:
            bgra.write(b'\x00\x00\x00\xFF')
        else:
            bgra.write(b'\xFF\xFF\xFF\xFF')
    return 16, num_icons*16, bgra.getvalue()
