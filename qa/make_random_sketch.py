"""Genera un croquis ALEATORIO 'como debe ser' (colores que el pipeline espera:
paredes=NEGRO, puertas=AZUL, vanos=VERDE, muebles=ROJO) para explorar distintas
plantas y rutas posibles en cada iteración del loop.

Uso: python qa/make_random_sketch.py [seed] -> imprime la ruta del PNG generado.
"""
import os
import sys
import time
import random
import numpy as np
import cv2

BLACK = (20, 20, 20)
BLUE = (210, 120, 20)
GREEN = (40, 170, 40)
RED = (40, 40, 210)

OUT = os.path.join(os.path.dirname(__file__), 'sketches')
os.makedirs(OUT, exist_ok=True)


def gen(seed):
    rng = random.Random(seed)
    W, H = 1300, 900
    img = np.full((H, W, 3), 255, np.uint8)
    M = 80                                  # margen
    L, R, T, B = M, W - M, M, H - M

    def wall(p1, p2, t=7):
        cv2.line(img, p1, p2, BLACK, t)

    # contorno
    wall((L, T), (R, T)); wall((L, B), (R, B))
    wall((L, T), (L, B)); wall((R, T), (R, B))

    # pasillo horizontal a una altura aleatoria
    cy = rng.randint(T + 240, B - 240)
    ch = rng.choice([70, 90, 110])          # alto del pasillo
    top_y, bot_y = cy - ch // 2, cy + ch // 2

    # columnas (2..4) → habitaciones arriba y abajo, repartidas uniformemente
    # con jitter (evita columnas demasiado angostas para una puerta)
    ncol = rng.randint(2, 4)
    inner = R - L
    xs = [L]
    for k in range(1, ncol):
        base = L + inner * k / ncol
        xs.append(int(base + rng.randint(-50, 50)))
    xs.append(R)

    doors = []   # (p1,p2) huecos a marcar en azul
    vanos = []
    # divisiones verticales arriba y abajo (con offsets distintos → variedad)
    for x in xs[1:-1]:
        wall((x, T), (x, top_y))
        wall((x, bot_y), (x, B))

    # paredes del pasillo con un hueco (puerta) por habitación
    def corridor_wall(y, cells):
        for (a, b) in cells:
            wall((a, y), (b, y))

    def gaps_for(side_y):
        cells, ds = [], []
        prev = L
        for i in range(len(xs) - 1):
            x0, x1 = xs[i], xs[i + 1]
            span = x1 - x0
            gw = min(rng.randint(55, 90), max(30, span - 50))
            lo, hi = x0 + 25, x1 - 25 - gw
            gx = rng.randint(lo, hi) if hi > lo else (x0 + x1 - gw) // 2
            cells.append((prev, gx)); prev = gx + gw
            ds.append((gx, gx + gw))
        cells.append((prev, R))
        return cells, ds

    top_cells, top_doors = gaps_for(top_y)
    bot_cells, bot_doors = gaps_for(bot_y)
    corridor_wall(top_y, top_cells)
    corridor_wall(bot_y, bot_cells)

    # marcar puertas (azul); una de ellas como vano (verde)
    alld = [(y, g) for y, gs in ((top_y, top_doors), (bot_y, bot_doors)) for g in gs]
    vano_idx = rng.randrange(len(alld))
    for i, (y, (gx0, gx1)) in enumerate(alld):
        if i == vano_idx:
            cv2.line(img, (gx0, y), (gx1, y), GREEN, 5)
        else:
            cv2.line(img, (gx0, y), (gx1, y), BLUE, 5)

    # muebles (rojo) aleatorios dentro de algunas habitaciones
    for i in range(len(xs) - 1):
        for (ya, yb) in ((T + 20, top_y - 20), (bot_y + 20, B - 20)):
            if rng.random() < 0.6:
                rw = rng.randint(110, 200); rh = rng.randint(70, 130)
                rx = rng.randint(xs[i] + 30, max(xs[i] + 31, xs[i + 1] - rw - 30))
                ry = rng.randint(ya, max(ya + 1, yb - rh))
                cv2.rectangle(img, (rx, ry), (rx + rw, ry + rh), RED, 3)
    return img


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else int(time.time())
    path = os.path.join(OUT, f'auto_{seed}.png')
    cv2.imwrite(path, gen(seed))
    print(path)


if __name__ == '__main__':
    main()
