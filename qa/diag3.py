"""Probar deteccion de hoja con iluminacion normalizada y deteccion de paredes."""
import sys
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IMG = r"C:\Users\Julian\.claude\image-cache\16d78e5e-5fa8-4c12-88f9-4a5c23f31f99\2.png"
OUT = Path(__file__).resolve().parent / "out"

img = cv2.imread(IMG)
h, w = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

# --- normalizar iluminacion ---
sigma = max(h, w) / 16
bg = cv2.GaussianBlur(gray, (0, 0), sigma)
norm = cv2.divide(gray, bg, scale=192).astype(np.uint8)
cv2.imwrite(str(OUT / "norm.png"), norm)

_, bright = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
k = max(15, int(min(h, w) * 0.02)) | 1
bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
n, labels, stats, _ = cv2.connectedComponentsWithStats(bright, 8)
idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
page = np.zeros((h, w), np.uint8)
page[labels == idx] = 255
# convex hull para tapar la hoja entera
cnts, _ = cv2.findContours(page, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
hull = cv2.convexHull(np.vstack(cnts))
page_hull = np.zeros((h, w), np.uint8)
cv2.drawContours(page_hull, [hull], -1, 255, -1)
erode_k = max(5, int(min(h, w) * 0.012)) | 1
page_hull = cv2.erode(page_hull, np.ones((erode_k, erode_k), np.uint8))
cv2.imwrite(str(OUT / "page_hull.png"), page_hull)
print("page_hull px:", cv2.countNonZero(page_hull), "of", h * w)

# --- deteccion de paredes: tinta oscura, baja saturacion, dentro de hoja ---
inside = page_hull > 0
S = hsv[:, :, 1]
# umbral adaptativo: trazos mas oscuros que el papel local
block = max(31, int(min(h, w) * 0.05)) | 1
ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY_INV, block, 10)
ink[~inside] = 0
cv2.imwrite(str(OUT / "ink_adaptive.png"), ink)

# colores (azul/rojo/verde) para restar
def color_mask(ranges):
    m = np.zeros((h, w), np.uint8)
    for lo, hi in ranges:
        m = cv2.bitwise_or(m, cv2.inRange(hsv, np.array(lo), np.array(hi)))
    return m

blue = color_mask([((85, 20, 20), (145, 255, 255))])
red = color_mask([((0, 20, 20), (14, 255, 255)), ((165, 20, 20), (180, 255, 255))])
green = color_mask([((30, 20, 20), (90, 255, 255))])
colored = cv2.bitwise_or(cv2.bitwise_or(blue, red), green)
colored = cv2.dilate(colored, np.ones((7, 7), np.uint8))

# paredes = tinta - color, baja saturacion
walls = ink.copy()
walls[colored > 0] = 0
walls[S > 70] = 0
cv2.imwrite(str(OUT / "walls_raw.png"), walls)

# quitar grilla fina con apertura (grilla delgada, pared gruesa)
ok = max(3, int(min(h, w) * 0.004)) | 1
walls_open = cv2.morphologyEx(walls, cv2.MORPH_OPEN, np.ones((ok, ok), np.uint8))
cv2.imwrite(str(OUT / "walls_open.png"), walls_open)
print("walls_raw px:", cv2.countNonZero(walls), "walls_open px:", cv2.countNonZero(walls_open), "open_k:", ok)
