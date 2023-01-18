from typing import Any, Callable

import struct

from rsrcdump.packutils import Unpacker
from rsrcdump.pict import convert_pict_to_image, convert_cicn_to_image, convert_ppat_to_image, convert_sicn_to_image
from rsrcdump.png import pack_png
from rsrcdump.sndtoaiff import convert_snd_to_aiff
from rsrcdump.icons import convert_4bit_icon_to_bgra, convert_8bit_icon_to_bgra, convert_1bit_icon_to_bgra
from rsrcdump.resfork import Resource


class ResourceConverter:
    """ Base class for all resource converters. """

    separate_file: str

    def __init__(self, separate_file: str = "") -> None:
        self.separate_file = separate_file

    def convert(self, res: Resource, res_map: dict[bytes, dict[int, Resource]]) -> Any:
        return res.data


class StructConverter(ResourceConverter):
    format: str
    record_length: int
    field_names: list[str]
    is_list: bool

    def __init__(self, fmt: str, field_names: list[str]):
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

        self.format = fmt
        self.record_length = struct.calcsize(fmt)
        self.field_names = field_names
        self.is_list = is_list

    def convert(self, res: Resource, res_map: dict[bytes, dict[int, Resource]]) -> Any:
        if self.is_list:
            res_object = []
            assert len(res.data) % self.record_length == 0
            for i in range(len(res.data) // self.record_length):
                res_object.append(self.parse_record(res.data, i*self.record_length))
            return res_object
        else:
            assert len(res.data) == self.record_length
            return self.parse_record(res.data, 0)

    def parse_record(self, data: bytes, offset: int) -> Any:
        values = struct.unpack_from(self.format, data, offset)

        if self.field_names:
            # We have some field names: return name-tagged values in a dict
            record = {}
            for field_name, field_val in zip(self.field_names, values):
                if field_name:  # if name is missing, skip over that field
                    record[field_name] = field_val
            return record

        elif len(values) == 1:
            # Single-element structure, no field names: just return the naked value
            return values[0]

        else:
            # Multiple-element structure but no field names: return the tuple
            return values


class SingleStringConverter(ResourceConverter):
    """ Converts STR to a string. """

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> str:
        result = Unpacker(res.data).unpack_pstr()
        return result


class StringListConverter(ResourceConverter):
    """ Converts STR# to a list of strings. """

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> list[str]:
        u = Unpacker(res.data)
        str_list = []
        count, = u.unpack(">H")
        for _ in range(count):
            value = u.unpack_pstr()
            str_list.append(value)
        return str_list


class TextConverter(ResourceConverter):
    """ Converts TEXT to a string. """

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> str:
        return res.data.decode("macroman")


class SoundToAiffConverter(ResourceConverter):
    """ Converts snd to an AIFF-C file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.aiff')

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> bytes:
        return convert_snd_to_aiff(res.data, res.name)


class PictConverter(ResourceConverter):
    """ Converts a raster PICT to a PNG file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> bytes:
        w, h, data = convert_pict_to_image(res.data)
        return pack_png(data, w, h)


class CicnConverter(ResourceConverter):
    """ Converts cicn (arbitrary-sized color icon with embedded palette) to a PNG file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> bytes:
        w, h, data = convert_cicn_to_image(res.data)
        return pack_png(data, w, h)


class PpatConverter(ResourceConverter):
    """ Converts ppat to a PNG file. """

    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> bytes:
        w, h, data = convert_ppat_to_image(res.data)
        return pack_png(data, w, h)


class SicnConverter(ResourceConverter):
    """ Converts sicn to a PNG file. """
    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> bytes:
        w, h, data = convert_sicn_to_image(res.data)
        return pack_png(data, w, h)


class TemplateConverter(ResourceConverter):
    """ Parses TMPL resources. """

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> list[dict[str, str | bytes]]:
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

    def convert(self, res: Resource, res_map: dict[bytes, dict[int, Resource]]) -> bytes:
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
    
    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> bytes:
        if res.type in [b'icl8', b'icl4', b'ICN#']:
            width, height = 32, 32
            bw_icon_type = b'ICN#'
        elif res.type in [b'ics8', b'ics4', b'ics#']:
            width, height = 16, 16
            bw_icon_type = b'ics#'

        color_icon = res.data

        if res.num in res_map[bw_icon_type]:
            bw_icon = res_map[bw_icon_type][res.num].data
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

converters = {
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
