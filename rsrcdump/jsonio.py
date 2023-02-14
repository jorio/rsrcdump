from typing import Any

import base64
import os
import json

from rsrcdump.resconverters import ResourceConverter, Base16Converter
from rsrcdump.textio import sanitize_type_name, sanitize_resource_name, parse_type_name
from rsrcdump.resfork import Resource, ResourceFork


class JSONEncoderBase16Fallback(json.JSONEncoder):
    def default(self, o: Any):
        if isinstance(o, bytes):
            return base64.b16encode(o).decode('ascii')
        else:
            return JSONEncoderBase16Fallback(self, o)


def resource_fork_to_json(
        fork: ResourceFork,
        outpath: str,
        include_types: list[bytes] = [],
        exclude_types: list[bytes] = [],
        converters: dict[bytes, ResourceConverter] = {},
        encoding: str = 'macroman',
        metadata: Any = None,
        quiet: bool = False,
):

    json_blob: dict = {'_metadata': {
        'junk1': fork.junk_nextresmap,
        'junk2': fork.junk_filerefnum,
        'file_attributes': fork.file_attributes
    }}

    if metadata:
        json_blob['_metadata'].update(metadata)

    for res_type, res_dir in fork.tree.items():
        res_type_key = res_type.decode(encoding)

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
                typestr = res.type.decode(encoding)
                print(F"{typestr:4} {res.num:6} {len(res.data):8}  {res.name.decode('macroman')}")

            obj = converter.unpack(res, fork)

            wrapper: dict[str, Any] = {}
            
            if res.name:
                wrapper['name'] = res.name.decode(encoding)

            if res.flags != 0:
                wrapper['flags'] = res.flags

            if res.junk != 0:
                wrapper['junk'] = res.junk

            if res.order != 0xFFFFFFFF:
                wrapper['order'] = res.order

            if converter and converter.separate_file:
                ext = converter.separate_file
                os.makedirs(res_dirpath, exist_ok=True)
                if res.name:
                    sanitized_name = sanitize_resource_name(res.name.decode(encoding))
                else:
                    sanitized_name = ""
                if sanitized_name:
                    filename = F"{res_id}.{sanitized_name}{ext}"
                else:
                    filename = F"{res_id}{ext}"
                wrapper['file'] = F"{res_dirname}/{filename}"
                with open(os.path.join(res_dirpath, filename), 'wb') as extfile:
                    extfile.write(obj)
                    if not quiet:
                        print(F"Wrote \"{os.path.relpath(extfile.name, '.')}\"")
            else:
                wrapper[converter.json_key] = obj

            json_blob[res_type_key][res_id] = wrapper

    json_text = json.dumps(json_blob, indent='\t', cls=JSONEncoderBase16Fallback)

    with open(outpath, 'wt', encoding='utf-8') as file:
        file.write(json_text)

        if not quiet:
            print(F"Wrote \"{os.path.relpath(file.name, '.')}\"")


def json_to_resource_fork(
        json_blob: dict,
        converters: dict[bytes, ResourceConverter],
        only_types: list[bytes] = [],
        skip_types: list[bytes] = [],
        encoding: str = 'macroman'
) -> ResourceFork:
    assert isinstance(json_blob, dict)

    fork = ResourceFork()

    fork.file_attributes = json_blob['_metadata']['file_attributes']
    fork.junk_nextresmap = json_blob['_metadata']['junk1']
    fork.junk_filerefnum = json_blob['_metadata']['junk2']

    for type_name, type_records in json_blob.items():
        if len(type_name) > 4:  # probably metadata
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
            res_name = res_blob.get("name", "").encode(encoding)
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

