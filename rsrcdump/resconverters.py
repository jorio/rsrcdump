from typing import Any, Callable, Dict, List, Tuple, Union

import struct

from rsrcdump.packutils import Unpacker
from rsrcdump.pict import convert_pict_to_image, convert_cicn_to_image, convert_ppat_to_image, convert_sicn_to_image
from rsrcdump.png import pack_png
from rsrcdump.sndtoaiff import convert_snd_to_aiff
from rsrcdump.icons import convert_4bit_icon_to_bgra, convert_8bit_icon_to_bgra, convert_1bit_icon_to_bgra
from rsrcdump.resfork import Resource

class ResourceConverter:
    separate_file: str

    def __init__(self, separate_file: str="") -> None:
        self.separate_file = separate_file

    def convert(self, res: Resource, res_map: Dict[bytes, Dict[int, Resource]]) -> Any:
        return res.data

class StructConverter(ResourceConverter):
    fmt: str
    record_length: int
    field_names: list[str]
    is_list: bool

    def __init__(self, fmt: str, field_name_str: str, is_list: bool=False) -> None:
        super().__init__()
        self.fmt = fmt
        self.record_length = struct.calcsize(fmt)
        self.field_names = field_name_str.split(",")
        self.is_list = is_list

    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> list[dict[str, bytes]] | dict[str, bytes]:
        if self.is_list:
            res_object = []
            assert len(res.data) % self.record_length == 0
            for i in range(len(res.data) // self.record_length):
                res_object.append(self.parse_record(res.data, i*self.record_length))
            return res_object
        return self.parse_record(res.data, 0)

    def parse_record(self, data: bytes, offset: int) -> Dict[str, bytes]:
        record = {}
        field_values = struct.unpack_from(self.fmt, data, offset)
        for field_name, field_val in zip(self.field_names, field_values):
            if field_name:
                record[field_name] = field_val
        return record

class SingleStringConverter(ResourceConverter):
    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> bytes:
        result = Unpacker(res.data).unpack_pstr()
        assert not isinstance(result, str), 'This should be impossible'
        return result

class StringListConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> List[bytes]:
        u = Unpacker(res.data)
        str_list = []
        count, = u.unpack(">H")
        for i in range(count):
            value = u.unpack_pstr()
            assert not isinstance(value, str), 'This should be impossible'
            str_list.append(value)
        return str_list

class TextConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def convert(self, res: Resource,
                res_map: dict[bytes, dict[int, Resource]]) -> str:
        return res.data.decode("macroman")

class IcnsConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def __init__(self) -> None:
        super().__init__(separate_file='.icns')

    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
        return res.data

class SoundToAiffConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def __init__(self) -> None:
        super().__init__(separate_file='.aiff')

    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
        return convert_snd_to_aiff(res.data, res.name)

class PictConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
        w, h, data = convert_pict_to_image(res.data)
        return pack_png(data, w, h)

class CicnConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
        w, h, data = convert_cicn_to_image(res.data)
        return pack_png(data, w, h)

class PpatConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
        w, h, data = convert_ppat_to_image(res.data)
        return pack_png(data, w, h)

class SicnConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def __init__(self) -> None:
        super().__init__(separate_file='.png')

    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
        w, h, data = convert_sicn_to_image(res.data)
        return pack_png(data, w, h)

class TemplateConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> List[Dict[str, Union[str, bytes]]]:
        u = Unpacker(res.data)
        fields = []
        while not u.eof():
            field_name = u.unpack_pstr()
            field_fourcc = u.read(4).decode('macroman')
            fields.append({"label": field_name, "type": field_fourcc})
        return fields

class FileDumper(ResourceConverter):
    __slots__ = ('preprocess',)
    def __init__(self, extension: str, preprocess: Callable[[bytes], bytes]=None) -> None:
        super().__init__(extension)
        self.preprocess = preprocess

    def convert(self, res: Resource, res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
        if self.preprocess:
            return self.preprocess(res.data)
        else:
            return res.data

class IconConverter(ResourceConverter):
    __slots__: Tuple = tuple()
    def __init__(self) -> None:
        super().__init__(separate_file='.png')
    
    def convert(self, res: Resource,
                res_map: Dict[bytes, Dict[int, Resource]]) -> bytes:
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
