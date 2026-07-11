"""Simula buildGrid + A* del editor (canvas.js) para verificar que TODOS los
recintos llegan a la salida (puerta más ancha)."""
import sys, heapq, math
sys.path.insert(0, '.')
from apps.processing.services.pipeline import ProcessingPipeline

GRID=10; CLEAR=20; DOCW=1320; DOCH=864
OBST={'pared','mueble','zona'}

IMG = sys.argv[1] if len(sys.argv) > 1 else 'media/croquis_cuadricula.jpeg'
res=ProcessingPipeline().process(IMG)
objs=res['canvas_data']['objects']

def bbox(o):
    l=o.get('left',0); t=o.get('top',0); w=o.get('width',0); h=o.get('height',0)
    if o['type']=='ellipse':
        rx=o.get('rx',0); ry=o.get('ry',0); return (l-rx,t-ry,2*rx,2*ry)
    return (l,t,w,h)

cols=math.ceil(DOCW/GRID); rows=math.ceil(DOCH/GRID)
blocked=bytearray(cols*rows)
def rect_cells(l,t,w,h,padx,pady,val):
    x0=max(0,int((l-padx)//GRID)); x1=min(cols-1,int((l+w+padx)//GRID))
    y0=max(0,int((t-pady)//GRID)); y1=min(rows-1,int((t+h+pady)//GRID))
    for cy in range(y0,y1+1):
        for cx in range(x0,x1+1): blocked[cy*cols+cx]=val

# 1) bloquear paredes/muebles
for o in objs:
    if o.get('srType') in OBST:
        pad=CLEAR+(o.get('strokeWidth',0))/2
        l,t,w,h=bbox(o); rect_cells(l,t,w,h,pad,pad,1)
# 2) abrir puertas/vanos
OPEN=CLEAR+8
for o in objs:
    if o.get('srType') in ('puerta','vano'):
        l,t,w,h=bbox(o)
        horiz = (o.get('srDir')=='h') if o.get('srDir') else (w>=h)
        padx=1 if horiz else OPEN; pady=OPEN if horiz else 1
        rect_cells(l,t,w,h,padx,pady,0)

def free(cx,cy): return 0<=cx<cols and 0<=cy<rows and not blocked[cy*cols+cx]
def nearest_free(cx,cy):
    if free(cx,cy): return (cx,cy)
    for r in range(1,40):
        for dy in range(-r,r+1):
            for dx in range(-r,r+1):
                if max(abs(dx),abs(dy))!=r: continue
                if free(cx+dx,cy+dy): return (cx+dx,cy+dy)
    return None

def astar(s,g):
    if not s or not g: return None
    sk=s[1]*cols+s[0]; gk=g[1]*cols+g[0]
    openh=[(0,sk)]; came={}; gsc={sk:0}
    while openh:
        _,cur=heapq.heappop(openh)
        if cur==gk:
            path=[cur]
            while cur in came: cur=came[cur]; path.append(cur)
            return path
        cx,cy=cur%cols,cur//cols
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny=cx+dx,cy+dy
            if not free(nx,ny): continue
            nk=ny*cols+nx; ng=gsc[cur]+1
            if ng<gsc.get(nk,1e9):
                gsc[nk]=ng; came[nk]=cur
                f=ng+abs(nx-g[0])+abs(ny-g[1]); heapq.heappush(openh,(f,nk))
    return None

# salida = puerta más ancha (gap center)
doors=[o for o in objs if o.get('srType') in ('puerta','vano')]
doors.sort(key=lambda o:max(bbox(o)[2],bbox(o)[3]),reverse=True)
exit_d=doors[0]
gx=exit_d.get('srGapX'); gy=exit_d.get('srGapY')
if gx is None:
    l,t,w,h=bbox(exit_d); gx=l+w/2; gy=t+h/2
gcell=nearest_free(int(gx//GRID),int(gy//GRID))
print(f"EXIT door bbox={tuple(round(b) for b in bbox(exit_d))} gap=({round(gx)},{round(gy)}) goalcell={gcell}")

rooms=[o for o in objs if o.get('srType')=='recinto']
print(f"recintos: {len(rooms)}, puertas: {len(doors)}")
ok=0
for i,r in enumerate(rooms):
    l,t,w,h=bbox(r); cx=l+w/2; cy=t+h/2
    sc=nearest_free(int(cx//GRID),int(cy//GRID))
    path=astar(sc,gcell)
    reach = path and len(path)>=2
    if reach: ok+=1
    print(f"  recinto{i} centro=({round(cx)},{round(cy)}) start={sc} -> {'OK len='+str(len(path)) if reach else 'SIN RUTA'}")
print(f"\n{ok}/{len(rooms)} recintos llegan a la salida")
