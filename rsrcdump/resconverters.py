import struct
from rsrcdump.packutils import Unpacker
from rsrcdump.pict import convert_pict_to_image, convert_cicn_to_image, convert_ppat_to_image, convert_sicn_to_image
from rsrcdump.png import pack_png
from rsrcdump.sndtoaiff import convert_snd_to_aiff
from rsrcdump.icons import convert_4bit_icon_to_bgra, convert_8bit_icon_to_bgra, convert_1bit_icon_to_bgra

class ResourceConverter:
    def __init__(self, separate_file=None):
        self.separate_file = separate_file

    def convert(self, res, res_map):
        return res.data

class StructConverter(ResourceConverter):
    def __init__(self, fmt, field_name_str, is_list=False):
        super().__init__()
        self.fmt = fmt
        self.record_length = struct.calcsize(fmt)
        self.field_names = field_name_str.split(",")
        self.is_list = is_list

    def convert(self, res, res_map):
        if self.is_list:
            res_object = []
            assert len(res.data) % self.record_length == 0
            for i in range(len(res.data) // self.record_length):
                res_object.append(self.parse_record(res.data, i*self.record_length))
            return res_object
        else:
            return self.parse_record(res.data, 0)

    def parse_record(self, data, offset):
        record = {}
        field_values = struct.unpack_from(self.fmt, data, offset)
        for field_name, field_val in zip(self.field_names, field_values):
            if field_name:
                record[field_name] = field_val
        return record

class SingleStringConverter(ResourceConverter):
    def convert(self, res, res_map):
        return Unpacker(res.data).unpack_pstr()

class StringListConverter(ResourceConverter):
    def convert(self, res, res_map):
        u = Unpacker(res.data)
        str_list = []
        count, = u.unpack(">H")
        for i in range(count):
            str_list.append(u.unpack_pstr())
        return str_list

class TextConverter(ResourceConverter):
    def convert(self, res, res_map):
        return res.data.decode("macroman")

class IcnsConverter(ResourceConverter):
    def __init__(self):
        super().__init__(separate_file='.icns')

    def convert(self, res, res_map):
        return res.data

class SoundToAiffConverter(ResourceConverter):
    def __init__(self):
        super().__init__(separate_file='.aiff')

    def convert(self, res, res_map):
        return convert_snd_to_aiff(res.data, res.name)

class PictConverter(ResourceConverter):
    def __init__(self):
        super().__init__(separate_file='.png')

    def convert(self, res, res_map):
        w, h, data = convert_pict_to_image(res.data)
        return pack_png(data, w, h)

class CicnConverter(ResourceConverter):
    def __init__(self):
        super().__init__(separate_file='.png')

    def convert(self, res, res_map):
        w, h, data = convert_cicn_to_image(res.data)
        return pack_png(data, w, h)

class PpatConverter(ResourceConverter):
    def __init__(self):
        super().__init__(separate_file='.png')

    def convert(self, res, res_map):
        w, h, data = convert_ppat_to_image(res.data)
        return pack_png(data, w, h)

class SicnConverter(ResourceConverter):
    def __init__(self):
        super().__init__(separate_file='.png')

    def convert(self, res, res_map):
        w, h, data = convert_sicn_to_image(res.data)
        return pack_png(data, w, h)

class TemplateConverter(ResourceConverter):
    def convert(self, res, res_map):
        u = Unpacker(res.data)
        fields = []
        while not u.eof():
            field_name = u.unpack_pstr()
            field_fourcc = u.read(4).decode('macroman')
            fields.append({"label": field_name, "type": field_fourcc})
        return fields

class FileDumper(ResourceConverter):
    def __init__(self, extension, preprocess=None):
        super().__init__(extension)
        self.preprocess = preprocess

    def convert(self, res, res_map):
        if self.preprocess:
            return self.preprocess(res.data)
        else:
            return res.data

class IconConverter(ResourceConverter):
    def __init__(self):
        super().__init__(separate_file='.png')
    
    def convert(self, res, res_map):
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
            bw_icon = None
            bw_mask = None

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
