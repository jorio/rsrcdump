import math
import io
from rsrcdump.packutils import Unpacker, WritePlaceholder, pack_pstr
from dataclasses import dataclass
from struct import pack

kSoundResourceType_Standard     = 0x0001
kSoundResourceType_HyperCard    = 0x0002

kSampledSoundEncoding_stdSH     = 0x00      # standard sound header (noncompressed 8-bit mono sample data)
kSampledSoundEncoding_cmpSH     = 0xFE      # compressed sound header
kSampledSoundEncoding_extSH     = 0xFF      # extended sound header (noncompressed 8/16-bit mono or stereo)

initChanLeft                    = 0x0002    # left stereo channel
initChanRight                   = 0x0003    # right stereo channel
initMono                        = 0x0080    # monophonic channel
initStereo                      = 0x00C0    # stereo channel
initMACE3                       = 0x0300    # 3:1 compression
initMACE6                       = 0x0400    # 6:1 compression
initNoInterp                    = 0x0004    # no linear interpolation
initNoDrop                      = 0x0008    # no drop-sample conversion

@dataclass
class CodecInfo:
    name: str
    samples_per_packet: int
    bytes_per_packet: int
    aiff_bit_depth: int

    def calcsize(self, num_channels, num_packets):
        return num_channels * num_packets * self.bytes_per_packet

codec_info = {
    b'MAC3': CodecInfo("MACE 3-to-1",               6, 2, 8),
    #b'MAC6': None,  # MACE 6-to-1 unsupported for now
    b'ima4': CodecInfo("IMA 16 bit 4-to-1",         64, 34, 16),
    #b'NONE': CodecInfo("Signed PCM",                1, 0, 0),
    b'twos': CodecInfo("Signed big-endian PCM",     1, 2, 16),  # Assume 16-bit if 'twos' appears in cmpSH
    b'sowt': CodecInfo("Signed little-endian PCM",  1, 2, 16),  # Assume 16-bit if 'sowt' appears in cmpSH
    b'raw ': CodecInfo("Unsigned PCM",              1, 1, 8),   # Default for stdSH
    b'ulaw': CodecInfo("mu-law",                    1, 1, 8),
    b'alaw': CodecInfo("A-law",                     1, 1, 8),
}

class IFFChunkWriter:
    def __init__(self, stream, chunk_type):
        assert type(chunk_type) is bytes
        assert len(chunk_type) == 4
        self.stream = stream
        self.stream.write(chunk_type)
        self.length_placeholder = WritePlaceholder(stream, ">L")
        self.start_of_chunk = self.stream.tell()

    def __enter__(self):
        return self

    def __exit__(self, a, b, c):
        chunk_length = self.stream.tell() - self.start_of_chunk

        # Add zero pad byte if chunk length is odd
        if (chunk_length % 2) != 0:
            self.stream.write(b'\x00')

        self.length_placeholder.commit(chunk_length)

def convert_to_ieee_extended(num):
    if num < 0:
        sign = 0x8000
        num *= -1.0
    else:
        sign = 0x0000

    if num == 0:
        return b'\0' * 10

    fMant, expon = math.frexp(num)
    if (expon > 0x4000) or not (fMant < 1):  # infinity or NaN
        expon = sign | 0x7FFF  # infinity
        hiMant = 0
        loMant = 0
    else:  # finite
        expon += 0x3FFE
        if expon < 0:  # denormalized
            fMant = math.ldexp(fMant, expon)
            expon = 0
        expon |= sign
        fMant = math.ldexp(fMant, 32)
        fsMant = math.floor(fMant)
        hiMant = fsMant & 0xFFFFFFFF  # to ulong
        fMant = math.ldexp(fMant - fsMant, 32)
        fsMant = math.floor(fMant)
        loMant = fsMant & 0xFFFFFFFF  # to ulong

    return pack(">HLL", expon & 0xFFFF, hiMant, loMant)

