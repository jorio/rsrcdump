from typing import Any, Callable, Generator
from itertools import zip_longest

import base64
import struct

from rsrcdump.packutils import Unpacker
from rsrcdump.pict import convert_pict_to_image, convert_cicn_to_image, convert_ppat_to_image, convert_sicn_to_image
from rsrcdump.png import pack_png
from rsrcdump.sndtoaiff import convert_snd_to_aiff
from rsrcdump.icons import convert_4bit_icon_to_bgra, convert_8bit_icon_to_bgra, convert_1bit_icon_to_bgra
from rsrcdump.resfork import Resource, ResourceFork


def split_struct_format_fields(fmt: str) -> Generator[str, None, None]:
    repeat = 0

    for c in fmt:
        if c.isspace():
            continue

        elif c in "@!><=":
            continue

        elif c in "0123456789":
            if repeat != 0:
                repeat *= 10
            repeat += ord(c) - ord('0')
            continue

        elif c.upper() in "CB?HILFQD":
            for _ in range(max(repeat, 1)):
                yield c
            repeat = 0

        elif c == "s":
            yield f"{max(repeat, 1)}{c}"
            repeat = 0

        else:
            raise ValueError(f"Unsupported struct format character '{c}'")


class ResourceConverter:
    """ Base class for all resource converters. """

    separate_file: str

    def __init__(self, separate_file: str = ""):
        self.separate_file = separate_file
        self.json_key = "obj"

    def unpack(self, res: Resource, fork: ResourceFork) -> Any:
        return res.data

    def pack(self, obj: Any):
        raise NotImplementedError("JSON->Binary packing not implemented in " + self.__class__.__name__)

    
class Base16Converter(ResourceConverter):
    """ Converts arbitrary data to base-16. """

    def __init__(self):
        super().__init__()
        self.json_key = "data"
    
    def unpack(self, res: Resource, fork: ResourceFork) -> Any:
        return base64.b16encode(res.data).decode('ascii')

    def pack(self, obj: Any) -> bytes:
        assert isinstance(obj, str)
        return base64.b16decode(obj)


