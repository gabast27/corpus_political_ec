"""Trazabilidad: embudo de datos, hash del dataset de entrada, commit de git, versiones."""
import hashlib
import subprocess
import sys
from importlib import metadata


class Funnel:
    """Registra cuántas filas entran y salen en cada paso (útil para la memoria del TFM)."""

    def __init__(self):
        self.rows = []

    def record(self, step, n_in, n_out):
        self.rows.append({"paso": step, "entran": int(n_in), "salen": int(n_out),
                          "descartadas": int(n_in - n_out)})

    def print(self):
        print(f"\n{'paso':<34}{'entran':>10}{'salen':>10}{'descartadas':>13}")
        for r in self.rows:
            print(f"{r['paso']:<34}{r['entran']:>10}{r['salen']:>10}{r['descartadas']:>13}")


def _git(*args):
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def git_info():
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "commit": commit,
        "tag": _git("describe", "--tags", "--always"),
        "dirty": None if status is None else bool(status),
    }


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def library_versions():
    out = {"python": sys.version.split()[0]}
    for name in ["pandas", "numpy", "datasketch", "lingua-language-detector", "emoji", "PyYAML"]:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out
