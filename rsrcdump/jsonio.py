from typing import Any

import base64
import os
import json

from rsrcdump.resconverters import ResourceConverter, Base16Converter
from rsrcdump.textio import get_global_encoding, sanitize_type_name, sanitize_resource_name, parse_type_name
from rsrcdump.resfork import Resource, ResourceFork


class JSONEncoderBase16Fallback(json.JSONEncoder):
    def default(self, o: Any):
        if isinstance(o, bytes):
            return base64.b16encode(o).decode('ascii')
        else:
            return super().default(o)


def resource_fork_to_json(
        fork: ResourceFork,
        outpath: str,
        include_types: list[bytes] = [],
        exclude_types: list[bytes] = [],
        converters: dict[bytes, ResourceConverter] = {},
        metadata: Any = None,
        quiet: bool = False,
) -> int:

    json_blob: dict = {'_metadata': {
        'junk1': fork.junk_nextresmap,
        'junk2': fork.junk_filerefnum,
        'file_attributes': fork.file_attributes
    }}

    if metadata:
        json_blob['_metadata'].update(metadata)

    errors = []

    for res_type, res_dir in fork.tree.items():
        # Use the same encoding as the resource sub-directory name so the key
        # round-trips through parse_type_name() on repack. Decoding the raw
        # bytes here instead would not survive parse_type_name()'s unquote step
        # for FourCCs containing high bytes or trailing spaces.
        res_type_key = sanitize_type_name(res_type)

        if res_type in exclude_types:
            continue
        if include_types and res_type not in include_types:
            continue

        json_blob[res_type_key] = {}

        converter = converters.get(res_type, Base16Converter())

        res_dirname = sanitize_type_name(res_type)
        res_dirpath = os.path.join(outpath + "_resources", res_dirname)

        for res_id, res in res_dir.items():
            if not quiet:
                print(F"{res.type_str:4} {res.num:6} {len(res.data):8}  {res.name_str}")

            wrapper: dict[str, Any] = {}

            if res.name:
                wrapper['name'] = res.name_str

            if res.flags != 0:
                wrapper['flags'] = res.flags

            if res.junk != 0:
                wrapper['junk'] = res.junk

            if res.order != 0xFFFFFFFF:
                wrapper['order'] = res.order

            try:
                obj = converter.unpack(res, fork)
                separate_file = bool(converter.separate_file)
            except BaseException as convert_exception:
                errors.append(f"Failed to convert {res_type_key} #{res_id}: {convert_exception}")
                if not quiet:
                    print("!!!", errors[-1])
                wrapper['conversion_error'] = str(convert_exception)
                # Fall back to base16
                obj = Base16Converter().unpack(res, fork)
                separate_file = False

            if separate_file:
                ext = converter.separate_file
                os.makedirs(res_dirpath, exist_ok=True)
                if res.name:
                    sanitized_name = sanitize_resource_name(res.name_str)
                else:
                    sanitized_name = ""
                if sanitized_name:
                    filename = F"{res_id}.{sanitized_name}{ext}"
                else:
                    filename = F"{res_id}{ext}"
                wrapper['file'] = F"{res_dirname}/{filename}"
                with open(os.path.join(res_dirpath, filename), 'wb') as extfile:
                    extfile.write(obj)
            else:
                wrapper[converter.json_key] = obj

            json_blob[res_type_key][res_id] = wrapper

    json_text = json.dumps(json_blob, indent='\t', cls=JSONEncoderBase16Fallback)

    with open(outpath, 'wt', encoding='utf-8') as file:
        file.write(json_text)

        if not quiet:
            print(F"Wrote \"{os.path.relpath(file.name, '.')}\"")

    # Repeat errors at end
    for error in errors:
        print("***", error)

    return len(errors)


def json_to_resource_fork(
        json_blob: dict,
        converters: dict[bytes, ResourceConverter],
        only_types: list[bytes] = [],
        skip_types: list[bytes] = [],
) -> ResourceFork:
    assert isinstance(json_blob, dict)

    fork = ResourceFork()

    fork.file_attributes = json_blob['_metadata']['file_attributes']
    fork.junk_nextresmap = json_blob['_metadata']['junk1']
    fork.junk_filerefnum = json_blob['_metadata']['junk2']

    for type_name, type_records in json_blob.items():
        # Skip the metadata block. (A plain length check would wrongly drop
        # URL-encoded type keys such as "%A9icn", which are longer than 4
        # characters yet decode back to a 4-byte FourCC.)
        if type_name == "_metadata":
            continue

        res_type = parse_type_name(type_name)

        if (res_type in skip_types) or (only_types and res_type not in only_types):
            continue

        fork.tree[res_type] = {}

        assert isinstance(type_records, dict)
        converter = converters.get(res_type, Base16Converter())

        for res_id_str, res_blob in type_records.items():
            assert isinstance(res_blob, dict)

            res_num = int(res_id_str)
            res_name = res_blob.get("name", "").encode(get_global_encoding(), 'replace')
            res_flags = res_blob.get("flags", 0)
            res_junk = res_blob.get("junk", 0)
            res_order = res_blob.get("order", -1)

            data_blob = res_blob.get(converter.json_key, None)
            res_data = converter.pack(data_blob)

            res = Resource(
                type=res_type,
                num=res_num,
                data=res_data,
                name=res_name,
                flags=res_flags,
                junk=res_junk,
                order=res_order)

            fork.tree[res_type][res_num] = res

    return fork

