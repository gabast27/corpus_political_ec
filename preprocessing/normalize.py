"""Normalización de texto.

El texto limpio (`text_clean`) CONSERVA mayúsculas, puntuación y emojis, porque
aportan señal para el análisis de sentimiento. Solo se sustituyen URLs, emails,
teléfonos y menciones por marcadores, y se eliminan caracteres invisibles.

La clave de deduplicación (`make_key`) es otra cosa: es agresiva (minúsculas,
sin tildes ni puntuación) y solo sirve para comparar textos entre sí.
"""
import html
import re
import unicodedata

import emoji

EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")

URL_RE = re.compile(
    r"(?i)"
    r"(?:\b(?:https?://|www\.)\S+"
    r"|\b(?:youtu\.be|bit\.ly|t\.me|wa\.me|goo\.gl)/\S+"
    r"|\b[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.(?:com|net|org|info|xyz|ec)\b(?:/\S*)?)"
)

# Móviles de Ecuador (09XXXXXXXX, +593 9XXXXXXXX) e internacionales con prefijo +
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s\-]?\d[\d\s\-]{6,13}\d"
    r"|(?:\+?593[\s\-]?|0)?9\d[\s\-]?\d{3}[\s\-]?\d{4})(?!\w)"
)

MENTION_RE = re.compile(r"(?<![\w@])@+\w+(?:[.\-]\w+)*")
HASHTAG_RE = re.compile(r"(?<!\w)#\w+")

# Se excluye \u200d (ZWJ) a propósito: une los emojis compuestos (👨‍👩‍👧, ❤️‍🔥)
_INVISIBLE_RE = re.compile("[\u200b\u200c\u2060\ufeff\u00ad]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_URL_TRAILING = ".,;:!?)]}\"'»”’"


def _url_repl(placeholder):
    """Sustituye la URL pero conserva la puntuación final ("...web.com)." -> "<URL>).")."""
    def repl(m):
        url, trail = m.group(0), ""
        while url and url[-1] in _URL_TRAILING:
            trail = url[-1] + trail
            url = url[:-1]
        return placeholder + trail
    return repl


def _collapse_repeated(text, placeholder):
    """'<USUARIO> <USUARIO> <USUARIO>' -> '<USUARIO>' (listas de menciones)."""
    p = re.escape(placeholder)
    return re.sub(rf"{p}(?:\s+{p})+", placeholder, text)


def normalize_text(raw, ph):
    """Limpieza conservadora. `ph` = dict con los marcadores (url, mention, email, phone)."""
    t = html.unescape(raw)
    t = unicodedata.normalize("NFC", t)
    t = _INVISIBLE_RE.sub("", t)
    t = _CTRL_RE.sub(" ", t)
    t = EMAIL_RE.sub(ph["email"], t)           # antes que URL (el dominio del email casaría)
    t = URL_RE.sub(_url_repl(ph["url"]), t)
    t = PHONE_RE.sub(ph["phone"], t)
    t = MENTION_RE.sub(ph["mention"], t)
    t = _collapse_repeated(t, ph["mention"])
    return " ".join(t.split())                 # espacios y saltos de línea -> un espacio


def has_content(text_clean, ph):
    """False si, quitando marcadores, no queda ni una letra/número ni un emoji."""
    t = text_clean
    for p in ph.values():
        t = t.replace(p, " ")
    return any(c.isalnum() for c in t) or emoji.emoji_count(t) > 0


def fold(text):
    """Minúsculas, NFKC (convierte letras decorativas en normales) y sin tildes."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def make_key(text_clean, ph):
    """Clave para comparar textos: sin marcadores, tildes, puntuación ni emojis."""
    t = text_clean
    for p in ph.values():
        t = t.replace(p, " ")
    t = fold(t)
    t = re.sub(r"[^\w\s]|_", " ", t)
    t = re.sub(r"(\w)\1{2,}", r"\1\1", t)      # holaaaa -> holaa
    return " ".join(t.split())
