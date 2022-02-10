from io import BytesIO
from rsrcdump.packutils import Unpacker, WritePlaceholder
from struct import pack

ADF_MAGIC   = 0x00051607
ADF_VERSION = 0x00020000
ADF_ENTRYNUM_RESOURCEFORK = 2

def unpack_adf(adf_data):
    u = Unpacker(adf_data)

    magic, version, num_entries = u.unpack(">LL16xH")
    
    assert ADF_MAGIC == magic, "AppleDouble magic number not found"
    assert ADF_VERSION == version, "Not a Version 2 ADF"

    entry_offsets = []

    for i in range(num_entries):
        entry_offsets.append(u.unpack(">LLL"))

    entries = {}
    for entry_id, offset, length in entry_offsets:
        u.seek(offset)
        entries[entry_id] = u.read(length)

    return entries

def pack_adf(adf_entries):
    stream = BytesIO()
    stream.write(pack(">LL16xH", ADF_MAGIC, ADF_VERSION, len(adf_entries)))

    wp_offsets = {}

    for entry_num, entry_data in adf_entries.items():
        stream.write(pack(">L", entry_num))
        wp_offsets[entry_num] = WritePlaceholder(stream, ">L")
        stream.write(pack(">L", len(entry_data)))

    for entry_num, entry_data in adf_entries.items():
        wp_offsets[entry_num].commit(stream.tell())
        stream.write(entry_data)

    return stream.getvalue()
