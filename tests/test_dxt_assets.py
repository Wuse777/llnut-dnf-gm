"""Standard block vectors and synthetic IMG only, never actual game artwork."""
import struct
import zlib

import pytest

from dnfgm.npk_assets import AssetFormatError, decode_dxt, decode_img, decode_png


def color_block(c0=0xf800, c1=0x07e0, indices=None):
    indices = [0, 1, 2, 3] * 4 if indices is None else indices
    return struct.pack('<HHI', c0, c1, sum(n << (2 * i) for i, n in enumerate(indices)))


def img(fmt, raw, *, compressed=False, version=2, width=4, height=4,
        x=0, y=0, canvas=None, links=False, palette=b''):
    payload = zlib.compress(raw) if compressed else raw
    cw, ch = canvas or (width, height)
    table = struct.pack('<9i', fmt, 6 if compressed else 5, width, height,
                        len(payload), x, y, cw, ch)
    if links:
        table += struct.pack('<2i', 17, 0)
    return (b'Neople Img File'.ljust(16, b'\0')
            + struct.pack('<4i', len(table), 0, version, 2 if links else 1)
            + (struct.pack('<i', len(palette) // 4) + palette if version == 4 else b'')
            + table + payload)


def pixel(rgba, width, x, y):
    return tuple(rgba[(y * width + x) * 4:(y * width + x + 1) * 4])


@pytest.mark.parametrize('compressed', [False, True])
def test_dxt1_four_colors_transparent_mode_and_png(compressed):
    r = decode_img(img(18, color_block(), compressed=compressed), 0)
    assert [pixel(r.rgba, 4, x, 0) for x in range(4)] == [
        (255, 0, 0, 255), (0, 255, 0, 255), (170, 85, 0, 255), (85, 170, 0, 255)]
    assert decode_png(r.png()) == r
    transparent = decode_dxt(color_block(0x001f, 0xf800), 4, 4, 18)
    assert [pixel(transparent, 4, x, 0) for x in range(4)] == [
        (0, 0, 255, 255), (255, 0, 0, 255), (127, 0, 127, 255), (0, 0, 0, 0)]
    equal = decode_dxt(color_block(0xf800, 0xf800, [3] * 16), 4, 4, 18)
    assert equal == b'\0' * 64


@pytest.mark.parametrize('compressed', [False, True])
def test_dxt3_explicit_alpha_and_four_colors_even_when_endpoints_ascending(compressed):
    alpha = sum(n << (4 * n) for n in range(16)).to_bytes(8, 'little')
    raw = alpha + color_block(0, 0xf800, [3] * 16)
    r = decode_img(img(19, raw, compressed=compressed), 0)
    assert [r.rgba[n * 4 + 3] for n in range(16)] == [n * 17 for n in range(16)]
    assert all(tuple(r.rgba[n * 4:n * 4 + 3]) == (170, 0, 0) for n in range(16))


@pytest.mark.parametrize('a0,a1,expected', [
    (255, 0, [255, 0, 218, 182, 145, 109, 72, 36]),
    (0, 255, [0, 255, 51, 102, 153, 204, 0, 255]),
    (77, 77, [77, 77, 77, 77, 77, 77, 0, 255]),
])
def test_dxt5_alpha_branches_and_index_order(a0, a1, expected):
    alpha = bytes((a0, a1)) + sum((n % 8) << (3 * n) for n in range(16)).to_bytes(6, 'little')
    raw = alpha + color_block(0, 0xf800, [3] * 16)
    r = decode_img(img(20, raw, compressed=True), 0)
    assert [r.rgba[n * 4 + 3] for n in range(16)] == expected * 2
    assert all(tuple(r.rgba[n * 4:n * 4 + 3]) == (170, 0, 0) for n in range(16))


@pytest.mark.parametrize('fmt', [18, 19, 20])
def test_partial_edge_blocks_canvas_link_and_v4_without_palette(fmt):
    alpha = b'' if fmt == 18 else b'\xff' * 8
    # Four physical blocks, row-major; 5x5 logical pixels, 7x7 transparent canvas.
    raw = b''.join(alpha + color_block(c, c, [0] * 16)
                   for c in (0xf800, 0x07e0, 0x001f, 0xffff))
    kwargs = dict(width=5, height=5, x=1, y=1, canvas=(7, 7), links=True)
    first = decode_img(img(fmt, raw, **kwargs), 1)
    assert (first.width, first.height) == (7, 7)
    assert pixel(first.rgba, 7, 1, 1) == (255, 0, 0, 255)
    assert pixel(first.rgba, 7, 5, 1) == (0, 255, 0, 255)
    assert pixel(first.rgba, 7, 1, 5) == (0, 0, 255, 255)
    assert pixel(first.rgba, 7, 5, 5) == (255, 255, 255, 255)
    assert pixel(first.rgba, 7, 0, 0) == pixel(first.rgba, 7, 6, 6) == (0, 0, 0, 0)
    assert decode_img(img(fmt, raw, compressed=True, version=4, **kwargs), 0) == first


def test_raw_dxt_followed_by_other_frame_preserves_offsets():
    raw = color_block(indices=[0] * 16)
    table = (struct.pack('<9i', 18, 5, 4, 4, len(raw), 0, 0, 4, 4)
             + struct.pack('<9i', 16, 5, 1, 1, 4, 0, 0, 1, 1))
    data = (b'Neople Img File'.ljust(16, b'\0') + struct.pack('<4i', len(table), 0, 2, 2)
            + table + raw + b'\x30\x20\x10\xff')
    assert decode_img(data, 1).rgba == b'\x10\x20\x30\xff'


def test_dxt_rejects_wrong_lengths_invalid_sizes_and_unverified_combinations():
    raw = color_block()
    for bad in (raw[:-1], raw + b'\0'):
        with pytest.raises(AssetFormatError):
            decode_dxt(bad, 4, 4, 18)
        with pytest.raises(AssetFormatError):
            decode_img(img(18, bad, compressed=True), 0)
    for width, height, fmt in ((0, 4, 18), (513, 4, 18), (True, 4, 18), (4, 4, 21)):
        with pytest.raises(AssetFormatError):
            decode_dxt(raw, width, height, fmt)
    with pytest.raises(AssetFormatError, match='raw DXT'):
        decode_img(img(18, raw + b'\0'), 0)
    with pytest.raises(AssetFormatError, match='palette/DXT'):
        decode_img(img(18, raw, compressed=True, version=4, palette=b'\0' * 4), 0)
    for damaged in (img(18, raw)[:-1], img(18, zlib.compress(raw) + b'trailing', compressed=False)):
        with pytest.raises(AssetFormatError):
            decode_img(damaged, 0)
