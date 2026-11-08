"""Offline, bounded NPK/IMG reader; no archive member is extracted as a path.

Independent format implementation. References and unsupported variants are
listed in THIRD_PARTY.md. Never imported by the runtime image HTTP handler.
"""
from dataclasses import dataclass
from pathlib import Path
import binascii
import struct
import zlib

KEY=b'puchikon@neople dungeon and fighter '+b'DNF'*73+b'\0'
MAX_IMG=64*1024*1024
MAX_PIXELS=512*512
PNG_MAGIC=b'\x89PNG\r\n\x1a\n'


class AssetFormatError(ValueError):
    pass


def normalized(name):
    value=name.replace('\\','/').lower().strip('/')
    if not value or any(p in ('','..','.') for p in value.split('/')) or '\0' in value:
        raise AssetFormatError('Invalid logical asset name')
    return value


def inflate(data,expected):
    if not 0<=expected<=MAX_PIXELS*4:raise AssetFormatError('Decoded raster exceeds budget')
    stream=zlib.decompressobj()
    try:raw=stream.decompress(data,expected+1)
    except zlib.error as error:raise AssetFormatError('Invalid compressed raster') from error
    if len(raw)!=expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise AssetFormatError('Raster stream length mismatch')
    return raw


@dataclass(frozen=True)
class Raster:
    width:int
    height:int
    rgba:bytes

    def __post_init__(self):
        if not 1<=self.width<=512 or not 1<=self.height<=512 or len(self.rgba)!=self.width*self.height*4:
            raise AssetFormatError('Invalid icon/portrait dimensions')

    def png(self):
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)
        lines=b''.join(b'\0'+self.rgba[y*self.width*4:(y+1)*self.width*4] for y in range(self.height))
        return PNG_MAGIC+chunk(b'IHDR',struct.pack('>IIBBBBB',self.width,self.height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(lines))+chunk(b'IEND',b'')


def decode_png(data):
    """Normalize optional local RGB/RGBA8 PNG portraits; strip all ancillary data."""
    if not data.startswith(PNG_MAGIC) or len(data)>2*1024*1024:raise AssetFormatError('Invalid PNG')
    pos=8;header=None;payload=bytearray();ended=False;idat=False
    while pos<len(data):
        if pos+12>len(data):raise AssetFormatError('Truncated PNG chunk')
        n=struct.unpack_from('>I',data,pos)[0];kind=data[pos+4:pos+8];end=pos+12+n
        if end>len(data):raise AssetFormatError('PNG chunk exceeds file')
        value=data[pos+8:pos+8+n]
        if binascii.crc32(kind+value)&0xffffffff!=struct.unpack_from('>I',data,pos+8+n)[0]:raise AssetFormatError('PNG checksum mismatch')
        if pos==8 and kind!=b'IHDR':raise AssetFormatError('PNG header missing')
        if kind==b'IHDR':
            if header is not None or n!=13:raise AssetFormatError('Duplicate/invalid PNG header')
            header=struct.unpack('>IIBBBBB',value);w,h,depth,color,compress,filtering,interlace=header
            if not 1<=w<=512 or not 1<=h<=512 or depth!=8 or color not in (2,6) or any((compress,filtering,interlace)):
                raise AssetFormatError('Portrait PNG must be noninterlaced RGB/RGBA8, at most 512x512')
        elif kind==b'IDAT':payload.extend(value);idat=True
        elif kind==b'IEND':
            if n or end!=len(data):raise AssetFormatError('Invalid PNG end')
            ended=True;break
        elif kind[:1].isupper() and kind!=b'PLTE':raise AssetFormatError('Unsupported critical PNG chunk')
        pos=end
    if not ended or not header or not idat:raise AssetFormatError('Incomplete PNG')
    bpp=4 if header[3]==6 else 3;stride=w*bpp
    # Inflate includes one filter byte per row; independent bounded output.
    stream=zlib.decompressobj();limit=(stride+1)*h
    try:raw=stream.decompress(bytes(payload),limit+1)
    except zlib.error as error:raise AssetFormatError('Invalid PNG deflate') from error
    if len(raw)!=limit or not stream.eof or stream.unused_data or stream.unconsumed_tail:raise AssetFormatError('PNG decoded size mismatch')
    rgba=bytearray();prior=bytearray(stride)
    for y in range(h):
        method=raw[y*(stride+1)];line=bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        if method>4:raise AssetFormatError('Invalid PNG filter')
        for x in range(stride):
            a=line[x-bpp] if x>=bpp else 0;b=prior[x];c=prior[x-bpp] if x>=bpp else 0
            if method==1:predict=a
            elif method==2:predict=b
            elif method==3:predict=(a+b)//2
            elif method==4:
                p=a+b-c;dist=(abs(p-a),abs(p-b),abs(p-c));predict=(a,b,c)[dist.index(min(dist))]
            else:predict=0
            line[x]=(line[x]+predict)&255
        if bpp==4:rgba.extend(line)
        else:
            for x in range(0,stride,3):rgba.extend(line[x:x+3]);rgba.append(255)
        prior=line
    return Raster(w,h,bytes(rgba))


class Npk:
    def __init__(self,path):
        self.path=Path(path);self.members={}
        size=self.path.stat().st_size
        with self.path.open('rb') as f:
            if f.read(16).rstrip(b'\0')!=b'NeoplePack_Bill':raise AssetFormatError('Invalid NPK magic')
            raw=f.read(4)
            if len(raw)!=4:raise AssetFormatError('Truncated NPK')
            count=struct.unpack('<I',raw)[0];table_end=20+count*264
            if count>100000 or table_end>size:raise AssetFormatError('Invalid NPK member count')
            for _ in range(count):
                offset,length=struct.unpack('<II',f.read(8));encoded=f.read(256)
                name=bytes(a^b for a,b in zip(encoded,KEY)).split(b'\0',1)[0].decode('cp949')
                name=normalized(name)
                if offset<table_end or offset+length>size or length>MAX_IMG:raise AssetFormatError('NPK member outside bounded file')
                if name in self.members:raise AssetFormatError('Ambiguous duplicate NPK member')
                self.members[name]=(offset,length)

    def read(self,name):
        offset,length=self.members[normalized(name)]
        with self.path.open('rb') as f:f.seek(offset);data=f.read(length)
        if len(data)!=length:raise AssetFormatError('NPK changed while reading')
        return data



def dxt_size(width, height, fmt):
    """BC1/2/3 physical block size, including partial edge blocks."""
    if (type(width) is not int or type(height) is not int
            or not 1 <= width <= 512 or not 1 <= height <= 512
            or type(fmt) is not int or fmt not in (18, 19, 20)):
        raise AssetFormatError('Invalid DXT raster dimensions or format')
    return ((width + 3) // 4) * ((height + 3) // 4) * (8 if fmt == 18 else 16)


def decode_dxt(raw, width, height, fmt):
    """Independent, offline-only DXT1/3/5 -> straight RGBA8 decoder.

    Format identifiers come from the NPK format reference; block layout and
    interpolation come from Microsoft's BC1/BC2/BC3 documentation. No third-
    party decoder, native library, DDS wrapper or external command is used.
    """
    if len(raw) != dxt_size(width, height, fmt):
        raise AssetFormatError('DXT block payload length mismatch')
    pixels = bytearray(width * height * 4)
    stride = 8 if fmt == 18 else 16
    blocks_x = (width + 3) // 4
    for offset in range(0, len(raw), stride):
        block = raw[offset:offset + stride]
        color_offset = 0 if fmt == 18 else 8
        color0, color1, indices = struct.unpack_from('<HHI', block, color_offset)
        colors = []
        for color in (color0, color1):
            r, g, b = (color >> 11) & 31, (color >> 5) & 63, color & 31
            colors.append(((r << 3) | (r >> 2), (g << 2) | (g >> 4),
                           (b << 3) | (b >> 2), 255))
        if fmt != 18 or color0 > color1:
            for a, b in ((2, 1), (1, 2)):
                colors.append(tuple((a * colors[0][c] + b * colors[1][c]) // 3
                                    for c in range(3)) + (255,))
        else:
            colors.append(tuple((colors[0][c] + colors[1][c]) // 2
                                for c in range(3)) + (255,))
            colors.append((0, 0, 0, 0))
        alpha_bits = 0
        alpha_values = None
        if fmt == 19:
            alpha_bits = int.from_bytes(block[:8], 'little')
        elif fmt == 20:
            a0, a1 = block[0], block[1]
            alpha_values = [a0, a1]
            if a0 > a1:
                alpha_values.extend(((7 - n) * a0 + n * a1) // 7
                                    for n in range(1, 7))
            else:
                alpha_values.extend(((5 - n) * a0 + n * a1) // 5
                                    for n in range(1, 5))
                alpha_values.extend((0, 255))
            alpha_bits = int.from_bytes(block[2:8], 'little')
        block_index = offset // stride
        x0, y0 = (block_index % blocks_x) * 4, (block_index // blocks_x) * 4
        for n in range(16):
            x, y = x0 + n % 4, y0 + n // 4
            if x >= width or y >= height:
                continue
            r, g, b, a = colors[(indices >> (2 * n)) & 3]
            if fmt == 19:
                a = ((alpha_bits >> (4 * n)) & 15) * 17
            elif fmt == 20:
                a = alpha_values[(alpha_bits >> (3 * n)) & 7]
            start = (y * width + x) * 4
            pixels[start:start + 4] = bytes((r, g, b, a))
    return bytes(pixels)

def decode_img(data,index):
    """v2/v4 common frames, links, raw color, palette and DXT1/3/5.

    Sprite compression, palette+DXT, v1 and v5 remain explicit unsupported
    states. Both cropped and transparent canvas bounds are checked.
    """
    if len(data)<32 or len(data)>MAX_IMG or data[:16].rstrip(b'\0')!=b'Neople Img File':raise AssetFormatError('Unsupported IMG header')
    table_size,_,version,count=struct.unpack_from('<4i',data,16)
    if version not in (2,4):raise AssetFormatError('Unsupported IMG version')
    if not 0<count<=100000 or type(index) is not int or not 0<=index<count:raise AssetFormatError('IMG frame out of range')
    pos=32;palette=None
    if version==4:
        if pos+4>len(data):raise AssetFormatError('Truncated palette')
        colors=struct.unpack_from('<i',data,pos)[0];pos+=4
        if not 0<=colors<=256 or pos+colors*4>len(data):raise AssetFormatError('Invalid palette')
        if colors:palette=[data[p:p+4] for p in range(pos,pos+colors*4,4)]
        pos+=colors*4
    frames=[]
    for _ in range(count):
        if pos+4>len(data):raise AssetFormatError('Truncated frame table')
        fmt=struct.unpack_from('<i',data,pos)[0]
        if fmt==17:
            if pos+8>len(data):raise AssetFormatError('Truncated linked frame')
            target=struct.unpack_from('<i',data,pos+4)[0]
            if not 0<=target<count:raise AssetFormatError('Linked frame out of range')
            frames.append({'link':target});pos+=8;continue
        if pos+36>len(data):raise AssetFormatError('Truncated frame table')
        fmt,extra,w,h,size,x,y,cw,ch=struct.unpack_from('<9i',data,pos);pos+=36
        if fmt not in (14,15,16,18,19,20) or extra not in (5,6):raise AssetFormatError('Unsupported IMG pixel/compression variant')
        # Every payload must remain bounded so offsets can be checked, but a
        # different frame's placement does not determine this icon's canvas.
        # Real client sheets contain unused frames just outside that canvas.
        if not 1<=w<=512 or not 1<=h<=512 or not 1<=cw<=512 or not 1<=ch<=512:
            raise AssetFormatError('Icon canvas out of bounds')
        if fmt in (18,19,20):
            if palette:raise AssetFormatError('Unsupported palette/DXT combination')
            decoded=dxt_size(w,h,fmt)
            # For raw block data the declared size must agree with the block
            # layout; do not guess padding or shift every subsequent frame.
            if extra==5 and size!=decoded:
                raise AssetFormatError('Unsupported raw DXT payload size')
        else:
            decoded=w*h*(4 if fmt==16 else 2)
            if extra==5:size=decoded
            elif palette:decoded=w*h
        if not 0<size<=MAX_IMG:raise AssetFormatError('Invalid frame payload size')
        frames.append(dict(fmt=fmt,extra=extra,w=w,h=h,size=size,x=x,y=y,cw=cw,ch=ch,decoded=decoded))
    payload=32+table_size if version==2 else pos
    if payload<pos or payload>len(data):raise AssetFormatError('Invalid IMG data offset')
    for frame in frames:
        if 'link' in frame:continue
        frame['offset']=payload;payload+=frame['size']
        if payload>len(data):raise AssetFormatError('IMG frame outside file')
    seen=set()
    while 'link' in frames[index]:
        if index in seen:raise AssetFormatError('Cyclic IMG frame link')
        seen.add(index);index=frames[index]['link']
    f=frames[index]
    if not 0<=f['x']<=f['cw']-f['w'] or not 0<=f['y']<=f['ch']-f['h']:
        raise AssetFormatError('Icon canvas out of bounds')
    raw=data[f['offset']:f['offset']+f['size']]
    if f['extra']==6:raw=inflate(raw,f['decoded'])
    pixels=bytearray()
    if f['fmt'] in (18,19,20):
        pixels.extend(decode_dxt(raw,f['w'],f['h'],f['fmt']))
    elif palette and f['extra']==6:
        for n in raw:
            if n>=len(palette):raise AssetFormatError('Palette index out of range')
            pixels.extend(palette[n])
    elif f['fmt']==16:
        for i in range(0,len(raw),4):pixels.extend((raw[i+2],raw[i+1],raw[i],raw[i+3]))
    else:
        for (v,) in struct.iter_unpack('<H',raw):
            if f['fmt']==14:
                r,g,b=(v>>10)&31,(v>>5)&31,v&31
                pixels.extend(((r<<3)|(r>>2),(g<<3)|(g>>2),(b<<3)|(b>>2),255 if v&0x8000 else 0))
            else:pixels.extend((((v>>8)&15)*17,((v>>4)&15)*17,(v&15)*17,((v>>12)&15)*17))
    canvas=bytearray(f['cw']*f['ch']*4)
    for y in range(f['h']):
        start=((f['y']+y)*f['cw']+f['x'])*4
        canvas[start:start+f['w']*4]=pixels[y*f['w']*4:(y+1)*f['w']*4]
    return Raster(f['cw'],f['ch'],bytes(canvas))
