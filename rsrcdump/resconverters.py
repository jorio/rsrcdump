import base64
from typing import Any, Callable

from rsrcdump.icons import convert_4bit_icon_to_bgra, convert_8bit_icon_to_bgra, convert_1bit_icon_to_bgra
from rsrcdump.packutils import Unpacker
from rsrcdump.pict import convert_pict_to_image, convert_cicn_to_image, convert_ppat_to_image, convert_sicn_to_image
from rsrcdump.png import pack_png
from rsrcdump.resfork import Resource, ResourceFork
from rsrcdump.sndtoaiff import convert_snd_to_aiff
from rsrcdump.structtemplate import StructTemplate
from rsrcdump.textio import parse_type_name


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
    @staticmethod
    def from_template_string_with_typename(template_arg: str):
        template_arg = template_arg.strip()
        if not template_arg or template_arg.startswith("//"):  # skip blank lines
            return None, None

        split = template_arg.split(":", 1)
        assert len(split) >= 2

        restype = parse_type_name(split[0])
        formatstr = split[1]
        template = StructTemplate.from_template_string(formatstr)
        return StructConverter(template), restype

    def __init__(self, template: StructTemplate):
        super().__init__()
        self.template = template

    def unpack(self, res: Resource, fork: ResourceFork) -> Any:
        template = self.template

        if template.is_list:
            res_object = []

            if len(res.data) % template.record_length != 0:
                raise ValueError(f"The length of {res.desc()} ({len(res.data)} bytes) "
                                 f"isn't a multiple of the struct format for this resource type "
                                 f"({template.record_length} bytes)")

            assert len(res.data) % template.record_length == 0
            for i in range(len(res.data) // template.record_length):
                record = template.unpack_record(res.data, i * template.record_length)
                res_object.append(record)
            return res_object

        else:
            if len(res.data) != template.record_length:
                raise ValueError(f"The length of {res.desc()} ({len(res.data)} bytes) "
                                 f"doesn't match the struct format for this resource type "
                                 f"({template.record_length} bytes)")

            return template.unpack_record(res.data, 0)

    def pack(self, obj: Any) -> bytes:
        return self.template.pack(obj)


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
