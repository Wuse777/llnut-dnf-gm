"""Local-only PVF metadata reader. No code injection and no PVF editing.

Independent implementation of the PVF word-rotation format: XOR with file CRC
and 0x81a79011, rotate each little-endian 32-bit word right by six. Format
reference (not vendored): Zageku/DNF_pvf_python @ 8b01148bb93c0ddf47d0b35bd222646be039084d.
Bounds are checked; unknown token/string constructs never gain mailing rights.
"""
from array import array
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys


def decode_words(data, crc):
    if len(data) % 4:
        raise ValueError('Unaligned encrypted PVF block')
    a = array('I')
    a.frombytes(data)
    if sys.byteorder != 'little':
        a.byteswap()
    key = crc ^ 0x81A79011
    for i, word in enumerate(a):
        n = word ^ key
        a[i] = ((n >> 6) | ((n & 63) << 26)) & 0xffffffff
    if sys.byteorder != 'little':
        a.byteswap()
    return a.tobytes()


class Reader:
    def __init__(self, path, encoding='gbk'):
        self.file = Path(path).open('rb')
        self.size = Path(path).stat().st_size
        self.encoding = encoding
        def u32():
            return struct.unpack('<I', self.file.read(4))[0]
        n = u32()
        if n > 1024:
            raise ValueError('Invalid PVF identifier')
        self.file.read(n)
        self.version, length, crc, count = u32(),u32(),u32(),u32()
        if length > self.size or count > 2000000:
            raise ValueError('Invalid PVF header')
        self.base = self.file.tell()+length
        tree = memoryview(decode_words(self.file.read(length),crc))
        self.tree = {}
        pos = 0
        for _ in range(count):
            _, pathlen = struct.unpack_from('<II',tree,pos)
            pos += 8
            if pathlen > 2048 or pos+pathlen+12 > len(tree):
                raise ValueError('Invalid PVF directory entry')
            name = bytes(tree[pos:pos+pathlen]).decode('utf-8',errors='surrogateescape').lower().replace('\\','/')
            pos += pathlen
            size,crc,offset = struct.unpack_from('<III',tree,pos)
            pos += 12
            if self.base+offset+((size+3)&~3) > self.size:
                raise ValueError('PVF offset out of range')
            self.tree[name] = (size,crc,offset)
        self.strings = self.read('stringtable.bin')[4:]
        self.string_count = struct.unpack('<I',self.read('stringtable.bin')[:4])[0]
        self.nstrings = dict(self.mapping('n_string.lst')) if 'n_string.lst' in self.tree else {}

    def close(self):
        self.file.close()

    def read(self,name):
        size,crc,offset = self.tree[name.lower()]
        self.file.seek(self.base+offset)
        return decode_words(self.file.read((size+3)&~3),crc)[:size]

    @lru_cache(maxsize=65536)
    def string(self,n):
        if not 0 <= n < self.string_count:
            raise ValueError('PVF string index out of range')
        start,end = struct.unpack_from('<II',self.strings,n*4)
        if end < start or end > len(self.strings):
            raise ValueError('PVF string offset out of range')
        return self.strings[start:end].decode(self.encoding,errors='replace')

    @lru_cache(maxsize=64)
    def external_strings(self, n):
        path=self.nstrings.get(n)
        if not path or path.lower() not in self.tree:
            return {}
        values={}
        for line in self.read(path).decode(self.encoding,errors='replace').splitlines():
            if '>' in line:
                k,v=line.split('>',1);values[k]=v
        return values

    def tokens(self, name):
        data=self.read(name)
        tokens=[]
        i=2
        while i+5 <= len(data):
            kind=data[i];n=struct.unpack_from('<i',data,i+1)[0];i+=5
            if kind in (2,3):tokens.append((kind,n))
            elif kind==4:tokens.append((kind,struct.unpack('<f',struct.pack('<i',n))[0]))
            elif kind in (5,6,7,8):tokens.append((kind,self.string(n)))
            elif kind==9 and i+5<=len(data):
                key=self.string(struct.unpack_from('<i',data,i+1)[0]);i+=5
                tokens.append((7,self.external_strings(n).get(key,'')))
            else:tokens.append((kind,None))
        return tokens

    def mapping(self,name):
        tokens=self.tokens(name)
        for i in range(0,len(tokens)-1,2):
            a,b=tokens[i:i+2]
            if a[0]==2 and b[0]==7:yield a[1],b[1]
            elif b[0]==2 and a[0]==7:yield b[1],a[1]

    def fields(self,name):
        fields={};key=None
        for t,v in self.tokens(name):
            if t==5 and isinstance(v,str):
                key=v;fields.setdefault(key,[])
            elif key:
                fields[key].append(v)
        return fields


