"""Detección y procesamiento de líneas para planos arquitectónicos.

Pipeline:
1. LSD (Line Segment Detector) como método principal — funciona mejor
   para trazos hechos a mano que Hough probabilístico
2. Si LSD no da suficientes segmentos, fallback a skeletonize + Hough
3. Clasificar en H/V
4. Fusionar colineales (agrupar por y/x, extender)
5. Extender hasta intersecciones (cerrar esquinas)
6. Cerrar gaps
7. Snap a grilla

Todo asume coordenadas absolutas (no relativas al canvas)."""

import numpy as np
import cv2


# ── Skeletonize (solo para fallback Hough) ────────────────────

def skeletonize(binary):
    skel = np.zeros(binary.shape, dtype=np.uint8)
    temp = binary.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(temp) > 0:
        eroded = cv2.erode(temp, kernel)
        dilated = cv2.dilate(eroded, kernel)
        subset = cv2.subtract(temp, dilated)
        skel = cv2.bitwise_or(skel, subset)
        temp = eroded
    return skel


# ── LSD: Line Segment Detector ────────────────────────────────

def detect_lines_lsd(gray, min_length=20):
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    lines, _, _, _ = lsd.detect(gray)
    if lines is None:
        return []
    segs = []
    for line in lines:
        pts = line[0] if line.ndim > 1 and line.shape[-1] == 4 else line
        x1, y1, x2, y2 = [float(v) for v in pts]
        length = np.hypot(x2 - x1, y2 - y1)
        if length >= min_length:
            segs.append([x1, y1, x2, y2])
    return segs


# ── Hough (fallback) ──────────────────────────────────────────

def detect_lines_hough(binary, min_length=30, max_gap=15):
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 360,
        threshold=25,
        minLineLength=min_length,
        maxLineGap=max_gap,
    )
    if lines is None:
        return []
    return lines[:, 0, :].tolist()


# ── Detector unificado ────────────────────────────────────────

def detect_segments(gray, binary, config=None):
    """Detecta segmentos de línea usando LSD (preferido) o Hough (fallback).

    Args:
        gray: imagen en escala de grises (para LSD)
        binary: imagen binaria (para Hough)
        config: dict con claves opcionales:
            - method: 'lsd', 'hough' o 'auto' (default: 'auto')
            - min_length: longitud mínima del segmento
            - max_gap: gap máximo para Hough

    Returns:
        list de segmentos [x1, y1, x2, y2]
    """
    cfg = config or {}
    method = cfg.get('method', 'auto')
    min_length = cfg.get('min_length', 20)
    max_gap = cfg.get('max_gap', 15)

    if method == 'lsd':
        return detect_lines_lsd(gray, min_length)

    if method == 'hough':
        return detect_lines_hough(binary, min_length, max_gap)

    # auto: probar LSD, si da pocos o ningún segmento → Hough
    segs = detect_lines_lsd(gray, min_length)
    if len(segs) >= 5:
        return segs
    segs_h = detect_lines_hough(binary, min_length, max_gap)
    if len(segs_h) > len(segs):
        return segs_h
    return segs


def classify_lines(segments, angle_tolerance=5):
    horizontals = []
    verticals = []
    others = []
    for seg in segments:
        x1, y1, x2, y2 = seg
        dx = x2 - x1
        dy = y2 - y1
        length = np.hypot(dx, dy)
        if length < 1:
            continue
        angle = abs(np.degrees(np.arctan2(dy, dx))) % 180
        if angle < angle_tolerance or angle > 180 - angle_tolerance:
            horizontals.append(seg)
        elif abs(angle - 90) < angle_tolerance:
            verticals.append(seg)
        else:
            others.append(seg)
    return horizontals, verticals, others


def merge_colinear(segments, angle_tol=3, dist_tol=15, gap_tol=30, min_len=20):
    """Agrupa segmentos colineales y los fusiona en uno solo.

    Para horizontales: agrupa por coordenada Y (con tolerancia),
    luego toma min(x1) y max(x2) de todo el grupo.
    Para verticales: agrupa por coordenada X, luego min(y1) y max(y2).

    Esto es más robusto que el enfoque greedy anterior."""
    if not segments:
        return []

    # separar H y V
    hs = [s for s in segments if _is_horizontal(np.array(s), angle_tol)]
    vs = [s for s in segments if not _is_horizontal(np.array(s), angle_tol)]

    merged = _merge_group(hs, is_horizontal=True, dist_tol=dist_tol, gap_tol=gap_tol)
    merged += _merge_group(vs, is_horizontal=False, dist_tol=dist_tol, gap_tol=gap_tol)

    return _clean_short_segments(merged, min_len=min_len)


