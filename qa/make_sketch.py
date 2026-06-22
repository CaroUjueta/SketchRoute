"""Genera croquis sintéticos 'como debe ser', con los colores que el pipeline
espera (ver COLOR_MAP): paredes=NEGRO, puertas=AZUL, vanos=VERDE, muebles=ROJO.

Dibuja sobre papel blanco, líneas rectas y gruesas, dejando huecos donde van
las puertas (y un trazo azul de la puerta en ese hueco). Es exactamente lo que
una persona dibujaría a mano, pero limpio."""
import os
import numpy as np
import cv2

BLACK = (20, 20, 20)      # paredes
BLUE  = (210, 120, 20)    # puertas (BGR de un azul)
GREEN = (40, 170, 40)     # vanos
RED   = (40, 40, 210)     # muebles
WHITE = (255, 255, 255)

OUT = os.path.join(os.path.dirname(__file__), 'sketches')
os.makedirs(OUT, exist_ok=True)


def wall(img, p1, p2, t=7):
    cv2.line(img, p1, p2, BLACK, t)


def door(img, p1, p2):
    # trazo azul de la puerta dentro del hueco de la pared
    cv2.line(img, p1, p2, BLUE, 5)


def vano(img, p1, p2):
    cv2.line(img, p1, p2, GREEN, 5)


def furniture(img, x, y, w, h):
    cv2.rectangle(img, (x, y), (x + w, y + h), RED, 3)


def clinica():
    """Planta tipo: pasillo central con 4 consultorios + recepción + baño."""
    img = np.full((900, 1300, 3), 255, np.uint8)
    # contorno exterior
    wall(img, (80, 80), (1220, 80))
    wall(img, (80, 820), (1220, 820))
    wall(img, (80, 80), (80, 820))
    wall(img, (1220, 80), (1220, 820))

    # pared horizontal media (pasillo) con huecos para puertas
    # tramo superior de habitaciones
    for x0 in (80, 420, 760):
        wall(img, (x0, 420), (x0, 80))                # divisiones verticales arriba
    for x0 in (420, 760, 1100):
        wall(img, (x0, 820), (x0, 480))               # divisiones verticales abajo

    # pared del pasillo (dos franjas con hueco = puerta a cada cuarto)
    segs_top = [(80, 300), (360, 480), (700, 1040), (1100, 1220)]
    for a, b in segs_top:
        wall(img, (a, 420), (b, 420))
    segs_bot = [(80, 360), (460, 700), (800, 1040), (1100, 1220)]
    for a, b in segs_bot:
        wall(img, (a, 480), (b, 480))

    # puertas (azul) en los huecos del pasillo
    door(img, (300, 420), (360, 420))
    door(img, (480, 420), (700, 420))   # hueco ancho → puerta doble
    door(img, (1040, 420), (1100, 420))
    door(img, (360, 480), (460, 480))
    door(img, (700, 480), (800, 480))
    door(img, (1040, 480), (1100, 480))

    # un vano (verde) entre recepción y pasillo
    vano(img, (200, 420), (300, 420))

    # muebles (rojo): camillas / escritorios
    furniture(img, 150, 150, 180, 90)
    furniture(img, 520, 150, 150, 90)
    furniture(img, 900, 560, 220, 120)
    furniture(img, 150, 560, 150, 110)
    return img


def bodega():
    """Espacio grande con 2 cuartos y salida lateral."""
    img = np.full((800, 1200, 3), 255, np.uint8)
    wall(img, (70, 70), (1130, 70))
    wall(img, (70, 730), (1130, 730))
    wall(img, (70, 70), (70, 730))
    wall(img, (1130, 70), (1130, 730))
    # cuarto interior arriba-izq con puerta
    wall(img, (70, 360), (450, 360))
    wall(img, (450, 70), (450, 280))
    door(img, (450, 280), (450, 360))
    # cuarto interior abajo-der con vano
    wall(img, (760, 470), (1130, 470))
    wall(img, (760, 470), (760, 730))
    vano(img, (760, 560), (760, 640))
    # muebles
    furniture(img, 850, 150, 200, 150)
    furniture(img, 150, 470, 200, 180)
    return img


for name, fn in (('clinica', clinica), ('bodega', bodega)):
    path = os.path.join(OUT, f'{name}.png')
    cv2.imwrite(path, fn())
    print('escrito', path)
