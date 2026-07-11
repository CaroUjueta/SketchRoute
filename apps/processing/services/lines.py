"""Detección y procesamiento de líneas para planos arquitectónicos.

Pipeline:
1. Skeletonización (adelgazar trazos a 1px)
2. Hough probabilístico (detectar segmentos)
3. Clasificar en H/V
4. Fusionar colineales (agrupar por y/x, extender)
5. Extender hasta intersecciones (cerrar esquinas)
6. Cerrar gaps
7. Snap a grilla

Todo asume coordenadas absolutas (no relativas al canvas)."""

import numpy as np
import cv2


def _skeletonize_erode_dilate(binary):
    """Adelgazado casero (erode/dilate iterativo). Lento en imágenes grandes
    pero sin dependencias — se usa si cv2.ximgproc no está disponible."""
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


def skeletonize(binary):
    """Adelgaza el trazo a 1px. Usa cv2.ximgproc.thinning (opencv-contrib,
    vectorizado en C++) si está disponible; si no, cae al método casero."""
    if hasattr(cv2, 'ximgproc'):
        try:
            return cv2.ximgproc.thinning(binary)
        except Exception:
            pass
    return _skeletonize_erode_dilate(binary)


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
    # OpenCV 4 devuelve (N,1,4); versiones nuevas (N,4). Normalizar.
    return np.asarray(lines).reshape(-1, 4).tolist()


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


def _point_seg_dist(px, py, s):
    """Distancia de un punto al segmento s=(x1,y1,x2,y2)."""
    x1, y1, x2, y2 = s
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-6:
        return np.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return np.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _segments_touch(a, b, tol):
    """True si los segmentos a y b se tocan/cruzan dentro de `tol`."""
    for (px, py) in ((a[0], a[1]), (a[2], a[3])):
        if _point_seg_dist(px, py, b) <= tol:
            return True
    for (px, py) in ((b[0], b[1]), (b[2], b[3])):
        if _point_seg_dist(px, py, a) <= tol:
            return True
    return False


def filter_within_bbox(segments, bbox, margin=30):
    """Conserva solo segmentos que tocan el bounding box `bbox` (x1,y1,x2,y2)
    expandido por `margin`. Descarta ruido fuera del edificio (logo del
    cuaderno, margen impreso) que cae afuera del área de las paredes."""
    if not bbox:
        return segments
    bx1, by1, bx2, by2 = bbox
    bx1 -= margin; by1 -= margin; bx2 += margin; by2 += margin
    kept = []
    for s in segments:
        sx1, sy1, sx2, sy2 = s
        # bbox del segmento
        smnx, smxx = min(sx1, sx2), max(sx1, sx2)
        smny, smxy = min(sy1, sy2), max(sy1, sy2)
        # intersección con el bbox de paredes
        if smxx < bx1 or smnx > bx2 or smxy < by1 or smny > by2:
            continue
        kept.append(s)
    return kept


def prune_dangling(segments, tol=22, max_iter=6, min_keep_len=55):
    """Quita SOLO las colitas cortas que cuelgan (stubs con un extremo libre).

    Un trazo se descarta únicamente si tiene un extremo libre Y es corto
    (< min_keep_len): eso es ruido/cola sobrante de la vectorización. Los
    trazos largos con un extremo libre (mostradores, separaciones en 'L',
    góndolas) son muebles legítimos y se conservan aunque no formen una
    figura cerrada. Itera porque al quitar una colita puede quedar otra
    al descubierto."""
    segs = [list(s) for s in segments]
    if len(segs) <= 2:
        return segs

    def connected(px, py, skip):
        for j, t in enumerate(segs):
            if j == skip:
                continue
            if _point_seg_dist(px, py, t) <= tol:
                return True
        return False

    for _ in range(max_iter):
        keep = []
        removed = False
        for i, s in enumerate(segs):
            length = float(np.hypot(s[2] - s[0], s[3] - s[1]))
            c1 = connected(s[0], s[1], i)
            c2 = connected(s[2], s[3], i)
            free = (not c1) or (not c2)
            if free and length < min_keep_len:
                removed = True  # colita corta colgando → descartar
            else:
                keep.append(s)
        if not removed or len(keep) < 2:
            break
        segs = keep
    return segs


