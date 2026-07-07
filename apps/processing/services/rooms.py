import cv2
import numpy as np
from collections import defaultdict


def build_intersection_graph(horizontals, verticals, snap_dist=15, wall_binary=None):
    """Construye un grafo planar de segmentos de pared.

    Nodos: puntos extremos e intersecciones de segmentos.
    Aristas: subsegmentos entre nodos consecutivos.

    Esto forma la base para detectar recintos cerrados como ciclos
    en el grafo."""
    segments = horizontals + verticals

    # coleccionar todos los puntos de interseccion
    points = set()
    seg_intersections = defaultdict(list)

    for i, seg in enumerate(segments):
        x1, y1, x2, y2 = seg
        points.add((round(x1), round(y1)))
        points.add((round(x2), round(y2)))

        for j, other in enumerate(segments):
            if i == j:
                continue
            pt = _segment_intersection(seg, other)
            if pt:
                px, py = pt
                # verificar que el punto esta dentro de ambos segmentos
                if _point_on_segment(px, py, seg, tol=5) and _point_on_segment(px, py, other, tol=5):
                    rpt = (round(px), round(py))
                    points.add(rpt)
                    seg_intersections[i].append(rpt)
                    seg_intersections[j].append(rpt)

    # construir aristas: partir cada segmento en subsegmentos por intersecciones
    edges = []
    point_index = {p: i for i, p in enumerate(points)}
    adjacency = defaultdict(set)

    for i, seg in enumerate(segments):
        x1, y1, x2, y2 = seg
        ips = seg_intersections.get(i, [])
        endpoints = [(round(x1), round(y1)), (round(x2), round(y2))]
        all_pts = endpoints + ips

        # ordenar puntos a lo largo del segmento
        if abs(x2 - x1) > abs(y2 - y1):
            all_pts = sorted(set(all_pts), key=lambda p: p[0])
        else:
            all_pts = sorted(set(all_pts), key=lambda p: p[1])

        for k in range(len(all_pts) - 1):
            p1 = all_pts[k]
            p2 = all_pts[k + 1]
            d = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if d < snap_dist:
                continue
            if p1 in point_index and p2 in point_index:
                idx1 = point_index[p1]
                idx2 = point_index[p2]
                adjacency[idx1].add(idx2)
                adjacency[idx2].add(idx1)
                edges.append((p1, p2))

    return {
        'points': list(points),
        'point_index': point_index,
        'edges': edges,
        'adjacency': adjacency,
        'wall_binary': wall_binary,
    }


def _segment_intersection(s1, s2):
    """Calcula intersección entre dos segmentos.

    Usa álgebra lineal para encontrar el punto de cruce entre dos líneas
    definidas por sus extremos."""
    x1, y1, x2, y2 = s1
    x3, y3, x4, y4 = s2

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-8:
        return None

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 <= t <= 1 and 0 <= u <= 1:
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        return (ix, iy)
    return None


def _point_on_segment(px, py, seg, tol=3):
    """Verifica si un punto está sobre un segmento con tolerancia."""
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    length = np.hypot(dx, dy)
    if length < 1:
        return False

    # distancia punto a línea
    dist = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / length

    # proyección a lo largo del segmento
    proj = ((px - x1) * dx + (py - y1) * dy) / (length * length)

    return dist < tol and -0.1 <= proj <= 1.1


