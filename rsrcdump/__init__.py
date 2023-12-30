from os import PathLike

from rsrcdump.resfork import InvalidResourceFork, ResourceFork
from rsrcdump.adf import unpack_adf, ADF_ENTRYNUM_RESOURCEFORK, pack_adf, NotADFError
from rsrcdump.jsonio import resource_fork_to_json, json_to_resource_fork
from rsrcdump.textio import set_global_encoding, parse_type_name
from rsrcdump.resconverters import standard_converters, StructConverter, Base16Converter


def load(data_or_path: bytes | PathLike) -> ResourceFork:
    if type(data_or_path) is not bytes:
        path = data_or_path
        with open(path, 'rb') as f:
            data = f.read()
    else:
        data: bytes = data_or_path

    try:
        adf_entries = unpack_adf(data)
        adf_resfork = adf_entries[ADF_ENTRYNUM_RESOURCEFORK]
        fork = ResourceFork.from_bytes(adf_resfork)
    except NotADFError:
        fork = ResourceFork.from_bytes(data)
    return fork