def drop_isolated_segments(segments, tol=25):
    """Descarta segmentos que no conectan con ningún otro.

    En un plano, los muros forman una estructura interconectada. Las líneas
    espurias (sombra del borde de la hoja, margen impreso) quedan flotando
    sin tocar nada → se eliminan. Conserva todo si hay 2 o menos segmentos."""
    if len(segments) <= 2:
        return segments
    keep = []
    for i, s in enumerate(segments):
        for j, t in enumerate(segments):
            if i != j and _segments_touch(s, t, tol):
                keep.append(s)
                break
    return keep


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

        vx_vals = (v_arr[:, 0] + v_arr[:, 2]) / 2
        vy_min = np.minimum(v_arr[:, 1], v_arr[:, 3])
        vy_max = np.maximum(v_arr[:, 1], v_arr[:, 3])

        # verticales que cruzan esta horizontal
        crosses = (vy_min - max_extend < ly) & (ly < vy_max + max_extend)

        # a la izquierda: verticales <= lx1 + margin
        mask_left = crosses & (vx_vals <= lx1 + margin)
        if np.any(mask_left):
            candidates = vx_vals[mask_left]
            nearest = candidates.max()
            if lx1 - nearest > 0 and lx1 - nearest < max_extend:
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
            if nearest - lx2 > 0 and nearest - lx2 < max_extend:
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

        # horizontales que cruzan esta vertical
        crosses = (hx_min - max_extend < lx) & (lx < hx_max + max_extend)

        mask_top = crosses & (hy_vals <= ly1 + margin)
        if np.any(mask_top):
            candidates = hy_vals[mask_top]
            nearest = candidates.max()
            if ly1 - nearest > 0 and ly1 - nearest < max_extend:
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
            if nearest - ly2 > 0 and nearest - ly2 < max_extend:
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


def snap_segments_to_walls(segments, wall_h, wall_v, tol=30):
    """Pega segmentos (puertas/vanos) a la pared más cercana para que la
    'corten' y se vean como abertura, en vez de quedar flotando al lado.

    Una puerta horizontal se pega en Y a la pared horizontal cercana (si su X
    se solapa); una vertical se pega en X a la pared vertical cercana."""
    if not segments:
        return segments
    out = []
    for s in segments:
        x1, y1, x2, y2 = s
        if abs(x2 - x1) >= abs(y2 - y1):  # horizontal
            sy = (y1 + y2) / 2
            slo, shi = min(x1, x2), max(x1, x2)
            best = None
            for w in wall_h:
                wy = (w[1] + w[3]) / 2
                wlo, whi = min(w[0], w[2]), max(w[0], w[2])
                if abs(wy - sy) <= tol and shi >= wlo - 5 and slo <= whi + 5:
                    d = abs(wy - sy)
                    if best is None or d < best[0]:
                        best = (d, wy)
            if best:
                y1 = y2 = best[1]
        else:  # vertical
            sx = (x1 + x2) / 2
            slo, shi = min(y1, y2), max(y1, y2)
            best = None
            for w in wall_v:
                wx = (w[0] + w[2]) / 2
                wlo, whi = min(w[1], w[3]), max(w[1], w[3])
                if abs(wx - sx) <= tol and shi >= wlo - 5 and slo <= whi + 5:
                    d = abs(wx - sx)
                    if best is None or d < best[0]:
                        best = (d, wx)
            if best:
                x1 = x2 = best[1]
        out.append([x1, y1, x2, y2])
    return out


