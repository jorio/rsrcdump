from typing import Final

from io import BytesIO
from struct import pack

from rsrcdump.packutils import Unpacker, WritePlaceholder

ADF_MAGIC: Final   = 0x00051607
ADF_VERSION: Final = 0x00020000
ADF_ENTRYNUM_RESOURCEFORK: Final = 2


def unpack_adf(adf_data: bytes) -> dict[int, bytes]:
    u = Unpacker(adf_data)

    magic, version, filler, num_entries = u.unpack(">LL16sH")
    
    assert ADF_MAGIC == magic, "AppleDouble magic number not found"
    assert ADF_VERSION == version, "Not a Version 2 ADF"

    entry_offsets = []

    for _ in range(num_entries):
        entry_offsets.append(u.unpack(">LLL"))

    entries = {0: filler}  # Entry #0 is invalid -- use it for the filler

    for entry_id, offset, length in entry_offsets:
        u.seek(offset)
        entries[entry_id] = u.read(length)

    return entries


def pack_adf(adf_entries: dict[int, bytes]) -> bytes:
    has_fake_entry0 = 0 in adf_entries

    filler = adf_entries.get(0, b'\0'*16)
    assert len(filler) == 16

    num_entries = len(adf_entries)
    if has_fake_entry0:
        num_entries -= 1

    stream = BytesIO()
    stream.write(pack(">LL16sH", ADF_MAGIC, ADF_VERSION, filler, num_entries))

    wp_offsets = {}

    for entry_num, entry_data in adf_entries.items():
        if entry_num == 0:
            continue
        stream.write(pack(">L", entry_num))
        wp_offsets[entry_num] = WritePlaceholder(stream, ">L")
        stream.write(pack(">L", len(entry_data)))
    
    for entry_num, entry_data in adf_entries.items():
        if entry_num == 0:
            continue
        wp_offsets[entry_num].commit(stream.tell())
        stream.write(entry_data)

    return stream.getvalue()
