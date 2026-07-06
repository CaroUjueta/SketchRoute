"""Detección de símbolos en planos arquitectónicos usando YOLO.

Símbolos detectables:
    - puerta (door symbol)
    - ventana (window)
    - escalera (stairs)
    - extintor (fire extinguisher)
    - salida_emergencia (exit sign)
    - punto_reunion (meeting point)
    - extintor_rojo (red fire hose)
    - botiquin (first aid)

Requiere:
    ultralytics (YOLOv8) instalado: pip install ultralytics

El modelo pre-entrenado se descarga automáticamente la primera vez
desde Hugging Face Hub o desde una ruta local.
"""

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Mapa de clases YOLO → tipos de SketchRoute
DEFAULT_CLASS_MAP = {
    0: 'puerta',
    1: 'vano',
    2: 'escalera',
    3: 'extintor',
    4: 'salida_emergencia',
    5: 'punto_reunion',
    6: 'botiquin',
}

DEFAULT_MODEL_NAME = 'yolov8n.pt'  # nano para CPU


class SymbolDetector:
    """Detector de símbolos en planos usando YOLO.

    Uso:
        detector = SymbolDetector()
        detector.load('yolov8n.pt')  # o ruta a modelo fine-tuned
        symbols = detector.detect(image_bgr)
    """

    def __init__(self, model_path=None, class_map=None):
        self.model = None
        self.model_path = Path(model_path) if model_path else None
        self.class_map = class_map or DEFAULT_CLASS_MAP

    def load(self, model_path=None):
        if model_path:
            self.model_path = Path(model_path)

        try:
            from ultralytics import YOLO
            model_path_str = str(self.model_path) if self.model_path else DEFAULT_MODEL_NAME
            self.model = YOLO(model_path_str)
            logger.info('YOLO cargado: %s', model_path_str)
            return True
        except ImportError:
            logger.warning(
                'ultralytics no instalado. '
                'Ejecuta: pip install ultralytics'
            )
            return False
        except Exception as e:
            logger.exception('Error al cargar YOLO: %s', e)
            return False

    def is_loaded(self):
        return self.model is not None

    def detect(self, bgr_image, conf_threshold=0.25, iou_threshold=0.45):
        """Detecta símbolos en la imagen.

        Args:
            bgr_image: numpy array (H, W, 3) en BGR
            conf_threshold: umbral de confianza
            iou_threshold: umbral NMS

        Returns:
            list de dicts: {
                'class': nombre clase,
                'confidence': float,
                'bbox': (x1, y1, x2, y2),  # coordenadas absolutas
                'center': (cx, cy),
            }
        """
        if self.model is None:
            logger.warning('YOLO no cargado')
            return []

        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        results = self.model(
            rgb, conf=conf_threshold, iou=iou_threshold,
            verbose=False,
        )

        symbols = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                class_name = self.class_map.get(cls_id, f'class_{cls_id}')
                symbols.append({
                    'class': class_name,
                    'confidence': conf,
                    'bbox': (x1, y1, x2, y2),
                    'center': ((x1 + x2) / 2, (y1 + y2) / 2),
                })

        return symbols


# Singleton
_detector_instance = None


def get_detector(model_path=None):
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = SymbolDetector(model_path)
    if model_path and not _detector_instance.is_loaded():
        _detector_instance.load(model_path)
    return _detector_instance
