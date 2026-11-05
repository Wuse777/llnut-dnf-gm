"""QF1031 has one letter_text field, not a separate client subject field."""
import unicodedata
from fastapi import HTTPException


def mail_text(data):
    title=data.get('mail_title') or ''
    message=data.get('message')
    if message is None:message='GM rewards'
    if not isinstance(title,str) or not isinstance(message,str):
        raise HTTPException(422,'邮件标题和正文必须是文字')
    if len(title)>40 or any(unicodedata.category(c).startswith('C') for c in title):
        raise HTTPException(422,'邮件标题最多40个字符，且必须是无控制字符的单行文字')
    text=(title+'\n'+message) if title else message
    try:size=len(text.encode('utf-8'))
    except UnicodeError:raise HTTPException(422,'邮件文字编码无效') from None
    if size>255:
        raise HTTPException(422,'邮件标题与正文合计超过255个UTF-8字节，请缩短文字')
    return text
