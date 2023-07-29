from dataclasses import dataclass, field
from struct import unpack_from, pack, calcsize
from io import BytesIO

from rsrcdump.packutils import Unpacker, WritePlaceholder
from rsrcdump.textio import get_global_encoding, sanitize_type_name


ResType = bytes


class InvalidResourceFork(ValueError):
    pass


@dataclass
class Resource:
    type: ResType
    "FourCC of the resource type."

    num: int
    "ID of this resource. Should be unique within the resource type."

    data: bytes
    "Raw data of the resource."

    name: bytes
    "Raw resource name. Typically encoded as MacRoman."

    flags: int
    "Flag byte."

    junk: int
    """Some 32-bit handle. This should be 0, but some files in the wild contain some junk here instead.
    We're only preserving it so that --create can output a perfect copy of the original resource fork."""

    order: int = 0xFFFFFFFF
    """Order in which the resource appears in the original resource fork.
    0xFFFFFFFF indicates the order is unknown (e.g. for resources that we added programmatically).
    The order is preserved so that --create can output a perfect copy of the original resource fork."""

    def desc(self) -> str:
        return f"{sanitize_type_name(self.type)}#{self.num}"

    @property
    def type_str(self, errors='replace') -> str:
        return self.type.decode(get_global_encoding(), errors)

    @property
    def name_str(self, errors='replace') -> str:
        return self.name.decode(get_global_encoding(), errors)


