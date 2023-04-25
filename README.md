# rsrcdump: Extract & convert Mac resource forks

Run rsrcdump on an [AppleDouble file](https://en.wikipedia.org/wiki/AppleDouble) and it’ll produce a JSON file with the contents of the [resource fork](https://en.wikipedia.org/wiki/Resource_fork).

You can also use rsrcdump to [create a resource fork from JSON input](#create), enabling you to edit resource forks on a modern setup without fiddling with ResEdit.

Additionally, rsrcdump can convert some resource types to formats usable in modern tools:

| Resource type                      | Converts to                                               |
|------------------------------------|-----------------------------------------------------------|
| cicn                               | PNG                                                       |
| icl4, icl8, ICN#, ics#, ics4, ics8 | PNG                                                       |
| PICT                               | PNG (raster only – see [known limitations](#limitations)) |
| ppat                               | PNG                                                       |
| snd                                | AIFF-C (see [note on AIFF-C files](#aiff) below)          |
| SICN                               | PNG                                                       |
| STR, TEXT                          | UTF-8 text (stored in index.json)                         |
| STR#                               | Array of UTF-8 strings (stored in index.json)             |
| Other resource types               | Hex dump or [structured JSON](#struct)                    |


## Requirements

Python **3.10** or later.

(Note that macOS currently ships with Python 3.9, which is too old; you can install a more recent version via Homebrew.)

## Table of contents

- How to use
  - [Dual-fork files on macOS](#dualfork)
  - [Zip archives made with macOS, extracted on Windows/Linux](#zip)
  - [Old archive formats (.bin/.sit/.cpt) extracted by The Unarchiver](#unar)
  - [Files on a host volume shared with BasiliskII or SheepShaver](#emulators)
- [Advanced usage patterns (list, include, exclude)](#advanced-usage-patterns)
- [Dealing with “weird” resource type names](#weird)
- [Generate structured JSON from arbitrary resource data](#struct)
- [Create resource forks from JSON files](#create)
- [Note on AIFF-C files](#aiff)
- [Known limitations](#limitations)
- [License](#license)

## How to use

Let’s look at extracting a resource fork when your file originates from one of the following scenarios:

- Dual-fork files on modern versions of macOS
- Zip archives made with macOS, extracted on Windows/Linux (__MACOSX folder)
- Old archive formats (.bin/.sit/.cpt) extracted by The Unarchiver
- Files on a host volume shared with BasiliskII or SheepShaver (not AppleDouble)

### <a name="dualfork"/>Dual-fork files on macOS

This section only applies to macOS.

On modern versions of macOS, resource forks still exist. They can be accessed by appending `/..namedfork/rsrc` to a filename. This yields a “naked” resource fork (not encapsulated in an AppleDouble file), so you must tell rsrcdump about it with the `--no-adf` switch.

So, **on macOS,** let's try to extract the music from Mighty Mike. Get [`Mighty Mike.zip` from Pangea Software](https://pangeasoft.net/mightymike/files), and unzip it. Then run:

```bash
rsrcdump.sh --extract "Mighty Mike™/Data/Music/..namedfork/rsrc" --no-adf
```
You’ll find the extracted files in `Music.json` plus a folder named `Music.json_resources` in the current working directory.

### <a name="zip"/>Zip archives made with macOS, extracted on Windows/Linux (__MACOSX folder)

If you have ever come across a zip file made with macOS, you may have noticed that extracting it on Windows or Linux produces a directory named `__MACOSX`. That folder contains resource forks as AppleDouble files. rsrcdump can work with those. (Note that files inside __MACOSX may be hidden for you because they start with a dot.)

For example, if you’re using **Linux,** get [`Mighty Mike.zip` from Pangea Software](https://pangeasoft.net/mightymike/files), and unzip it. You can then run this command to extract the game’s music:

```bash
rsrcdump.sh --extract "__MACOSX/Mighty Mike™/Data/._Music"
```

You’ll find the extracted files in `Music.json` plus a folder named `Music.json_resources` in the current working directory.

### <a name="unar"/>Old archive formats (.bin/.sit/.cpt) extracted by The Unarchiver

If you have an old Mac archive (such as .sit, .cpt, .bin, etc.), you can use [the command-line version of The Unarchiver](https://theunarchiver.com/command-line) and tell it to keep the resource forks. They’ll appear as `.rsrc` files once extracted. The Unarchiver wraps them in an AppleDouble container, which is perfect for use with rsrcdump.

As an example, get [`bloodsuckers.bin` from Pangea Software](https://pangeasoft.net/files) and extract it like so:

```bash
unar -k visible bloodsuckers.bin
```

Then you can extract the sound effects with:

```bash
rsrcdump.sh --extract "bloodsuckers/Data/Sounds.rsrc"
```

You’ll find the extracted files in `Sounds.json` plus a folder named `Sounds.json_resources` in the current working directory.

### <a name="emulators"/>Files on a host volume shared with BasiliskII or SheepShaver (not AppleDouble)

When you share a host volume with BasiliskII or Sheepshaver, the emulator stores resource forks in a folder named `.rsrc`.

The emulators do **not** encapsulate the resource forks in an AppleDouble container; they’re just “naked” resource forks. So you must tell rsrcdump to bypass AppleDouble detection with the `--no-adf` argument.

For example:

```bash
rsrcdump.sh --extract ".rsrc/SomeResourceFile" --no-adf
```

## Advanced usage patterns

### List resources without extracting

```bash
rsrcdump.sh --list "Bloodsuckers 2.0.1.rsrc"
```

### Only include specific resource types

If you’re only interested in a few resource types, pass them with `-i` (or `--include`).

For example, if you’re interested in `STR ` and `icl8` resources only, you could use this:

```bash
rsrcdump.sh --extract "Bloodsuckers 2.0.1.rsrc" -i STR -i icl8
```

### Exclude specific resource types

Same as above, but use `-e` (or `--exclude`) instead of `-i`.

## <a name="weird"/>Dealing with “weird” resource type names

Switches like `--include`, `--exclude` and [`--struct`](#struct) work with 4-character resource type names (also known as “ResType”).

If a ResType is difficult to spell out on the command line, you can use a “URL-encoded” version of it. For example, `%53%54%52%23` and `STR%23` are both equivalent to `STR#`.

Also note that if you pass a ResType with fewer than 4 characters, it will be right-padded with spaces. So, `STR` will be interpreted as `STR `.

## <a name="struct"/>Generate structured JSON from arbitrary resource data

With `--struct`, you can customize the JSON output for specific resource types. These resources will appear as structured data in the JSON output instead of a raw hex dump.

`--struct` takes an argument that must follow the `restype:format:fields` template, where:

- `restype` is the four-character code of the resource type;
- `format` is a [Python struct format string](https://docs.python.org/3/library/struct.html#format-characters) describing the data layout of the struct;
- `fields` is a list of names for each field (optional).

Adding a `+` to the end of the format string signifies that this struct may be repeated multiple times in a single resource.

You can combine several `--struct` switches. You can also put all of your struct specifications in a text file and pass it to rsrcdump with `--struct-file` (see the included file [sample-specs.txt](sample-specs.txt)).

**Example 1:** Parse a `Hedr` from [Otto Matic](https://github.com/jorio/OttoMatic) terrain files:

```bash
rsrcdump.sh --extract \
  --struct "Hedr:L5i3f4i44s:vers,items,width,height,tilePages,tiles,tileSize,minY,maxY,splines,fences,uniqueST,waters" \
  EarthFarm.ter.rsrc
```

The JSON output will look like:

```json
{
  "vers": 134217728,
  "items": 594,
  "width": 176,
  "height": 176,
  "tilePages": 28,
  "tiles": 21881,
  "tileSize": 10.0,
  "minY": 0.0,
  "maxY": 68.0,
  "splines": 26,
  "fences": 46,
  "uniqueST": 428,
  "waters": 7,
  ".field13": "0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
}
```

**Example 2:** Parse a *list* of `FnNb` (fence nub positions) from Otto Matic terrain files:

```bash
rsrcdump.sh --extract --struct "FnNb:ii+:x,z" EarthFarm.ter.rsrc
```

The JSON output will look like:

```json
[
  [409, 2057],
  [335, 2057],
  [259, 2060],
  [184, 2062],
  ...
]
```

**Example 3:** Parse an Otto Matic terrain file with all struct converters defined in [sample-specs.txt](sample-specs.txt):

```bash
rsrcdump.sh --extract --struct-file sample-specs.txt EarthFarm.ter.rsrc
```

## <a name="create"/>Create resource forks from JSON files

With `--create`, rsrcdump can *create* resource files from JSON input, enabling you to edit resource forks on a modern setup without fiddling with ResEdit.

The JSON input may be structured with the help of [custom struct converters](#struct).

**Example:** Say you have extracted one of Otto Matic’s level files, for example “EarthFarm.ter.rsrc”, to “EarthFarm.ter.json” (with `--struct-file sample-specs.txt`). You’ve edited the JSON file by hand and now you want to pack it back to a resource fork so you can play your modded version. Simply run `rsrcdump --create` with the JSON file as input:

```bash
rsrcdump.sh --create --struct-file sample-specs.txt EarthFarm.ter.json -o MyModdedEarthFarm.ter.rsrc
```

## <a name="aiff"/>Note on AIFF-C files

AIFF-C files produced by rsrcdump are 1-to-1 conversions of the `snd` resources. The sample stream inside the AIFF-C file is a verbatim copy of the `snd` resource’s sample stream, keeping the original codec intact.

This means that, for further processing, you’ll need to use software that supports the codec used in the original resource. (Common codecs include `MAC3`, `ima4`, etc.)

You’ll have good results with ffmpeg or Audacity. Other audio editors may have incomplete support for old AIFF-C codecs.

## <a name="limitations"/>Known limitations

- Compressed resources are not supported.
- PICT conversion:
    - Only raster images are supported
    - Vector and text opcodes not supported.
    - QuickTime-compressed images not supported.
- `--create` doesn’t support external files (e.g. you can’t create a resource fork of PICTs from PNG files).

## License

© 2023 Iliyas Jorio, [MIT license](LICENSE.md)