def _merge_group(segments, is_horizontal, dist_tol=15, gap_tol=30):
    """Agrupa segmentos paralelos y los fusiona."""
    if not segments:
        return []

    if is_horizontal:
        # agrupar por Y
        segs = sorted(segments, key=lambda s: (s[1] + s[3]) / 2)
        groups = []
        used = set()
        for i, a in enumerate(segs):
            if i in used:
                continue
            ya = (a[1] + a[3]) / 2
            cluster = [i]
            used.add(i)
            for j, b in enumerate(segs):
                if j in used:
                    continue
                yb = (b[1] + b[3]) / 2
                if abs(ya - yb) > dist_tol:
                    continue
                # mismas Y, verificar gap
                ax1, ax2 = min(a[0], a[2]), max(a[0], a[2])
                bx1, bx2 = min(b[0], b[2]), max(b[0], b[2])
                gap = max(bx1 - ax2, ax1 - bx2)
                if gap < gap_tol:
                    cluster.append(j)
                    used.add(j)
            groups.append([segs[i] for i in cluster])

        result = []
        for group in groups:
            xs = []
            for s in group:
                xs.append(s[0])
                xs.append(s[2])
            y = np.median([s[1] for s in group] + [s[3] for s in group])
            result.append([min(xs), y, max(xs), y])
        return result
    else:
        # verticales: agrupar por X
        segs = sorted(segments, key=lambda s: (s[0] + s[2]) / 2)
        groups = []
        used = set()
        for i, a in enumerate(segs):
            if i in used:
                continue
            xa = (a[0] + a[2]) / 2
            cluster = [i]
            used.add(i)
            for j, b in enumerate(segs):
                if j in used:
                    continue
                xb = (b[0] + b[2]) / 2
                if abs(xa - xb) > dist_tol:
                    continue
                ay1, ay2 = min(a[1], a[3]), max(a[1], a[3])
                by1, by2 = min(b[1], b[3]), max(b[1], b[3])
                gap = max(by1 - ay2, ay1 - by2)
                if gap < gap_tol:
                    cluster.append(j)
                    used.add(j)
            groups.append([segs[i] for i in cluster])

        result = []
        for group in groups:
            ys = []
            for s in group:
                ys.append(s[1])
                ys.append(s[3])
            x = np.median([s[0] for s in group] + [s[2] for s in group])
            result.append([x, min(ys), x, max(ys)])
        return result


def _is_horizontal(seg, tol=5):
    dx = seg[2] - seg[0]
    dy = seg[3] - seg[1]
    angle = abs(np.degrees(np.arctan2(dy, dx))) % 180
    return angle < tol or angle > 180 - tol


def _clean_short_segments(segments, min_len):
    return [s for s in segments if np.hypot(s[2] - s[0], s[3] - s[1]) >= min_len]


def _is_circle(cnt, min_radius, max_radius, circularity_thresh=0.8, area_ratio_thresh=0.75):
    area = cv2.contourArea(cnt)
    if area < np.pi * min_radius * min_radius * 0.8:
        return None
    perimeter = cv2.arcLength(cnt, True)
    if perimeter < 1:
        return None
    circularity = 4 * np.pi * area / (perimeter * perimeter)
    if circularity < circularity_thresh:
        return None
    (cx, cy), r = cv2.minEnclosingCircle(cnt)
    if r < 1:
        return None
    area_ratio = area / (np.pi * r * r)
    if area_ratio < area_ratio_thresh:
        return None
    if min_radius <= r <= max_radius:
        return ('circle', float(cx), float(cy), float(r))
    return None


