"""Simula buildGrid + A* del editor (canvas.js) para verificar que TODOS los
recintos llegan a la salida (puerta más ancha). Núcleo en qa/routelib.py."""
import sys

sys.path.insert(0, '.')
from apps.processing.services.pipeline import ProcessingPipeline
from qa.routelib import GRID, bbox, build_blocked, make_astar, exit_goal

IMG = sys.argv[1] if len(sys.argv) > 1 else 'qa/sketches/clinica.png'
res = ProcessingPipeline().process(IMG)
assert res['success'], res['error']
objs = res['canvas_data']['objects']

blocked, cols, rows = build_blocked(objs)
free, nearest_free, astar = make_astar(blocked, cols, rows)
goal = exit_goal(objs, nearest_free)

doors = [o for o in objs if o.get('srType') in ('puerta', 'vano')]
rooms = [o for o in objs if o.get('srType') == 'recinto']
print(f"EXIT goalcell={goal}")
print(f"recintos: {len(rooms)}, puertas: {len(doors)}")
ok = 0
for i, r in enumerate(rooms):
    l, t, w, h = bbox(r)
    cx, cy = l + w / 2, t + h / 2
    sc = nearest_free(int(cx // GRID), int(cy // GRID))
    path = astar(sc, goal)
    reach = path and len(path) >= 2
    if reach:
        ok += 1
    print(f"  recinto{i} centro=({round(cx)},{round(cy)}) start={sc} -> "
          f"{'OK len=' + str(len(path)) if reach else 'SIN RUTA'}")
print(f"\n{ok}/{len(rooms)} recintos llegan a la salida")
