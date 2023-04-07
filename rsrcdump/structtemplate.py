import base64
import struct
from typing import Any, Generator


class StructTemplate:
    format: str
    record_length: int
    field_formats: list[str]
    field_names: list[str]
    is_list: bool

    @staticmethod
    def from_template_string(template):
        split = template.split(":", 2)

        formatstr = split.pop(0)

        if split:
            fieldnames = split.pop(0).split(",")
        else:
            fieldnames = []

        assert formatstr
        return StructTemplate(formatstr, fieldnames)

    @staticmethod
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

    def __init__(self, fmt: str, user_field_names: list[str]):
        if not fmt.startswith(("!", ">", "<", "@", "=")):
            # struct.unpack needs to know what endianness to work in; default to big-endian
            fmt = ">" + fmt

        if fmt.endswith("+"):
            # "+" suffix specifies that the resource is a list of records
            is_list = True
            fmt = fmt.removesuffix("+")
        else:
            is_list = False

        self.field_formats = list(StructTemplate.split_struct_format_fields(fmt))
        self.format = fmt
        self.record_length = struct.calcsize(fmt)
        self.is_list = is_list
        self.is_scalar = len(self.field_formats) == 1

        # Make field names match amount of fields in fmt
        self.field_names = []
        if user_field_names:
            user_field_names_i = 0
            for field_number, field_format in enumerate(StructTemplate.split_struct_format_fields(fmt)):
                fallback = f".field{field_number}"
                if user_field_names_i < len(user_field_names):
                    name = user_field_names[user_field_names_i]
                    if not name:
                        name = fallback
                    user_field_names_i += 1
                else:
                    name = fallback
                self.field_names.append(name)

    def unpack_record(self, data: bytes, offset: int) -> Any:
        values = struct.unpack_from(self.format, data, offset)
        return self.tag_values(values)

    def tag_values(self, values: tuple):
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
            return self.pack_record(obj)
        else:
            assert isinstance(obj, list)
            buf = b""
            for item in obj:
                buf += self.pack_record(item)
            return buf

    def pack_record(self, json_obj: Any) -> bytes:
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



