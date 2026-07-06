"""Inferencia del modelo U-Net para segmentación de planos.

Integración con el pipeline de procesamiento:
    1. Cargar el modelo (lazy, singleton)
    2. Segmentar la imagen → máscaras por clase
    3. Post-procesar máscaras para vectorización
"""

import logging
from pathlib import Path

import cv2
import numpy as np

from .model import get_segmenter, CLASS_NAMES

logger = logging.getLogger(__name__)

# Ruta por defecto donde buscar el modelo entrenado
DEFAULT_MODEL_PATH = Path('media/models/unet_segmentation.pt')


def segment_image(bgr_image, model_path=None, fallback_to_color=True):
    """Segmenta una imagen usando U-Net (si está disponible) o clustering.

    Args:
        bgr_image: numpy array (H, W, 3) en BGR
        model_path: ruta al modelo .pt (opcional)
        fallback_to_color: si True, retorna máscaras vacías cuando
            no hay modelo en vez de fallar

    Returns:
        dict con máscaras por clase, o {} si no hay modelo
    """
    path = model_path or DEFAULT_MODEL_PATH
    segmenter = get_segmenter(path)

    if segmenter.is_loaded():
        logger.info('Segmentando con U-Net...')
        return segmenter.predict(bgr_image)

    if fallback_to_color:
        logger.info('Modelo U-Net no disponible, usando segmentación por color')
        return None  # señal para que el pipeline use color segmentation

    raise RuntimeError(
        'Modelo U-Net no encontrado en %s. '
        'Ejecuta train.py o descarga un modelo pre-entrenado.', path
    )


def masks_to_elements(masks, min_area=100):
    """Convierte máscaras de segmentación en elementos vectorizables.

    Para cada clase no-fondo, identifica componentes conectados
    y genera bounding boxes + contornos.

    Args:
        masks: dict de {class_name: máscara binaria uint8 (H, W)}
        min_area: área mínima en píxeles para considerar un elemento

    Returns:
        dict: {
            'pared': [contornos, ...],
            'puerta': [{'bbox': (x, y, w, h), 'contour': ...}, ...],
            'mueble': [...],
            'vano': [...],
        }
    """
    elements = {}
    for name in CLASS_NAMES:
        if name == 'fondo':
            continue
        mask = masks.get(name, np.zeros((100, 100), dtype=np.uint8))
        if cv2.countNonZero(mask) < min_area:
            elements[name] = []
            continue

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        elements[name] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area >= min_area:
                x, y, w, h = cv2.boundingRect(cnt)
                elements[name].append({
                    'contour': cnt,
                    'bbox': (x, y, w, h),
                    'area': area,
                    'center': (x + w / 2, y + h / 2),
                })

    return elements