def close_exterior(horizontals, verticals, min_side=80):
    """Cierra el contorno exterior del edificio como un rectángulo.

    Calcula el bounding box de todas las paredes y agrega los 4 lados
    exteriores, de modo que el envolvente del edificio quede siempre cerrado
    aunque alguna pared esté demasiado tenue en la foto para detectarse. Las
    paredes interiores (divisiones) se conservan. Los lados que ya existen se
    fusionan luego con merge_colinear (no se duplican).

    Asume que el edificio es rectangular (decisión del usuario)."""
    segs = horizontals + verticals
    if len(segs) < 3:
        return horizontals, verticals

    xs = [c for s in segs for c in (s[0], s[2])]
    ys = [c for s in segs for c in (s[1], s[3])]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    if maxx - minx < min_side or maxy - miny < min_side:
        return horizontals, verticals

    # quitar paredes paralelas pegadas a un borde exterior: son detecciones
    # redundantes del propio contorno que, al sumar el borde limpio, quedarían
    # como pared doble. edge_tol = qué tan cerca del borde se considera duplicado.
    edge_tol = 45
    H = [h for h in horizontals
         if not (abs((h[1] + h[3]) / 2 - miny) < edge_tol
                 or abs((h[1] + h[3]) / 2 - maxy) < edge_tol)]
    V = [v for v in verticals
         if not (abs((v[0] + v[2]) / 2 - minx) < edge_tol
                 or abs((v[0] + v[2]) / 2 - maxx) < edge_tol)]

    H.append([minx, miny, maxx, miny])  # arriba
    H.append([minx, maxy, maxx, maxy])  # abajo
    V.append([minx, miny, minx, maxy])  # izquierda
    V.append([maxx, miny, maxx, maxy])  # derecha
    return H, V


