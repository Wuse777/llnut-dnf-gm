"""Offline-only preservation of registered appearance v2 atlas resources."""
import binascii
import hashlib
import json
from pathlib import Path
import struct

from .appearance_manifest import MAX_DECODED_BYTES,SHA,validate_clip
from .npk_assets import AssetFormatError


def copy_appearance_atlases(connection,source,output):
    """Validate copied SQLite references and copy exact private PNGs to a NEW pack.

    The caller has already backed up the complete source database. This helper
    never changes either database and never copies unregistered directory files.
    """
    meta=dict(connection.execute('SELECT key,value FROM metadata'))
    if 'appearance_version' not in meta:return
    if meta['appearance_version']!='2':raise AssetFormatError('Unsupported source appearance version')
    source,output=Path(source),Path(output)
    directory=source/'atlases';target=output/'atlases'
    if directory.is_symlink() or not directory.is_dir() or target.exists() or target.is_symlink():
        raise AssetFormatError('Invalid source or target appearance atlas directory')
    pages={}
    for key,width,height,size in connection.execute('SELECT sha256,width,height,bytes FROM appearance_atlases'):
        if (not isinstance(key,str) or not SHA.fullmatch(key) or key in pages
                or any(type(v) is not int for v in (width,height,size))
                or not 1<=width<=2048 or not 1<=height<=2048 or not 33<=size<=16*1024*1024):
            raise AssetFormatError('Invalid source appearance atlas registry')
        pages[key]={'width':width,'height':height,'bytes':size}
    for state,payload in connection.execute('SELECT state,payload_json FROM appearance_parts'):
        if state not in ('ready','partial','unsupported'):raise AssetFormatError('Invalid source appearance state')
        if state=='unsupported':continue
        if not isinstance(payload,str) or len(payload)>512*1024:raise AssetFormatError('Source appearance component budget')
        clip=validate_clip(json.loads(payload),pages)
        used={d['atlas'] for f in clip['frames'] for d in f['draws']}
        if sum(pages[key]['width']*pages[key]['height']*4 for key in used)>MAX_DECODED_BYTES:
            raise AssetFormatError('Source appearance decoded atlas budget')
    target.mkdir(mode=0o750)
    for key,page in pages.items():
        path=directory/(key+'.png')
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=page['bytes']:
            raise AssetFormatError('Source appearance atlas unavailable')
        data=path.read_bytes()
        if (len(data)!=page['bytes'] or hashlib.sha256(data).hexdigest()!=key or len(data)<33
                or data[:16]!=b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR'
                or struct.unpack('>II',data[16:24])!=(page['width'],page['height'])
                or data[24:29]!=bytes((8,6,0,0,0))
                or struct.unpack('>I',data[29:33])[0]!=(binascii.crc32(data[12:29])&0xffffffff)):
            raise AssetFormatError('Source appearance atlas checksum or dimensions mismatch')
        (target/path.name).write_bytes(data)
