"""Duplicados exactos y casi-duplicados (MinHash + LSH).

Se agrupan los comentarios en clústeres. De cada clúster se conserva UNA copia
(la más votada o la más antigua). "Exacto" significa idéntico tras normalizar
(mayúsculas, tildes, puntuación y alargamientos no cuentan); "casi-duplicado" es
distinto pero con similitud de Jaccard >= `near_dup_threshold`. Las estadísticas del clúster (tamaño y nº de
vídeos distintos) se guardan en columnas porque sirven luego para detectar
campañas coordinadas.
"""
import numpy as np
import pandas as pd
from datasketch import MinHash, MinHashLSH
from tqdm import tqdm


def _shingles(key, k):
    toks = key.split()
    if len(toks) < k:
        return {key}
    return {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


def _cluster_keys(keys, cfg):
    """Devuelve {clave_normalizada: id_de_clúster} agrupando casi-duplicados."""
    n = len(keys)
    if n == 0:
        return {}
    lsh = MinHashLSH(threshold=cfg["near_dup_threshold"], num_perm=cfg["num_perm"])
    mhs = []
    for i, k in enumerate(tqdm(keys, desc="MinHash", leave=False)):
        m = MinHash(num_perm=cfg["num_perm"], seed=cfg["seed"])
        for s in _shingles(k, cfg["shingle_size"]):
            m.update(s.encode("utf-8"))
        mhs.append(m)
        lsh.insert(str(i), m)

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, m in enumerate(mhs):
        for j in lsh.query(m):
            ri, rj = find(i), find(int(j))
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)

    return {keys[i]: find(i) for i in range(n)}


def find_duplicates(df, cfg):
    """Añade cluster_id (-1 = no elegible), cluster_size y cluster_n_videos."""
    df = df.copy()
    eligible = df["text_key"].str.len() >= cfg["min_chars"]
    df["cluster_id"] = -1
    uniq = df.loc[eligible, "text_key"].drop_duplicates().tolist()
    mapping = _cluster_keys(uniq, cfg)
    df.loc[eligible, "cluster_id"] = df.loc[eligible, "text_key"].map(mapping).astype(int)

    df["cluster_size"] = 1
    df["cluster_n_videos"] = 1
    m = df["cluster_id"] >= 0
    if m.any():
        g = df.loc[m].groupby("cluster_id")
        df.loc[m, "cluster_size"] = g["comment_id"].transform("size")
        df.loc[m, "cluster_n_videos"] = g["video_id"].transform("nunique")
    return df


def remove_duplicates(df, cfg):
    """Conserva una copia por clúster. Devuelve (conservados, descartados)."""
    m = df["cluster_id"] >= 0
    work = df.loc[m].copy()
    if cfg["keep"] == "most_liked":
        work = work.sort_values(["likes", "published_at"], ascending=[False, True], kind="stable")
    else:
        work = work.sort_values("published_at", kind="stable")

    group_cols = ["cluster_id"] + (["video_id"] if cfg["scope"] == "per_video" else [])
    work["_rep_key"] = work.groupby(group_cols)["text_key"].transform("first")
    dup_mask = work.duplicated(subset=group_cols, keep="first")

    dropped = work.loc[dup_mask].copy()
    dropped["drop_reason"] = np.where(
        dropped["text_key"] == dropped["_rep_key"], "duplicado_exacto", "casi_duplicado"
    )
    dropped = dropped.drop(columns="_rep_key")
    kept = df.loc[~df.index.isin(dropped.index)]
    return kept, dropped
