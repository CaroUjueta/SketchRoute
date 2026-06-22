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
def cmask(rs):
    m=np.zeros((h,w),np.uint8)
    for lo,hi in rs: m=cv2.bitwise_or(m,cv2.inRange(hsv,np.array(lo),np.array(hi)))
    return m
blue=cmask([((85,20,20),(145,255,255))]); red=cmask([((0,20,20),(14,255,255)),((165,20,20),(180,255,255))]); green=cmask([((30,20,20),(90,255,255))])
colored=cv2.dilate(cv2.bitwise_or(cv2.bitwise_or(blue,red),green),np.ones((9,9),np.uint8))
ink[colored>0]=0
dist=cv2.distanceTransform(ink,cv2.DIST_L2,3)
for t in (1.2,1.3,1.4,1.5):
    core=(dist>=t).astype(np.uint8)*255
    seed=cv2.dilate(core,np.ones((max(7,int(scale*0.0075))|1,)*2,np.uint8))
    wlls=cv2.bitwise_and(ink,seed)
    if page is not None: wlls=cv2.bitwise_and(wlls,page)
    ma=int(scale*scale*0.00025)
    wlls=P._keep_large_components(wlls,min_abs=ma)
    cv2.imwrite(f'qa/out/wmedia_t{t}.png', wlls)
    print(f't={t}: {cv2.countNonZero(wlls)} px')
