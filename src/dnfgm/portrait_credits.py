"""Small attribution contract shared by offline packer and read-only runtime."""
from urllib.parse import urlsplit
KINDS={'client','official_promotional','custom'}


def source_page(value):
    if not isinstance(value,str) or len(value)>500:raise ValueError('Invalid portrait attribution URL')
    if not value:return ''
    url=urlsplit(value)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.port not in (None,443):raise ValueError('Portrait source must be a plain HTTPS page')
    return value
