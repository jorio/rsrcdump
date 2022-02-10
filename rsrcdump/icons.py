from io import BytesIO
from rsrcdump.packutils import Unpacker
from rsrcdump.palettes import clut4, clut8
from struct import pack

def convert_icon_to_bgra(bw_mask, width, height, get_pixel):
    icon = BytesIO()
    u_mask = Unpacker(bw_mask)

    for y in range(height):
        if not bw_mask:
            scanline_mask = 0xFFFFFFFF
        elif width == 32:
            scanline_mask, = u_mask.unpack(">L")
        elif width == 16:
            scanline_mask, = u_mask.unpack(">H")
        else:
            assert False, "unsupported width"

        for x in range(width):
            argb = get_pixel(x, y)
            opaque = scanline_mask & (1 << (width - 1 -x))
            if not opaque:
                argb &= 0x00FFFFFF
            icon.write(pack("<L", argb))

    return icon.getvalue()

def convert_8bit_icon_to_bgra(color_icon, bw_mask, width, height):
    def getpixel8(x, y):
        pixel = color_icon[y * width + x]
        return clut8[pixel]
    return convert_icon_to_bgra(bw_mask, width, height, getpixel8)

def convert_4bit_icon_to_bgra(color_icon, bw_mask, width, height):
    def getpixel4(x, y):
        pixel = color_icon[y * (width>>1) + (x>>1)]
        if 0 == (x & 1):
            pixel >>= 4
        pixel &= 0x0F
        return clut4[pixel]
    return convert_icon_to_bgra(bw_mask, width, height, getpixel4)

def convert_1bit_icon_to_bgra(bw_data, bw_mask, width, height):
    icon = BytesIO()
    u_data = Unpacker(bw_data)
    u_mask = Unpacker(bw_mask)

    for y in range(height):
        if width == 32:
            scanline_data, = u_data.unpack(">L")
            scanline_mask, = u_mask.unpack(">L")
        elif width == 16:
            scanline_data, = u_data.unpack(">H")
            scanline_mask, = u_mask.unpack(">H")
        else:
            assert False, "unsupported width"

        for x in range(width):
            is_black = scanline_data & (1 << (width - 1 - x))
            opaque = scanline_mask & (1 << (width - 1 - x))
            argb = 0xFF000000 if is_black else 0xFFFFFFFF
            if not opaque:
                argb &= 0x00FFFFFF
            icon.write(pack("<L", argb))

    return icon.getvalue()
