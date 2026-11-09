"""Filtro de idioma con Lingua (sin descargar modelos; funciona bien en textos cortos).

Para detectar se quitan marcadores y emojis. Los textos con pocas letras no se
pueden clasificar con fiabilidad: se marcan "und" y se aplica `undetermined_policy`.
Los mensajes que mezclan español e inglés se clasifican por el idioma dominante.
"""
import emoji
import numpy as np
from lingua import IsoCode639_1, Language, LanguageDetectorBuilder
from tqdm import tqdm


def _build_detector(codes):
    langs = [Language.from_iso_code_639_1(getattr(IsoCode639_1, c.upper())) for c in codes]
    return LanguageDetectorBuilder.from_languages(*langs).with_preloaded_language_models().build()


def _lang_text(text_clean, ph):
    t = text_clean
    for p in ph.values():
        t = t.replace(p, " ")
    t = emoji.replace_emoji(t, " ")
    return " ".join(t.split())


def filter_language(df, cfg, ph):
    """Devuelve (conservados, descartados). Añade lang y lang_conf."""
    detector = _build_detector(cfg["candidates"])
    keep = set(cfg["keep"])
    cache, langs, confs = {}, [], []

    for t in tqdm(df["text_clean"], desc="Idioma", leave=False):
        txt = _lang_text(t, ph)
        if txt not in cache:
            if sum(ch.isalpha() for ch in txt) < cfg["min_letters"]:
                cache[txt] = ("und", np.nan)
            else:
                vals = detector.compute_language_confidence_values(txt)
                if vals:
                    top = vals[0]
                    cache[txt] = (top.language.iso_code_639_1.name.lower(), float(top.value))
                else:
                    cache[txt] = ("und", np.nan)
        lang, conf = cache[txt]
        langs.append(lang)
        confs.append(conf)

    df = df.copy()
    df["lang"], df["lang_conf"] = langs, confs

    is_und = df["lang"] == "und"
    confident = df["lang_conf"] >= cfg["min_confidence"]
    ok = (df["lang"].isin(keep) & confident) | (is_und & (cfg["undetermined_policy"] == "keep"))

    reason = np.select(
        [is_und, ~confident, ~df["lang"].isin(keep)],
        ["idioma_indeterminado", "idioma_baja_confianza", "idioma_no_deseado"],
        default="idioma_no_deseado",
    )
    dropped = df[~ok].copy()
    dropped["drop_reason"] = reason[~ok.to_numpy()]
    return df[ok], dropped
