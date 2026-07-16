"""Pipeline principal de procesamiento de imágenes.

Orquesta las etapas de:
1. Preprocesamiento (perspectiva, segmentación por color)
2. Detección de líneas por máscara de color (paredes, puertas, muebles)
3. Fusión de segmentos
4. Detección de recintos (grafo planar, ciclos) — solo paredes
5. Generación de JSON Fabric.js con objetos tipados por color

Cada tipo de elemento se procesa por separado usando su máscara
de color, lo que permite diferenciar paredes (negro), puertas
(azul) y muebles (rojo) sin necesidad de clasificación ML."""

import cv2
import numpy as np
import logging
from pathlib import Path

from . import preprocessing
from . import lines
from . import rooms
from . import fabric

logger = logging.getLogger(__name__)


class ProcessingPipeline:

    def __init__(self, config=None):
        self.config = {
            'sensitivity': 'media',  # 'alta' | 'media' | 'baja' — ver preprocessing.SENSITIVITY_PRESETS
            'target_w': 1320,
            'target_h': 864,
            'hough_min_length': 20,
            'hough_max_gap': 20,
            'merge_angle_tol': 6,
            'merge_dist_tol': 30,
            'merge_gap_tol': 70,
            'extend_max': 400,
            'close_gap_tol': 55,
            'snap_grid': 12,
            'min_segment_length': 20,
            'room_min_area': 5000,
            'room_max_area': 500000,
        }
        if config:
            self.config.update(config)

    def process(self, image_path):
        debug = {}

        try:
            logger.info('Cargando imagen: %s', image_path)
            image = cv2.imread(str(image_path))
            if image is None:
                return self._error('No se pudo cargar la imagen')

            debug['input_shape'] = image.shape

            # Normalizar resolución de entrada: fotos de celular (4000px+)
            # solo agregan ruido y tiempo; los umbrales relativos de
            # preprocessing siguen válidos a este tamaño.
            MAX_INPUT_W = 2400
            if image.shape[1] > MAX_INPUT_W:
                scale = MAX_INPUT_W / image.shape[1]
                image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                debug['downscaled_to'] = image.shape

            # ── Etapa 1: Corrección de perspectiva ────────────
            image = preprocessing.correct_perspective(image)

            # ── Etapa 1b: Orientar el plano para que la salida principal
            # (la puerta más ancha y más exterior — la única forma de salir)
            # quede a la derecha. ──
            image, rot = self._orient_exit_right(image)
            debug['rotation'] = rot

            # ── Etapa 2: Segmentación por color ───────────────
            logger.info('Segmentando por color...')
            masks = preprocessing.segment_by_color(image, sensitivity=self.config['sensitivity'])
            masks = preprocessing.resize_mask_to_canvas(
                masks, self.config['target_w'], self.config['target_h'],
            )

            debug['segments'] = {k: cv2.countNonZero(v['binary']) for k, v in masks.items()}

            # ── Etapa 3: Detección de líneas por tipo ─────────
            all_objects = []  # objetos Fabric.js de todos los tipos
            all_segments = {}
            wall_segments_h = []
            wall_segments_v = []
            wall_style = {'stroke': '#777777', 'stroke_width': 8}
            elem_styles = {}  # estilo por tipo (para generar objetos tras el bucle)
            door_segments_h = []
            door_segments_v = []
            vano_segments_h = []
            vano_segments_v = []

            for elem_type, mask_data in masks.items():
                binary = mask_data['binary']
                if cv2.countNonZero(binary) < 30:
                    logger.debug('Tipo %s: muy pocos píxeles, saltando', elem_type)
                    continue

                logger.info('Procesando %s...', elem_type)

                # ── Detectar formas (círculos y rectángulos) ─────
                # Para muebles, detectar formas antes de Hough para
                # evitar que sus bordes generen segmentos espurios
                elem_circles = []
                elem_rects = []
                if elem_type == 'mueble':
                    elem_circles, elem_rects = lines.detect_shapes(binary)
                    # descartar formas fuera del área de paredes (ruido/borde)
                    if wall_segments_h or wall_segments_v:
                        wpts = wall_segments_h + wall_segments_v
                        wxs = [c for s in wpts for c in (s[0], s[2])]
                        wys = [c for s in wpts for c in (s[1], s[3])]
                        wb = (min(wxs) - 30, min(wys) - 30, max(wxs) + 30, max(wys) + 30)
                        elem_circles = [c for c in elem_circles
                                        if wb[0] <= c[0] <= wb[2] and wb[1] <= c[1] <= wb[3]]
                        elem_rects = [r for r in elem_rects
                                      if wb[0] <= r[0] + r[2] / 2 <= wb[2]
                                      and wb[1] <= r[1] + r[3] / 2 <= wb[3]]
                    if elem_circles or elem_rects:
                        binary = lines.mask_out_shapes(binary, elem_circles, elem_rects)
                        for c in elem_circles:
                            all_objects.append(
                                fabric.circle_to_fabric(
                                    c[0], c[1], c[2],
                                    sr_type='mueble',
                                    color=mask_data['stroke'],
                                    stroke_width=mask_data['stroke_width'],
                                )
                            )
                        for r in elem_rects:
                            all_objects.append(
                                fabric.rect_to_fabric(
                                    r[0], r[1], r[2], r[3],
                                    sr_type='mueble',
                                    color=mask_data['stroke'],
                                    stroke_width=mask_data['stroke_width'],
                                )
                            )
                        debug[f'{elem_type}_circles'] = len(elem_circles)
                        debug[f'{elem_type}_rects'] = len(elem_rects)

                # adelgazar a 1px para que Hough no detecte bordes dobles
                src = lines.skeletonize(binary)
                # líneas finas (muebles, puertas) necesitan min_length más bajo
                hough_min = self.config['hough_min_length']
                hough_gap = self.config['hough_max_gap']
                if elem_type != 'pared':
                    hough_min = max(15, hough_min - 10)
                raw = lines.detect_lines_hough(
                    src,
                    min_length=hough_min,
                    max_gap=hough_gap,
                )

                # paredes: usar clasificación H/V estricta para el grafo
                # puertas/vanos/muebles: usar todos los segmentos (trazos finos y temblorosos)
                if elem_type == 'pared':
                    h, v, _ = lines.classify_lines(raw, angle_tolerance=5)
                    h = lines.merge_colinear(
                        h,
                        angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=self.config['min_segment_length'],
                    )
                    v = lines.merge_colinear(
                        v,
                        angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=self.config['min_segment_length'],
                    )
                    # guardar antes de extender para detección de vanos
                    wall_h_pre_extend = list(h)
                    wall_v_pre_extend = list(v)
                    h, v = lines.extend_to_intersections(
                        h, v, max_extend=self.config['extend_max'],
                    )
                    h = lines.merge_colinear(
                        h, angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=self.config['min_segment_length'],
                    )
                    v = lines.merge_colinear(
                        v, angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=self.config['min_segment_length'],
                    )
                    # recortar colgajos que se pasan de las esquinas
                    h, v = lines.trim_overshoots(h, v, margin=30)
                    # descartar muros flotantes (sombra del borde de la hoja,
                    # margen impreso) que no conectan con la estructura — ANTES
                    # de cerrar el contorno, para que no inflen el bounding box
                    kept = lines.drop_isolated_segments(h + v, tol=25)
                    h = [s for s in h if list(s) in [list(k) for k in kept]]
                    v = [s for s in v if list(s) in [list(k) for k in kept]]
                    # cerrar el contorno exterior como rectángulo (completa
                    # paredes exteriores demasiado tenues para detectarse)
                    h, v = lines.close_exterior(h, v)
                    h = lines.merge_colinear(
                        h, angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=self.config['min_segment_length'],
                    )
                    v = lines.merge_colinear(
                        v, angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=self.config['min_segment_length'],
                    )
                    wall_segments_h = h
                    wall_segments_v = v
                    wall_style = {
                        'stroke': mask_data['stroke'],
                        'stroke_width': mask_data['stroke_width'],
                    }
                    segs = h + v
                else:
                    # puertas/vanos/muebles: clasificar con tolerancia amplia
                    h, v, o = lines.classify_lines(raw, angle_tolerance=10)
                    seg_min_len = max(10, self.config['min_segment_length'] - 10)
                    h = lines.merge_colinear(
                        h,
                        angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=seg_min_len,
                    )
                    v = lines.merge_colinear(
                        v,
                        angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=seg_min_len,
                    )
                    if elem_type in ('puerta', 'vano'):
                        if elem_type == 'puerta':
                            door_segments_h = h
                            door_segments_v = v
                        else:
                            vano_segments_h = h
                            vano_segments_v = v
                    # muebles: conectar como las paredes (las divisiones rojas
                    # del croquis deben quedar como figuras limpias, no trazos
                    # sueltos colgando)
                    if elem_type == 'mueble':
                        h, v = lines.extend_to_intersections(
                            h, v, max_extend=200,
                        )
                        # margen amplio: recorta las colitas que sobresalen de
                        # las uniones en T (p.ej. el palo vertical que se pasa
                        # por encima del mostrador) para dejar figuras limpias
                        h, v = lines.trim_overshoots(h, v, margin=70)
                        # re-fusionar para colapsar bordes dobles tras extender
                        h = lines.merge_colinear(
                            h, angle_tol=self.config['merge_angle_tol'],
                            dist_tol=self.config['merge_dist_tol'],
                            gap_tol=self.config['merge_gap_tol'], min_len=seg_min_len,
                        )
                        v = lines.merge_colinear(
                            v, angle_tol=self.config['merge_angle_tol'],
                            dist_tol=self.config['merge_dist_tol'],
                            gap_tol=self.config['merge_gap_tol'], min_len=seg_min_len,
                        )
                        kept = lines.drop_isolated_segments(h + v, tol=25)
                        h = [s for s in h if list(s) in [list(k) for k in kept]]
                        v = [s for s in v if list(s) in [list(k) for k in kept]]
                        # quitar trazos que cuelgan → muebles como figuras limpias
                        pruned = lines.prune_dangling(h + v, tol=22)
                        pk = [list(k) for k in pruned]
                        h = [s for s in h if list(s) in pk]
                        v = [s for s in v if list(s) in pk]
                        # estirar extremos libres hasta la pared colineal cercana
                        # para que el mueble no quede "volando"
                        if wall_segments_h or wall_segments_v:
                            ext = lines.extend_free_ends_to_walls(
                                h + v, wall_segments_h, wall_segments_v,
                                max_reach=80,
                            )
                            h = [s for s in ext if lines._is_horizontal(np.array(s))]
                            v = [s for s in ext if not lines._is_horizontal(np.array(s))]
                    segs = h + v
                segs = lines.close_gaps(segs, gap_tol=self.config['close_gap_tol'])
                segs = lines.snap_to_grid(segs, grid_size=self.config['snap_grid'])
                clean_min = self.config['min_segment_length']
                if elem_type != 'pared':
                    clean_min = max(10, clean_min - 10)
                segs = lines._clean_short_segments(segs, min_len=clean_min)

                # descartar color fuera del área de paredes (logo del cuaderno,
                # margen impreso): solo nos interesa lo que está dentro del edificio
                if elem_type != 'pared' and (wall_segments_h or wall_segments_v):
                    wpts = wall_segments_h + wall_segments_v
                    xs = [c for s in wpts for c in (s[0], s[2])]
                    ys = [c for s in wpts for c in (s[1], s[3])]
                    wbb = (min(xs), min(ys), max(xs), max(ys))
                    segs = lines.filter_within_bbox(segs, wbb, margin=30)
                    # pegar puertas/vanos a la pared cercana para que la corten
                    # (sin esto, al cerrar el contorno la puerta de salida queda
                    # flotando justo afuera de la pared)
                    if elem_type in ('puerta', 'vano'):
                        segs = lines.snap_segments_to_walls(
                            segs, wall_segments_h, wall_segments_v, tol=35,
                        )

                all_segments[elem_type] = segs
                elem_styles[elem_type] = {
                    'stroke': mask_data['stroke'],
                    'stroke_width': mask_data['stroke_width'],
                    'sr_type': mask_data['sr_type'],
                }

                # Paredes, puertas y vanos se generan DESPUÉS del bucle: las
                # puertas se filtran (solo las que están sobre un muro) y las
                # paredes se cortan donde caen las puertas (hueco real). Para
                # eso necesitamos todos los segmentos estructurales primero.
                if elem_type in ('pared', 'puerta', 'vano'):
                    debug[f'{elem_type}_segments'] = len(segs)
                    continue

                # convertir a objetos Fabric.js
                objs = fabric.segments_to_fabric_lines(
                    segs,
                    sr_type=mask_data['sr_type'],
                    color=mask_data['stroke'],
                    stroke_width=mask_data['stroke_width'],
                )
                all_objects.extend(objs)
                debug[f'{elem_type}_segments'] = len(segs)

            debug['total_segments'] = sum(len(v) for v in all_segments.values())

            # ── Etapa 4: Detección de recintos ──────────────────
            logger.info('Detectando recintos...')

            room_list = []
            if wall_segments_h or wall_segments_v:
                # forzar grid y cerrar gaps para que el grafo sea preciso
                segs = wall_segments_h + wall_segments_v
                segs = lines.snap_to_grid(segs, grid_size=self.config['snap_grid'])
                segs = lines.close_gaps(segs, gap_tol=20)
                segs = lines._clean_short_segments(segs, min_len=self.config['min_segment_length'])
                sh = [s for s in segs if lines._is_horizontal(s)]
                sv = [s for s in segs if not lines._is_horizontal(s)]
                graph = rooms.build_intersection_graph(sh, sv)
                room_list = rooms.find_rooms(
                    graph,
                    min_area=self.config['room_min_area'],
                    max_area=self.config['room_max_area'],
                )
                debug['graph_nodes'] = len(graph['points'])
                debug['rooms_found'] = len(room_list)

                # ── Detectar puertas desde gaps en muros ────────────
                door_binary = masks.get('puerta', {}).get('binary')
                door_gaps = lines.find_wall_gaps(
                    wall_h_pre_extend, wall_v_pre_extend,
                    door_mask=door_binary,
                )
                debug['door_gaps'] = len(door_gaps)

                zone_objs = fabric.rooms_to_fabric_zones(room_list)
                all_objects[:0] = zone_objs  # zonas al fondo

            # ── Etapa 4b: Filtrar puertas y cortar paredes ──────
            # 1) descartar puertas que no están sobre un muro (flotando dentro
            #    de un recinto) o que son fragmentos diminutos.
            # 2) cortar las paredes donde caen las puertas para dejar un HUECO
            #    real (no la puerta encima de una pared continua) y que las
            #    rutas de evacuación crucen por la abertura.
            # Se hace tras detectar recintos (que necesitan los muros completos).
            # Primero cerrar micro-gaps en las uniones en T (p.ej. el muro
            # horizontal que queda a 7px del muro central) para que las uniones
            # existan y el recorte de puertas/paredes las respete.
            snapped = lines.close_gaps(
                wall_segments_h + wall_segments_v, gap_tol=20,
            )
            wall_segments_h = [s for s in snapped
                               if lines._is_horizontal(np.array(s))]
            wall_segments_v = [s for s in snapped
                               if not lines._is_horizontal(np.array(s))]
            for dtype in ('puerta', 'vano'):
                if dtype not in all_segments:
                    continue
                kept = lines.keep_doors_on_walls(
                    all_segments[dtype], wall_segments_h, wall_segments_v,
                )
                # acortar puertas que cruzan una unión en T (se ven feas y
                # rompen la esquina del muro perpendicular)
                kept = lines.clamp_doors_to_junctions(
                    kept, wall_segments_h, wall_segments_v,
                )
                all_segments[dtype] = kept
                st = elem_styles.get(dtype, {})
                door_objs = fabric.segments_to_fabric_lines(
                    kept,
                    sr_type=st.get('sr_type', dtype),
                    color=st.get('stroke', '#000000'),
                    stroke_width=st.get('stroke_width', 3),
                )
                all_objects.extend(door_objs)

            door_segs = (all_segments.get('puerta', [])
                         + all_segments.get('vano', []))
            wh, wv = wall_segments_h, wall_segments_v
            if door_segs:
                wh, wv = lines.cut_walls_at_doors(wh, wv, door_segs)
            wall_objs = fabric.segments_to_fabric_lines(
                wh + wv,
                sr_type='pared',
                color=wall_style['stroke'],
                stroke_width=wall_style['stroke_width'],
            )
            all_objects.extend(wall_objs)

            # ── Etapa 5: JSON Fabric.js ────────────────────────
            logger.info('Generando JSON Fabric.js...')
            canvas_data = fabric.build_canvas_json(
                all_objects, [],
                doc_w=self.config['target_w'],
                doc_h=self.config['target_h'],
            )

            debug['fabric_objects_count'] = len(canvas_data['objects'])

            logger.info(
                'Pipeline completado: %d objetos, %d recintos',
                len(all_objects), len(room_list),
            )

            return {
                'success': True,
                'canvas_data': canvas_data,
                'walls': len(all_segments.get('pared', [])),
                'doors': len(all_segments.get('puerta', [])),
                'furniture': len(all_segments.get('mueble', [])),
                'rooms': len(room_list),
                'error': None,
                'debug': debug,
            }

        except Exception as e:
            logger.exception('Error en pipeline de procesamiento')
            return self._error(str(e))

    def _orient_exit_right(self, image):
        """Rota el plano para que la salida principal quede a la derecha.

        La salida principal = la puerta (azul) más grande, que es la que da a
        la calle. Se detecta en qué lado del edificio está y se rota la imagen
        en múltiplos de 90° para llevar ese lado a la derecha. Como efecto
        secundario, un plano vertical suele quedar horizontal y llenar mejor
        la página. Devuelve (imagen_rotada, grados_rotados)."""
        try:
            masks = preprocessing.segment_by_color(image, sensitivity=self.config['sensitivity'])
        except Exception:
            return image, 0

        door = masks.get('puerta', {}).get('binary')
        wall = masks.get('pared', {}).get('binary')
        if door is None or cv2.countNonZero(door) < 50:
            return image, 0

        # centro de referencia: bbox de las paredes (o de la imagen)
        if wall is not None and cv2.countNonZero(wall) > 0:
            ys, xs = np.where(wall > 0)
            wx1, wy1, wx2, wy2 = xs.min(), ys.min(), xs.max(), ys.max()
        else:
            wy1, wx1 = 0, 0
            wy2, wx2 = image.shape[0], image.shape[1]
        bx, by = (wx1 + wx2) / 2, (wy1 + wy2) / 2
        half_w = max((wx2 - wx1) / 2, 1)
        half_h = max((wy2 - wy1) / 2, 1)

        # La salida principal = puerta grande Y exterior (la única forma de
        # salir). Puntúa cada puerta por área × (1 + qué tan cerca está del
        # perímetro del edificio), para no elegir una puerta interior aunque
        # sea ancha.
        n, labels, stats, cents = cv2.connectedComponentsWithStats(door, 8)
        if n <= 1:
            return image, 0
        best_idx, best_score = -1, -1.0
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < 30:
                continue
            dcx, dcy = cents[i]
            outward = max(abs(dcx - bx) / half_w, abs(dcy - by) / half_h)  # 0=centro 1=borde
            score = area * (1.0 + 1.5 * outward)
            if score > best_score:
                best_score, best_idx = score, i
        if best_idx < 0:
            return image, 0
        cx, cy = cents[best_idx]

        dx, dy = cx - bx, cy - by
        # lado donde está la salida
        if abs(dx) >= abs(dy):
            side = 'right' if dx > 0 else 'left'
        else:
            side = 'bottom' if dy > 0 else 'top'

        # rotación para llevar ese lado a la derecha
        if side == 'right':
            return image, 0
        if side == 'left':
            return cv2.rotate(image, cv2.ROTATE_180), 180
        if side == 'bottom':
            return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE), 90
        # top
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE), 270

    def _error(self, msg):
        return {
            'success': False,
            'canvas_data': None,
            'walls': 0,
            'doors': 0,
            'furniture': 0,
            'rooms': 0,
            'error': msg,
            'debug': {},
        }