def trim_overshoots(horizontals, verticals, margin=30):
    """Recorta los extremos de pared que se pasan de una esquina.

    Si el extremo de una horizontal sobresale apenas más allá de una vertical
    perpendicular (o al revés), lo recorta hasta la intersección para que las
    esquinas queden limpias en vez de con un "colgajo" sobresaliente."""
    if not horizontals or not verticals:
        return horizontals, verticals

    v_arr = np.array(verticals, dtype=float)
    vx = (v_arr[:, 0] + v_arr[:, 2]) / 2
    vy1 = np.minimum(v_arr[:, 1], v_arr[:, 3])
    vy2 = np.maximum(v_arr[:, 1], v_arr[:, 3])

    out_h = []
    for h in horizontals:
        x1, y1, x2, y2 = h
        ly = (y1 + y2) / 2
        lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
        # verticales que cruzan esta horizontal en Y (tolerancia amplia para
        # captar esquinas que no se tocan del todo por trazo tembloroso)
        cross = (vy1 - margin <= ly) & (ly <= vy2 + margin)
        # extremo derecho sobresale apenas más allá de una vertical interior
        rs = np.where(cross & (vx >= hi - margin) & (vx < hi))[0]
        if len(rs):
            hi = float(vx[rs].max())
        ls = np.where(cross & (vx <= lo + margin) & (vx > lo))[0]
        if len(ls):
            lo = float(vx[ls].min())
        if hi - lo >= 15:
            out_h.append([lo, ly, hi, ly])

    h_arr = np.array(horizontals, dtype=float)
    hy = (h_arr[:, 1] + h_arr[:, 3]) / 2
    hx1 = np.minimum(h_arr[:, 0], h_arr[:, 2])
    hx2 = np.maximum(h_arr[:, 0], h_arr[:, 2])

    out_v = []
    for v in verticals:
        x1, y1, x2, y2 = v
        lx = (x1 + x2) / 2
        lo, hi = (y1, y2) if y1 <= y2 else (y2, y1)
        cross = (hx1 - margin <= lx) & (lx <= hx2 + margin)
        bs = np.where(cross & (hy >= hi - margin) & (hy < hi))[0]
        if len(bs):
            hi = float(hy[bs].max())
        ts = np.where(cross & (hy <= lo + margin) & (hy > lo))[0]
        if len(ts):
            lo = float(hy[ts].min())
        if hi - lo >= 15:
            out_v.append([lx, lo, lx, hi])

    return out_h, out_v


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

    Para cada línea de muro ordena los segmentos y busca espacios.
    Si door_mask se proporciona, solo devuelve gaps con ≥5 %
    superposición con la máscara. Devuelve lista de dicts
    {x, y, width, height}."""
    gaps = []

    lines_h = {}
    for s in h_segments:
        x1, y1, x2, y2 = s
        y = round((y1 + y2) / 2)
        lines_h.setdefault(y, []).append((min(x1, x2), max(x1, x2)))

    for y, segs in lines_h.items():
        segs.sort()
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
                        gaps.append({'x': (last[1] + x1) / 2, 'y': y, 'width': gap, 'height': 8})
                    merged.append([x1, x2])

    lines_v = {}
    for s in v_segments:
        x1, y1, x2, y2 = s
        x = round((x1 + x2) / 2)
        lines_v.setdefault(x, []).append((min(y1, y2), max(y1, y2)))

    for x, segs in lines_v.items():
        segs.sort()
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
                        gaps.append({'x': x, 'y': (last[1] + y1) / 2, 'width': 8, 'height': gap})
                    merged.append([y1, y2])

    if door_mask is not None and gaps:
        validated = []
        for g in gaps:
            x, y, w, h = int(g['x']), int(g['y']), int(g['width']), int(g['height'])
            x1 = max(0, x - w // 2 - 4)
            y1 = max(0, y - h // 2 - 4)
            x2 = min(door_mask.shape[1] - 1, x + w // 2 + 4)
            y2 = min(door_mask.shape[0] - 1, y + h // 2 + 4)
            region = door_mask[y1:y2 + 1, x1:x2 + 1]
            if region.size > 0 and np.sum(region > 0) / region.size > 0.05:
                validated.append(g)
        return validated

    return gaps


def keep_doors_on_walls(door_segments, walls_h, walls_v, on_tol=25,
                        min_len=22):
    """Conserva solo las puertas que están SOBRE una pared (colineales y
    cerca) y que no son fragmentos diminutos. Una puerta que flota dentro de
    un recinto no abre ningún muro y estorba al rutear las flechas → se
    descarta."""
    vx = [(v[0] + v[2]) / 2.0 for v in walls_v]
    vy1 = [min(v[1], v[3]) for v in walls_v]
    vy2 = [max(v[1], v[3]) for v in walls_v]
    hy = [(h[1] + h[3]) / 2.0 for h in walls_h]
    hx1 = [min(h[0], h[2]) for h in walls_h]
    hx2 = [max(h[0], h[2]) for h in walls_h]

    kept = []
    for d in door_segments:
        dx1, dy1, dx2, dy2 = d
        if np.hypot(dx2 - dx1, dy2 - dy1) < min_len:
            continue
        horizontal = abs(dx2 - dx1) >= abs(dy2 - dy1)
        on = False
        if horizontal:
            dy = (dy1 + dy2) / 2.0
            dcx = (dx1 + dx2) / 2.0
            for k in range(len(walls_h)):
                if abs(hy[k] - dy) <= on_tol and hx1[k] - on_tol <= dcx <= hx2[k] + on_tol:
                    on = True
                    break
        else:
            dx = (dx1 + dx2) / 2.0
            dcy = (dy1 + dy2) / 2.0
            for k in range(len(walls_v)):
                if abs(vx[k] - dx) <= on_tol and vy1[k] - on_tol <= dcy <= vy2[k] + on_tol:
                    on = True
                    break
        if on:
            kept.append(d)
    return kept


def cut_walls_at_doors(walls_h, walls_v, door_segments, on_tol=20,
                       gap_pad=8, min_piece=10):
    """Parte las paredes donde hay una puerta para dejar un HUECO real.

    En lugar de dibujar la puerta encima de una pared continua (lo que deja la
    pared sólida y bloquea el ruteo de las flechas), se corta el segmento de
    pared en el tramo que ocupa la puerta. La puerta marca visualmente la
    abertura y las rutas pueden cruzar por ahí.

    `on_tol`: distancia máxima (perpendicular) para considerar que la puerta
    está SOBRE la pared. `gap_pad`: cuánto agrandar el hueco a cada lado.
    Devuelve (walls_h, walls_v) con los tramos resultantes."""

    def _mk(horizontal, pos, start, end):
        return [start, pos, end, pos] if horizontal else [pos, start, pos, end]

    def _junctions(perp, horizontal, wpos, a, b):
        """Posiciones (a lo largo del eje de la pared) donde una pared
        perpendicular se cruza con esta → uniones en T que NO deben romperse."""
        js = []
        for p in perp:
            px1, py1, px2, py2 = p
            if horizontal:
                # pared en estudio es horizontal (y=wpos); perpendicular vertical
                ppos = (px1 + px2) / 2.0            # x de la vertical
                pa, pb = min(py1, py2), max(py1, py2)
            else:
                ppos = (py1 + py2) / 2.0            # y de la horizontal
                pa, pb = min(px1, px2), max(px1, px2)
            # la perpendicular toca la pared (su rango cubre wpos) y cae dentro
            if pa - on_tol <= wpos <= pb + on_tol and a < ppos < b:
                js.append(ppos)
        return js

    def _split(walls, horizontal, perp):
        out = []
        for w in walls:
            wx1, wy1, wx2, wy2 = w
            if horizontal:
                wpos = (wy1 + wy2) / 2.0
                a, b = min(wx1, wx2), max(wx1, wx2)
            else:
                wpos = (wx1 + wx2) / 2.0
                a, b = min(wy1, wy2), max(wy1, wy2)

            jpts = _junctions(perp, horizontal, wpos, a, b)

            cuts = []
            for d in door_segments:
                dx1, dy1, dx2, dy2 = d
                d_h = abs(dx2 - dx1) >= abs(dy2 - dy1)
                if d_h != horizontal:
                    continue  # la puerta debe ir A LO LARGO de la pared
                if horizontal:
                    dpos = (dy1 + dy2) / 2.0
                    da, db = min(dx1, dx2), max(dx1, dx2)
                else:
                    dpos = (dx1 + dx2) / 2.0
                    da, db = min(dy1, dy2), max(dy1, dy2)
                if abs(dpos - wpos) > on_tol:
                    continue  # la puerta no está sobre esta pared
                dc = (da + db) / 2.0
                lo = max(a, da - gap_pad)
                hi = min(b, db + gap_pad)
                # No dejar que el hueco cruce una unión en T: recortarlo a la
                # unión más cercana a cada lado del centro de la puerta, para que
                # el muro perpendicular siga tocando limpio (T cerrada).
                lows = [j for j in jpts if j <= dc]
                highs = [j for j in jpts if j >= dc]
                if lows:
                    lo = max(lo, max(lows))
                if highs:
                    hi = min(hi, min(highs))
                if hi - lo > 4:
                    cuts.append((lo, hi))

            if not cuts:
                out.append(w)
                continue

            cuts.sort()
            pos = a
            for lo, hi in cuts:
                if lo - pos >= min_piece:
                    out.append(_mk(horizontal, wpos, pos, lo))
                pos = max(pos, hi)
            if b - pos >= min_piece:
                out.append(_mk(horizontal, wpos, pos, b))
        return out

    return _split(walls_h, True, walls_v), _split(walls_v, False, walls_h)


def clamp_doors_to_junctions(door_segments, walls_h, walls_v, on_tol=20,
                             min_len=14):
    """Acorta cada puerta para que no cruce una unión en T con una pared
    perpendicular. Una puerta que se pasa de la esquina/cruce se ve fea (cruza
    la línea del muro perpendicular); se recorta al lado de la unión donde está
    su centro. Devuelve la lista de puertas recortadas."""
    out = []
    for d in door_segments:
        dx1, dy1, dx2, dy2 = d
        horizontal = abs(dx2 - dx1) >= abs(dy2 - dy1)
        if horizontal:
            pos = (dy1 + dy2) / 2.0
            lo, hi = min(dx1, dx2), max(dx1, dx2)
            perp = walls_v
        else:
            pos = (dx1 + dx2) / 2.0
            lo, hi = min(dy1, dy2), max(dy1, dy2)
            perp = walls_h
        dc = (lo + hi) / 2.0
        js = []
        for p in perp:
            px1, py1, px2, py2 = p
            if horizontal:
                ppos = (px1 + px2) / 2.0
                pa, pb = min(py1, py2), max(py1, py2)
            else:
                ppos = (py1 + py2) / 2.0
                pa, pb = min(px1, px2), max(px1, px2)
            if pa - on_tol <= pos <= pb + on_tol and lo < ppos < hi:
                js.append(ppos)
        lows = [j for j in js if j <= dc]
        highs = [j for j in js if j >= dc]
        if lows:
            lo = max(lo, max(lows))
        if highs:
            hi = min(hi, min(highs))
        if hi - lo < min_len:
            continue
        if horizontal:
            out.append([lo, pos, hi, pos])
        else:
            out.append([pos, lo, pos, hi])
    return out


def extend_free_ends_to_walls(segments, walls_h, walls_v, max_reach=80,
                              align_tol=18):
    """Extiende los extremos LIBRES de cada mueble hasta la pared colineal más
    cercana para que no queden 'volando'. Un extremo se considera libre si no
    toca otro mueble. Solo se estira hacia una pared paralela alineada (misma
    fila/columna) dentro de `max_reach`."""
    if not segments:
        return segments
    segs = [list(s) for s in segments]

    def touches_other(px, py, skip):
        for j, t in enumerate(segs):
            if j == skip:
                continue
            if _point_seg_dist(px, py, t) <= 14:
                return True
        return False

    vx = [(v[0] + v[2]) / 2.0 for v in walls_v]
    vy1 = [min(v[1], v[3]) for v in walls_v]
    vy2 = [max(v[1], v[3]) for v in walls_v]
    hy = [(h[1] + h[3]) / 2.0 for h in walls_h]
    hx1 = [min(h[0], h[2]) for h in walls_h]
    hx2 = [max(h[0], h[2]) for h in walls_h]

    for i, s in enumerate(segs):
        x1, y1, x2, y2 = s
        horizontal = abs(x2 - x1) >= abs(y2 - y1)
        for end in (0, 1):
            px = s[0] if end == 0 else s[2]
            py = s[1] if end == 0 else s[3]
            if touches_other(px, py, i):
                continue
            best = None
            if horizontal:
                ly = (y1 + y2) / 2.0
                for k in range(len(walls_v)):
                    if vy1[k] - align_tol <= ly <= vy2[k] + align_tol:
                        dist = abs(vx[k] - px)
                        if dist <= max_reach and (best is None or dist < best[1]):
                            best = (vx[k], dist)
                if best is not None:
                    if end == 0:
                        s[0] = best[0]
                    else:
                        s[2] = best[0]
            else:
                lx = (x1 + x2) / 2.0
                for k in range(len(walls_h)):
                    if hx1[k] - align_tol <= lx <= hx2[k] + align_tol:
                        dist = abs(hy[k] - py)
                        if dist <= max_reach and (best is None or dist < best[1]):
                            best = (hy[k], dist)
                if best is not None:
                    if end == 0:
                        s[1] = best[0]
                    else:
                        s[3] = best[0]
    return segs
