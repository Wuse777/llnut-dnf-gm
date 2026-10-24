"""Read-only reconstruction of UTF-8 names stored through MySQL latin1.

Never rename rows. A candidate is used only when the stored Unicode spelling
exactly matches MySQL's latin1 byte mapping AND the original bytes are valid
UTF-8. IDs, not decoded names, continue to authorize character operations.
"""

# MySQL 5.7 latin1 differs from Python's strict cp1252 at these five bytes.
# MySQL preserves each as the same-numbered Unicode control code point.
# https://dev.mysql.com/doc/refman/5.7/en/charset-we-sets.html
_MYSQL_LATIN1_UNDEFINED = frozenset((0x81, 0x8D, 0x8F, 0x90, 0x9D))
_MYSQL_LATIN1_TABLE = tuple(
    chr(value) if value in _MYSQL_LATIN1_UNDEFINED
    else bytes((value,)).decode('cp1252', errors='strict')
    for value in range(256)
)


def mysql_latin1_text(data: bytes) -> str:
    """Lossless MySQL latin1 -> Unicode, NOT a permissive cp1252 fallback.

    Also used to construct read-only name search candidates. Outbound game
    mail encoding deliberately remains unchanged pending its own validation.
    """
    return ''.join(_MYSQL_LATIN1_TABLE[value] for value in data)


def inspect_name(stored: str, latin1_bytes: bytes) -> dict:
    result = {
        'stored_name': stored,
        'client_name_candidate': None,
        'name_encoding': 'unverified',
    }
    # Reject SQL CONVERT replacements, corruption and mismatched byte sources.
    if mysql_latin1_text(latin1_bytes) != stored:
        return result
    try:
        candidate = latin1_bytes.decode('utf-8', errors='strict')
        if candidate.encode('utf-8') != latin1_bytes:
            return result
    except UnicodeError:
        return result
    result.update(
        client_name_candidate=candidate,
        name_encoding='ascii' if stored.isascii() else 'utf8_via_latin1_candidate',
    )
    return result
