import struct

class Unpacker:
    def __init__(self, data, offset=0):
        self.data = data
        self.offset = 0
    
    def unpack(self, fmt):
        record_length = struct.calcsize(fmt)
        fields = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += record_length
        return fields

    def seek(self, offset):
        self.offset = offset

    def read(self, size):
        data_slice = self.data[self.offset : self.offset + size]
        assert len(data_slice) == size
        self.offset += size
        return data_slice

    def unpack_pstr(self, decode=True):
        length, = self.unpack(">B")
        binary_pstr = self.read(length)
        if decode:
            return binary_pstr.decode("macroman")
        else:
            return binary_pstr

    def eof(self):
        return self.offset >= len(self.data)

    def remaining(self):
        return len(self.data) - self.offset

class WritePlaceholder:
    def __init__(self, stream, fmt):
        self.stream = stream
        self.fmt = fmt
        self.position = self.stream.tell()
        self.stream.write(b'\xCA' * struct.calcsize(fmt))
        self.committed = False

    def commit(self, value):
        assert not self.committed, "Already committed"
        position_backup = self.stream.tell()
        data = struct.pack(self.fmt, value)
        self.stream.seek(self.position)
        self.stream.write(data)
        self.stream.seek(position_backup)
        self.committed = True

    def __del__(self):
        if not self.committed:
            print(F"WARNING: WritePlaceholder is being garbage-collected but was not committed")

def pack_pstr(text, padding, encoding='macroman'):
    bintext = text.encode(encoding)
    buf = struct.pack(">B", len(bintext)) + bintext
    pad_count = (1 + len(bintext)) % padding
    buf += b'\0' * pad_count
    return buf
