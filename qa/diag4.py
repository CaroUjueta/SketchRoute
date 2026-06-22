"""Filtro de grosor por distance transform para quitar cuadricula."""
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

# ink adaptativo
block = max(31, int(min(h, w) * 0.05)) | 1
ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY_INV, block, 10)

# quitar colores
def color_mask(ranges):
    m = np.zeros((h, w), np.uint8)
    for lo, hi in ranges:
        m = cv2.bitwise_or(m, cv2.inRange(hsv, np.array(lo), np.array(hi)))
    return m

blue = color_mask([((85, 20, 20), (145, 255, 255))])
red = color_mask([((0, 20, 20), (14, 255, 255)), ((165, 20, 20), (180, 255, 255))])
green = color_mask([((30, 20, 20), (90, 255, 255))])
colored = cv2.dilate(cv2.bitwise_or(cv2.bitwise_or(blue, red), green), np.ones((7, 7), np.uint8))

black = ink.copy()
black[colored > 0] = 0

# distance transform: grosor del trazo
dist = cv2.distanceTransform(black, cv2.DIST_L2, 3)
print("dist max:", dist.max())
vals = dist[dist > 0]
print("dist percentiles (px radius):", np.percentile(vals, [50, 75, 90, 95, 99]))

for t in (1.5, 2.0, 2.5, 3.0):
    core = (dist >= t).astype(np.uint8) * 255
    # reconstruir trazo completo: dilatar core y AND con black
    seed = cv2.dilate(core, np.ones((9, 9), np.uint8))
    rec = cv2.bitwise_and(black, seed)
    cv2.imwrite(str(OUT / f"thick_t{t}.png"), rec)
    print(f"t={t}: core={cv2.countNonZero(core)} reconstructed={cv2.countNonZero(rec)}")
