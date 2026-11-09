#!/usr/bin/env python
"""Preprocesamiento de comentarios de YouTube para análisis de sentimiento.

Uso:
    python run_preprocessing.py --config config.yaml
    python run_preprocessing.py --config config.yaml --input data/raw/otro.csv

Pasos (en este orden; cada uno registra qué descarta y por qué):
    1. comment_id repetido
    2. limpieza conservadora + comentarios sin contenido
    3. duplicados exactos y casi-duplicados
    4. spam y posibles bots
    5. filtro de idioma
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from preprocessing import __version__
from preprocessing.dedup import find_duplicates, remove_duplicates
from preprocessing.language import filter_language
from preprocessing.normalize import has_content, make_key, normalize_text
from preprocessing.provenance import Funnel, git_info, library_versions, sha256_file
from preprocessing.spam import flag_spam

REQUIRED = ["video_id", "comment_id", "likes", "published_at"]
FINAL_COLS = ["video_id", "comment_id", "text_raw", "text_clean", "likes", "reply_count",
              "published_at", "lang", "lang_conf", "spam_score", "cluster_id",
              "cluster_size", "cluster_n_videos"]
DROPPED_COLS = ["video_id", "comment_id", "text_raw", "drop_step", "drop_reason", "spam_score",
                "spam_reasons", "cluster_id", "cluster_size", "cluster_n_videos",
                "lang", "lang_conf"]


def load_data(cfg):
    text_col = cfg["columns"]["text"]
    # keep_default_na=False: un comentario que diga literalmente "NA" o "null" no debe pasar a NaN
    df = pd.read_csv(cfg["input_path"], dtype=str, keep_default_na=False, encoding="utf-8")
    missing = [c for c in REQUIRED + [text_col] if c not in df.columns]
    if missing:
        sys.exit(f"Faltan columnas en el CSV de entrada: {missing}")
    df = df.rename(columns={text_col: "text_raw"})
    df["likes"] = pd.to_numeric(df["likes"], errors="coerce").fillna(0).astype(int)
    if "reply_count" in df.columns:
        df["reply_count"] = pd.to_numeric(df["reply_count"], errors="coerce").fillna(0).astype(int)
    else:
        df["reply_count"] = 0
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    return df.reset_index(drop=True)


def run(cfg, config_path="config.yaml"):
    started = datetime.now(timezone.utc)
    git = git_info()
    tag = git["commit"][:7] if git["commit"] else "nogit"
    run_dir = Path(cfg["output_dir"]) / f"{started:%Y%m%d_%H%M%S}_{tag}"
    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy(config_path, run_dir / "config_usada.yaml")

    ph = cfg["placeholders"]
    funnel, dropped = Funnel(), []

    def register(removed, step):
        if len(removed):
            dropped.append(removed.assign(drop_step=step))

    df = load_data(cfg)
    n_input = len(df)
    print(f"Pipeline v{__version__} | commit {tag}{' (CAMBIOS SIN COMMITEAR)' if git['dirty'] else ''}")
    print(f"Entrada: {n_input} filas")

    # 1. comment_id repetido
    mask = df.duplicated("comment_id", keep="first")
    register(df[mask].assign(drop_reason="comment_id_repetido"), "1_comment_id")
    funnel.record("1. comment_id repetido", len(df), (~mask).sum())
    df = df[~mask]

    # 2. limpieza conservadora + sin contenido
    df = df.assign(
        text_clean=df["text_raw"].map(lambda t: normalize_text(t, ph)),
    )
    df["text_key"] = df["text_clean"].map(lambda t: make_key(t, ph))
    mask = ~df["text_clean"].map(lambda t: has_content(t, ph))
    register(df[mask].assign(drop_reason="sin_contenido"), "2_sin_contenido")
    funnel.record("2. sin contenido (vacío, solo <URL>...)", len(df), (~mask).sum())
    df = df[~mask]

    # 3. duplicados y casi-duplicados
    n0 = len(df)
    df = find_duplicates(df, cfg["dedup"])
    df, dups = remove_duplicates(df, cfg["dedup"])
    register(dups, "3_duplicados")
    n_exact = int((dups["drop_reason"] == "duplicado_exacto").sum()) if len(dups) else 0
    funnel.record("3a. duplicados exactos", n0, n0 - n_exact)
    funnel.record("3b. casi-duplicados", n0 - n_exact, len(df))

    # 4. spam y bots
    n0 = len(df)
    df, spam_dropped = flag_spam(df, cfg["spam"])
    register(spam_dropped, "4_spam_bot")
    funnel.record("4. spam / posibles bots", n0, len(df))

    # 5. idioma
    n0 = len(df)
    df, lang_dropped = filter_language(df, cfg["language"], ph)
    register(lang_dropped, "5_idioma")
    funnel.record("5. idioma", n0, len(df))

    # Salidas
    dropped_all = pd.concat(dropped, ignore_index=True) if dropped else pd.DataFrame()
    final = df.reindex(columns=FINAL_COLS)
    final.to_csv(run_dir / "comentarios_limpios.csv", index=False, encoding="utf-8")
    try:
        final.to_parquet(run_dir / "comentarios_limpios.parquet", index=False)
    except Exception:
        pass  # pyarrow es opcional
    if len(dropped_all):
        dropped_all.reindex(columns=DROPPED_COLS).to_csv(
            run_dir / "descartados.csv", index=False, encoding="utf-8")
    pd.DataFrame(funnel.rows).to_csv(run_dir / "embudo.csv", index=False)

    report = {
        "pipeline_version": __version__,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "git": git,
        "libraries": library_versions(),
        "input": {"path": str(cfg["input_path"]), "sha256": sha256_file(cfg["input_path"]),
                  "rows": n_input},
        "output": {"rows": len(final), "videos": int(final["video_id"].nunique())},
        "funnel": funnel.rows,
        "drop_reasons": dropped_all["drop_reason"].value_counts().to_dict() if len(dropped_all) else {},
        "idioma_indeterminado_conservados": int((final["lang"] == "und").sum()),
        "config": cfg,
    }
    (run_dir / "informe.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    funnel.print()
    print(f"\nResultados en: {run_dir}")
    return run_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--input", help="sobrescribe input_path del config")
    args = ap.parse_args()
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if args.input:
        cfg["input_path"] = args.input
    run(cfg, args.config)


if __name__ == "__main__":
    main()
