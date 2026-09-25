"""Remove outgoing links while retaining text styles and Telegram UTF-16 offsets."""
import copy
import re

LINKS = re.compile(
    r"(?i)(?:\b(?:https?|ftp|tg|mailto|tel):[^\s<>]+"
    r"|(?<![\w@])(?:[\w.+-]+@)?(?:[\w-]+\.)+[a-z\u0080-\uffff]{2,63}"
    r"(?::\d+)?(?:[/\?#][^\s<>]*)?"
    r"|(?<!\w)@[a-z0-9_]{5,32}\b)"
)
REMOVE_TEXT = {"MessageEntityUrl", "MessageEntityEmail", "MessageEntityMention", "MessageEntityPhone"}
REMOVE_ENTITY = REMOVE_TEXT | {"MessageEntityTextUrl", "MessageEntityMentionName", "InputMessageEntityMentionName"}


def without_links(text, entities=None):
    text = text or ""
    raw = text.encode("utf-16-le")
    size = len(raw) // 2
    removed = [False] * size
    def remove(start, end):
        for i in range(max(0, start), min(size, end)):
            removed[i] = True
    for entity in entities or []:
        if type(entity).__name__ in REMOVE_TEXT:
            remove(entity.offset, entity.offset + entity.length)
    for match in LINKS.finditer(text):
        start = len(text[:match.start()].encode("utf-16-le")) // 2
        length = len(match.group().encode("utf-16-le")) // 2
        remove(start, start + length)
    offsets = [0]
    for is_removed in removed:
        offsets.append(offsets[-1] + (not is_removed))
    result = b"".join(raw[i*2:i*2+2] for i in range(size) if not removed[i]).decode("utf-16-le")
    cleaned_entities = []
    for entity in entities or []:
        if type(entity).__name__ in REMOVE_ENTITY:
            continue
        start, end = entity.offset, entity.offset + entity.length
        if not (0 <= start <= end <= size):
            continue
        length = offsets[end] - offsets[start]
        if length:
            cloned = copy.copy(entity)
            cloned.offset, cloned.length = offsets[start], length
            cleaned_entities.append(cloned)
    return result, cleaned_entities