def find_rooms(graph_data, min_area=5000, max_area=500000):
    """Detecta recintos cerrados encontrando ciclos en el grafo planar.

    Usa una estrategia de búsqueda de ciclos mínimos:
    1. Para cada nodo, explora aristas ordenadas por ángulo (sentido horario)
    2. Sigue la arista más a la derecha en cada bifurcación
    3. Cuando vuelve al inicio, tiene un recinto cerrado

    Esto funciona para planos arquitectónicos donde las paredes forman
    ciclos que representan habitaciones."""
    adjacency = graph_data['adjacency']
    points = graph_data['points']
    point_index = graph_data['point_index']

    if len(adjacency) < 3:
        return []

    index_to_point = {i: p for p, i in point_index.items()}

    # precalcular ángulos de las aristas para cada nodo
    node_angles = {}
    for node, neighbors in adjacency.items():
        angles = []
        px, py = index_to_point[node]
        for nb in neighbors:
            nx, ny = index_to_point[nb]
            angle = np.degrees(np.arctan2(ny - py, nx - px))
            angles.append((nb, angle))
        angles.sort(key=lambda x: x[1])
        node_angles[node] = angles

    visited_edges = set()
    rooms = []

    for start_node in adjacency:
        for next_node, _ in node_angles[start_node]:
            edge = (min(start_node, next_node), max(start_node, next_node))
            if edge in visited_edges:
                continue

            path = [start_node, next_node]
            current = next_node
            prev = start_node

            while current != start_node and len(path) < 1000:
                neighbors_with_angles = node_angles.get(current, [])
                if len(neighbors_with_angles) < 2:
                    break

                # encontrar el ángulo de la arista previa
                prev_p = index_to_point[prev]
                curr_p = index_to_point[current]
                entry_angle = np.degrees(np.arctan2(
                    prev_p[1] - curr_p[1], prev_p[0] - curr_p[0],
                ))

                # en sentido horario: siguiente arista después de la de entrada
                angles = node_angles[current]
                entry_idx = None
                for idx, (nb, ang) in enumerate(angles):
                    if nb == prev:
                        entry_idx = idx
                        break

                if entry_idx is None:
                    break

                next_idx = (entry_idx + 1) % len(angles)
                next_node = angles[next_idx][0]

                if next_node == start_node:
                    path.append(next_node)
                    break

                if next_node == prev:
                    break

                path.append(next_node)
                prev = current
                current = next_node

            if len(path) >= 4 and path[0] == path[-1]:
                polygon = [index_to_point[n] for n in path]
                area = _polygon_area(polygon)
                if min_area < area < max_area:
                    # filtrar recintos muy delgados
                    xs = [p[0] for p in polygon]
                    ys = [p[1] for p in polygon]
                    pw = max(xs) - min(xs)
                    ph = max(ys) - min(ys)
                    if pw < 40 or ph < 40:
                        continue
                    rooms.append({
                        'polygon': polygon,
                        'area': area,
                        'nodes': path,
                    })
                    # marcar aristas como visitadas
                    for i in range(len(path) - 1):
                        a, b = path[i], path[i + 1]
                        visited_edges.add((min(a, b), max(a, b)))

    # eliminar duplicados (ciclos que son el mismo recinto)
    unique_rooms = _deduplicate_rooms(rooms)

    if not unique_rooms:
        # fallback: usar contornos sobre la máscara binaria de paredes
        wall_binary = graph_data.get('wall_binary')
        if wall_binary is not None:
            unique_rooms = _find_rooms_from_contours(
                wall_binary, min_area=5000, max_area=500000,
            )

    return unique_rooms


def _polygon_area(polygon):
    """Área de un polígono (fórmula de Shoelace)."""
    area = 0
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        area += polygon[i][0] * polygon[j][1]
        area -= polygon[j][0] * polygon[i][1]
    return abs(area) / 2


def _deduplicate_rooms(rooms, overlap_threshold=0.8):
    """Elimina recintos duplicados (mismo espacio detectado múltiples veces)."""
    if not rooms:
        return []

    kept = []
    for r in rooms:
        duplicate = False
        for existing in kept:
            overlap = _polygon_overlap_ratio(r['polygon'], existing['polygon'])
            if overlap > overlap_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(r)

    return kept


def _polygon_overlap_ratio(poly1, poly2):
    """Estima la relación de superposición entre dos polígonos usando
    intersección de rectángulos envolventes (bounding box).

    Para una solución más precisa se usaría Shapely, pero esta
    aproximación evita la dependencia."""
    def bbox(poly):
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return (min(xs), min(ys), max(xs), max(ys))

    b1 = bbox(poly1)
    b2 = bbox(poly2)

    xi = max(b1[0], b2[0])
    yi = max(b1[1], b2[1])
    xf = min(b1[2], b2[2])
    yf = min(b1[3], b2[3])

    if xi >= xf or yi >= yf:
        return 0.0

    inter_area = (xf - xi) * (yf - yi)
    a1 = _polygon_area(poly1)
    a2 = _polygon_area(poly2)
    union = a1 + a2 - inter_area
    if union < 1:
        return 0.0

    return inter_area / union


