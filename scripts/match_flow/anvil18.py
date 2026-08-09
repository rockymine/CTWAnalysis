#!/usr/bin/env python3
"""Minimal Minecraft 1.8 (pre-flattening) Anvil reader.

Reads region files directly so that block-level structure — bedrock walls in
particular — can be located without a world scan through the main pipeline.
1.8 stores a section's blocks as a flat 4096-byte array plus an optional `Add`
nibble array, which is why anvil-parser (written for 1.13+ block states) cannot
be used here.

Used by bedrock.py.
"""
import os, struct, zlib, io
from nbt import nbt

def region_files(region_dir):
    for f in os.listdir(region_dir):
        if f.startswith('r.') and f.endswith('.mca'):
            _, rx, rz, _ = f.split('.')
            yield int(rx), int(rz), os.path.join(region_dir, f)

def chunks(path):
    with open(path, 'rb') as fh:
        header = fh.read(4096)
        for i in range(1024):
            off, cnt = struct.unpack('>I', b'\x00' + header[i*4:i*4+3])[0], header[i*4+3]
            if off == 0: continue
            fh.seek(off * 4096)
            length = struct.unpack('>I', fh.read(4))[0]
            comp = fh.read(1)[0]
            data = fh.read(length - 1)
            raw = zlib.decompress(data) if comp == 2 else data
            yield nbt.NBTFile(buffer=io.BytesIO(raw))

def scan(region_dir, x0, x1, z0, z1, want_ids, ymax=64):
    """Return {(x, y, z): block_id} for blocks whose id is in want_ids inside the bbox."""
    out = {}
    for rx, rz, path in region_files(region_dir):
        if (rx+1)*512 <= x0 or rx*512 > x1 or (rz+1)*512 <= z0 or rz*512 > z1: continue
        for nbtf in chunks(path):
            lvl = nbtf['Level']
            cx, cz = lvl['xPos'].value, lvl['zPos'].value
            bx, bz = cx*16, cz*16
            if bx+15 < x0 or bx > x1 or bz+15 < z0 or bz > z1: continue
            for sec in lvl['Sections']:
                sy = sec['Y'].value * 16
                if sy > ymax: continue
                blocks = sec['Blocks'].value
                add = sec['Add'].value if 'Add' in sec else None
                for i, b in enumerate(blocks):
                    if b == 0: continue
                    bid = b & 0xFF
                    if add is not None:
                        hi = add[i >> 1]
                        bid |= ((hi >> 4) if i & 1 else (hi & 0x0F)) << 8
                    if bid not in want_ids: continue
                    y = sy + (i >> 8); z = bz + ((i >> 4) & 15); x = bx + (i & 15)
                    if x0 <= x <= x1 and z0 <= z <= z1 and y <= ymax:
                        out[(x, y, z)] = bid
    return out
