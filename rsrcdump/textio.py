from urllib.parse import quote_from_bytes, unquote_to_bytes

def sanitize_type_name(ostype: bytes) -> str:
    assert len(ostype) == 4
    if ostype != b'    ':
        ostype = ostype.rstrip(b' ')
    return quote_from_bytes(ostype, safe=b"")

def parse_type_name(sane_name: str) -> bytes:
    ostype = unquote_to_bytes(sane_name)
    ostype = ostype.ljust(4, b' ')
    assert len(ostype) == 4
    return ostype

def sanitize_resource_name(name: str) -> str:
    sanitized = ""
    for c in name:
        if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-':
            sanitized += c
    return sanitized
