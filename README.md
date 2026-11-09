# Preprocesamiento de comentarios de YouTube (TFM)

Pipeline reproducible para limpiar comentarios antes del análisis de sentimiento.

## Pasos (en orden)

| # | Paso | Qué hace |
|---|------|----------|
| 1 | `comment_id` repetido | Elimina filas repetidas de la descarga |
| 2 | Limpieza + sin contenido | Sustituye URLs, emails, teléfonos y menciones por marcadores; **conserva mayúsculas, puntuación y emojis**; descarta comentarios que quedan vacíos (p. ej. solo un enlace) |
| 3 | Duplicados | *Exactos* (iguales tras normalizar) y *casi-duplicados* (MinHash + LSH). Conserva una copia (la más votada). Solo se aplica a textos de ≥20 caracteres normalizados, para no borrar respuestas legítimas como "Verdad" |
| 4 | Spam / bots | Puntuación por reglas (enlaces, teléfonos, frases de spam, repeticiones, mensaje copiado en muchos vídeos…) |
| 5 | Idioma | Conserva español (Lingua). Textos con <15 letras se marcan `und` y se conservan (configurable) |

Cada paso registra lo que descarta y **por qué** en `descartados.csv`.

## Instalación y uso

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                              # comprobar que todo funciona
python run_preprocessing.py --config config.yaml       # o --input ruta/al.csv
```

Entrada: CSV con `video_id, comment_id, text, likes, published_at` (y `reply_count`).

## Qué genera cada ejecución

`runs/<fecha>_<commit>/`

| Archivo | Contenido |
|---------|-----------|
| `comentarios_limpios.csv` / `.parquet` | Dataset final (`text_raw` y `text_clean`) |
| `descartados.csv` | Todo lo eliminado, con `drop_step`, `drop_reason`, `spam_score`, `spam_reasons` |
| `embudo.csv` | Filas que entran/salen en cada paso (para la memoria del TFM) |
| `informe.json` | Versión del pipeline, commit de git, hash SHA-256 del dataset de entrada, versiones de librerías y configuración completa |
| `config_usada.yaml` | Copia exacta de la configuración |

## Flujo de trabajo con git

```bash
git init
git add .
git commit -m "Pipeline de preprocesamiento v1.0.0"
git tag -a v1.0.0 -m "Primera versión del pipeline"
```

1. Para cambiar un umbral o una lista de palabras: edita `config.yaml` → `git commit` → ejecuta.
   El `informe.json` indicará `"dirty": true` si ejecutaste con cambios sin commitear.
2. Si cambias la lógica del código, sube `__version__` en `preprocessing/__init__.py` y crea un tag nuevo (`v1.1.0`…).
3. Los datos **no se versionan** (`.gitignore`): pesan, y los términos de YouTube y el RGPD recomiendan no
   redistribuirlos. Sí se versionan `informe.json`, `embudo.csv` y `config_usada.yaml`.
4. Para fijar versiones exactas: `pip freeze > requirements.lock.txt` y commitéalo.

## Qué revisar antes de dar el resultado por bueno

- **`descartados.csv`**: lee una muestra de cada `drop_reason`, sobre todo `spam_bot` e `idioma_*`.
  Ajusta `spam.keywords` y los umbrales en `config.yaml` según lo que veas.
- **Mensajes coordinados:** se marcan (`coordinated` en `spam_reasons`) pero por defecto **no** se descartan
  (solo se conserva una copia). Si la campaña coordinada es parte de lo que estudias, analízala aparte.
- **Placeholders:** si usas `pysentimiento`/`robertuito`, cambia `<URL>` y `<USUARIO>` en `config.yaml` por
  `url` y `@usuario` para coincidir con su preprocesado.

## Limitaciones conocidas

- No hay identificador de autor, así que no se pueden detectar cuentas bot, solo patrones en el texto.
- Menciones con espacios (`@Juan Pérez`) solo sustituyen la primera palabra.
- La detección de URLs sin `http` solo reconoce dominios `.com .net .org .info .xyz .ec`.
- Los casi-duplicados se agrupan por transitividad (A≈B y B≈C ⇒ mismo grupo, aunque A y C difieran más).
- Textos con mezcla español-inglés se clasifican por el idioma dominante.
