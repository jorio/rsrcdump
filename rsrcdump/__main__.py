import base64
import json
import os
import sys
import argparse

from rsrcdump.resfork import InvalidResourceFork, ResourceFork
from rsrcdump.adf import unpack_adf, ADF_ENTRYNUM_RESOURCEFORK, pack_adf, NotADFError
from rsrcdump.jsonio import resource_fork_to_json, json_to_resource_fork
from rsrcdump.textio import set_global_encoding, parse_type_name
from rsrcdump.resconverters import standard_converters, StructConverter, Base16Converter

description = (
    "Extract resources from a Macintosh resource fork. "
    "https://github.com/jorio/rsrcdump"
)

epilog = (
    "When specifying a ResType (resource type name), it will be padded with "
    "spaces if it is less than 4 characters long. You can also pass ResTypes as "
    "a URL-encoded string, e.g. '%53%54%52%20' will be interpreted as 'STR '."
)

parser = argparse.ArgumentParser(prog="rsrcdump", description=description, epilog=epilog)

cmdgroup = parser.add_mutually_exclusive_group(required=True)

cmdgroup.add_argument(
    '-x', "--extract", action='store_true',
    help="Extract resources from a resource fork.")

cmdgroup.add_argument(
    '-c', "--create", action='store_true',
    help="Create a resource fork from a json file.")

cmdgroup.add_argument(
    '-t', "--list", action='store_true',
    help="List the contents of a resource fork.")

parser.add_argument('file', type=str, help="Path to resource fork.")

parser.add_argument(
    '-o', metavar='outpath', type=str,
    help="Destination file. If omitted, will create a folder named <FILENAME>.json in the current working directory.")

parser.add_argument(
    '--no-adf', action='store_true',
    help="With -c, do not encapsulate resource fork in an AppleDouble container.")

parser.add_argument(
    '-i', '--include-type', action='append', metavar='type',
    help=("Only extract this resource type (four-character ResType). "
          "You may pass this switch several times to include several ResType."))

parser.add_argument(
    '-e', '--exclude-type', action='append', metavar='type',
    help=("Exclude this resource type (four-character ResType). "
          "You may pass this switch several times to exclude several ResType."))

parser.add_argument(
    '-s', '--struct', action='append', metavar='SPEC',
    help="Specify custom struct converters. See documentation for details.")

parser.add_argument(
    '-S', "--struct-file", type=str,
    help=(
        "Text file containing custom struct converter specifications "
        "so you don't have to pass them all via --struct."))

parser.add_argument(
    '--encoding', type=str, default="macroman",
    help="String encoding to use throughout the resource fork (MacRoman by default).")

args = parser.parse_args()

inpath = args.file

only_types = []
skip_types = []

if args.include_type:
    only_types = [parse_type_name(t) for t in args.include_type]

if args.exclude_type:
    skip_types = [parse_type_name(t) for t in args.exclude_type]

converters = standard_converters.copy()

struct_specs = []

if args.struct_file:
    with open(args.struct_file, "rt") as struct_file:
        struct_specs += struct_file.readlines()

if args.struct:
    struct_specs += args.struct

for template_arg in struct_specs:
    converter, restype = StructConverter.from_template_string_with_typename(template_arg)
    if converter:
        converters[restype] = converter


def load_resmap():
    with open(inpath, 'rb') as file:
        data = file.read()

    try:
        adf_entries = unpack_adf(data)
        adf_resfork = adf_entries[ADF_ENTRYNUM_RESOURCEFORK]
        fork = ResourceFork.from_bytes(adf_resfork)
        return fork, adf_entries
    except NotADFError:
        fork = ResourceFork.from_bytes(data)
        return fork, []


def do_list():
    fork, adf_entries = load_resmap()
    print(F"{'Type':4} {'ID':6} {'Size':8}  {'Name'}")
    print(F"{'-'*4} {'-'*6} {'-'*8}  {'-'*32}")
    for res_type in fork.tree:
        for res_id in fork.tree[res_type]:
            res = fork.tree[res_type][res_id]
            print(F"{res.type_str:4} {res.num:6} {len(res.data):8}  {res.name_str}")

    return 0


def do_extract():
    outpath = args.o

    # Generate an output path if we're not given one
    if not outpath:
        stem = inpath
        stem = stem.removesuffix("/..namedfork/rsrc")
        stem = stem.removesuffix(".rsrc")
        stem = os.path.basename(stem)
        outpath = os.path.join(os.getcwd(), stem + ".json")
        outpath = outpath.removeprefix("._")

    fork, adf_entries = load_resmap()

    metadata = {}

    if adf_entries:
        metadata["adf"] = {}
        del adf_entries[ADF_ENTRYNUM_RESOURCEFORK]
        for adf_entry_num, adf_entry in adf_entries.items():
            metadata["adf"][adf_entry_num] = base64.b16encode(adf_entry).decode("ascii")

    return resource_fork_to_json(
        fork,
        outpath,
        only_types,
        skip_types,
        converters=converters,
        metadata=metadata)


def do_pack():
    outpath = args.o

    # Generate an output path if we're not given one
    if not outpath:
        stem = args.file
        stem = stem.removesuffix(".json")
        stem = os.path.basename(stem)
        outpath = os.path.join(os.getcwd(), stem + "_regen.rsrc")

    with open(inpath, "r") as json_file:
        json_blob = json.load(json_file)

    # We've got to convert the json_blob to ResMap
    assert isinstance(json_blob, dict)

    fork = json_to_resource_fork(
        json_blob,
        converters=converters,
        only_types=only_types,
        skip_types=skip_types,
        encoding=args.encoding)

    binary_fork = fork.pack()

    if args.no_adf:
        output_blob = binary_fork
    else:
        adf_entries = {}
        try:
            adf_metadata = json_blob['_metadata']['adf']
            for adf_entry_id, adf_entry_blob in adf_metadata.items():
                adf_entries[int(adf_entry_id)] = base64.b16decode(adf_entry_blob)
        except KeyError:
            pass
        adf_entries[ADF_ENTRYNUM_RESOURCEFORK] = binary_fork
        output_blob = pack_adf(adf_entries)

    with open(outpath, "wb") as output_file:
        output_file.write(output_blob)

    return 0


# Non-zero result causes sys.exit(1)
result = -1

if args.encoding:
    set_global_encoding(args.encoding)

try:
    if args.list:
        result = do_list()
    elif args.extract:
        result = do_extract()
    elif args.create:
        result = do_pack()
except InvalidResourceFork as exc:
    print(f"Invalid resource fork: {exc}")

if result:
    sys.exit(1)