def _is_rectangle(cnt, min_area=200):
    area = cv2.contourArea(cnt)
    if area < min_area:
        return None
    perimeter = cv2.arcLength(cnt, True)
    if perimeter < 1:
        return None
    epsilon = 0.04 * perimeter
    approx = cv2.approxPolyDP(cnt, epsilon, True)
    if len(approx) != 4:
        return None
    if not cv2.isContourConvex(approx):
        return None
    x, y, w, h = cv2.boundingRect(cnt)
    # descartar rectángulos muy alargados (no son muebles típicos)
    aspect = max(w, h) / max(min(w, h), 1)
    if aspect > 4:
        return None
    return ('rect', float(x), float(y), float(w), float(h))


def detect_shapes(binary, min_radius=10, max_radius=200):
    """Detecta círculos y rectángulos en una máscara binaria.

    Devuelve (circles, rects), donde cada circle es (cx, cy, r)
    y cada rect es (x, y, w, h)."""
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    circles = []
    rects = []
    for cnt in contours:
        c = _is_circle(cnt, min_radius, max_radius, circularity_thresh=0.8)
        if c:
            circles.append(c[1:])
            continue
        r = _is_rectangle(cnt, min_area=200)
        if r:
            rects.append(r[1:])
    return circles, rects


def mask_out_shapes(binary, circles, rects):
    """Rellena círculos y rectángulos en la máscara binaria para que
    Hough no detecte sus bordes como líneas."""
    result = binary.copy()
    for cx, cy, r in circles:
        cv2.circle(result, (int(cx), int(cy)), int(r), 0, -1)
    for x, y, w, h in rects:
        padding = 2
        x1 = max(0, int(x) - padding)
        y1 = max(0, int(y) - padding)
        x2 = min(result.shape[1], int(x + w) + padding)
        y2 = min(result.shape[0], int(y + h) + padding)
        result[y1:y2, x1:x2] = 0
    return result


