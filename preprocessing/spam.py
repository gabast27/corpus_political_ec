"""Detección de spam y posibles bots mediante reglas con puntuación.

Los comentarios solo traen texto, no el autor, así que la detección de bots es
a nivel de texto (patrones de spam y mensajes copiados en muchos vídeos). Para
detectar cuentas bot haría falta guardar un identificador de autor (hasheado).

Las características se calculan sobre el texto ORIGINAL (antes de sustituir URLs
y menciones por marcadores). Nada se descarta en silencio: todo lo descartado se
guarda en descartados.csv con su puntuación y los motivos.
"""
import html
import re

import numpy as np
import pandas as pd

from .normalize import EMAIL_RE, HASHTAG_RE, MENTION_RE, PHONE_RE, URL_RE, fold

_FANCY_RE = re.compile("[\U0001D400-\U0001D7FF\u24B6-\u24E9\uFF21-\uFF3A\uFF41-\uFF5A]")
_RUN_RE = re.compile(r"(.)\1{14,}")


def _compile_keywords(keywords):
    if not keywords:
        return None
    alts = "|".join(re.escape(fold(k)) for k in keywords)
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)")


def extract_features(raw, kw_re):
    t = html.unescape(raw)
    no_email = EMAIL_RE.sub(" ", t)
    n_urls = len(URL_RE.findall(no_email))
    no_url = URL_RE.sub(" ", no_email)
    return {
        "n_urls": n_urls,
        "n_emails": len(EMAIL_RE.findall(t)),
        "n_mentions": len(MENTION_RE.findall(no_url)),
        "n_hashtags": len(HASHTAG_RE.findall(t)),
        "has_phone": bool(PHONE_RE.search(no_url)),
        "kw_hits": len(set(kw_re.findall(fold(t)))) if kw_re else 0,
        "has_char_run": bool(_RUN_RE.search(t)),
        "n_fancy": len(_FANCY_RE.findall(t)),
        "low_unique": len(t) >= 30 and len(set(t)) / len(t) < 0.15,
    }


def flag_spam(df, cfg):
    """Devuelve (conservados, descartados). Añade spam_score y spam_reasons."""
    kw_re = _compile_keywords(cfg["keywords"])
    feats = pd.DataFrame([extract_features(t, kw_re) for t in df["text_raw"]], index=df.index)

    coordinated = (
        (df["cluster_size"] >= cfg["coordinated_min_cluster"])
        & (df["cluster_n_videos"] >= cfg["coordinated_min_videos"])
    )
    flags = pd.DataFrame({
        "url": feats["n_urls"] >= 1,
        "multiple_urls": feats["n_urls"] >= 2,
        "contact": feats["has_phone"] | (feats["n_emails"] > 0),
        "spam_keywords": feats["kw_hits"] >= 1,
        "many_spam_keywords": feats["kw_hits"] >= 2,
        "many_mentions": feats["n_mentions"] >= cfg["max_mentions"],
        "many_hashtags": feats["n_hashtags"] >= cfg["max_hashtags"],
        "char_run": feats["has_char_run"],
        "fancy_unicode": feats["n_fancy"] >= 5,
        "low_unique_chars": feats["low_unique"],
        "coordinated": coordinated,
    }, index=df.index)

    w = cfg["weights"]
    score = sum(flags[k].astype(int) * w[k] for k in flags.columns)
    reasons = pd.Series([""] * len(df), index=df.index)
    for k in flags.columns:
        sep = np.where(reasons.eq(""), "", ";")
        reasons = reasons.where(~flags[k], reasons + sep + k)

    df = df.copy()
    df["spam_score"] = score
    df["spam_reasons"] = reasons

    drop = (df["spam_score"] >= cfg["drop_threshold"]) | (coordinated & cfg["drop_coordinated"])
    dropped = df[drop].assign(drop_reason="spam_bot")
    return df[~drop], dropped