def convert_snd_to_aiff(data, name):
    u = Unpacker(data)

    fmt, = u.unpack(">H")

    default_compression_type = b'????'

    if fmt == kSoundResourceType_Standard:
        num_modifiers, synth_type, init_bits = u.unpack(">hHL")
        assert 1 == num_modifiers
        assert 5 == synth_type
        if 0 != (init_bits & initMACE6):
            default_compression_type = b'MAC6'
        elif 0 != (init_bits & initMACE3):
            default_compression_type = b'MAC3'
    elif fmt == kSoundResourceType_HyperCard:
        u.unpack(">2x")  # skip reference count
        default_compression_type = b'MAC3'
    else:
        raise RuntimeError("Unsupported snd format")

    num_commands, = u.unpack(">h")
    #assert num_commands == 1
    sndhdr_offset = -1
    for i in range(num_commands):
        cmd, param1, param2 = u.unpack(">HHi")
        cmd &= 0x7FFF
        if cmd in [80, 81]:  # soundCmd or bufferCmd
            sndhdr_offset = param2
            break

    assert sndhdr_offset >= 0
    u.seek(sndhdr_offset)

    # ----
    # Read sound header

    zero, union_int, sample_rate_fixed, loop_start, loop_end, encoding, base_note = u.unpack(">iiLLLBB")
    assert 0 == zero

    if encoding == kSampledSoundEncoding_stdSH:
        compression_type = b'raw '
        num_channels = 1
        num_packets = union_int
    elif encoding == kSampledSoundEncoding_cmpSH:
        num_packets, compression_type = u.unpack(">i14x4s20x")
        num_channels = union_int
        if compression_type == b'\0\0\0\0':
            compression_type = default_compression_type
    elif encoding == kSampledSoundEncoding_extSH:
        num_channels = union_int
        num_packets, codec_bit_depth = u.unpack(">i22xh14x")
        if codec_bit_depth == 8:
            compression_type = b'raw '
        else:
            compression_type = b'twos'  # TODO: if 16-bit, should we use 'raw ' or NONE/twos?
        print(compression_type, codec_bit_depth, codec_info[compression_type])
        assert codec_info[compression_type].aiff_bit_depth == codec_bit_depth
    else:
        assert False, "Unsupported snd resource encoding"

    compressed_length = codec_info[compression_type].calcsize(num_channels, num_packets)

    if compressed_length != u.remaining():
        print(F"[WARNING] {u.remaining() - compressed_length} trailing bytes in snd resource '{name.decode('macroman')}'!")

    sample_data = u.read(compressed_length)

    # ----
    # Write AIFF

    return pack_aiff(
        codec_4cc       = compression_type,
        num_channels    = num_channels,
        num_packets     = num_packets,
        sample_rate     = sample_rate_fixed / 65536.0,
        sample_data     = sample_data,
        loop_start      = loop_start,
        loop_end        = loop_end,
        base_note       = base_note,
        name            = name)

def pack_aiff(
        codec_4cc,
        num_channels,
        num_packets,
        sample_rate,
        sample_data,
        loop_start,
        loop_end,
        base_note,
        name):
    has_loop = (loop_end - loop_start) > 1
    codec = codec_info[codec_4cc]

    aiff = io.BytesIO()

    with IFFChunkWriter(aiff, b'FORM'):
        aiff.write(b'AIFC')

        with IFFChunkWriter(aiff, b'FVER'):
            aiff.write(pack(">L", 0xA2805140))
        
        with IFFChunkWriter(aiff, b'COMM'):
            aiff.write(pack(">hLh10s4s",
                num_channels,
                num_packets,
                codec.aiff_bit_depth,
                convert_to_ieee_extended(sample_rate),
                codec_4cc))
            aiff.write(pack_pstr(codec.name, 2))

        if has_loop:
            with IFFChunkWriter(aiff, b'MARK'):
                aiff.write(pack(">h", 2))                    # 2 markers
                aiff.write(pack(">hL", 101, loop_start))     # marker 101
                aiff.write(pack_pstr("beg loop", 2))
                aiff.write(pack(">hL", 102, loop_end))       # marker 102
                aiff.write(pack_pstr("end loop", 2))

        if base_note != 60 or has_loop:
            with IFFChunkWriter(aiff, b'INST'):
                aiff.write(pack(">6b4h6x",
                    base_note,
                    0,                          #detune
                    0x00,0x7f,                  #lowNote, highNote
                    0x00,0x7f,                  #lowVelocity, highVelocity
                    0,                          #gain
                    1 if has_loop else 0,       #sustainLoop.playMode
                    101 if has_loop else 0,     #sustainLoop.beginLoop
                    102 if has_loop else 0))    #sustainLoop.endLoop
        
        if name:
            with IFFChunkWriter(aiff, b'NAME'):
                aiff.write(name)
        
        with IFFChunkWriter(aiff, b'ANNO'):
            annotation = F"Verbatim copy of data stream from 'snd ' resource.\n" + \
                F"MIDI base note: {int(base_note)}, sustain loop: {loop_start}-{loop_end}\n"
            aiff.write(annotation.encode('ascii'))

        with IFFChunkWriter(aiff, b'SSND'):
            aiff.write(b'\0\0\0\0')  # offset; don't care
            aiff.write(b'\0\0\0\0')  # blockSize; don't care
            aiff.write(sample_data)

    return aiff.getvalue()
