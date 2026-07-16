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


class RoutabilityTests(TestCase):
    """La métrica que el usuario percibe: los recintos detectados deben poder
    trazar ruta hasta la salida en el mismo modelo de grid del editor."""

    def test_clinica_recintos_llegan_a_la_salida(self):
        path = SKETCHES / 'clinica.png'
        if not path.exists():
            self.skipTest('qa/sketches/clinica.png no disponible')
        import sys
        sys.path.insert(0, str(SKETCHES.parent.parent))
        from qa.routelib import routability
        result = ProcessingPipeline().process(path)
        self.assertTrue(result['success'])
        ok, total = routability(result['canvas_data']['objects'])
        # el fixture tiene UN recinto sin puerta dibujada (tabique inferior
        # derecho): ese debe fallar y el resto llegar.
        self.assertGreaterEqual(total, 7)
        self.assertGreaterEqual(ok, total - 1, f'solo {ok}/{total} recintos con ruta')


class AutoSensitivityTests(TestCase):
    def test_score_result_prefiere_mejor_deteccion(self):
        from .services.pipeline import score_result
        vacio = {'success': True, 'rooms': 0, 'doors': 0, 'canvas_data': {'objects': []}}
        bueno = {'success': True, 'rooms': 4, 'doors': 3, 'canvas_data': {'objects': [
            {'type': 'path', 'srType': 'puerta', 'left': 0, 'top': 0, 'width': 40, 'height': 8},
            {'type': 'path', 'srType': 'puerta', 'left': 100, 'top': 0, 'width': 40, 'height': 8},
            {'type': 'path', 'srType': 'puerta', 'left': 200, 'top': 0, 'width': 40, 'height': 8},
        ]}}
        self.assertGreater(score_result(bueno), score_result(vacio))

    def test_score_result_fallo_es_cero(self):
        from .services.pipeline import score_result
        self.assertEqual(score_result({'success': False}), 0.0)

    def test_auto_elige_sensibilidad_y_reporta_score(self):
        path = SKETCHES / 'clinica.png'
        if not path.exists():
            self.skipTest('qa/sketches/clinica.png no disponible')
        res = ProcessingPipeline(config={'sensitivity': 'auto'}).process(path)
        self.assertTrue(res['success'])
        self.assertIn(res['debug']['sensitivity_chosen'], ('alta', 'media', 'baja'))
        self.assertGreater(res['quality_score'], 50)
        self.assertEqual(len(res['debug']['sensitivity_scores']), 3)


class TJunctionGapTests(TestCase):
    """Micro-gap en unión T: el extremo que no llega a la pared perpendicular
    debe proyectarse sobre ella (lo hace close_gaps antes de detectar recintos)."""

    def test_close_gaps_cierra_t_de_7px(self):
        from .services.lines import close_gaps
        segs = [
            [0, 0, 300, 0], [0, 300, 300, 300],
            [0, 0, 0, 300], [300, 0, 300, 300],
            [0, 150, 293, 150],   # tabique que no llega por 7px
        ]
        out = close_gaps(segs, gap_tol=20)
        t = next(s for s in out if s[1] == 150 and s[3] == 150)
        self.assertEqual(max(t[0], t[2]), 300)


class CloseExteriorTests(TestCase):
    def test_planta_en_l_conserva_la_muesca(self):
        from .services.lines import close_exterior
        H = [[0, 0, 600, 0], [300, 300, 600, 300], [0, 600, 300, 600]]
        V = [[0, 0, 0, 600], [600, 0, 600, 300], [300, 300, 300, 600]]
        h2, v2 = close_exterior(H, V)
        # 6 lados (L), no 4 (rectángulo): la esquina interior existe
        self.assertEqual(len(h2) + len(v2), 6)
        corners = {(round(s[0]), round(s[1])) for s in h2 + v2}
        corners |= {(round(s[2]), round(s[3])) for s in h2 + v2}
        self.assertIn((300, 300), corners)

    def test_rectangulo_sigue_cerrando_igual(self):
        from .services.lines import close_exterior
        H = [[0, 0, 600, 0], [0, 400, 600, 400]]
        V = [[0, 0, 0, 400], [600, 0, 600, 400]]
        h2, v2 = close_exterior(H, V)
        self.assertEqual(len(h2) + len(v2), 4)


