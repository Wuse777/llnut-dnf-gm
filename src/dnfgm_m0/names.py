"""Read-only name diagnostics for the pinned game image; never rename game rows.

The observed client sends UTF-8 bytes through a latin1 MySQL connection before
storage in a utf8 column. Keep the stored spelling and label any reconstructed
client spelling as a candidate: it must not replace UID/character-id ownership
checks or count as client acceptance. Unsupported or lossy encodings fail closed.
"""


def inspect_name(stored: str, latin1_bytes: bytes) -> dict:
    result = {
        'stored_name': stored,
        'client_name_candidate': None,
        'name_encoding': 'unverified',
    }
    try:
        # Reject MySQL's replacement '?' conversions of non-latin1 Unicode.
        # Unsupported cp1252 codepoints deliberately remain unverified.
        if stored.encode('cp1252', errors='strict') != latin1_bytes:
            return result
        candidate = latin1_bytes.decode('utf-8', errors='strict')
        if candidate.encode('utf-8') != latin1_bytes:
            return result
    except (UnicodeEncodeError, UnicodeDecodeError):
        return result
    result.update(
        client_name_candidate=candidate,
        name_encoding='ascii' if stored.isascii() else 'utf8_via_latin1_candidate',
    )
    return result
