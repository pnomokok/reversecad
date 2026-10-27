"""Fast decoder for SAM's "one_bit" mask payloads, with the meta_sam_parser library as fallback.

The payload is base85 text holding a range-coded bitmap: each pixel is coded with an adaptive
probability chosen by a 12-bit context (2 pixels to its left, 5 above, 5 two rows above). That
makes decoding inherently sequential, so numpy only does the parallel parts (base85 unpacking,
building the result). The pixel loop is a tightened copy of the library's (_mask_codec.py):
  - the context is updated by shifting from the previous pixel instead of rebuilt from 12 reads;
  - the range decoder lives in local variables instead of method calls;
  - the library's re-encode of the whole mask (its canonical-form check) is skipped.
In place of that check, the decoder must end having read exactly every input byte; any problem
(other encodings, malformed payloads, a leftover or missing byte) falls back to the library.
tests/test_sam_decode.py checks the raster is identical to the library's on every saved SAM answer.
"""
import functools

import numpy as np
from meta_sam_parser import _segmentation
from meta_sam_parser import decode_mask_to_raster as library_decode

_EXCLUDED = set('"\\,;<>|')
_ALPHABET = "".join(chr(code) for code in range(0x21, 0x7F) if chr(code) not in _EXCLUDED)
_DIGITS = np.full(128, 255, dtype=np.uint8)
_DIGITS[[ord(c) for c in _ALPHABET]] = np.arange(len(_ALPHABET))
_POWERS = 85 ** np.arange(4, -1, -1, dtype=np.uint64)

_M32 = 0xFFFFFFFF
_TOP = 1 << 24
_BOTTOM_MASK = (1 << 16) - 1
_BOTTOM = 1 << 16
_KEEP = 0x7BC  # context bits that slide one step left: above x-1..x+2 and two above x-1..x+2


class FastDecodeError(ValueError):
    """The fast path could not decode this payload; the caller uses the library instead."""


def _unpack(text):
    """Base85 text (5-char length prefix, then groups of 5 chars per 4 bytes) to bytes."""
    codes = np.frombuffer(text.encode("ascii"), dtype=np.uint8)
    if codes.max(initial=0) >= 128:
        raise FastDecodeError("non-ASCII payload")
    digits = _DIGITS[codes]
    if (digits >= 85).any() or len(digits) < 5:
        raise FastDecodeError("invalid payload character or missing prefix")
    length = int(digits[:5].astype(np.uint64) @ _POWERS)
    full, remainder = divmod(length, 4)
    if len(digits) != 5 + full * 5 + (remainder + 1 if remainder else 0):
        raise FastDecodeError("payload length does not match its prefix")
    groups = digits[5:5 + full * 5].astype(np.uint64).reshape(-1, 5) @ _POWERS
    if remainder:  # the tail group is padded with the highest digit, as in the library
        tail = np.full(5, 84, dtype=np.uint64)
        tail[:remainder + 1] = digits[5 + full * 5:]
        groups = np.append(groups, tail @ _POWERS)
    if (groups > _M32).any():
        raise FastDecodeError("out-of-range group")
    return groups.astype(">u4").tobytes()[:length]


def _decode_bits(data, width, height):
    """Range-decode the bitmap; returns a bytearray of 0/1, row-major."""
    if len(data) < 4:
        raise FastDecodeError("payload too short")
    size = len(data)
    code = int.from_bytes(data[:4], "big")
    position = 4
    low, rng = 0, _M32
    counts = [1] * 8192
    output = bytearray(width * height)
    zeros = [0] * (width + 4)
    above, two_above = zeros, zeros  # previous rows, padded by 2 on each side
    out = 0
    for _ in range(height):
        # Bits entering the context window at each x: above[x+3] and two_above[x+3] (padded index x+5).
        # The last pixel's entry is never used (its context would be for x = width).
        incoming = [(above[i] << 6) | (two_above[i] << 11) for i in range(5, width + 4)] + [0]
        row = [0] * (width + 4)
        context = (above[2] << 4) | (above[3] << 5) | (above[4] << 6) | (two_above[2] << 9) | (two_above[3] << 10) | (two_above[4] << 11)
        for x in range(width):
            offset = context << 1
            zero = counts[offset]
            one = counts[offset + 1]
            scaled = rng // (zero + one)
            if scaled == 0:
                raise FastDecodeError("invalid coding state")
            if ((code - low) & _M32) // scaled < zero:
                bit = 0
                rng = scaled * zero
                zero += 14
                counts[offset] = zero
            else:
                bit = 1
                low = (low + scaled * zero) & _M32
                rng = scaled * one
                one += 14
                counts[offset + 1] = one
            if zero + one >= 4096:
                counts[offset] = (zero >> 1) or 1
                counts[offset + 1] = (one >> 1) or 1
            # With rng >= 2^24 and no wrap-around, low and low + rng differ in the top byte, so the
            # library's loop below would exit at once; skipping it this way is exact.
            while rng < _TOP or low + rng > _M32:
                if (low ^ ((low + rng) & _M32)) < _TOP:
                    pass
                elif rng < _BOTTOM:
                    rng = (-low) & _BOTTOM_MASK
                else:
                    break
                if position >= size:
                    raise FastDecodeError("payload ended early")
                code = ((code << 8) | data[position]) & _M32
                position += 1
                low = (low << 8) & _M32
                rng = (rng << 8) & _M32
            if bit:
                output[out] = 1
                row[x + 2] = 1
            out += 1
            context = ((context >> 1) & _KEEP) | ((context & 1) << 1) | bit | incoming[x]
        two_above, above = above, row
    # Every saved SAM answer is consumed exactly; anything else is treated as malformed.
    if position != size:
        raise FastDecodeError(f"{size - position} bytes left over")
    return output


def fast_decode(payload, width, height):
    """Decode a one_bit payload ("!..."); raises FastDecodeError if it cannot."""
    if not isinstance(payload, str) or not payload.startswith("!"):
        raise FastDecodeError("not a one_bit payload")
    if width <= 0 or height <= 0:
        raise FastDecodeError("bad size")
    return bytes(_decode_bits(_unpack(payload[1:]), width, height))


def decode_mask_to_raster(mask):
    """Same result as meta_sam_parser.decode_mask_to_raster (0/1 bytes, row-major), faster.

    Uses the fast path for one_bit masks; anything it cannot handle goes to the library, which
    also raises the library's own error for a broken payload. Recent results are cached, since
    the parser decodes every mask once to validate it and the caller decodes it again.
    """
    if mask.encoding == "one_bit":
        try:
            return _fast_cached(mask.payload, int(mask.width), int(mask.height))
        except (FastDecodeError, TypeError, ValueError):
            pass
    return library_decode(mask)


@functools.lru_cache(maxsize=8)
def _fast_cached(payload, width, height):
    return fast_decode(payload, width, height)


def use_in_parser():
    """Make meta_sam_parser's stream parser validate masks with decode_mask_to_raster above.

    The parser decodes every mask on arrival only to check it; with the library's decoder that
    took as long as the decode we need afterwards. Same results, same errors for broken payloads.
    """
    if hasattr(_segmentation, "decode_mask_to_raster"):
        _segmentation.decode_mask_to_raster = decode_mask_to_raster
