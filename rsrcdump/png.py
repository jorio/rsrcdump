from typing import Optional
from types import TracebackType

import io
import zlib
import struct

from rsrcdump.packutils import WritePlaceholder

class PNGChunkWriter:
    def __init__(self, stream: io.BytesIO, chunk_type: bytes) -> None:
        assert type(chunk_type) is bytes
        assert len(chunk_type) == 4
        self.stream = stream
        self.crc = 0
        self.length_placeholder = WritePlaceholder(self.stream, ">L")
        self.start_of_block = self.stream.tell()
        self.write(chunk_type)

    def __enter__(self) -> 'PNGChunkWriter':
        return self

    def __exit__(self,
                 _a: Optional[BaseException],
                 _b: Optional[str],
                 _c: Optional[TracebackType]) -> None:
        end_of_block = self.stream.tell()
        block_length = end_of_block - self.start_of_block
        data_length = block_length - 4
        self.stream.write(struct.pack(">L", self.crc))
        self.length_placeholder.commit(data_length)

    def write(self, data: bytes) -> None:
        self.crc = zlib.crc32(data, self.crc)
        self.stream.write(data)

def pack_png(bgra_image: bytes, width: int, height: int) -> bytes:
    png = io.BytesIO()
    png.write(b"\x89PNG\r\n\x1A\n")

    with PNGChunkWriter(png, b'IHDR') as chunk:
        chunk.write(struct.pack(">LLBBBBB",
            width,
            height,
            8,  # bit depth
            6,  # color type (RGBA)
            0,  # compression (zlib)
            0,  # filter type
            0,  # not interlaced
        ))
    
    # Prepare scanlines
    raw = io.BytesIO()
    for y in range(height):
        raw.write(b"\x00")  # no filter for this scanline
        for x in range(width):
            b = bgra_image[y*width*4 + x*4 + 0]
            g = bgra_image[y*width*4 + x*4 + 1]
            r = bgra_image[y*width*4 + x*4 + 2]
            a = bgra_image[y*width*4 + x*4 + 3]
            raw.write(struct.pack(">BBBB", r,g,b,a))

    with PNGChunkWriter(png, b'IDAT') as chunk:
        chunk.write(zlib.compress(raw.getvalue(), 9))

    with PNGChunkWriter(png, b'IEND') as chunk:
        pass

    return png.getvalue()
