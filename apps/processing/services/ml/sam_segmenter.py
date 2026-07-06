"""Segmentación zero-shot con SAM (Segment Anything Model) de Meta.

SAM permite segmentar cualquier objeto en una foto sin entrenamiento
previo.  Para SketchRoute lo usamos para:

1. Extraer el croquis del fondo del papel
2. Segmentar líneas de pared, muebles, puertas por color/lápiz
3. Generar máscaras de alta calidad para vectorización

Dos modos:
- SAM completo (mayor precisión, requiere ~2.4GB VRAM)
- MobileSAM / FastSAM (más rápido, ~1GB, ideal para CPU)

Uso:
    segmenter = SAMSegmenter()
    segmenter.load('mobile')  # o 'sam', o ruta a checkpoint
    masks = segmenter.segment(image_bgr)
"""

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

MODEL_URLS = {
    'sam': 'https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth',
    'mobile': 'https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt',
}

MODEL_DIR = Path('media/models')

# ── Módulo de abstracción para SAM ──────────────────────────

try:
    from segment_anything import sam_model_registry, SamPredictor
    HAS_SAM = True
except ImportError:
    HAS_SAM = False


class SAMSegmenter:
    """Wrapper para SAM / MobileSAM.

    Si no hay GPU, SAM corre en CPU pero es lento (~10s por imagen).
    MobileSAM es ~3× más rápido en CPU.
    """

    def __init__(self, model_type='mobile', device=None):
        self.model_type = model_type
        self.device = device or 'cpu'
        self.predictor = None
        self.model = None

    def load(self, model_type_or_path=None):
        if model_type_or_path:
            self.model_type = model_type_or_path

        if not HAS_SAM:
            logger.error(
                'segment_anything no instalado. '
                'Ejecuta: pip install git+https://github.com/facebookresearch/segment-anything.git'
            )
            return False

        try:
            MODEL_DIR.mkdir(parents=True, exist_ok=True)

            if self.model_type == 'mobile':
                checkpoint = MODEL_DIR / 'mobile_sam.pt'
                if not checkpoint.exists():
                    logger.info('Descargando MobileSAM...')
                    self._download(MODEL_URLS['mobile'], checkpoint)
                sam = sam_model_registry['vit_t'](str(checkpoint))
            elif self.model_type == 'sam':
                checkpoint = MODEL_DIR / 'sam_vit_h_4b8939.pth'
                if not checkpoint.exists():
                    logger.info('Descargando SAM (2.4GB, puede tomar varios minutos)...')
                    self._download(MODEL_URLS['sam'], checkpoint)
                sam = sam_model_registry['default'](str(checkpoint))
            else:
                checkpoint = Path(self.model_type)
                if not checkpoint.exists():
                    logger.error('Checkpoint no encontrado: %s', checkpoint)
                    return False
                sam = sam_model_registry['default'](str(checkpoint))

            sam.to(self.device)
            self.predictor = SamPredictor(sam)
            self.model = sam
            logger.info('SAM cargado: %s', self.model_type)
            return True

        except Exception as e:
            logger.exception('Error al cargar SAM: %s', e)
            return False

    def is_loaded(self):
        return self.predictor is not None

    @staticmethod
    def _download(url, dest):
        import urllib.request
        import sys

        def report(block, total, done):
            if total > 0:
                pct = done * block * 100 / total
                sys.stdout.write(f'\r  Descargando... {pct:.0f}%')
                sys.stdout.flush()

        urllib.request.urlretrieve(url, str(dest), reporthook=report)
        print()

    def segment(self, bgr_image, points_per_side=16):
        """Segmenta la imagen completa usando SAM en modo automático.

        SAM genera múltiples máscaras. Las filtramos por tamaño
        y forma para quedarnos con las relevantes para planos.

        Args:
            bgr_image: numpy array (H, W, 3) en BGR
            points_per_side: densidad de puntos para SAM automático

        Returns:
            list de dicts:
                {'mask': máscara binaria, 'score': float,
                 'bbox': (x1,y1,x2,y2)}
        """
        if not self.is_loaded():
            logger.warning('SAM no cargado')
            return []

        try:
            from segment_anything import SamAutomaticMaskGenerator
            generator = SamAutomaticMaskGenerator(
                self.model,
                points_per_side=points_per_side,
                pred_iou_thresh=0.7,
                stability_score_thresh=0.85,
                min_mask_region_area=500,
            )

            rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
            masks = generator.generate(rgb)

            logger.info('SAM generó %d máscaras', len(masks))
            return masks

        except Exception as e:
            logger.exception('Error en segmentación SAM: %s', e)
            return []

    def segment_foreground(self, bgr_image):
        """Segmenta el croquis del fondo del papel.

        Usa SAM para encontrar la máscara del contenido principal
        (el dibujo) ignorando el fondo del papel.

        Returns:
            máscara binaria (H, W) o None si falla
        """
        masks = self.segment(bgr_image, points_per_side=8)
        if not masks:
            return None

        h, w = bgr_image.shape[:2]
        combined = np.zeros((h, w), dtype=np.uint8)

        for m in masks:
            mask = m['segmentation'].astype(np.uint8) * 255
            area = cv2.countNonZero(mask)
            # ignorar máscaras muy pequeñas o que sean el fondo completo
            if area < h * w * 0.01 or area > h * w * 0.98:
                continue
            combined = cv2.bitwise_or(combined, mask)

        return combined


# ── Integración con el pipeline ──────────────────────────────

def enhance_with_sam(bgr_image, model_type='mobile'):
    """Función de alto nivel: usa SAM para mejorar la segmentación.

    1. SAM segmenta la imagen
    2. Extrae la máscara del croquis (foreground)
    3. Aplica la máscara para limpiar el fondo
    4. Retorna la imagen limpia + máscara de croquis

    Args:
        bgr_image: imagen BGR original
        model_type: 'mobile' o 'sam'

    Returns:
        (imagen_limpia, mascara_croquis) o (original, None) si falla
    """
    segmenter = SAMSegmenter(model_type)
    if not segmenter.load():
        return bgr_image, None

    fg_mask = segmenter.segment_foreground(bgr_image)
    if fg_mask is None:
        return bgr_image, None

    # máscara + dilatación suave para evitar bordes duros
    kernel = np.ones((5, 5), np.uint8)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel, iterations=1)

    cleaned = cv2.bitwise_and(bgr_image, bgr_image, mask=fg_mask)
    return cleaned, fg_mask
