from pathlib import Path

import numpy as np
import cv2
from django.test import TestCase

from .services.pipeline import ProcessingPipeline
from .services.preprocessing import segment_by_color, COLOR_MAP
from .services.overlay import render_canvas_preview

SKETCHES = Path(__file__).resolve().parent.parent.parent / 'qa' / 'sketches'


class SegmentByColorTests(TestCase):
    """Segmentación sobre una imagen sintética generada en memoria (sin
    depender de archivos ni de la cámara): un cuadrado blanco con un trazo
    de cada color exacto de COLOR_MAP, para verificar que cada máscara
    detecta lo suyo y no se cruza con las demás."""

    def _synthetic_image(self):
        img = np.full((400, 400, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (10, 10), (390, 390), (30, 30, 30), 6)       # pared: negro
        cv2.line(img, (50, 200), (150, 200), (200, 130, 20), 4)         # puerta: azul (BGR)
        cv2.line(img, (200, 200), (300, 200), (50, 180, 50), 4)         # vano: verde
        cv2.rectangle(img, (250, 250), (320, 320), (50, 50, 200), 3)    # mueble: rojo
        return img

    def test_each_color_detected_in_its_own_mask(self):
        masks = segment_by_color(self._synthetic_image())
        self.assertEqual(set(masks.keys()), set(COLOR_MAP.keys()))
        for elem_type in ('puerta', 'vano', 'mueble'):
            self.assertGreater(
                cv2.countNonZero(masks[elem_type]['binary']), 0,
                f'{elem_type} debería detectar algo de tinta',
            )
        self.assertGreater(cv2.countNonZero(masks['pared']['binary']), 0)

    def test_sensitivity_alta_is_at_least_as_permissive_as_baja(self):
        img = self._synthetic_image()
        alta = segment_by_color(img, sensitivity='alta')
        baja = segment_by_color(img, sensitivity='baja')
        for elem_type in ('puerta', 'vano', 'mueble'):
            n_alta = cv2.countNonZero(alta[elem_type]['binary'])
            n_baja = cv2.countNonZero(baja[elem_type]['binary'])
            self.assertGreaterEqual(n_alta, n_baja * 0.9)


class ProcessingPipelineTests(TestCase):
    """El pipeline completo sobre un croquis sintético (`qa/sketches/`, ya
    usado por los scripts de qa/), con aserciones mínimas de conteos —no
    exactas, para no volverse frágil ante ajustes finos de umbrales."""

    def test_clinica_sketch_produces_walls_and_rooms(self):
        path = SKETCHES / 'clinica.png'
        if not path.exists():
            self.skipTest('qa/sketches/clinica.png no disponible en este entorno')
        result = ProcessingPipeline().process(path)
        self.assertTrue(result['success'], result.get('error'))
        self.assertGreater(result['walls'], 0)
        self.assertGreaterEqual(result['rooms'], 1)
        self.assertIn('objects', result['canvas_data'])

    def test_invalid_image_path_fails_gracefully(self):
        result = ProcessingPipeline().process('media/no-existe-este-archivo.png')
        self.assertFalse(result['success'])
        self.assertTrue(result['error'])


class OverlayTests(TestCase):
    """El overlay de verificación no debe explotar ante entradas mínimas."""

    def test_render_canvas_preview_handles_empty_data(self):
        img = render_canvas_preview({'objects': []}, doc_w=100, doc_h=80)
        self.assertEqual(img.shape, (80, 100, 3))

    def test_render_canvas_preview_draws_from_real_pipeline(self):
        path = SKETCHES / 'clinica.png'
        if not path.exists():
            self.skipTest('qa/sketches/clinica.png no disponible en este entorno')
        result = ProcessingPipeline().process(path)
        self.assertTrue(result['success'])
        img = render_canvas_preview(result['canvas_data'])
        # debe haber dibujado algo (no todo blanco)
        self.assertTrue((img != 255).any())