def extend_to_intersections(horizontals, verticals, max_extend=200, margin=5):
    """Extiende cada segmento hasta la intersección más cercana.

    Para cada horizontal, busca verticales cuyos rangos Y crucen la línea
    y extiende hasta la vertical más cercana a cada extremo (incluyendo
    verticales dentro del segmento que actúan como topes intermedios).

    `margin` define cuán cerca del extremo debe estar una perpendicular
    para considerarse un tope válido (evita que el segmento se extienda
    más allá de una pared que cruza justo en su extremo)."""
    if not horizontals or not verticals:
        return horizontals, verticals

    h_arr = np.array(horizontals)
    v_arr = np.array(verticals)

    extended_h = []
    for h in horizontals:
        x1, y1, x2, y2 = h
        ly = (y1 + y2) / 2
        lx1, lx2 = min(x1, x2), max(x1, x2)
        orig_len = lx2 - lx1
        # No extender un segmento más de 3× su largo original
        effective_max_extend = min(max_extend, max(orig_len * 3, 50))

        vx_vals = (v_arr[:, 0] + v_arr[:, 2]) / 2
        vy_min = np.minimum(v_arr[:, 1], v_arr[:, 3])
        vy_max = np.maximum(v_arr[:, 1], v_arr[:, 3])

        # verticales que cruzan esta horizontal
        crosses = (vy_min - effective_max_extend < ly) & (ly < vy_max + effective_max_extend)

        # a la izquierda: verticales <= lx1 + margin
        mask_left = crosses & (vx_vals <= lx1 + margin)
        if np.any(mask_left):
            candidates = vx_vals[mask_left]
            nearest = candidates.max()
            if lx1 - nearest > 0 and lx1 - nearest < effective_max_extend:
                lx1 = nearest
            elif lx1 - nearest <= 0:  # vertical dentro/derecha del extremo
                # la vertical más cercana a lx1 (puede estar a la derecha)
                candidates_right = vx_vals[crosses & (vx_vals >= lx1)]
                if np.any(candidates_right):
                    nearest_right = candidates_right.min()
                    if nearest_right - lx1 < margin:
                        lx1 = nearest_right

        # a la derecha: verticales >= lx2 - margin
        mask_right = crosses & (vx_vals >= lx2 - margin)
        if np.any(mask_right):
            candidates = vx_vals[mask_right]
            nearest = candidates.min()
            if nearest - lx2 > 0 and nearest - lx2 < effective_max_extend:
                lx2 = nearest
            elif nearest - lx2 <= 0:  # vertical dentro/izquierda del extremo
                candidates_left = vx_vals[crosses & (vx_vals <= lx2)]
                if np.any(candidates_left):
                    nearest_left = candidates_left.max()
                    if lx2 - nearest_left < margin:
                        lx2 = nearest_left

        if lx2 - lx1 >= 20:
            extended_h.append([lx1, ly, lx2, ly])

    extended_v = []
    hy_vals = (h_arr[:, 1] + h_arr[:, 3]) / 2
    hx_min = np.minimum(h_arr[:, 0], h_arr[:, 2])
    hx_max = np.maximum(h_arr[:, 0], h_arr[:, 2])

    for v in verticals:
        vx1, vy1, vx2, vy2 = v
        lx = (vx1 + vx2) / 2
        ly1, ly2 = min(vy1, vy2), max(vy1, vy2)
        orig_len = ly2 - ly1
        effective_max_extend = min(max_extend, max(orig_len * 3, 50))

        # horizontales que cruzan esta vertical
        crosses = (hx_min - effective_max_extend < lx) & (lx < hx_max + effective_max_extend)

        mask_top = crosses & (hy_vals <= ly1 + margin)
        if np.any(mask_top):
            candidates = hy_vals[mask_top]
            nearest = candidates.max()
            if ly1 - nearest > 0 and ly1 - nearest < effective_max_extend:
                ly1 = nearest
            elif ly1 - nearest <= 0:
                candidates_bot = hy_vals[crosses & (hy_vals >= ly1)]
                if np.any(candidates_bot):
                    nearest_bot = candidates_bot.min()
                    if nearest_bot - ly1 < margin:
                        ly1 = nearest_bot

        mask_bot = crosses & (hy_vals >= ly2 - margin)
        if np.any(mask_bot):
            candidates = hy_vals[mask_bot]
            nearest = candidates.min()
            if nearest - ly2 > 0 and nearest - ly2 < effective_max_extend:
                ly2 = nearest
            elif nearest - ly2 <= 0:
                candidates_top = hy_vals[crosses & (hy_vals <= ly2)]
                if np.any(candidates_top):
                    nearest_top = candidates_top.max()
                    if ly2 - nearest_top < margin:
                        ly2 = nearest_top

        if ly2 - ly1 >= 20:
            extended_v.append([lx, ly1, lx, ly2])

    return extended_h, extended_v


def snap_to_grid(segments, grid_size=10):
    snapped = []
    for s in segments:
        snapped.append([
            round(s[0] / grid_size) * grid_size,
            round(s[1] / grid_size) * grid_size,
            round(s[2] / grid_size) * grid_size,
            round(s[3] / grid_size) * grid_size,
        ])
    return snapped


def close_gaps(segments, gap_tol=20):
    """Extiende segmentos para cerrar pequeños gaps ortogonales."""
    if len(segments) < 2:
        return segments

    horizontals = [s for s in segments if _is_horizontal(np.array(s))]
    verticals = [s for s in segments if not _is_horizontal(np.array(s))]

    result = list(segments)
    modified = [False] * len(result)

    for h in horizontals:
        x1, y1, x2, y2 = h
        ly = (y1 + y2) / 2
        lx1, lx2 = min(x1, x2), max(x1, x2)
        changed = False

        for v in verticals:
            vx = (v[0] + v[2]) / 2
            vy1, vy2 = min(v[1], v[3]), max(v[1], v[3])

            if vy1 - gap_tol < ly < vy2 + gap_tol:
                if lx1 - gap_tol < vx < lx1:
                    lx1 = vx
                    changed = True
                elif lx2 < vx < lx2 + gap_tol:
                    lx2 = vx
                    changed = True

        if changed:
            idx = next(i for i, s in enumerate(result) if s == h)
            result[idx] = (lx1, ly, lx2, ly)
            modified[idx] = True

    for v in verticals:
        vx1, vy1, vx2, vy2 = v
        lx = (vx1 + vx2) / 2
        vy1, vy2 = min(vy1, vy2), max(vy1, vy2)
        changed = False

        for h in horizontals:
            hy = (h[1] + h[3]) / 2
            hx1, hx2 = min(h[0], h[2]), max(h[0], h[2])

            if hx1 - gap_tol < lx < hx2 + gap_tol:
                if vy1 - gap_tol < hy < vy1:
                    vy1 = hy
                    changed = True
                elif vy2 < hy < vy2 + gap_tol:
                    vy2 = hy
                    changed = True

        if changed:
            idx = next(i for i, s in enumerate(result) if s == v)
            result[idx] = (lx, vy1, lx, vy2)
            modified[idx] = True

    return result


