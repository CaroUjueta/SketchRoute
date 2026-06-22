import sys; sys.path.insert(0,'.')
import cv2, numpy as np
from apps.processing.services import preprocessing as P

img = cv2.imread('media/croquis_cuadricula.jpeg')
h,w = img.shape[:2]; scale=min(h,w)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
page = P.detect_page_mask(img)

block = max(31,int(scale*0.05))|1
ink = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,block,10)
if page is not None: ink = cv2.bitwise_and(ink, page)

H = hsv[:,:,0]; S = hsv[:,:,1]; V = hsv[:,:,2]
m = ink>0
print('ink pixels:', int(m.sum()))
print('HUE percentiles en ink:', np.percentile(H[m],[10,25,50,75,90]))
print('SAT percentiles en ink:', np.percentile(S[m],[10,25,50,75,90]))

# blue-ish (grid): hue 90-140
blue_ish = m & (H>=90)&(H<=140)
neutral = m & ((H<90)|(H>140))
print('blue-ish ink px:', int(blue_ish.sum()), 'SAT pct:', np.percentile(S[blue_ish],[25,50,75,90]) if blue_ish.sum() else None)
print('neutral  ink px:', int(neutral.sum()), 'SAT pct:', np.percentile(S[neutral],[25,50,75,90]) if neutral.sum() else None)

# probar: grid = hue azul Y saturacion > t. Quitar grid de ink.
for sat_t in (12,16,20,25):
    grid = m & (H>=90)&(H<=140)&(S>=sat_t)
    walls = ink.copy(); walls[grid]=0
    cv2.imwrite(f'qa/out/walls_colorgrid_s{sat_t}.png', walls)
    print(f'sat_t={sat_t}: grid removed={int(grid.sum())} walls left={int((walls>0).sum())}')