class DeskewTests(TestCase):
    """Fotos torcidas 2-15° se enderezan por rotación pura y el pipeline
    produce los mismos conteos que con la foto derecha."""

    def test_deskew_recupera_rotacion_leve(self):
        import cv2
        from .services.preprocessing import deskew
        path = SKETCHES / 'clinica.png'
        if not path.exists():
            self.skipTest('qa/sketches/clinica.png no disponible')
        img = cv2.imread(str(path))
        h, w = img.shape[:2]
        for ang in (5, -6):
            M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
            rot = cv2.warpAffine(img, M, (w, h), borderValue=(255, 255, 255))
            _, applied = deskew(rot)
            self.assertAlmostEqual(applied, -ang, delta=1.0)

    def test_foto_derecha_no_se_toca(self):
        import cv2
        from .services.preprocessing import deskew
        path = SKETCHES / 'clinica.png'
        if not path.exists():
            self.skipTest('qa/sketches/clinica.png no disponible')
        _, applied = deskew(cv2.imread(str(path)))
        self.assertEqual(applied, 0.0)


class ArcDoorTests(TestCase):
    """Puertas dibujadas como arco de apertura: el blob azul sin trazo recto
    se proyecta sobre la pared más cercana como hueco."""

    def test_arco_se_proyecta_sobre_pared(self):
        import numpy as np
        from .services.lines import doors_from_arcs
        mask = np.zeros((400, 400), np.uint8)
        import cv2
        cv2.ellipse(mask, (200, 100), (60, 60), 0, 0, 90, 255, 3)  # arco pegado a pared y=100
        walls_h = [[50, 100, 350, 100]]
        h, v = doors_from_arcs(mask, walls_h, [], existing=[])
        self.assertEqual(len(h), 1)
        seg = h[0]
        self.assertEqual(seg[1], 100)                       # sobre la pared
        self.assertGreaterEqual(seg[2] - seg[0], 18)        # ancho útil

    def test_blob_lejos_de_pared_se_ignora(self):
        import numpy as np, cv2
        from .services.lines import doors_from_arcs
        mask = np.zeros((400, 400), np.uint8)
        cv2.circle(mask, (200, 300), 30, 255, -1)           # a 170px de la pared
        h, v = doors_from_arcs(mask, [[50, 100, 350, 100]], [], existing=[])
        self.assertEqual((len(h), len(v)), (0, 0))


class FotoRealDegradadaTests(TestCase):
    """Condiciones de foto real (papel crema, cuadrícula, sombra diagonal,
    rotación 4°, ruido) sobre un fixture con verdad conocida: la planta debe
    seguir ruteando completa con sensibilidad automática."""

    def test_farmacia_degradada_rutea_completa(self):
        import cv2
        import numpy as np
        path = SKETCHES / 'farmacia.png'
        if not path.exists():
            self.skipTest('qa/sketches/farmacia.png no disponible')
        img = cv2.imread(str(path)).astype(np.float32)
        h, w = img.shape[:2]
        for x in range(0, w, 24):
            cv2.line(img, (x, 0), (x, h), (235, 215, 205), 1)
        for y in range(0, h, 24):
            cv2.line(img, (0, y), (w, y), (235, 215, 205), 1)
        gx = np.linspace(1.0, 0.55, w, dtype=np.float32)
        gy = np.linspace(1.0, 0.75, h, dtype=np.float32)
        img *= (gy[:, None] * gx[None, :])[:, :, None]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 4, 1.0)
        img = cv2.warpAffine(img, M, (w, h), borderValue=(200, 198, 192))
        img += np.random.default_rng(7).normal(0, 4, img.shape).astype(np.float32)
        import tempfile, os
        tmp = os.path.join(tempfile.gettempdir(), 'sr_farmacia_degradada.png')
        cv2.imwrite(tmp, np.clip(img, 0, 255).astype(np.uint8))

        import sys
        sys.path.insert(0, str(SKETCHES.parent.parent))
        from qa.routelib import routability
        res = ProcessingPipeline(config={'sensitivity': 'auto'}).process(tmp)
        self.assertTrue(res['success'])
        ok, total = routability(res['canvas_data']['objects'])
        self.assertGreaterEqual(total, 2)
        self.assertEqual(ok, total, f'{ok}/{total} recintos con ruta en foto degradada')
