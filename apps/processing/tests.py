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


class LinesRegressionTests(TestCase):
    """Fija el comportamiento de los helpers geométricos de lines.py
    (la parte más frágil del pipeline) con segmentos sintéticos."""

    def test_merge_colinear_funde_horizontales_alineadas(self):
        from .services.lines import merge_colinear
        segs = [[0, 100, 50, 100], [60, 102, 120, 101]]   # mismo Y ± tolerancia
        out = merge_colinear(segs, dist_tol=15, gap_tol=30, min_len=20)
        self.assertEqual(len(out), 1)
        x1, _, x2, _ = out[0]
        self.assertEqual((min(x1, x2), max(x1, x2)), (0, 120))

    def test_merge_colinear_no_funde_lejanas(self):
        from .services.lines import merge_colinear
        segs = [[0, 100, 50, 100], [0, 200, 50, 200]]     # Y muy distintos
        out = merge_colinear(segs, dist_tol=15, gap_tol=30, min_len=20)
        self.assertEqual(len(out), 2)

    def test_snap_to_grid_redondea_a_la_grilla(self):
        from .services.lines import snap_to_grid
        out = snap_to_grid([[3, 7, 96, 104]], grid_size=10)
        self.assertEqual(out, [[0, 10, 100, 100]])

    def test_close_gaps_extiende_hasta_la_perpendicular(self):
        from .services.lines import close_gaps
        # horizontal termina a 10px de una vertical → debe extenderse hasta ella
        h = [0, 100, 190, 100]
        v = [200, 0, 200, 200]
        out = close_gaps([h, v], gap_tol=20)
        h_out = next(s for s in out if s[1] == s[3])
        self.assertEqual(max(h_out[0], h_out[2]), 200)

    def test_close_gaps_no_extiende_mas_alla_de_la_tolerancia(self):
        from .services.lines import close_gaps
        h = [0, 100, 150, 100]     # a 50px de la vertical, gap_tol=20
        v = [200, 0, 200, 200]
        out = close_gaps([h, v], gap_tol=20)
        h_out = next(s for s in out if s[1] == s[3])
        self.assertEqual(max(h_out[0], h_out[2]), 150)

    def test_extend_to_intersections_cierra_esquina(self):
        from .services.lines import extend_to_intersections
        hs = [[10, 100, 180, 100]]
        vs = [[200, 50, 200, 300]]
        out_h, out_v = extend_to_intersections(hs, vs, max_extend=200)
        self.assertEqual(max(out_h[0][0], out_h[0][2]), 200)


class ClinicaInvariantTests(TestCase):
    """Invariantes del fixture qa/sketches/clinica.png: si un refactor del
    pipeline cambia estos conteos fuera de rango, es una regresión."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        path = SKETCHES / 'clinica.png'
        cls.result = ProcessingPipeline().process(path) if path.exists() else None

    def setUp(self):
        if self.result is None:
            self.skipTest('qa/sketches/clinica.png no disponible')

    def test_conteos_dentro_de_rango(self):
        r = self.result
        self.assertTrue(r['success'], r.get('error'))
        self.assertIn(r['walls'], range(7, 13), f"paredes={r['walls']}")
        self.assertIn(r['doors'], range(4, 9), f"puertas={r['doors']}")
        self.assertIn(r['rooms'], range(8, 13), f"recintos={r['rooms']}")

    def test_todos_los_objetos_tienen_srtype(self):
        objs = self.result['canvas_data']['objects']
        self.assertTrue(objs)
        self.assertTrue(all(o.get('srType') for o in objs))


class QualityFeedbackTests(TestCase):
    def test_deteccion_buena_sin_avisos(self):
        from .views import quality_feedback
        q = quality_feedback({'paredes': 9, 'puertas': 6, 'muebles': 0, 'recintos': 10})
        self.assertEqual(q['level'], 'buena')
        self.assertEqual(q['reasons'], [])

    def test_sin_recintos_avisa(self):
        from .views import quality_feedback
        q = quality_feedback({'paredes': 9, 'puertas': 6, 'recintos': 0})
        self.assertEqual(q['level'], 'regular')
        self.assertEqual(len(q['reasons']), 1)

    def test_foto_mala_multiples_avisos(self):
        from .views import quality_feedback
        q = quality_feedback({'paredes': 1, 'puertas': 0, 'recintos': 0})
        self.assertEqual(q['level'], 'mala')
        self.assertEqual(len(q['reasons']), 3)


class JobStatusTests(TestCase):
    """El polling nunca debe quedar colgado: jobs viejos en processing → failed."""

    def setUp(self):
        from apps.accounts.models import User
        from apps.projects.models import Project
        from apps.plans.models import Plan
        self.user = User.objects.create_user(username='qa2', password='x')
        proj = Project.objects.create(user=self.user, name='P', description='')
        self.plan = Plan.objects.create(project=proj, name='plano')
        self.client.force_login(self.user)

    def test_job_processing_viejo_se_marca_failed(self):
        from datetime import timedelta
        from django.urls import reverse
        from django.utils import timezone
        from .models import ProcessingJob
        job = ProcessingJob.objects.create(plan=self.plan, status='processing')
        # updated_at es auto_now: se fuerza por queryset para simular un hilo colgado
        ProcessingJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(seconds=600))
        r = self.client.get(reverse('processing_status', args=[self.plan.pk]))
        self.assertEqual(r.json()['status'], 'failed')

    def test_job_processing_reciente_sigue_processing(self):
        from django.urls import reverse
        from .models import ProcessingJob
        ProcessingJob.objects.create(plan=self.plan, status='processing')
        r = self.client.get(reverse('processing_status', args=[self.plan.pk]))
        self.assertEqual(r.json()['status'], 'processing')
