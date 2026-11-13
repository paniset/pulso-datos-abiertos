"""Build estático sin dependencias; lista explícita de archivos publicables."""
from pathlib import Path
import json
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from factory.radar_schema import validate_radar
from factory.security import headers_file, protect_html
from factory.catalog import RADAR_GENERATED_FILES
from scripts.pulso_sample import sample_files
from factory.indexing import apply_indexing

def build(radar_data_path=None):
    raw = Path(radar_data_path or ROOT / 'data/radar.json').read_bytes()
    data = json.loads(raw)
    validate_radar(data)
    dest = ROOT / 'dist'
    dest.mkdir(exist_ok=True)
    names = ('index.html', 'legal.html', 'style.css', 'app.js', 'lib.mjs', 'favicon.svg')
    allowed = set(names) | set(RADAR_GENERATED_FILES) | {'data/radar.json', 'robots.txt', '_headers', '404.html', 'sitemap.xml'}
    # Fallar sin borrar nada si un build anterior contiene archivos inesperados.
    for item in dest.rglob('*'):
        relative = item.relative_to(dest).as_posix()
        if item.is_symlink() or (item.is_file() and relative not in allowed) or (item.is_dir() and relative != 'data'):
            raise ValueError(f'Archivo ajeno al artefacto: {relative}. Conserva y retira el archivo antes de compilar.')
    # La portada lleva el resumen estático derivado de los mismos bytes del radar.
    sample = sample_files(raw, (ROOT / 'site/index.html').read_bytes())
    for name in names:
        shutil.copyfile(ROOT / 'site' / name, dest / name)
    (dest / 'data').mkdir(exist_ok=True)
    (dest / 'data/radar.json').write_bytes(raw)
    for name, content in sample.items():
        (dest / name).write_bytes(content)
    (dest / '_headers').write_text(headers_file(),encoding='utf-8')
    (dest / '404.html').write_text('<!doctype html><html lang="es"><meta charset="utf-8"><title>No encontrado</title><h1>Página no encontrada</h1><a href="/">Volver al radar</a></html>',encoding='utf-8')
    html_names = ('index.html', 'legal.html', '404.html') + tuple(name for name in RADAR_GENERATED_FILES if name.endswith('.html') and (dest / name).exists())
    pages = {name: (dest / name).read_bytes() for name in html_names}
    if (dest / 'og.png').exists():
        pages['og.png'] = (dest / 'og.png').read_bytes()  # para que el static ponga og:image igual que el pipeline
    indexed = apply_indexing(pages, 'pulso-local', 'radar')
    for name, content in indexed.items():
        (dest / name).write_bytes(content)
    for name in html_names:
        path = dest / name
        path.write_text(protect_html(path.read_text(encoding='utf-8-sig')), encoding='utf-8')
    print(f'Build listo: {len(data["changes"])} registros, modo {data["meta"]["mode"]}')

if __name__ == '__main__':
    build()
