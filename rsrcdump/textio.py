from urllib.parse import quote_from_bytes, unquote_to_bytes


def sanitize_type_name(restype: bytes) -> str:
    assert len(restype) == 4
    if restype != b'    ':
        restype = restype.rstrip(b' ')
    return quote_from_bytes(restype, safe=b"")


def parse_type_name(sane_name: str) -> bytes:
    restype = unquote_to_bytes(sane_name)
    restype = restype.ljust(4, b' ')
    assert len(restype) == 4
    return restype


def sanitize_resource_name(name: str) -> str:
    sanitized = ""
    for c in name:
        if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-':
            sanitized += c
    return sanitized
