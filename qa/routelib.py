"""Réplica en Python del modelo de ruteo del editor (canvas.js buildGrid + A*).

La usan qa/route_test.py, qa/diag_grid.py y los tests de regresión para medir
"rutabilidad": cuántos recintos detectados llegan a la salida. Debe mantenerse
en sincronía con las constantes de static/js/canvas.js.
"""
import heapq
import math

GRID = 10
CLEAR = 20        # holgura para abrir puertas (OPEN_PAD) — igual que canvas.js
BLOCK_PAD = 8     # holgura del bloqueo duro de paredes/muebles — igual que canvas.js
DOCW = 1320
DOCH = 864
OBST = {'pared', 'mueble', 'zona'}


def bbox(o):
    l = o.get('left', 0); t = o.get('top', 0)
    w = o.get('width', 0); h = o.get('height', 0)
    if o['type'] == 'ellipse':
        rx = o.get('rx', 0); ry = o.get('ry', 0)
        return (l - rx, t - ry, 2 * rx, 2 * ry)
    return (l, t, w, h)


def build_blocked(objs):
    """Grid de celdas bloqueadas: paredes/muebles con BLOCK_PAD, puertas abren."""
    cols = math.ceil(DOCW / GRID); rows = math.ceil(DOCH / GRID)
    blocked = bytearray(cols * rows)

    def rect_cells(l, t, w, h, padx, pady, val):
        x0 = max(0, int((l - padx) // GRID)); x1 = min(cols - 1, int((l + w + padx) // GRID))
        y0 = max(0, int((t - pady) // GRID)); y1 = min(rows - 1, int((t + h + pady) // GRID))
        for cy in range(y0, y1 + 1):
            for cx in range(x0, x1 + 1):
                blocked[cy * cols + cx] = val

    for o in objs:
        if o.get('srType') in OBST:
            pad = BLOCK_PAD + (o.get('strokeWidth', 0)) / 2
            l, t, w, h = bbox(o)
            rect_cells(l, t, w, h, pad, pad, 1)

    open_pad = CLEAR + 8
    for o in objs:
        if o.get('srType') in ('puerta', 'vano'):
            l, t, w, h = bbox(o)
            horiz = (o.get('srDir') == 'h') if o.get('srDir') else (w >= h)
            padx = 1 if horiz else open_pad
            pady = open_pad if horiz else 1
            rect_cells(l, t, w, h, padx, pady, 0)

    return blocked, cols, rows


def make_astar(blocked, cols, rows):
    def free(cx, cy):
        return 0 <= cx < cols and 0 <= cy < rows and not blocked[cy * cols + cx]

    def nearest_free(cx, cy):
        if free(cx, cy):
            return (cx, cy)
        for r in range(1, 40):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    if free(cx + dx, cy + dy):
                        return (cx + dx, cy + dy)
        return None

    def astar(s, g):
        if not s or not g:
            return None
        sk = s[1] * cols + s[0]; gk = g[1] * cols + g[0]
        openh = [(0, sk)]; came = {}; gsc = {sk: 0}
        while openh:
            _, cur = heapq.heappop(openh)
            if cur == gk:
                path = [cur]
                while cur in came:
                    cur = came[cur]; path.append(cur)
                return path
            cx, cy = cur % cols, cur // cols
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if not free(nx, ny):
                    continue
                nk = ny * cols + nx; ng = gsc[cur] + 1
                if ng < gsc.get(nk, 1e9):
                    gsc[nk] = ng; came[nk] = cur
                    f = ng + abs(nx - g[0]) + abs(ny - g[1])
                    heapq.heappush(openh, (f, nk))
        return None

    return free, nearest_free, astar


def exit_goal(objs, nearest_free):
    """Celda meta = centro del hueco de la puerta más ancha (como el editor)."""
    doors = [o for o in objs if o.get('srType') in ('puerta', 'vano')]
    if not doors:
        return None
    doors.sort(key=lambda o: max(bbox(o)[2], bbox(o)[3]), reverse=True)
    d = doors[0]
    gx = d.get('srGapX'); gy = d.get('srGapY')
    if gx is None:
        l, t, w, h = bbox(d); gx = l + w / 2; gy = t + h / 2
    return nearest_free(int(gx // GRID), int(gy // GRID))


def routability(objs):
    """(recintos_con_ruta, recintos_totales) para un canvas_data['objects']."""
    blocked, cols, rows = build_blocked(objs)
    free, nearest_free, astar = make_astar(blocked, cols, rows)
    goal = exit_goal(objs, nearest_free)
    rooms = [o for o in objs if o.get('srType') == 'recinto']
    ok = 0
    for r in rooms:
        l, t, w, h = bbox(r)
        start = nearest_free(int((l + w / 2) // GRID), int((t + h / 2) // GRID))
        path = astar(start, goal)
        if path and len(path) >= 2:
            ok += 1
    return ok, len(rooms)
