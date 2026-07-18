"""Dibujos de prueba propios para la batería de calidad foto→mapa:
  - farmacia.png : local con pasillo central y 4 zonas (croquis limpio)
  - ele.png      : planta en L (ejercita el hull rectilíneo)
  - ele_torcida.png : la misma L rotada 6° con fondo papel (ejercita deskew)
"""
import os
import sys

import cv2
import numpy as np

BLACK = (20, 20, 20)
BLUE = (210, 120, 20)
GREEN = (40, 170, 40)
RED = (40, 40, 210)
WHITE = (255, 255, 255)

OUT = os.path.join(os.path.dirname(__file__), 'sketches')


def wall(img, p1, p2, t=7):
    cv2.line(img, p1, p2, BLACK, t)


def door(img, p1, p2, t=7):
    cv2.line(img, p1, p2, BLUE, t)


def farmacia():
    img = np.full((900, 1300, 3), 255, np.uint8)
    # exterior
    wall(img, (100, 100), (1200, 100))
    wall(img, (100, 800), (1200, 800))
    wall(img, (100, 100), (100, 800))
    wall(img, (1200, 100), (1200, 800))
    # pasillo horizontal central (y 420-480)
    # arriba: dos zonas con puerta al pasillo
    wall(img, (100, 420), (380, 420)); door(img, (380, 420), (450, 420)); wall(img, (450, 420), (700, 420))
    door(img, (700, 420), (770, 420)); wall(img, (770, 420), (1200, 420))
    wall(img, (650, 100), (650, 420))
    # abajo: dos zonas
    wall(img, (100, 480), (500, 480)); door(img, (500, 480), (570, 480)); wall(img, (570, 480), (900, 480))
    door(img, (900, 480), (970, 480)); wall(img, (970, 480), (1200, 480))
    wall(img, (700, 480), (700, 800))
    # salida a la calle: puerta grande en la pared derecha, a la altura del pasillo
    door(img, (1200, 420), (1200, 480), t=9)
    # muebles
    cv2.rectangle(img, (180, 180), (420, 300), RED, 5)
    cv2.rectangle(img, (850, 600), (1080, 720), RED, 5)
    return img


def ele():
    img = np.full((900, 1300, 3), 255, np.uint8)
    # L: brazo horizontal arriba (100,100)-(1200,450) + brazo vertical izquierdo (100,450)-(600,800)
    wall(img, (100, 100), (1200, 100))
    wall(img, (1200, 100), (1200, 450))
    wall(img, (600, 450), (1200, 450))
    wall(img, (600, 450), (600, 800))
    wall(img, (100, 800), (600, 800))
    wall(img, (100, 100), (100, 800))
    # división del brazo horizontal con puerta
    wall(img, (700, 100), (700, 300)); door(img, (700, 300), (700, 370)); wall(img, (700, 370), (700, 450))
    # división del brazo vertical con puerta
    wall(img, (100, 560), (300, 560)); door(img, (300, 560), (370, 560)); wall(img, (370, 560), (600, 560))
    # salida principal: puerta grande abajo del brazo vertical
    door(img, (250, 800), (360, 800), t=9)
    # mueble
    cv2.rectangle(img, (850, 200), (1080, 330), RED, 5)
    return img


def torcida(img, deg=6):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderValue=(246, 244, 240))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(os.path.join(OUT, 'farmacia.png'), farmacia())
    cv2.imwrite(os.path.join(OUT, 'ele.png'), ele())
    cv2.imwrite(os.path.join(OUT, 'ele_torcida.png'), torcida(ele()))
    print('dibujos en', OUT)
