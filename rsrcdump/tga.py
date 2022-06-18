from io import BytesIO
import struct

def pack_tga(bgra_image: bytes, width: int, height: int) -> bytes:
    assert len(bgra_image) == 4*width*height
    tga = BytesIO()
    tga.write(struct.pack("<BBBHHBHHHHBB",
        0,      # idFieldLength
        0,      # colorMapType
        2,      # imageType (RAW_BGR)
        0,      # palette origin
        0,      # palette color count
        0,      # palette bits per color
        0,      # x origin
        0,      # y origin
        width,  # width
        height, # height
        32,     # bpp
        0x28    # imageDescriptor
    ))
    tga.write(bgra_image)
    return tga.getvalue()
