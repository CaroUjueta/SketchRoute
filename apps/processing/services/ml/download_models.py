"""Script de descarga de modelos pre-entrenados.

Uso:
    python -m apps.processing.services.ml.download_models [--all]

Descarga:
    - MobileSAM: ~38MB, rápido en CPU, para segmentación zero-shot
    - YOLOv8n: ~6MB, para detección de símbolos
    - Opcional: SAM completo (~2.4GB)

Los modelos se guardan en media/models/
"""

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

MODEL_DIR = Path('media/models')


def download_file(url, dest, desc=''):
    import urllib.request
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        logger.info('%s ya existe, saltando', dest.name)
        return

    def report(block, total, done):
        if total > 0:
            pct = done * block * 100 / max(total, 1)
            sys.stdout.write(f'\r  {desc}: {pct:.0f}%')
            sys.stdout.flush()

    logger.info('Descargando %s desde %s...', dest.name, url)
    urllib.request.urlretrieve(url, str(dest), reporthook=report)
    print()
    logger.info('Descargado: %s (%.1f MB)', dest.name, dest.stat().st_size / 1e6)


def main():
    parser = argparse.ArgumentParser(description='Descargar modelos pre-entrenados')
    parser.add_argument('--all', action='store_true', help='Descargar todos los modelos')
    args = parser.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # MobileSAM (~38MB) — segmentación zero-shot liviana
    download_file(
        'https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt',
        MODEL_DIR / 'mobile_sam.pt',
        desc='MobileSAM (38 MB)',
    )

    # YOLOv8n (~6MB) — detección de objetos
    try:
        from ultralytics import YOLO
        logger.info('Descargando YOLOv8n...')
        YOLO('yolov8n.pt')
        logger.info('YOLOv8n descargado')
    except ImportError:
        logger.warning('ultralytics no instalado, salteando YOLO')

    if args.all:
        # SAM completo (~2.4GB) — solo si se pide explícitamente
        download_file(
            'https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth',
            MODEL_DIR / 'sam_vit_h_4b8939.pth',
            desc='SAM ViT-H (2.4 GB)',
        )

    logger.info('Descarga completada. Modelos en: %s', MODEL_DIR)


if __name__ == '__main__':
    main()