def job_metadata(reader):
    """Offline names from the matching PVF, no hard-coded class/awakening guesses."""
    result = {}
    if 'character/character.lst' not in reader.tree:
        return result
    for job,path in reader.mapping('character/character.lst'):
        try:
            names = reader.fields('character/'+path).get('[growtype name]', [])
            if names and all(isinstance(n,str) and n for n in names):
                result[str(job)] = {'grow_names':names}
        except (ValueError,KeyError,UnicodeError):
            continue
    return result


def build_index(pvf_path, output, encoding='gbk', review_path=None):
    """Only explicitly reviewed ordinary items gain mailing permission.

    Review JSON maps id to {category,stack_limit,durability}. The extraction
    provides evidence, not an automatic declaration that a special item is safe.
    """
    pvf=Path(pvf_path)
    sha=hashlib.file_digest(pvf.open('rb'),'sha256').hexdigest()
    review=json.loads(Path(review_path).read_text()) if review_path else {}
    if review and review.get('pvf_sha256') != sha:
        raise ValueError('Review manifest does not match PVF')
    approved=review.get('items',{})
    output=Path(output)
    if output.exists():
        raise FileExistsError('Refusing to overwrite an installed index')
    r=Reader(pvf,encoding)
    c=sqlite3.connect(output)
    try:
        c.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE items(id INTEGER PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,level INTEGER NOT NULL,stack_limit INTEGER NOT NULL,durability INTEGER NOT NULL,allowed INTEGER NOT NULL,reviewed INTEGER NOT NULL,source_path TEXT NOT NULL); CREATE INDEX names ON items(name);')
        c.executemany('INSERT INTO metadata VALUES(?,?)',[('pvf_sha256',sha),('encoding',encoding),('format','dnfgm-catalog-v1')])
        c.execute('INSERT INTO metadata VALUES(?,?)',('jobs',json.dumps(job_metadata(r),ensure_ascii=False)))
        total,failed,allowed=0,0,0
        for prefix,lst in [('equipment','equipment/equipment.lst'),('stackable','stackable/stackable.lst')]:
            for item_id,relative in r.mapping(lst):
                if not isinstance(relative,str):continue
                path=(prefix+'/'+relative).replace('//','/').lower()
                try:
                    f=r.fields(path)
                    name=''.join(str(v) for v in f.get('[name]',[]) if v is not None).strip()
                    if not name:raise ValueError('Missing name')
                    def integer(k,default=0):
                        return next((v for v in f.get(k,[]) if type(v) is int),default)
                    kind=''.join(str(v) for v in f.get('[stackable type]',[]) if isinstance(v,str))
                    category='equipment' if prefix=='equipment' else ('material' if kind=='[material]' else 'consumable' if kind in ('[waste]','[usable]') else 'special')
                    if any(word in path for word in ('avatar','creature','pet/')):category='special'
                    cap=1 if category=='equipment' else integer('[stack limit]',0)
                    durability=integer('[durability]')
                    manifest=approved.get(str(item_id))
                    permitted=bool(manifest and category in ('equipment','material','consumable') and manifest['category']==category and manifest['stack_limit']==cap and manifest.get('durability',0)==durability and cap>=1)
                    if manifest and not permitted:raise ValueError('Review mismatch')
                    c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)',(item_id,name,category,integer('[minimum level]'),max(0,cap),max(0,durability),int(permitted),int(permitted),path))
                    total+=1;allowed+=int(permitted)
                except (ValueError,KeyError,UnicodeError,sqlite3.IntegrityError):
                    failed+=1
        c.execute('INSERT INTO metadata VALUES(?,?)',('extraction_failures',str(failed)))
        c.commit()
        if total==0:raise ValueError('Empty index')
        return {'pvf_sha256':sha,'items':total,'extraction_failures':failed,'reviewed_mailable':allowed}
    finally:
        c.close();r.close()
