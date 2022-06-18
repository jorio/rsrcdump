import os
import base64
import json

from rsrcdump.resconverters import converters
from rsrcdump.textio import sanitize_type_name, sanitize_resource_name
from rsrcdump.resfork import Resource

def extract_resource_map(res_map: dict[bytes, dict[int, Resource]],
                         outpath: str,
                         include_types: list[bytes]=[],
                         exclude_types: list[bytes]=[],
                         quiet: bool=False) -> None:
    try:
        os.mkdir(outpath)
    except FileExistsError:
        pass

    J: dict[str, dict[int, dict[str, Any]]] = {}
    for res_type, res_dir in res_map.items():
        res_type_key = res_type.decode('macroman')

        if res_type in exclude_types:
            continue
        if include_types and res_type not in include_types:
            continue

        J[res_type_key] = {}

        converter = converters.get(res_type, None)

        res_dirname = sanitize_type_name(res_type)
        res_dirpath = os.path.join(outpath, res_dirname)

        for res_id, res in res_dir.items():
            typestr = res.type.decode('macroman')
            #print(F"{typestr:4} {res.num:6} {len(res.data):8}  {res.name.decode('macroman')}")

            if converter:
                if res.data:
                    obj = converter.convert(res, res_map)
                else:
                    obj = b""
            else:
                obj = res.data

            wrapper: dict[str, Any] = {}
            
            if res.name:
                wrapper['name'] = res.name.decode('macroman')

            if res.flags != 0:
                wrapper['flags'] = res.flags

            if converter and converter.separate_file:
                ext = converter.separate_file
                os.makedirs(res_dirpath, exist_ok=True)
                if res.name:
                    sanitized_name = sanitize_resource_name(res.name.decode('macroman'))
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
                if type(obj) is bytes:
                    wrapper['data'] = base64.b16encode(res.data).decode('ascii')
                else:
                    wrapper['obj'] = obj

            J[res_type_key][res_id] = wrapper

    with open(outpath + "/index.json", 'w', encoding='utf-8') as file:
        file.write(json.dumps(J, indent='\t'))

        if not quiet:
            print(F"Wrote \"{os.path.relpath(file.name, '.')}\"")

