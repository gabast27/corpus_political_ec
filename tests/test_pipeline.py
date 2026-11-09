"""Tests de humo del pipeline. Ejecutar con:  pytest -q"""
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from preprocessing.normalize import has_content, make_key, normalize_text  # noqa: E402
from run_preprocessing import run  # noqa: E402

PH = {"url": "<URL>", "mention": "<USUARIO>", "email": "<EMAIL>", "phone": "<TELEFONO>"}


# ---------- normalización ----------
def test_url_conserva_puntuacion():
    assert normalize_text("Mira www.primicias.ec/noticia, es verdad.", PH) == "Mira <URL>, es verdad."
    assert normalize_text("(ver https://x.com/a).", PH) == "(ver <URL>)."


def test_menciones_se_colapsan():
    assert normalize_text("@Juan @maria.perez, gracias", PH) == "<USUARIO>, gracias"


def test_conserva_mayusculas_emojis_y_puntuacion():
    t = "NO MÁS CORRUPCIÓN!!! 😡🔥 ¿Hasta cuándo...?"
    assert normalize_text(t, PH) == t


def test_emoji_compuesto_no_se_rompe():
    t = "familia 👨‍👩‍👧 unida"
    assert normalize_text(t, PH) == t


def test_telefono_y_email():
    out = normalize_text("escríbeme al 0991234567 o a a@b.com", PH)
    assert "<TELEFONO>" in out and "<EMAIL>" in out


def test_sin_contenido():
    assert not has_content("<URL>", PH)
    assert not has_content("...", PH)
    assert has_content("😂😂", PH)


def test_clave_ignora_tildes_mayusculas_y_alargamientos():
    assert make_key("¡Qué BUENO, político!!!", PH) == make_key("que bueno politico", PH)
    assert make_key("holaaaaa", PH) == make_key("holaa", PH)


# ---------- pipeline completo ----------
@pytest.fixture
def run_dir(tmp_path):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    base = "El presidente debe renunciar porque no ha cumplido ninguna de sus promesas de campaña"
    rows = [
        # id, video, texto, likes
        ("c1", "v1", base, 10),
        ("c2", "v2", base, 3),                                   # duplicado exacto
        ("c3", "v1", base + " pues", 1),                         # casi-duplicado (una palabra más)
        ("c3b", "v1", base.upper() + "!!!", 1),                  # idéntico tras normalizar -> exacto
        ("c4", "v1", "Excelente análisis del debate, muy claro y bien argumentado por todos 👏", 5),
        ("c5", "v1", "Gana dinero desde casa escríbeme al +593 99 123 4567 ya https://bit.ly/xyz", 0),
        ("c6", "v1", "This government is a complete disaster and nobody here is doing anything about it", 2),
        ("c7", "v2", "😂😂😂", 1),                                  # emoji-solo: se conserva
        ("c8", "v2", "https://youtu.be/abc", 0),                 # sin contenido
        ("c9", "v2", "Verdad", 0),
        ("c10", "v2", "Verdad", 0),                              # corto: no se deduplica
        ("c4", "v1", "otro texto con comment_id repetido, no debería sobrevivir al filtro inicial", 0),
        ("c11", "v2", "@Juan @Pedro @Maria estoy de acuerdo con ustedes, el país necesita cambios reales", 4),
    ]
    df = pd.DataFrame(rows, columns=["comment_id", "video_id", "text", "likes"])
    df["published_at"] = "2025-03-01T12:00:00Z"
    df["reply_count"] = 0
    src = tmp_path / "in.csv"
    df.to_csv(src, index=False)
    cfg["input_path"], cfg["output_dir"] = str(src), str(tmp_path / "runs")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return run(cfg, cfg_path)


def test_resultado_esperado(run_dir):
    out = pd.read_csv(run_dir / "comentarios_limpios.csv", keep_default_na=False)
    dropped = pd.read_csv(run_dir / "descartados.csv", keep_default_na=False)
    reasons = dict(zip(dropped["comment_id"] + "|" + dropped["video_id"], dropped["drop_reason"]))
    kept = set(out["comment_id"])

    assert "c1" in kept                                  # conserva la más votada
    assert reasons["c2|v2"] == "duplicado_exacto"
    assert reasons["c3|v1"] == "casi_duplicado"
    assert reasons["c3b|v1"] == "duplicado_exacto"        # "exacto" = igual tras normalizar
    assert reasons["c5|v1"] == "spam_bot"
    assert reasons["c6|v1"] == "idioma_no_deseado"
    assert reasons["c8|v2"] == "sin_contenido"
    assert reasons["c4|v1"] in {"comment_id_repetido"} or "c4" in kept
    assert {"c7", "c9", "c10", "c11"} <= kept            # emojis, cortos y menciones se conservan
    assert out.loc[out["comment_id"] == "c11", "text_clean"].iloc[0].startswith("<USUARIO> estoy")
    assert (run_dir / "informe.json").exists() and (run_dir / "embudo.csv").exists()