class StructConverter(ResourceConverter):
    format: str
    record_length: int
    field_formats: list[str]
    field_names: list[str]
    is_list: bool

    def __init__(self, fmt: str, user_field_names: list[str]):
        super().__init__()

        if not fmt.startswith(("!", ">", "<", "@", "=")):
            # struct.unpack needs to know what endianness to work in; default to big-endian
            fmt = ">" + fmt

        if fmt.endswith("+"):
            # "+" suffix specifies that the resource is a list of records
            is_list = True
            fmt = fmt.removesuffix("+")
        else:
            is_list = False

        self.field_formats = list(split_struct_format_fields(fmt))
        self.format = fmt
        self.record_length = struct.calcsize(fmt)
        self.is_list = is_list
        self.is_scalar = len(self.field_formats) == 1

        # Make field names match amount of fields in fmt
        self.field_names = []
        if user_field_names:
            user_field_names_i = 0
            for field_number, field_format in enumerate(split_struct_format_fields(fmt)):
                fallback = f".field{field_number}"
                if user_field_names_i < len(user_field_names):
                    name = user_field_names[user_field_names_i]
                    if not name:
                        name = fallback
                    user_field_names_i += 1
                else:
                    name = fallback
                self.field_names.append(name)

    def unpack(self, res: Resource, fork: ResourceFork) -> Any:
        if self.is_list:
            res_object = []

            if len(res.data) % self.record_length != 0:
                raise ValueError(f"The length of {res.desc()} ({len(res.data)} bytes) isn't a multiple of the struct format for this resource type ({self.record_length} bytes)")

            assert len(res.data) % self.record_length == 0
            for i in range(len(res.data) // self.record_length):
                res_object.append(self._unpack_record(res.data, i*self.record_length))
            return res_object

        else:
            if len(res.data) != self.record_length:
                raise ValueError(f"The length of {res.desc()} ({len(res.data)} bytes) doesn't match the struct format for this resource type ({self.record_length} bytes)")

            return self._unpack_record(res.data, 0)

    def _unpack_record(self, data: bytes, offset: int) -> Any:
        values = struct.unpack_from(self.format, data, offset)

        if self.field_names:
            # We have some field names: return name-tagged values in a dict
            assert len(self.field_names) == len(values)
            record = {}
            for name, value in zip(self.field_names, values):
                record[name] = value
            return record

        elif self.is_scalar:
            # Single-element structure, no field names: just return the naked value
            assert len(values) == 1
            return values[0]

        else:
            # Multiple-element structure but no field names: return the tuple
            return values

    def pack(self, obj: Any) -> bytes:
        if not self.is_list:
            return self._pack_record(obj)
        else:
            assert isinstance(obj, list)
            buf = b""
            for item in obj:
                buf += self._pack_record(item)
            return buf

    def _pack_record(self, json_obj: Any) -> bytes:
        def process_json_field(_field_format, _field_value):
            if _field_format.endswith("s"):
                return base64.b16decode(_field_value)
            else:
                return _field_value

        if self.is_scalar:
            assert not isinstance(json_obj, list) and not isinstance(json_obj, dict)
            value = process_json_field(self.field_formats[0], json_obj)
            return struct.pack(self.format, value)

        elif self.field_names:
            assert isinstance(json_obj, dict)
            values = []
            for field_format, field_name in zip(self.field_formats, self.field_names):
                value = json_obj[field_name]
                value = process_json_field(field_format, value)
                values.append(value)
            return struct.pack(self.format, *values)

        else:
            assert isinstance(json_obj, list)
            values = []
            for field_format, value in zip(self.field_formats, json_obj):
                value = process_json_field(field_format, value)
                values.append(value)
            return struct.pack(self.format, *values)


class SingleStringConverter(ResourceConverter):
    """ Converts STR to a string. """

    def unpack(self, res: Resource, fork: ResourceFork) -> str:
        result = Unpacker(res.data).unpack_pstr()
        return result


class StringListConverter(ResourceConverter):
    """ Converts STR# to a list of strings. """

    def unpack(self, res: Resource, fork: ResourceFork) -> list[str]:
        u = Unpacker(res.data)
        str_list = []
        count, = u.unpack(">H")
        for _ in range(count):
            value = u.unpack_pstr()
            str_list.append(value)
        return str_list


class TextConverter(ResourceConverter):
    """ Converts TEXT to a string. """

    def unpack(self, res: Resource, fork: ResourceFork) -> str:
        return res.data.decode("macroman")


class SoundToAiffConverter(ResourceConverter):
    """ Converts snd to an AIFF-C file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.aiff')

    def unpack(self, res: Resource, fork: ResourceFork) -> bytes:
        return convert_snd_to_aiff(res.data, res.name)


class PictConverter(ResourceConverter):
    """ Converts a raster PICT to a PNG file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def unpack(self, res: Resource, fork: ResourceFork) -> bytes:
        w, h, data = convert_pict_to_image(res.data)
        return pack_png(data, w, h)


class CicnConverter(ResourceConverter):
    """ Converts cicn (arbitrary-sized color icon with embedded palette) to a PNG file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def unpack(self, res: Resource, fork: ResourceFork) -> bytes:
        w, h, data = convert_cicn_to_image(res.data)
        return pack_png(data, w, h)


class PpatConverter(ResourceConverter):
    """ Converts ppat to a PNG file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def unpack(self, res: Resource, fork: ResourceFork) -> bytes:
        w, h, data = convert_ppat_to_image(res.data)
        return pack_png(data, w, h)


class SicnConverter(ResourceConverter):
    """ Converts sicn to a PNG file. """
    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def unpack(self, res: Resource, fork: ResourceFork) -> bytes:
        w, h, data = convert_sicn_to_image(res.data)
        return pack_png(data, w, h)


class TemplateConverter(ResourceConverter):
    """ Parses TMPL resources. """

    def unpack(self, res: Resource, fork: ResourceFork) -> list[dict[str, str | bytes]]:
        u = Unpacker(res.data)
        fields = []
        while not u.eof():
            field_name = u.unpack_pstr()
            field_fourcc = u.read(4).decode('macroman')
            fields.append({"label": field_name, "type": field_fourcc})
        return fields


class FileDumper(ResourceConverter):
    preprocess: Callable[[bytes], bytes] | None

    def __init__(self, extension: str, preprocess: Callable[[bytes], bytes]=None) -> None:
        super().__init__(extension)
        self.preprocess = preprocess

    def unpack(self, res: Resource, fork: ResourceFork) -> bytes:
        if self.preprocess:
            return self.preprocess(res.data)
        else:
            return res.data


class IconConverter(ResourceConverter):
    """
    Converts Finder icon resources to a PNG file.

    Those are fixed-size icon resources that use the default system palette
    (icl8, ics8, icl4, ics4, ICN#, ics#).
    """

    def __init__(self) -> None:
        super().__init__(separate_file='.png')
    
    def unpack(self, res: Resource, fork: ResourceFork) -> bytes:
        if res.type in [b'icl8', b'icl4', b'ICN#']:
            width, height = 32, 32
            bw_icon_type = b'ICN#'
        elif res.type in [b'ics8', b'ics4', b'ics#']:
            width, height = 16, 16
            bw_icon_type = b'ics#'

        color_icon = res.data

        if res.num in fork.tree[bw_icon_type]:
            bw_icon = fork.tree[bw_icon_type][res.num].data
            bw_mask = bw_icon[width*height//8:]
        else:
            print(F"[WARNING] No {bw_icon_type.decode('macroman')} mask for {res.type.decode('macroman')} #{res.num}")
            bw_icon = b''
            bw_mask = b''

        if res.type in [b'icl8', b'ics8']:
            image = convert_8bit_icon_to_bgra(color_icon, bw_mask, width, height)
        elif res.type in [b'icl4', b'ics4']:
            image = convert_4bit_icon_to_bgra(color_icon, bw_mask, width, height)
        elif res.type in [b'ICN#', b'ics#']:
            image = convert_1bit_icon_to_bgra(color_icon, bw_mask, width, height)

        return pack_png(image, width, height)


# See: http://www.mathemaesthetics.com/ResTemplates.html
TMPL_types = {
    b'DBYT': 'b',
    b'DWRD': 'h',
    b'DLNG': 'i',
    b'UBYT': 'B',
    b'UWRD': 'H',
    b'ULNG': 'I',
    b'CHAR': '1s',
    b'TNAM': '4s',  # type name
}

standard_converters = {
    b'cicn': CicnConverter(),
    b'icl4': IconConverter(),
    b'icl8': IconConverter(),
    b'ICN#': IconConverter(),
    b'icns': FileDumper(".icns"),
    b'ics#': IconConverter(),
    b'ics4': IconConverter(),
    b'ics8': IconConverter(),
    #b'PICT': FileDumper(".pict", lambda data: b'\0'*512 + data),
    b'PICT': PictConverter(),
    b'plst': TextConverter(),
    b'ppat': PpatConverter(),
    b'SICN': SicnConverter(),
    b'snd ': SoundToAiffConverter(),
    b'STR ': SingleStringConverter(),
    b'STR#': StringListConverter(),
    b'TEXT': TextConverter(),
    b'TMPL': TemplateConverter(),
}
