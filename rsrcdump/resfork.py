from dataclasses import dataclass
from struct import unpack_from, pack
from io import BytesIO

from rsrcdump.packutils import Unpacker, WritePlaceholder

@dataclass
class Resource:
    type: bytes
    num: int
    data: bytes
    name: bytes
    flags: int  # byte

def unpack_resfork(fork: bytes) -> dict[bytes, dict[int, Resource]]:
    if not fork:
        return {}

    data_offset, map_offset, data_length, map_length = unpack_from(">LLLL", fork, 0)

    u_data = Unpacker(fork[data_offset : data_offset+data_length])
    u_map = Unpacker(fork[map_offset : map_offset+map_length])
    #file.seek(112+128, os.SEEK_CUR)  # system-reserved (112) and app-reserved (128) data

    file_attributes, typelist_offset_in_map, namelist_offset_in_map, num_types = u_map.unpack(">16x4x2xHHHH")
    num_types += 1

    res_map: Dict[bytes, Dict[int, Resource]] = {}

    u_types = Unpacker(u_map.data[typelist_offset_in_map:])
    u_names = Unpacker(u_map.data[namelist_offset_in_map:])

    for i in range(num_types):
        res_type, res_count, reslist_offset = u_map.unpack(">4sHH")
        res_count += 1

        assert res_type not in res_map, F"{res_type} already seen"
        res_map[res_type] = {}

        u_types.seek(reslist_offset)
        for j in range(res_count):
            res_id, res_name_offset, res_packed_attr = u_types.unpack(">hHL4x")

            # unpack attributes
            res_flags           = (res_packed_attr & 0xFF000000) >> 24
            res_data_offset     = (res_packed_attr & 0x00FFFFFF)

            # check compressed flag
            assert 0 == (res_flags & 1), "compressed resources are not supported"

            # fetch name
            if res_name_offset != 0xFFFF:
                u_names.seek(res_name_offset)
                name_length = u_names.unpack(">B")[0]
                res_name = u_names.read(name_length)
            else:
                res_name = b''
            
            # fetch resource data from data section
            u_data.seek(res_data_offset)
            res_size = u_data.unpack(">i")[0]
            res_data = u_data.read(res_size)

            assert res_id not in res_map[res_type]
            res_map[res_type][res_id] = Resource(res_type, res_id, res_data, res_name, res_flags)

    return res_map

def pack_resfork(res_map: Dict[bytes, Dict[str, Resource]]) -> bytes:
    stream = BytesIO()

    # Resource fork
    res_fork_offset = stream.tell()
    #wp_res_fork_offset.commit(res_fork_offset)
    wp_data_section_offset = WritePlaceholder(stream, ">L")
    wp_map_section_offset = WritePlaceholder(stream, ">L")
    wp_data_section_length = WritePlaceholder(stream, ">L")
    wp_map_section_length = WritePlaceholder(stream, ">L")
    stream.write(b'\0' * (112+128))  # system-reserved (112) and app-reserved (128) data

    # Commit offset to data section
    data_section_offset = stream.tell()
    wp_data_section_offset.commit(data_section_offset - res_fork_offset)

    # Write data section
    res_data_offsets = {}
    for res_type in res_map:
        for res_id in res_map[res_type]:
            res_data_offsets[(res_type, res_id)] = stream.tell()
            res = res_map[res_type][res_id]
            stream.write(pack(">i", len(res.data)))
            stream.write(res.data)
    
    # End of data section
    data_section_length = stream.tell() - data_section_offset
    wp_data_section_length.commit(stream.tell() - data_section_offset)

    # Commit offset to map section
    map_section_offset = stream.tell()
    wp_map_section_offset.commit(map_section_offset - res_fork_offset)

    # Write map section
    stream.write(b'\0' * (16+4+2))  # reserved for (copy of res header, handle to next res map, file ref number)
    stream.write(b'\0' * 2)  # file attributes
    wp_res_types_offset_in_map = WritePlaceholder(stream, ">H")
    wp_res_names_offset_in_map = WritePlaceholder(stream, ">H")
    stream.write(pack(">H", len(res_map) - 1))  # write number of resource types MINUS ONE

    wp_res_list_offsets = {}
    for res_type in res_map:
        assert len(res_map[res_type]) > 0  # Can't write resource types that contain 0 resources, as 1 is subtracted from the count below
        assert len(res_type) == 4
        stream.write(res_type)
        stream.write(pack(">H", len(res_map[res_type]) - 1))  # write count - 1
        wp_res_list_offsets[res_type] = WritePlaceholder(stream, ">H")

    # Commit res list offset
    res_list_offset = stream.tell()
    wp_res_types_offset_in_map.commit(res_list_offset - map_section_offset)

    wp_res_name_offsets = {}
    for res_type in res_map:
        wp_res_list_offsets[res_type].commit(stream.tell() - res_list_offset)
        for res_id in res_map[res_type]:
            res = res_map[res_type][res_id]

            # Write resource ID
            stream.write(pack(">h", res_id))

            # Write offset to name
            wp_res_name_offsets[(res_type, res_id)] = WritePlaceholder(stream, ">H")

            # Write flags + offset to data
            rel_offset = res_data_offsets[(res_type, res_id)] - data_section_offset
            packed_attr = (res.flags << 24) | (rel_offset)
            stream.write(pack(">L", packed_attr))

            stream.write(b'\0\0\0\0')  # handle to res

    # Commit res names offset
    res_names_offset = stream.tell()
    wp_res_names_offset_in_map.commit(res_names_offset - map_section_offset)

    # Write resource names
    for res_type in res_map:
        for res_id in res_map[res_type]:
            res = res_map[res_type][res_id]
            if res.name:
                wp_res_name_offsets[(res_type, res_id)].commit(stream.tell() - res_names_offset)
                stream.write(pack(">B", len(res.name)))
                stream.write(res.name)
            else:
                wp_res_name_offsets[(res_type, res_id)].commit(0xFFFF)

    # End of map section
    wp_map_section_length.commit(stream.tell() - map_section_offset)

    # End of resource fork
    #wp_res_fork_length.commit(stream.tell() - res_fork_offset)

    return stream.getvalue()
