"""Conservative, local-only extraction of betting text. Never opens source URLs."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape, unescape
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

from telethon.extensions import html

DEFAULTS = {
    "enabled": True, "default_sport": "football", "source_timezone": "Africa/Lagos",
    "stake_high": True, "promo_platform": "Stake", "promo_code": "", "crash_promo_code": "",
}
SPORTS = {
    "football": ("⚽", "FOOTBALL"), "table_tennis": ("🏓", "TABLE TENNIS"),
    "basketball": ("🏀", "BASKETBALL"), "tennis": ("🎾", "TENNIS"),
    "betting": ("🎟", "BETTING"), "crash": ("🚀", "CRASH"),
}
URL = re.compile(r'https?://[^\s<>"\u200b]+', re.I)
CODE = re.compile(r"\b(?:bet(?:ting)?|booking|book|share)\s*code(?:\s+\d{1,2}(?=\s*[^\w\s]))?[^\w\r\n]*([A-Z0-9][A-Z0-9_-]{2,31})\b", re.I)
AD = re.compile(r"promo\s*code|create\s+an?\s+account|register|referral|bonus|how\s+to\s+(?:deposit|setup|load)|video\s+on\s+how", re.I)
PLATFORMS = {
    "stake.com": "Stake", "sportybet.com": "SportyBet", "bet9ja.com": "Bet9ja",
    "betking.com": "BetKing", "betway.com": "Betway", "1xbet.com": "1xBet",
}


@dataclass
class Result:
    action: str = "unchanged"
    cards: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    reason: str = ""

    def preview(self):
        return {"action": self.action, "cards": [{"html": c, "text": html.parse(c)[0]} for c in self.cards],
                "warnings": self.warnings, "reason": self.reason}


def combine_messages(messages):
    """Include hidden Telegram links next to their labels, preserving message order."""
    return "\n".join(expand_links(m.message or "", m.entities) for m in messages)


def expand_links(text, entities=None):
    raw = text.encode("utf-16-le")
    for entity in sorted(entities or [], key=lambda e: e.offset + e.length, reverse=True):
        if type(entity).__name__ == "MessageEntityTextUrl":
            end = 2 * (entity.offset + entity.length)
            if 0 <= end <= len(raw):
                raw = raw[:end] + (" " + entity.url).encode("utf-16-le") + raw[end:]
    return raw.decode("utf-16-le")


def platform_for(url):
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            return None
        host = (parts.hostname or "").lower()
        return next((name for domain, name in PLATFORMS.items() if host == domain or host.endswith("." + domain)), None)
    except ValueError:
        return None


def booking_link(url):
    """Only known booking routes qualify; registration links never do."""
    name = platform_for(url)
    if not name:
        return None
    parts = urlsplit(url)
    query = {k.lower(): v for k, v in parse_qs(parts.query).items()}
    if any(k in query for k in ("offer", "ref", "referral", "affiliate", "promo", "promocode")):
        return None
    if name == "Stake" and parts.path.rstrip("/") == "/sports/home":
        iid = query.get("iid", [""])[0]
        if re.fullmatch(r"sport:[0-9]{3,32}", iid):
            return name, iid.split(":", 1)[1]
    for key in ("bookingcode", "sharecode", "booking_code"):
        code = query.get(key, [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{3,32}", code):
            return name, code
    return None


def detect_sport(text, default):
    for pattern, category in ((r"\b(?:crash|aviator)\b", "crash"),
                              (r"\b(?:table\s*tennis|ping[ -]?pong)\b", "table_tennis"),
                              (r"\bbasketball\b", "basketball"), (r"\btennis\b", "tennis"),
                              (r"\b(?:football|soccer)\b", "football")):
        if re.search(pattern, text, re.I):
            return category
    return default if default in SPORTS and default != "crash" else "betting"


def stated_time(text, crash=False):
    label = r"(?:get\s+in\s+at|entry(?:\s+time)?|start(?:\s+time)?)" if crash else r"(?:kick[ -]?off|match\s+time|start\s+time|time)"
    match = re.search(label + r"[^\w\r\n]*(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)(?!\d)(?:\s*(WAT|UTC|GMT))?", text, re.I)
    return match


def crash_entry(text, posted_at, settings, now):
    match = stated_time(text, True)
    if not match:
        return None, ["Crash entry time is missing; held for review."]
    value = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", match[1].replace(".", "").strip(), re.I)
    if not value:
        return None, ["Crash entry time could not be read."]
    hour, minute, meridiem = int(value[1]), int(value[2] or 0), (value[3] or "").lower()
    if minute > 59 or (meridiem and not 1 <= hour <= 12) or (not meridiem and hour > 23):
        return None, ["Invalid Crash entry time."]
    if not meridiem and ":" not in match[1]:
        return None, ["Crash entry needs AM/PM or a 24-hour time."]
    if meridiem:
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    zone_name = {"WAT": "Africa/Lagos", "UTC": "UTC", "GMT": "UTC"}.get((match[2] or "").upper(), settings["source_timezone"])
    zone = ZoneInfo(zone_name)
    source = (posted_at or now).astimezone(zone)
    day = source.date()
    explicit = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if explicit:
        try:
            day = datetime.strptime(explicit[1], "%Y-%m-%d").date()
        except ValueError:
            return None, ["Invalid date in Crash signal."]
    elif re.search(r"\btomorrow\b", text, re.I):
        day += timedelta(days=1)
    elif re.search(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b", text):
        return None, ["Ambiguous Crash date; use YYYY-MM-DD."]
    entry = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
    warnings = []
    if not match[2]:
        warnings.append("Entry uses the configured source timezone: " + zone_name + ".")
    relative = re.search(r"next\s+(\d+)\s+minutes?", text, re.I)
    if relative and posted_at and abs((entry - source).total_seconds() / 60 - int(relative[1])) > 1:
        return None, warnings + ["Countdown conflicts with the entry time; held for review."]
    if entry <= now:
        return None, warnings + ["Crash entry time has passed; signal was not sent."]
    return entry.strftime("%Y-%m-%d • %I:%M %p ") + ("WAT" if zone_name == "Africa/Lagos" else zone_name), warnings


def promo(settings, platform, crash=False):
    if not platform or platform.casefold() != settings["promo_platform"].strip().casefold():
        return ""
    code = (settings["crash_promo_code"] if crash else "") or settings["promo_code"]
    # Blank and demonstration codes must never reach a group.
    if not code or code.upper() in {"YOURCODE", "PROMOCODE", "PLACEHOLDER"}:
        return ""
    return "\n\n<b>Promo code:</b> <code>" + escape(code) + "</code>"


def format_post(text, settings=None, posted_at=None, now=None):
    settings = {**DEFAULTS, **(settings or {})}
    if not settings["enabled"]:
        return Result()
    now = now or datetime.now(timezone.utc)
    text = unescape(text or "").replace("\u200b", "")
    # Advertising cannot supply a sport, a time, or a booking code.
    content = "\n".join(line for line in text.splitlines() if not AD.search(line))
    category = detect_sport(content, settings["default_sport"])
    platform = next((platform_for(m[0].rstrip(".,;!)]}")) for m in URL.finditer(text)
                     if platform_for(m[0].rstrip(".,;!)]}"))), None)
    if not platform:
        platform = next((name for name in PLATFORMS.values()
                         if re.search((r"\b(?:on\s+|platform\s*:\s*)" if name == "Stake" else r"\b")
                                      + re.escape(name) + r"\b", text, re.I)), None)
    codes = list(dict.fromkeys(m[1] for m in CODE.finditer(content) if m[1].lower() not in {"here", "below", "link"}))
    links = {}
    for match in URL.finditer(content):
        url = match[0].rstrip(".,;!)]}")
        booking = booking_link(url)
        if booking:
            name, code = booking
            # Key by platform too: identical codes on different sites are separate bets.
            links.setdefault((name, code), url)
    warnings = []
    if category == "crash":
        target = re.search(r"cash\s*out(?:\s+(?:at|target))?[^\w\r\n]*(\d+(?:\.\d+)?)\s*(?:x|×|odds)?\b", content, re.I)
        entry, time_warnings = crash_entry(content, posted_at, settings, now)
        warnings.extend(time_warnings)
        if not target or not 1 < float(target[1]) <= 1000000:
            warnings.append("A valid Crash cash-out target is missing; held for review.")
        if not entry or not target or not 1 < float(target[1]) <= 1000000:
            return Result("skipped", warnings=warnings, reason=warnings[-1])
        signal = re.search(r"crash\s+signal\s*(\d+)\b", content, re.I)
        body = "<b>🚀 CRASH</b>\n"
        if platform:
            body += "\n<b>Platform:</b> " + escape(platform)
        if signal:
            body += "\n<b>Signal:</b> " + signal[1]
        body += "\n\n<b>Entry:</b> " + escape(entry) + "\n<b>Cash-out target:</b> " + target[1] + "×"
        body += promo(settings, platform, True)
        body += "\n\nSignal copied from the source; a win is not guaranteed."
        return Result("formatted", ["<blockquote>" + body + "</blockquote>"], warnings)
    if not codes and not links:
        if AD.search(text):
            return Result("skipped", reason="Promotional post without a booking code or signal.")
        return Result()
    entries = []
    for code in codes:
        matches = [(name, url) for (name, link_code), url in links.items() if link_code == code]
        if matches:
            entries.extend((name, code, url) for name, url in matches)
        else:
            entries.append((platform, code, None))
            warnings.append("No verified matching link for code " + code + "; code kept without a link.")
    for (name, code), url in links.items():
        if code not in codes:
            entries.append((name, code, url))
    # Keep platform-specific promo codes from leaking onto another bookmaker's post.
    groups = {}
    for name, code, url in entries:
        groups.setdefault(name, []).append((code, url))
    icon, title = SPORTS[category]
    time_match = stated_time(content)
    cards = []
    for name, bets in groups.items():
        header = "<b>" + icon + " " + title + "</b>\n"
        if name:
            header += "\n<b>Platform:</b> " + escape(name)
        if settings["stake_high"]:
            header += "\n<b>STAKE HIGH</b>"
        if time_match:
            header += "\n<b>Time:</b> " + escape(time_match[1].strip() + (" " + time_match[2] if time_match[2] else ""))
        footer = promo(settings, name)
        body = header
        for i, (code, url) in enumerate(bets, 1):
            block = "\n\n<b>BET " + str(i) + "</b>\n<b>Code:</b> <code>" + escape(code) + "</code>"
            if url:
                block += '\n🔗 <a href="' + escape(url, quote=True) + '">Open bet ' + str(i) + '</a>'
            # Bound each Telegram message while keeping each code/link pair together.
            if len((body + block + footer).encode("utf-16-le")) // 2 > 3400:
                cards.append("<blockquote>" + body + footer + "</blockquote>")
                body = header
            body += block
        cards.append("<blockquote>" + body + footer + "</blockquote>")
    return Result("formatted", cards, warnings)
