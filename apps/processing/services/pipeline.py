"""Pipeline principal de procesamiento de imágenes — Híbrido OpenCV + ML.

Orquesta las etapas de:
1. Preprocesamiento (perspectiva, CLAHE, binarización)
2. Segmentación: ML (U-Net) si hay modelo, si no clustering adaptativo
3. Detección de líneas: LSD (preferido) o skeletonize + Hough
4. Fusión de segmentos (merge colineal, extender, cerrar gaps, snap)
5. Detección de recintos (grafo planar, ciclos)
6. Detección de símbolos (YOLO, si está disponible)
7. Generación de JSON Fabric.js

Cada tipo de elemento se procesa por separado usando su máscara
de segmentación, lo que permite diferenciar paredes, puertas,
muebles y vanos.
"""

import cv2
import numpy as np
import logging
from pathlib import Path

from . import preprocessing
from . import lines
from . import rooms
from . import fabric

logger = logging.getLogger(__name__)

try:
    from sklearn.cluster import DBSCAN
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

# Intentar importar ML, pero no fallar si no está
try:
    from .ml.predict import segment_image, masks_to_elements
    HAS_ML = True
except ImportError:
    HAS_ML = False
    logger.info('Módulo ML no disponible, usando solo OpenCV')

try:
    from .ml.detector import get_detector
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False
    logger.info('YOLO no disponible, omitiendo detección de símbolos')


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
            'extend_max': 300,
            'close_gap_tol': 20,
            'snap_grid': 10,
            'min_segment_length': 25,
            'room_min_area': 5000,
            'room_max_area': 500000,
            # híbrido
            'use_lsd': True,             # LSD en vez de Hough cuando sea posible
            'use_clustering': True,      # k-means adaptativo vs HSV fijo
            'use_ml_segmentation': True, # U-Net si el modelo está disponible
            'use_yolo': True,            # YOLO para símbolos
            'n_clusters': 5,             # clusters para k-means
            # foto preprocessing
            'binarize_method': 'sauvola', # sauvola | adaptive | otsu | dog
            'use_bilateral': True,       # filtro bilateral pre-binarización
            'use_stroke_filter': True,   # filtrar por ancho de trazo
            'bilateral_d': 7,
            'bilateral_sigma_color': 50,
            'bilateral_sigma_space': 50,
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

            # ── Etapa 1: Preprocesamiento para fotos ────────────
            image = preprocessing.correct_perspective(image)
            gray = preprocessing.grayscale(image)
            gray = preprocessing.enhance_contrast(gray)

            # filtro bilateral para reducir textura del papel
            if self.config['use_bilateral']:
                gray = preprocessing.bilateral_filter(
                    gray,
                    d=self.config['bilateral_d'],
                    sigma_color=self.config['bilateral_sigma_color'],
                    sigma_space=self.config['bilateral_sigma_space'],
                )

            # binarización adaptativa (Sauvola para fotos)
            binary = preprocessing.binarize(gray, method=self.config['binarize_method'])

            # filtrar por forma de trazo (elimina sombras/manchas)
            if self.config['use_stroke_filter']:
                binary = preprocessing.stroke_confidence_filter(binary)

            binary = preprocessing.denoise(binary)
            stroke_binary = binary.copy()

            # ── Etapa 2: Segmentación ───────────────────────────
            masks = None

            # 2a: intentar ML (U-Net) si está disponible y habilitado
            if self.config['use_ml_segmentation'] and HAS_ML:
                logger.info('Intentando segmentación con ML...')
                ml_masks = segment_image(image)
                if ml_masks is not None:
                    masks = {}
                    for name, mask in ml_masks.items():
                        cfg = preprocessing.COLOR_MAP.get(name, {})
                        masks[name] = {
                            'binary': mask,
                            'stroke': cfg.get('stroke', '#000000'),
                            'stroke_width': cfg.get('stroke_width', 3),
                            'sr_type': name,
                        }
                    debug['segmentation_method'] = 'ml'

            # 2b: detectar si la imagen es a color o monocroma
            if masks is None:
                is_color = _has_color_info(image)
                debug['has_color'] = is_color

                if is_color:
                    logger.info('Imagen a color, usando clustering/color')
                    masks = preprocessing.segment_by_color_or_clustering(
                        image,
                        use_clustering=self.config['use_clustering'],
                        n_clusters=self.config['n_clusters'],
                    )
                    debug['segmentation_method'] = 'clustering' if self.config['use_clustering'] else 'color_hsv'
                else:
                    logger.info('Imagen monocroma, separando por ancho de trazo')
                    masks = preprocessing.build_masks_from_strokes(
                        binary,
                        stroke_config={'thick_threshold': 4},
                    )
                    debug['segmentation_method'] = 'stroke_width'

            # redimensionar máscaras al canvas
            masks = preprocessing.resize_mask_to_canvas(
                masks, self.config['target_w'], self.config['target_h'],
            )
            debug['segments_px'] = {
                k: int(cv2.countNonZero(v['binary']))
                for k, v in masks.items()
            }
            wall_binary = masks.get('pared', {}).get('binary')

            # Guardar imagen a color redimensionada para filtrar segmentos por color
            image_resized = cv2.resize(
                image, (self.config['target_w'], self.config['target_h']),
            )

            # ── Etapa 3: Detección de líneas por tipo ─────────
            all_objects = []
            all_segments = {}
            wall_segments_h = []
            wall_segments_v = []
            wall_h_gap_raw = []
            wall_v_gap_raw = []
            door_segments_h = []
            door_segments_v = []
            vano_segments_h = []
            vano_segments_v = []

            line_config = {
                'method': 'lsd' if self.config['use_lsd'] else 'auto',
                'min_length': self.config['hough_min_length'],
                'max_gap': self.config['hough_max_gap'],
            }

            for elem_type, mask_data in masks.items():
                binary = mask_data['binary']
                if cv2.countNonZero(binary) < 100:
                    logger.debug('Tipo %s: muy pocos píxeles, saltando', elem_type)
                    continue

                logger.info('Procesando %s...', elem_type)

                # ── Detectar formas (círculos y rectángulos) ─────
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

                # Detectar segmentos: usar gray original (no binarizada) para LSD
                # o skeletonize + Hough como fallback
                cfg = dict(line_config)
                if elem_type != 'pared':
                    cfg['min_length'] = max(15, cfg['min_length'] - 10)

                # Para LSD usamos la imagen gray (necesita grises),
                # para Hough usamos la binaria skeletonizada
                gray_resized = cv2.resize(
                    gray, (self.config['target_w'], self.config['target_h']),
                )
                raw = lines.detect_segments(gray_resized, binary, cfg)
                raw = _filter_segments_by_color(
                    raw, image_resized,
                    elem_type, masks,
                    stroke_binary=stroke_binary,
                )

                # paredes: usar clasificación H/V estricta para el grafo
                # puertas/vanos/muebles: usar todos los segmentos
                if elem_type == 'pared':
                    h, v, _ = lines.classify_lines(raw, angle_tolerance=15)
                    # guardar RAW (sin merge) para detección de vanos
                    wall_h_gap_raw = list(h)
                    wall_v_gap_raw = list(v)
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
                    # Refinar: agrupar paralelas cercanas y extender a esquinas
                    wall_segments_h, wall_segments_v = lines.refine_wall_segments(
                        wall_segments_h, wall_segments_v,
                        snap_y=12, snap_x=13,
                    )
                    segs = wall_segments_h + wall_segments_v
                else:
                    h, v, o = lines.classify_lines(raw, angle_tolerance=10)
                    seg_min_len = max(10, self.config['min_segment_length'] - 10)
                    h = lines.merge_colinear(
                        h, angle_tol=self.config['merge_angle_tol'],
                        dist_tol=self.config['merge_dist_tol'],
                        gap_tol=self.config['merge_gap_tol'],
                        min_len=seg_min_len,
                    )
                    v = lines.merge_colinear(
                        v, angle_tol=self.config['merge_angle_tol'],
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

                # Filtrar puertas lejos de cualquier pared
                # (anotaciones/labels en azul fuera del plano)
                if elem_type == 'puerta' and (wall_segments_h or wall_segments_v):
                    wall_segs = wall_segments_h + wall_segments_v
                    before = len(segs)
                    filtered = []
                    for s in segs:
                        mx, my = (s[0] + s[2]) / 2, (s[1] + s[3]) / 2
                        min_dist = min(
                            lines.point_to_segment_distance(mx, my, ws[0], ws[1], ws[2], ws[3])
                            for ws in wall_segs
                        )
                        if min_dist <= 60:
                            filtered.append(s)
                    segs = filtered
                    logger.info('Filtro dist pared: %d → %d puertas', before, len(segs))

                segs = lines.close_gaps(segs, gap_tol=self.config['close_gap_tol'])
                if elem_type == 'puerta':
                    # Las puertas deben tener tamaño realista (25-120px)
                    segs = [s for s in segs
                            if 25 <= max(abs(s[2]-s[0]), abs(s[3]-s[1])) <= 120]
                segs = lines.snap_to_grid(segs, grid_size=self.config['snap_grid'])
                clean_min = self.config['min_segment_length']
                if elem_type != 'pared':
                    clean_min = max(10, clean_min - 10)
                segs = lines._clean_short_segments(segs, min_len=clean_min)

                all_segments[elem_type] = segs

                if elem_type == 'mueble':
                    # Muebles: agrupar segmentos por proximidad y mostrar
                    # un bounding box por pieza, no líneas individuales
                    mueble_objs = _cluster_furniture_as_objects(
                        segs,
                        color=mask_data['stroke'],
                        stroke_width=mask_data['stroke_width'],
                    )
                    all_objects.extend(mueble_objs)
                else:
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
                segs = wall_segments_h + wall_segments_v
                segs = lines.snap_to_grid(segs, grid_size=self.config['snap_grid'])
                segs = lines.deduplicate_parallel_walls(segs, h_tol=12, v_tol=10)
                segs = lines.close_gaps(segs, gap_tol=20)
                segs = lines._clean_short_segments(segs, min_len=self.config['min_segment_length'])

                # Añadir muros virtuales para cerrar recintos abiertos al borde
                sh_pre = [s for s in segs if lines._is_horizontal(s)]
                sv_pre = [s for s in segs if not lines._is_horizontal(s)]
                if sh_pre and sv_pre:
                    all_pts = []
                    for s in sh_pre + sv_pre:
                        all_pts.append((s[0], s[1]))
                        all_pts.append((s[2], s[3]))
                    xs = [p[0] for p in all_pts]
                    ys = [p[1] for p in all_pts]
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    # Extender el muro horizontal superior hasta max_x
                    top_hs = sorted([s for s in sh_pre if abs(s[1] - min_y) < 15],
                                    key=lambda s: abs(s[2] - s[0]), reverse=True)
                    if top_hs and top_hs[0][2] < max_x - 30:
                        s = list(top_hs[0])
                        s[2] = max_x
                        segs.append(tuple(s))
                    # Extender el muro horizontal inferior hasta max_x
                    bot_hs = sorted([s for s in sh_pre if abs(s[1] - max_y) < 15],
                                    key=lambda s: abs(s[2] - s[0]), reverse=True)
                    if bot_hs and bot_hs[0][2] < max_x - 30:
                        s = list(bot_hs[0])
                        s[2] = max_x
                        segs.append(tuple(s))
                    # Añadir muro vertical virtual en max_x, de min_y a max_y
                    segs.append((max_x, min_y, max_x, max_y))

                sh = [s for s in segs if lines._is_horizontal(s)]
                sv = [s for s in segs if not lines._is_horizontal(s)]
                graph = rooms.build_intersection_graph(sh, sv, wall_binary=wall_binary)
                room_list = rooms.find_rooms(
                    graph,
                    min_area=self.config['room_min_area'],
                    max_area=self.config['room_max_area'],
                )
                debug['graph_nodes'] = len(graph['points'])

                # Si el grafo no alcanza los recintos esperados, construir
                # una máscara gruesa desde los segmentos de pared fusionados
                # y detectar recintos por contornos.
                if len(room_list) < 4 and sh and sv:
                    thick = np.zeros(
                        (self.config['target_h'], self.config['target_w']),
                        dtype=np.uint8,
                    )
                    for s in sh + sv:
                        x1, y1, x2, y2 = [int(v) for v in s]
                        cv2.line(thick, (x1, y1), (x2, y2), 255, thickness=8)
                    # cerrar vanos de puertas
                    closed = cv2.morphologyEx(
                        thick, cv2.MORPH_CLOSE,
                        np.ones((25, 25), np.uint8),
                    )
                    closed = cv2.dilate(closed, np.ones((5, 5), np.uint8), iterations=2)
                    contour_rooms = rooms._find_rooms_from_contours(
                        closed,
                        min_area=self.config['room_min_area'],
                        max_area=self.config['room_max_area'],
                    )
                    if len(contour_rooms) > len(room_list):
                        logger.info(
                            'Recintos por contornos: %d (grafo: %d)',
                            len(contour_rooms), len(room_list),
                        )
                        room_list = contour_rooms

                # segmentos pre-merge para detectar gaps (antes de que merge_colinear los cierre)
                gap_h = wall_h_gap_raw
                gap_v = wall_v_gap_raw
                door_binary = masks.get('puerta', {}).get('binary')
                door_gaps = lines.find_wall_gaps(
                    gap_h, gap_v,
                    door_mask=door_binary,
                    min_gap=15,
                    max_gap=200,
                )
                # Filtrar gaps: puertas deben tener al menos 25px de vano
                # y no más de 120px (evitar falsos positivos por paredes
                # paralelas que quedan como "gaps" anchos/angostos)
                door_gaps = [
                    g for g in door_gaps
                    if 25 <= (g['width'] if g['width'] >= g['height'] else g['height']) <= 120
                ]
                debug['door_gaps'] = len(door_gaps)

                # convertir gaps detectados en objetos puerta
                for g in door_gaps:
                    door_obj = fabric._make_door_from_gap(g)
                    if door_obj:
                        all_objects.append(door_obj)

                # Deduplicar puertas: si hay objetos puerta con centro
                # muy cercano (< 30px), conservar solo el primero
                door_objs = [
                    i for i, o in enumerate(all_objects)
                    if o.get('srType') == 'puerta'
                ]
                keep = set(range(len(all_objects)))
                for i in range(len(door_objs)):
                    for j in range(i + 1, len(door_objs)):
                        idx_i = door_objs[i]
                        idx_j = door_objs[j]
                        oi = all_objects[idx_i]
                        oj = all_objects[idx_j]
                        cxi = oi.get('srGapX', oi.get('left', 0))
                        cyi = oi.get('srGapY', oi.get('top', 0))
                        cxj = oj.get('srGapX', oj.get('left', 0))
                        cyj = oj.get('srGapY', oj.get('top', 0))
                        dist = np.hypot(cxi - cxj, cyi - cyj)
                        if dist < 30:
                            keep.discard(idx_j)
                # Filtrar puertas cuyo tamaño renderizado supere 120px
                for idx in list(keep):
                    o = all_objects[idx]
                    if o.get('srType') == 'puerta':
                        pw = o.get('width', 0)
                        ph = o.get('height', 0)
                        if max(pw, ph) > 120:
                            keep.discard(idx)
                all_objects = [all_objects[i] for i in sorted(keep)]

                zone_objs = fabric.rooms_to_fabric_zones(room_list)
                all_objects[:0] = zone_objs

            # ── Etapa 5: Detección de símbolos (YOLO) ──────────
            if self.config['use_yolo'] and HAS_YOLO:
                logger.info('Detectando símbolos con YOLO...')
                try:
                    detector = get_detector()
                    if detector.is_loaded():
                        symbols = detector.detect(image)
                        debug['symbols_found'] = len(symbols)
                        for sym in symbols:
                            obj = fabric.symbol_to_fabric(sym)
                            if obj:
                                all_objects.append(obj)
                    else:
                        debug['symbols_found'] = 0
                        debug['yolo_error'] = 'modelo no cargado'
                except Exception as e:
                    logger.warning('Error en detección YOLO: %s', e)
                    debug['symbols_found'] = 0
                    debug['yolo_error'] = str(e)

            # ── Etapa 6: JSON Fabric.js ────────────────────────
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

            # Agrupar muebles por proximidad (forma, no líneas individuales)
            mueble_segs = all_segments.get('mueble', [])
            mueble_rect_count = debug.get('mueble_rects', 0)
            mueble_circle_count = debug.get('mueble_circles', 0)
            furniture_count = mueble_rect_count + mueble_circle_count
            if mueble_segs:
                furniture_count += _cluster_furniture_items(mueble_segs)

            return {
                'success': True,
                'canvas_data': canvas_data,
                'walls': len(all_segments.get('pared', [])),
                'doors': len([o for o in all_objects if o.get('srType') == 'puerta']),
                'furniture': furniture_count,
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


def _cluster_furniture_items(segments, eps=100):
    """Agrupa segmentos de mueble por proximidad y devuelve el número
    estimado de piezas (formas), no de líneas individuales.

    Cada cluster de segmentos cercanos se considera una pieza.
    """
    if not segments:
        return 0
    pts = np.array([[(s[0] + s[2]) / 2, (s[1] + s[3]) / 2] for s in segments])
    if not HAS_SKLEARN or len(pts) < 2:
        return len(segments)
    clustering = DBSCAN(eps=eps, min_samples=1).fit(pts)
    return len(set(clustering.labels_))


def _cluster_furniture_as_objects(segments, color='#000000', stroke_width=8):
    """Agrupa segmentos de mueble por proximidad y genera un rectángulo
    Fabric.js por cada cluster (pieza de mobiliario)."""
    if not segments:
        return []
    pts = np.array([[(s[0] + s[2]) / 2, (s[1] + s[3]) / 2] for s in segments])
    if HAS_SKLEARN and len(pts) >= 2:
        clustering = DBSCAN(eps=100, min_samples=1).fit(pts)
        labels = clustering.labels_
    else:
        labels = np.zeros(len(segments), dtype=int)

    objects = []
    for label in set(labels):
        idxs = np.where(labels == label)[0]
        cluster_segs = [segments[i] for i in idxs]
        xs = []
        ys = []
        for s in cluster_segs:
            xs.extend([s[0], s[2]])
            ys.extend([s[1], s[3]])
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        if (x_max - x_min) < 10 and (y_max - y_min) < 10:
            continue  # muy pequeño, probable ruido
        obj = fabric.rect_to_fabric(
            x_min, y_min, x_max - x_min, y_max - y_min,
            sr_type='mueble', color=color, stroke_width=max(2, stroke_width // 2),
        )
        if obj:
            objects.append(obj)
    return objects


def _filter_segments_by_color(segments, image_bgr, elem_type, all_masks, stroke_binary=None):
    """Clasifica segmentos por color y devuelve solo los que pertenecen al tipo.

    Para cada segmento muestrea píxeles a lo largo de su trayectoria y
    cuenta en qué máscara de color cae cada píxel. El segmento se asigna
    al tipo con MÁS coincidencias, y se conserva si ese tipo es elem_type.

    Usa máscaras dilatadas para tolerar el desplazamiento de LSD respecto
    al centro del trazo real (1-3px).

    Args:
        segments: lista de segmentos [x1, y1, x2, y2]
        image_bgr: imagen a color redimensionada — no usado directamente
        elem_type: tipo de elemento actual ('pared', 'mueble', etc.)
        all_masks: dict de máscaras de color (con 'binary' por tipo)
        stroke_binary: máscara binaria de trazos (opcional, para determinar
            si un píxel es trazo dibujado o fondo)

    Returns:
        lista de segmentos clasificados como elem_type
    """
    if not segments:
        return segments

    first_mask = next((d['binary'] for d in all_masks.values() if d.get('binary') is not None), None)
    if first_mask is None:
        return segments
    h, w = first_mask.shape[:2]

    # Dilatar máscaras para tolerancia de borde (más iteraciones para
    # 'pared' porque las líneas de muro son muy finas y LSD puede
    # estar desplazado varios píxeles)
    kernel = np.ones((3, 3), np.uint8)
    dilated = {}
    for tname, data in all_masks.items():
        m = data.get('binary')
        if m is not None:
            iters = 6 if tname == 'pared' else 3
            dilated[tname] = cv2.dilate(m, kernel, iterations=iters)

    if stroke_binary is not None:
        stroke_binary = cv2.resize(stroke_binary, (w, h))

    filtered = []
    for s in segments:
        x1, y1, x2, y2 = [int(v) for v in s]
        length = max(abs(x2 - x1), abs(y2 - y1))
        if length < 2:
            continue

        n_samples = min(length, 16)
        votes = {}       # tipo -> recuento
        stroke_pixels = 0

        for t in np.linspace(0, 1, n_samples):
            px = int(x1 + t * (x2 - x1))
            py = int(y1 + t * (y2 - y1))
            if not (0 <= px < w and 0 <= py < h):
                continue

            # Si tenemos stroke_binary, ignorar píxeles que no son
            # trazo dibujado (ruido / fondo claro).
            if stroke_binary is not None and stroke_binary[py, px] == 0:
                # Si el pixel NO es trazo ni cae en mascara de color,
                # no lo contamos como voto negativo
                in_any_mask = False
                for dmask in dilated.values():
                    if dmask[py, px] > 0:
                        in_any_mask = True
                        break
                if not in_any_mask:
                    continue
            stroke_pixels += 1

            for tname, dmask in dilated.items():
                if dmask[py, px] > 0:
                    votes[tname] = votes.get(tname, 0) + 1
                    break

        if not votes:
            continue

        best_type = max(votes, key=votes.get)
        if best_type == elem_type:
            # Para muebles, requerir al menos 40% de los votos
            # (para evitar que bordes lejanos se clasifiquen como mueble)
            total = sum(votes.values())
            if elem_type == 'mueble' and votes[elem_type] / total < 0.4:
                continue
            filtered.append(s)

    return filtered


def _has_color_info(bgr_image, saturation_threshold=30, min_colored_px=0.01):
    """Detecta si una imagen tiene información de color significativa.

    Usa el canal de saturación de HSV: píxeles con saturación alta
    son colores reales; los grises/negros/blancos tienen baja saturación.

    Esto es más robusto que la desviación RGB porque resiste
    artefactos JPEG y ruido de cámara.

    Args:
        bgr_image: imagen en BGR
        saturation_threshold: umbral de saturación HSV (0-255)
            para considerar un píxel como coloreado (default 30)
        min_colored_px: fracción mínima de píxeles coloreados para
            considerar la imagen como "a color" (default 0.5%)

    Returns:
        True si la imagen tiene color significativo
    """
    h, w = bgr_image.shape[:2]
    if h * w == 0:
        return False

    hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1].astype(np.int32)
    colored = (saturation > saturation_threshold).sum()
    ratio = colored / (h * w)
    return ratio > min_colored_px