@dataclass
class ResourceFork:
    tree: dict[ResType, dict[int, Resource]] = field(default_factory=dict)
    "Map of all resources in the resource fork."

    junk_nextresmap: int = 0
    "Junk 32-bit value, preserved so that --create can output a perfect copy of the original resource fork."

    junk_filerefnum: int = 0
    "Junk 32-bit value, preserved so that --create can output a perfect copy of the original resource fork."

    file_attributes: int = 0
    "Finder file attributes."

    def ordered_flat_list(self):
        flat = []
        for res_type in self.tree:
            for res_id in self.tree[res_type]:
                flat.append(self.tree[res_type][res_id])
        return sorted(flat, key=lambda r: r.order)

    @staticmethod
    def from_bytes(data: bytes) -> 'ResourceFork':
        if not data:
            return ResourceFork()

        fork = ResourceFork()

        if len(data) < calcsize(">LLLL16x"):
            raise InvalidResourceFork("data is too small to contain a valid resource fork header")

        data_offset, map_offset, data_length, map_length = unpack_from(">LLLL", data, 0)

        if data_offset + data_length > len(data) or map_offset + map_length > len(data):
            raise InvalidResourceFork("offsets/lengths in header are nonsense")

        u_data = Unpacker(data[data_offset: data_offset + data_length])
        u_map = Unpacker(data[map_offset: map_offset + map_length])

        u_map.skip(16)  # skip copy of resource header
        fork.junk_nextresmap, fork.junk_filerefnum, fork.file_attributes = u_map.unpack(">LHH")
        typelist_offset_in_map, namelist_offset_in_map, num_types = u_map.unpack(">HHH")
        num_types += 1

        u_types = Unpacker(u_map.data[typelist_offset_in_map:])
        u_names = Unpacker(u_map.data[namelist_offset_in_map:])

        order = []

        for i in range(num_types):
            res_type, res_count, reslist_offset = u_map.unpack(">4sHH")
            res_count += 1

            assert res_type not in fork.tree, F"{res_type} already seen"
            fork.tree[res_type] = {}

            u_types.seek(reslist_offset)
            for j in range(res_count):
                res_id, res_name_offset, res_packed_attr, res_junk = u_types.unpack(">hHLL")

                # unpack attributes
                res_flags = (res_packed_attr & 0xFF000000) >> 24
                res_data_offset = (res_packed_attr & 0x00FFFFFF)

                order.append((res_type, res_id, res_data_offset))

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

                assert res_id not in fork.tree[res_type]
                res = Resource(res_type, res_id, res_data, res_name, res_flags, res_junk)
                fork.tree[res_type][res_id] = res

        order = sorted(order, key=lambda x: x[2])
        for i, (res_type, res_id, res_offset) in enumerate(order):
            fork.tree[res_type][res_id].order = i

        return fork

    def pack(self) -> bytes:
        stream = BytesIO()

        # Resource fork
        res_fork_offset = stream.tell()
        wp_data_section_offset = WritePlaceholder(stream, ">L")
        wp_map_section_offset = WritePlaceholder(stream, ">L")
        wp_data_section_length = WritePlaceholder(stream, ">L")
        wp_map_section_length = WritePlaceholder(stream, ">L")
        stream.write(b'\0' * (112 + 128))  # system-reserved (112) and app-reserved (128) data

        # Commit offset to data section
        data_section_offset = stream.tell()
        wp_data_section_offset.commit(data_section_offset - res_fork_offset)

        # Write data section
        res_data_offsets = {}
        for res in self.ordered_flat_list():
            res_data_offsets[(res.type, res.num)] = stream.tell()
            stream.write(pack(">i", len(res.data)))
            stream.write(res.data)

        # End of data section
        data_section_length = stream.tell() - data_section_offset
        wp_data_section_length.commit(stream.tell() - data_section_offset)

        # Commit offset to map section
        map_section_offset = stream.tell()
        wp_map_section_offset.commit(map_section_offset - res_fork_offset)

        # Write map section
        stream.flush()
        wp_copy_of_resource_header = WritePlaceholder(stream, ">16s")
        stream.write(pack(">LHH", self.junk_nextresmap, self.junk_filerefnum, self.file_attributes))
        wp_res_types_offset_in_map = WritePlaceholder(stream, ">H")
        wp_res_names_offset_in_map = WritePlaceholder(stream, ">H")

        # Commit res list offset
        res_list_offset = stream.tell()
        wp_res_types_offset_in_map.commit(res_list_offset - map_section_offset)

        stream.write(pack(">H", len(self.tree) - 1))  # write number of resource types MINUS ONE

        wp_res_list_offsets = {}
        for res_type in self.tree:
            assert len(self.tree[res_type]) > 0, "Can't write resource types that contain 0 resources, as 1 is subtracted from the count below"
            assert len(res_type) == 4
            stream.write(res_type)
            stream.write(pack(">H", len(self.tree[res_type]) - 1))  # write count - 1
            wp_res_list_offsets[res_type] = WritePlaceholder(stream, ">H")

        wp_res_name_offsets = {}
        for res_type in self.tree:
            wp_res_list_offsets[res_type].commit(stream.tell() - res_list_offset)
            for res_id in self.tree[res_type]:
                res = self.tree[res_type][res_id]

                # Write resource ID
                stream.write(pack(">h", res_id))

                # Write offset to name
                wp_res_name_offsets[(res_type, res_id)] = WritePlaceholder(stream, ">H")

                # Write flags + offset to data
                rel_offset = res_data_offsets[(res_type, res_id)] - data_section_offset
                packed_attr = (res.flags << 24) | (rel_offset)
                stream.write(pack(">L", packed_attr))

                # Write handle to res -- it's junk, really, but we're keeping it
                # so we can produce a verbatim copy of the original resource fork
                stream.write(pack(">L", res.junk))

        # Commit res names offset
        res_names_offset = stream.tell()
        wp_res_names_offset_in_map.commit(res_names_offset - map_section_offset)

        # Write resource names
        for res in self.ordered_flat_list():
            if res.name:
                wp_res_name_offsets[(res.type, res.num)].commit(stream.tell() - res_names_offset)
                stream.write(pack(">B", len(res.name)))
                stream.write(res.name)
            else:
                wp_res_name_offsets[(res.type, res.num)].commit(0xFFFF)

        # End of map section
        wp_map_section_length.commit(stream.tell() - map_section_offset)

        # Copy of resource header
        stream.seek(wp_data_section_offset.position)
        wp_copy_of_resource_header.commit(stream.read(16))

        return stream.getvalue()