def find_wall_gaps(h_segments, v_segments, door_mask=None, min_gap=15, max_gap=120):
    """Detecta vanos como gaps entre segmentos de muro.

    Agrupa segmentos horizontales por proximidad en Y (tolerancia de
    15px) para no perder gaps cuando los segmentos detectados por LSD
    no están exactamente alineados en Y. Luego busca espacios > min_gap
    y < max_gap entre segmentos consecutivos.

    Si door_mask se proporciona, solo devuelve gaps con ≥1 %
    superposición con la máscara (umbral bajo porque la máscara de
    puerta no siempre cubre el gap perfectamente).

    Devuelve lista de dicts {x, y, width, height}."""
    gaps = []

    # Agrupar horizontales por proximidad en Y (tolerancia 15px)
    y_groups = []
    for s in h_segments:
        x1, y1, x2, y2 = s
        y = round((y1 + y2) / 2)
        placed = False
        for g in y_groups:
            if abs(g['y'] - y) <= 15:
                g['segs'].append((min(x1, x2), max(x1, x2)))
                placed = True
                break
        if not placed:
            y_groups.append({'y': y, 'segs': [(min(x1, x2), max(x1, x2))]})

    for group in y_groups:
        segs = sorted(group['segs'])
        merged = []
        for x1, x2 in segs:
            if not merged:
                merged.append([x1, x2])
            else:
                last = merged[-1]
                if x1 <= last[1] + 5:
                    last[1] = max(last[1], x2)
                else:
                    gap = x1 - last[1]
                    if min_gap < gap < max_gap:
                        gaps.append({'x': (last[1] + x1) / 2, 'y': group['y'], 'width': gap, 'height': 8})
                    merged.append([x1, x2])

    # Agrupar verticales por proximidad en X
    x_groups = []
    for s in v_segments:
        x1, y1, x2, y2 = s
        x = round((x1 + x2) / 2)
        placed = False
        for g in x_groups:
            if abs(g['x'] - x) <= 15:
                g['segs'].append((min(y1, y2), max(y1, y2)))
                placed = True
                break
        if not placed:
            x_groups.append({'x': x, 'segs': [(min(y1, y2), max(y1, y2))]})

    for group in x_groups:
        segs = sorted(group['segs'])
        merged = []
        for y1, y2 in segs:
            if not merged:
                merged.append([y1, y2])
            else:
                last = merged[-1]
                if y1 <= last[1] + 5:
                    last[1] = max(last[1], y2)
                else:
                    gap = y1 - last[1]
                    if min_gap < gap < max_gap:
                        gaps.append({'x': group['x'], 'y': (last[1] + y1) / 2, 'width': 8, 'height': gap})
                    merged.append([y1, y2])

    # Validación con door_mask (opcional, desactivada porque la
    # máscara de color suele no coincidir con el vano exacto).
    return gaps


