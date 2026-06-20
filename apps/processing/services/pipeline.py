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
            'target_w': 1320,
            'target_h': 864,
            'hough_min_length': 30,
            'hough_max_gap': 15,
            'merge_angle_tol': 3,
            'merge_dist_tol': 20,
            'merge_gap_tol': 40,
            'extend_max': 400,
            'close_gap_tol': 20,
            'snap_grid': 10,
            'min_segment_length': 25,
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

            # ── Etapa 1: Corrección de perspectiva ────────────
            image = preprocessing.correct_perspective(image)

            # ── Etapa 2: Segmentación por color ───────────────
            logger.info('Segmentando por color...')
            masks = preprocessing.segment_by_color(image)
            masks = preprocessing.resize_mask_to_canvas(
                masks, self.config['target_w'], self.config['target_h'],
            )

            debug['segments'] = {k: cv2.countNonZero(v['binary']) for k, v in masks.items()}

            # ── Etapa 3: Detección de líneas por tipo ─────────
            all_objects = []  # objetos Fabric.js de todos los tipos
            all_segments = {}
            wall_segments_h = []
            wall_segments_v = []
            door_segments_h = []
            door_segments_v = []
            vano_segments_h = []
            vano_segments_v = []

            for elem_type, mask_data in masks.items():
                binary = mask_data['binary']
                if cv2.countNonZero(binary) < 100:
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

                # solo aplicar skeletonize a trazos gruesos (paredes)
                # puertas, vanos y muebles ya son líneas finas
                if mask_data.get('stroke_width', 8) >= 5:
                    src = lines.skeletonize(binary)
                else:
                    src = binary
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
                    wall_segments_h = h
                    wall_segments_v = v
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
                    segs = h + v
                segs = lines.close_gaps(segs, gap_tol=self.config['close_gap_tol'])
                segs = lines.snap_to_grid(segs, grid_size=self.config['snap_grid'])
                clean_min = self.config['min_segment_length']
                if elem_type != 'pared':
                    clean_min = max(10, clean_min - 10)
                segs = lines._clean_short_segments(segs, min_len=clean_min)

                all_segments[elem_type] = segs

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
                for g in door_gaps:
                    all_objects.append({
                        'type': 'rect',
                        'version': '5.3.1',
                        'originX': 'left',
                        'originY': 'top',
                        'left': float(g['x'] - g['width'] / 2),
                        'top': float(g['y'] - g['height'] / 2),
                        'width': float(g['width']),
                        'height': float(g['height']),
                        'fill': '#ffffff',
                        'stroke': '#000000',
                        'strokeWidth': 3,
                        'srType': 'puerta',
                        'srCat': 'shape',
                        'selectable': True,
                        'evented': True,
                        'hasControls': True,
                        'hasBorders': True,
                    })
                debug['door_gaps'] = len(door_gaps)

                zone_objs = fabric.rooms_to_fabric_zones(room_list)
                all_objects[:0] = zone_objs  # zonas al fondo

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
