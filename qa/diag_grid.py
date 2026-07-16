"""Diagnóstico visual del grid de rutas: celdas bloqueadas, huecos de puertas,
centros de recintos y salida. Vuelca qa/out/diag_grid_<tag>.png y números por
puerta para distinguir por qué un recinto queda 'sin salida'.

Uso: python qa/diag_grid.py [imagen]  (default qa/sketches/clinica.png)
"""
import math
import sys

import cv2
import numpy as np

sys.path.insert(0, '.')
from apps.processing.services.pipeline import ProcessingPipeline

from qa.routelib import GRID, CLEAR, BLOCK_PAD, DOCW, DOCH, OBST

IMG = sys.argv[1] if len(sys.argv) > 1 else 'qa/sketches/clinica.png'
TAG = IMG.split('/')[-1].split('\\')[-1].rsplit('.', 1)[0]

res = ProcessingPipeline().process(IMG)
assert res['success'], res['error']
objs = res['canvas_data']['objects']


def bbox(o):
    l = o.get('left', 0); t = o.get('top', 0)
    w = o.get('width', 0); h = o.get('height', 0)
    if o['type'] == 'ellipse':
        rx = o.get('rx', 0); ry = o.get('ry', 0)
        return (l - rx, t - ry, 2 * rx, 2 * ry)
    return (l, t, w, h)


cols = math.ceil(DOCW / GRID); rows = math.ceil(DOCH / GRID)
blocked = np.zeros((rows, cols), dtype=np.uint8)
opened = np.zeros((rows, cols), dtype=np.uint8)


def rect_cells(arr, l, t, w, h, padx, pady, val):
    x0 = max(0, int((l - padx) // GRID)); x1 = min(cols - 1, int((l + w + padx) // GRID))
    y0 = max(0, int((t - pady) // GRID)); y1 = min(rows - 1, int((t + h + pady) // GRID))
    arr[y0:y1 + 1, x0:x1 + 1] = val


for o in objs:
    if o.get('srType') in OBST:
        pad = BLOCK_PAD + (o.get('strokeWidth', 0)) / 2
        l, t, w, h = bbox(o)
        rect_cells(blocked, l, t, w, h, pad, pad, 1)

OPEN = CLEAR + 8
print('--- puertas/vanos ---')
for o in objs:
    if o.get('srType') in ('puerta', 'vano'):
        l, t, w, h = bbox(o)
        horiz = (o.get('srDir') == 'h') if o.get('srDir') else (w >= h)
        padx = 1 if horiz else OPEN
        pady = OPEN if horiz else 1
        rect_cells(blocked, l, t, w, h, padx, pady, 0)
        rect_cells(opened, l, t, w, h, padx, pady, 1)
        print(f"  {o['srType']:6s} type={o['type']:5s} bbox=({l:.0f},{t:.0f},{w:.0f},{h:.0f}) "
              f"srDir={o.get('srDir')} srGap=({o.get('srGapX')},{o.get('srGapY')}) horiz={horiz}")

print('--- tramos de pared (extremos) ---')
for o in objs:
    if o.get('srType') == 'pared':
        l, t, w, h = bbox(o)
        print(f"  pared bbox=({l:.0f},{t:.0f},{w:.0f},{h:.0f})")

# imagen: blanco libre, gris bloqueado, verde hueco abierto, azul recintos, rojo salida
img = np.full((rows, cols, 3), 255, dtype=np.uint8)
img[blocked == 1] = (170, 170, 170)
img[(opened == 1) & (blocked == 0)] = (120, 220, 120)

for o in objs:
    if o.get('srType') == 'recinto':
        l, t, w, h = bbox(o)
        cx, cy = int((l + w / 2) // GRID), int((t + h / 2) // GRID)
        cv2.circle(img, (cx, cy), 2, (200, 120, 0), -1)

doors = [o for o in objs if o.get('srType') in ('puerta', 'vano')]
doors.sort(key=lambda o: max(bbox(o)[2], bbox(o)[3]), reverse=True)
if doors:
    gx = doors[0].get('srGapX'); gy = doors[0].get('srGapY')
    if gx is None:
        l, t, w, h = bbox(doors[0]); gx = l + w / 2; gy = t + h / 2
    cv2.circle(img, (int(gx // GRID), int(gy // GRID)), 3, (0, 0, 230), -1)

img = cv2.resize(img, (cols * 8, rows * 8), interpolation=cv2.INTER_NEAREST)
out = f'qa/out/diag_grid_{TAG}.png'
cv2.imwrite(out, img)
print('->', out)