def point_to_segment_distance(px, py, x1, y1, x2, y2):
    """Distancia mínima desde un punto a un segmento de recta."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return np.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    nx = x1 + t * dx
    ny = y1 + t * dy
    return np.hypot(px - nx, py - ny)


def refine_wall_segments(h_segments, v_segments, snap_y=10, snap_x=10):
    """Refina segmentos de pared: elimina duplicados paralelos y
    extiende para formar esquinas limpias.

    1. Agrupa horizontales cercanas en Y, verticales cercanas en X.
    2. Para cada grupo, fusiona en una sola línea fusionando rangos.
    3. Extiende cada segmento hasta la perpendicular más cercana.

    Args:
        h_segments: lista de [x1, y1, x2, y2] (horizontales)
        v_segments: lista de [x1, y1, x2, y2] (verticales)
        snap_y: tolerancia para agrupar horizontales por Y
        snap_x: tolerancia para agrupar verticales por X

    Returns:
        (h_clean, v_clean): segmentos refinados
    """
    # ── 1. Agrupar horizontales por Y ──────────────────────────
    h_by_y = _group_by_proximity(h_segments, snap_y, axis='y')
    h_clean = []
    for y, group in sorted(h_by_y.items()):
        xs = []
        for s in group:
            xs.extend([s[0], s[2]])
        x_min, x_max = min(xs), max(xs)
        if x_max - x_min >= 20:
            h_clean.append([x_min, y, x_max, y])

    # ── 2. Agrupar verticales por X ────────────────────────────
    v_by_x = _group_by_proximity(v_segments, snap_x, axis='x')
    v_clean = []
    for x, group in sorted(v_by_x.items()):
        ys = []
        for s in group:
            ys.extend([s[1], s[3]])
        y_min, y_max = min(ys), max(ys)
        if y_max - y_min >= 20:
            # conservar la posición del segmento más largo (no el promedio)
            best = max(group, key=lambda s: abs(s[3] - s[1]))
            bx = (best[0] + best[2]) / 2  # X del segmento más largo
            v_clean.append([bx, y_min, bx, y_max])

    # ── 3. Extender cada horizontal hasta la vertical más cercana ──
    v_arr = np.array(v_clean)

    if len(v_arr) == 0:
        return h_clean, v_clean

    vx_vals = (v_arr[:, 0] + v_arr[:, 2]) / 2
    vy_min = np.minimum(v_arr[:, 1], v_arr[:, 3])
    vy_max = np.maximum(v_arr[:, 1], v_arr[:, 3])

    h_out = []
    for h in h_clean:
        x1, y, x2, _ = h

        # filtrar verticales que alcanzan esta Y
        reach = (vy_min - snap_y <= y) & (y <= vy_max + snap_y)
        if not np.any(reach):
            if x2 - x1 >= 20:
                h_out.append([x1, y, x2, y])
            continue

        vs_at_y = vx_vals[reach]
        vymin_at_y = vy_min[reach]
        vymax_at_y = vy_max[reach]

        # ── extender izquierda ──────────────────────────────
        left_vs = vs_at_y[vs_at_y < x1]
        # ¿x1 está en una vertical que TERMINA (arranca/acaba) en y?
        near_left = np.abs(vs_at_y - x1) <= snap_x
        terminates_left = np.any(
            near_left & ((np.abs(vymin_at_y - y) <= snap_y) |
                         (np.abs(vymax_at_y - y) <= snap_y))
        )
        if not terminates_left and len(left_vs) > 0:
            x1 = left_vs.min()

        # ── extender derecha ────────────────────────────────
        right_vs = vs_at_y[vs_at_y > x2]
        near_right = np.abs(vs_at_y - x2) <= snap_x
        terminates_right = np.any(
            near_right & ((np.abs(vymin_at_y - y) <= snap_y) |
                          (np.abs(vymax_at_y - y) <= snap_y))
        )
        if not terminates_right and len(right_vs) > 0:
            x2 = right_vs.max()

        if x2 - x1 >= 20:
            h_out.append([x1, y, x2, y])

    # ── 4. Extender cada vertical hasta la horizontal más cercana ──
    v_out = []
    if len(h_out) == 0:
        return h_out, v_clean

    h_arr2 = np.array(h_out)
    hy_vals = (h_arr2[:, 1] + h_arr2[:, 3]) / 2
    hx_min = np.minimum(h_arr2[:, 0], h_arr2[:, 2])
    hx_max = np.maximum(h_arr2[:, 0], h_arr2[:, 2])

    for v in v_clean:
        x, y1, _, y2 = v

        reach = (hx_min - snap_x <= x) & (x <= hx_max + snap_x)
        if not np.any(reach):
            if y2 - y1 >= 20:
                v_out.append([x, y1, x, y2])
            continue

        hs_at_x = hy_vals[reach]
        hxmin_at_x = hx_min[reach]
        hxmax_at_x = hx_max[reach]

        # ── extender arriba ─────────────────────────────────
        top_hs = hs_at_x[hs_at_x < y1]
        # ¿y1 está en una horizontal que TERMINA (arranca/acaba) en x?
        near_top = np.abs(hs_at_x - y1) <= snap_y
        terminates_top = np.any(
            near_top & ((np.abs(hxmin_at_x - x) <= snap_x) |
                        (np.abs(hxmax_at_x - x) <= snap_x))
        )
        if not terminates_top and len(top_hs) > 0:
            y1 = top_hs.max()

        # ── extender abajo ──────────────────────────────────
        bot_hs = hs_at_x[hs_at_x > y2]
        near_bot = np.abs(hs_at_x - y2) <= snap_y
        terminates_bot = np.any(
            near_bot & ((np.abs(hxmin_at_x - x) <= snap_x) |
                        (np.abs(hxmax_at_x - x) <= snap_x))
        )
        if not terminates_bot and len(bot_hs) > 0:
            y2 = bot_hs.min()

        if y2 - y1 >= 20:
            v_out.append([x, y1, x, y2])

    return h_out, v_out


def deduplicate_parallel_walls(segments, h_tol=12, v_tol=12):
    """Elimina segmentos de pared paralelos muy cercanos (ej. doble-trazo
    de la misma pared después de snap_to_grid).  Para horizontales agrupa
    por Y y solapamiento en X; para verticales por X y solapamiento en Y.
    Dentro de cada grupo conserva solo el segmento más largo."""
    h_segs = [s for s in segments if _is_horizontal(s)]
    v_segs = [s for s in segments if not _is_horizontal(s)]

    kept = []

    # horizontales: agrupar por Y y solapamiento en X
    h_groups = _group_by_proximity(h_segs, h_tol, axis='y')
    for y, group in h_groups.items():
        # entre segmentos del mismo grupo Y, solo fusionar si solapan en X
        subgroups = []
        for s in sorted(group, key=lambda x: x[0]):
            sx1, _, sx2, _ = s
            merged = False
            for sg in subgroups:
                gx1 = min(s[0] for s in sg)
                gx2 = max(s[2] for s in sg)
                # solapamiento: al menos 20px de overlap
                overlap = min(sx2, gx2) - max(sx1, gx1)
                if overlap >= 20:
                    sg.append(s)
                    merged = True
                    break
            if not merged:
                subgroups.append([s])
        for sg in subgroups:
            best = max(sg, key=lambda s: abs(s[2] - s[0]))
            kept.append(best)

    # verticales: agrupar por X y solapamiento en Y
    v_groups = _group_by_proximity(v_segs, v_tol, axis='x')
    for x, group in v_groups.items():
        subgroups = []
        for s in sorted(group, key=lambda s: s[1]):
            _, sy1, _, sy2 = s
            merged = False
            for sg in subgroups:
                gy1 = min(s[1] for s in sg)
                gy2 = max(s[3] for s in sg)
                overlap = min(sy2, gy2) - max(sy1, gy1)
                if overlap >= 20:
                    sg.append(s)
                    merged = True
                    break
            if not merged:
                subgroups.append([s])
        for sg in subgroups:
            best = max(sg, key=lambda s: abs(s[3] - s[1]))
            kept.append(best)

    return kept


def _group_by_proximity(segments, tol, axis='y'):
    """Agrupa segmentos paralelos cercanos por su coordenada
    media en el eje dado.  axis='y' agrupa horizontales, 'x' agrupa verticales."""
    idx = 1 if axis == 'y' else 0
    groups = {}
    used = set()
    sorted_segs = sorted(segments, key=lambda s: (s[idx] + s[idx + 2]) / 2)

    for i, s in enumerate(sorted_segs):
        if i in used:
            continue
        key = (s[idx] + s[idx + 2]) / 2
        group = [s]
        used.add(i)
        for j in range(i + 1, len(sorted_segs)):
            if j in used:
                continue
            sj = sorted_segs[j]
            keyj = (sj[idx] + sj[idx + 2]) / 2
            if abs(keyj - key) <= tol:
                group.append(sj)
                used.add(j)
        # usar la Y media del grupo como clave final
        avg_y = sum((s[idx] + s[idx + 2]) / 2 for s in group) / len(group)
        groups[round(avg_y)] = group
    return groups
