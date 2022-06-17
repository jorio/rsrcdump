import os
import sys
import argparse

from rsrcdump.resfork import unpack_resfork
from rsrcdump.adf import unpack_adf, ADF_ENTRYNUM_RESOURCEFORK
from rsrcdump.extract import extract_resource_map
from rsrcdump.textio import parse_type_name

description = (
    "Extract resources from a Macintosh resource fork. "
    "https://github.com/jorio/rsrcdump"
)

epilog = (
    "When specifying an OSType (resource type name), it will be padded with "
    "spaces if it is less than 4 characters long. You can also pass OSTypes as "
    "a URL-encoded string, e.g. '%53%54%52%20' will be interpreted as 'STR '."
)

parser = argparse.ArgumentParser(prog="rsrcdump", description=description, epilog=epilog)
parser.add_argument('file', type=str, help="path to resource fork")
parser.add_argument('-l', '--list', action='store_true', help="list resources on stdout instead of extracting")
parser.add_argument('-o', metavar='outpath', type=str, help="destination folder. If omitted, will create a folder named <FILENAME>_resources in the current working directory")
parser.add_argument('--no-adf', action='store_true', help="don't interpret input file as AppleDouble")
parser.add_argument('-i', '--include-type', action='append', metavar='type', help="only extract this resource type (four-character OSType)")
parser.add_argument('-x', '--exclude-type', action='append', metavar='type', help="exclude this resource type (four-character OSType)")
args = parser.parse_args()

inpath = args.file
outpath = args.o
listmode = args.list

# Generate an output path if we're not given one
if not outpath:
    namedfork_suffix = "/..namedfork/rsrc"

    stem = inpath
    print(stem)
    if stem.endswith(namedfork_suffix):
        stem = stem[:-len(namedfork_suffix)]
    stem = os.path.basename(stem)

    outpath = os.path.join(os.getcwd(), stem + "_resources")
    if outpath.startswith("._"):
        outpath = outpath[2:]

include_types = []
exclude_types = []
if args.include_type:
    include_types = [ parse_type_name(t) for t in args.include_type ]
if args.exclude_type:
    exclude_types = [ parse_type_name(t) for t in args.exclude_type ]

res_map = {}

with open(inpath, 'rb') as file:
    if not args.no_adf:
        adf_entries = unpack_adf(file.read())
        adf_resfork = adf_entries[ADF_ENTRYNUM_RESOURCEFORK]
        res_map = unpack_resfork(adf_resfork)
    else:
        res_map = unpack_resfork(file.read())

if listmode:
    print(F"{'Type':4} {'ID':6} {'Size':8}  {'Name'}")
    print(F"{'-'*4} {'-'*6} {'-'*8}  {'-'*32}")
    for res_type in sorted(res_map, key=lambda a: a.decode('macroman').upper()):
        for res_id in sorted(res_map[res_type]):
            res = res_map[res_type][res_id]
            typestr = res.type.decode('macroman')
            print(F"{typestr:4} {res.num:6} {len(res.data):8}  {res.name.decode('macroman')}")
    sys.exit(0)
else:
    extract_resource_map(res_map, outpath, include_types, exclude_types)