def _find_rooms_from_contours(wall_binary, min_area=5000, max_area=500000):
    """Detecta recintos como contornos cerrados en la máscara binaria de paredes."""
    try:
        from shapely.geometry import Polygon as ShapelyPolygon
        HAS_SHAPELY = True
    except ImportError:
        HAS_SHAPELY = False

    binary = (wall_binary > 0).astype(np.uint8) * 255

    kernel = np.ones((7, 7), np.uint8)
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # bounding box de toda la región de paredes (para excluir el contorno exterior)
    rows_w = np.any(closed, axis=1)
    cols_w = np.any(closed, axis=0)
    if rows_w.any() and cols_w.any():
        ys = np.where(rows_w)[0]
        xs = np.where(cols_w)[0]
        wall_bbox = (xs[0], ys[0], xs[-1], ys[-1])
        wall_bbox_w = wall_bbox[2] - wall_bbox[0]
        wall_bbox_h = wall_bbox[3] - wall_bbox[1]
    else:
        wall_bbox = (0, 0, binary.shape[1], binary.shape[0])
        wall_bbox_w, wall_bbox_h = binary.shape[1], binary.shape[0]

    inv = cv2.bitwise_not(closed)
    contours, hierarchy = cv2.findContours(inv, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    h, w = binary.shape
    rooms = []
    for i, cnt in enumerate(contours):
        # solo contornos internos (hijos de otro contorno) — son habitaciones
        parent = hierarchy[0][i][3] if hierarchy is not None else -1
        if parent < 0:
            continue
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        x, y, cw, ch = cv2.boundingRect(cnt)
        if x <= 2 and y <= 2 and (x + cw >= w - 2 or y + ch >= h - 2):
            continue
        # excluir el contorno exterior: si cubre > 80% del wall_bbox es fachada
        if wall_bbox_w > 0 and wall_bbox_h > 0:
            overlap_x = max(0, min(x + cw, wall_bbox[2]) - max(x, wall_bbox[0]))
            overlap_y = max(0, min(y + ch, wall_bbox[3]) - max(y, wall_bbox[1]))
            overlap_ratio = (overlap_x * overlap_y) / (wall_bbox_w * wall_bbox_h)
            if overlap_ratio > 0.8:
                continue
        # excluir recintos muy delgados (pseudohabitaciones entre paredes paralelas)
        if cw < 40 or ch < 40:
            continue

        poly = cnt.squeeze(axis=1).tolist()
        if len(poly) < 4:
            continue

        if HAS_SHAPELY:
            try:
                sp = ShapelyPolygon(poly)
                if not sp.is_valid:
                    sp = sp.buffer(0)
                if sp.is_valid and sp.area >= min_area:
                    simplified = sp.simplify(5, preserve_topology=True)
                    if len(simplified.exterior.coords) >= 4:
                        rooms.append({
                            'polygon': list(simplified.exterior.coords),
                            'area': sp.area,
                            'nodes': [],
                        })
                        continue
            except Exception:
                pass

        epsilon = 0.01 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        if len(approx) >= 4:
            pts = approx.squeeze(axis=1).tolist()
            rooms.append({
                'polygon': pts,
                'area': area,
                'nodes': [],
            })

    return _deduplicate_rooms(rooms)


def detect_exterior_contour(horizontals, verticals):
    """Encuentra el contorno exterior del plano.

    Toma el polígono convexo que envuelve todos los segmentos de pared
    detectados."""
    all_pts = []
    for s in horizontals + verticals:
        all_pts.append((s[0], s[1]))
        all_pts.append((s[2], s[3]))

    if not all_pts:
        return None

    pts = np.array(all_pts, dtype=np.int32)
    hull = cv2.convexHull(pts)
    return hull.reshape(-1, 2).tolist()



