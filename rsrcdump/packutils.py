from typing import Any

from io import BytesIO
import struct

class Unpacker:
    def __init__(self, data: bytes, offset: int=0) -> None:
        self.data = data
        self.offset = offset

    def unpack(self, fmt: str) -> tuple:
        record_length = struct.calcsize(fmt)
        fields = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += record_length
        return fields

    def seek(self, offset: int):
        self.offset = offset

    def skip(self, n: int):
        self.offset += n

    def read(self, size: int) -> bytes:
        data_slice = self.data[self.offset : self.offset + size]
        assert len(data_slice) == size
        self.offset += size
        return data_slice

    def unpack_raw_pstr(self) -> bytes:
        length, = self.unpack(">B")
        return self.read(length)

    def unpack_pstr(self, encoding: str = 'macroman', errors: str = 'replace') -> str:
        length, = self.unpack(">B")
        binary_pstr = self.read(length)
        return binary_pstr.decode(encoding, errors)

    def eof(self) -> bool:
        return self.offset >= len(self.data)

    def remaining(self) -> int:
        return len(self.data) - self.offset

class WritePlaceholder:
    def __init__(self, stream: BytesIO, fmt: str) -> None:
        self.stream = stream
        self.fmt = fmt
        self.position = self.stream.tell()
        self.stream.write(b'\xCA' * struct.calcsize(fmt))
        self.committed = False

    def commit(self, value: Any) -> None:
        assert not self.committed, "Already committed"
        position_backup = self.stream.tell()
        data = struct.pack(self.fmt, value)
        self.stream.seek(self.position)
        self.stream.write(data)
        self.stream.seek(position_backup)
        self.committed = True

    def __del__(self) -> None:
        if not self.committed:
            print("!!! WritePlaceholder is being garbage-collected but was not committed")

def pack_pstr(text: str, padding: int, encoding: str='macroman') -> bytes:
    bintext = text.encode(encoding)
    buf = struct.pack(">B", len(bintext)) + bintext
    pad_count = (1 + len(bintext)) % padding
    buf += b'\0' * pad_count
    return buf
