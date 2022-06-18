# rsrcdump

Extracts and converts resources from [Macintosh resource forks](https://en.wikipedia.org/wiki/Resource_fork).

Run rsrcdump on an [AppleDouble file](https://en.wikipedia.org/wiki/AppleDouble) and it’ll produce a JSON file with the contents of the resource fork.

Additionally, rsrcdump will convert some resource types to formats usable in modern tools:

Resource type | Converts to
-------|------------
cicn | PNG
icl4, icl8, ICN#, ics#, ics4, ics8 | PNG
PICT (raster only\*) | PNG
ppat | PNG
snd  | AIFF-C (see [note on AIFF-C files](#note-on-aiff-c-files) below)
SICN | PNG
STR, TEXT | UTF-8 text (stored in index.json)
STR# | Array of UTF-8 strings (stored in index.json)

\* Only the raster part of PICTs is extracted. Complex PICTs containing text or vector opcodes aren’t supported.

## Requirements

Python 3.10 or later.

## How to use

Let’s look at extracting a resource fork when your file originates from one of the following scenarios:

- Dual-fork files on modern versions of macOS
- Zip archives made with macOS, extracted on Windows/Linux (__MACOSX folder)
- Old archive formats (.bin/.sit/.cpt) extracted by The Unarchiver
- Files on a host volume shared with BasiliskII or SheepShaver (not AppleDouble)

### Dual-fork files on macOS

This section only applies to macOS.

On modern versions of macOS, resource forks still exist. They can be accessed by appending `/..namedfork/rsrc` to a filename. This yields a “naked” resource fork (not encapsulated in an AppleDouble file), so you must tell rsrcdump about it with the `--no-adf` switch.

So, **on macOS,** let's try to extract the music from Mighty Mike. Get [`Mighty Mike.zip` from Pangea Software](https://pangeasoft.net/mightymike/files), and unzip it. Then run:

```bash
rsrcdump.sh "Mighty Mike™/Data/Music/..namedfork/rsrc" --no-adf
```
You’ll find the extracted files in a folder named `Music_resources` in the current working directory.

### Zip archives made with macOS, extracted on Windows/Linux (__MACOSX folder)

If you have ever come across a zip file made with macOS, you may have noticed that extracting it on Windows or Linux produces a directory named `__MACOSX`. That folder contains resource forks as AppleDouble files. rsrcdump can work with those. (Note that files inside __MACOSX may be hidden for you because they start with a dot.)

For example, if you’re using **Linux,** get [`Mighty Mike.zip` from Pangea Software](https://pangeasoft.net/mightymike/files), and unzip it. You can then run this command to extract the game’s music:

```bash
rsrcdump.sh "__MACOSX/Mighty Mike™/Data/._Music"
```

You’ll find the extracted files in a folder named `Music_resources` in the current working directory.

### Old archive formats (.bin/.sit/.cpt) extracted by The Unarchiver

If you have an old Mac archive (such as .sit, .cpt, .bin, etc.), you can use [the command-line version of The Unarchiver](https://theunarchiver.com/command-line) and tell it to keep the resource forks. They’ll appear as `.rsrc` files once extracted. The Unarchiver wraps them in an AppleDouble container, which is perfect for use with rsrcdump.

As an example, get [`bloodsuckers.bin` from Pangea Software](https://pangeasoft.net/files) and extract it like so:

```bash
unar -k visible bloodsuckers.bin
```

Then you can extract the sound effects with:

```bash
rsrcdump.sh "bloodsuckers/Data/Sounds.rsrc"
```

You’ll find the extracted files in a folder named `Sounds_resources` in the current working directory.

### Files on a host volume shared with BasiliskII or SheepShaver (not AppleDouble)

When you share a host volume with BasiliskII or Sheepshaver, the emulator stores resource forks in a folder named `.rsrc`.

The emulators do **not** encapsulate the resource forks in an AppleDouble container; they’re just “naked” resource forks. So you must tell rsrcdump to bypass AppleDouble detection with the `--no-adf` argument.

For example:

```bash
rsrcdump.sh ".rsrc/SomeResourceFile" --no-adf
```

## Advanced usage patterns

### List resources without extracting

```bash
rsrcdump.sh "Bloodsuckers 2.0.1.rsrc" --list
```

### Only include specific resource types

If you’re only interested in a few resource types, pass them with `-i`.

For example, if you’re interested in `STR ` and `icl8` resources only, you could use this:

```bash
rsrcdump.sh "Bloodsuckers 2.0.1.rsrc" -i STR -i icl8
```

Note that if the resource types that you pass have less than 4 characters, they will be padded with spaces. So, passing `STR` will be interpreted as `STR `.

You can also pass a “URL-encoded” version of the resource type name: `-i %53%54%52%20` is equivalent to `-i STR`. This is useful if your resource type names contain non-ASCII characters.

### Exclude specific resource types

Same as above, but use `-x` instead of `-i`.

## Note on AIFF-C files

AIFF-C files produced by rsrcdump are 1-to-1 conversions of the `snd` resources. The sample stream inside the AIFF-C file is a verbatim copy of the `snd` resource’s sample stream, keeping the original codec intact.

This means that, for further processing, you’ll need to use software that supports the codec used in the original resource. (Common codecs include `MAC3`, `ima4`, etc.)

You’ll have good results with ffmpeg or Audacity. Other audio editors may have incomplete support for old AIFF-C codecs.

## Known limitations

- Compressed resources are not supported.
- PICT conversion:
    - Vector and text opcodes not supported.
    - QuickTime-compressed images not supported.
    - Extremely old (“version 1”) PICTs not supported.

## License

© 2022 Iliyas Jorio, [MIT license](LICENSE.md)
