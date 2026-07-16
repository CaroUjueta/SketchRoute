"""Smoke test del editor (Playwright, JS real de canvas.js).

Verifica el contrato de la Fase 1/2:
  - dibuja un recinto con vano + salida + origen, genera rutas de evacuación
  - cada ruta auto-generada es UN fabric.Group seleccionable
  - Supr borra la flecha completa; undo la restaura
  - guardar + recargar conserva los grupos
  - sin errores de consola JS

Requiere el server corriendo:  python manage.py runserver 8001 --noreload
Uso:  python qa/smoke_editor.py
"""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sketchroute.settings')
django.setup()

from django.test import Client
from django.urls import reverse
from apps.accounts.models import User
from apps.projects.models import Project
from apps.plans.models import Plan

PORT = os.environ.get('QA_PORT', '8001')
ORIGIN = f'http://127.0.0.1:{PORT}'

SEED_JS = """
() => {
  const c = SR.qaCanvas();
  const wall = (x1, y1, x2, y2) => c.add(new fabric.Line([x1, y1, x2, y2], {
    stroke: '#1f2937', strokeWidth: 8, strokeLineCap: 'square',
    srType: 'pared', srCat: 'shape',
    originX: 'center', originY: 'center', left: (x1 + x2) / 2, top: (y1 + y2) / 2,
  }));
  wall(300, 200, 900, 200);
  wall(300, 600, 900, 600);
  wall(300, 200, 300, 600);
  wall(900, 200, 900, 360);      // pared derecha con hueco 360-440
  wall(900, 440, 900, 600);
  // vano sobre el hueco para que buildGrid lo abra
  c.add(new fabric.Rect({ left: 892, top: 360, width: 16, height: 80,
    fill: 'transparent', srType: 'vano', srCat: 'shape', srDir: 'v' }));
  c.add(new fabric.Rect({ left: 960, top: 378, width: 44, height: 44, fill: '#15803d',
    srType: 'salida_emergencia', srCat: 'icon' }));
  c.add(new fabric.Circle({ left: 480, top: 390, radius: 9, fill: '#16a34a',
    srType: 'origen-evac', srCat: 'marker', srHidden: true }));
  c.renderAll();
}
"""

COUNT_ROUTES = "SR.qaCanvas().getObjects().filter(o => o.srCat === 'ruta-auto').length"
ROUTE_TYPES = "[...new Set(SR.qaCanvas().getObjects().filter(o => o.srCat === 'ruta-auto').map(o => o.type))]"


def main():
    user = User.objects.get(username='Julian')
    proj = Project.objects.filter(user=user).first() or Project.objects.create(
        user=user, name='QA smoke', description='')
    plan = Plan.objects.create(project=proj, name='QA smoke editor', canvas_data=None)
    cl = Client()
    cl.force_login(user)
    sid = cl.cookies['sessionid'].value

    from playwright.sync_api import sync_playwright
    url = ORIGIN + reverse('plan_editor', args=[plan.pk])
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={'width': 1600, 'height': 1000})
            ctx.add_cookies([{'name': 'sessionid', 'value': sid, 'url': ORIGIN}])
            ctx.route('**/*', lambda r: r.continue_()
                      if r.request.url.startswith(ORIGIN) else r.abort())
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))

            page.goto(url, wait_until='networkidle')
            page.wait_for_timeout(1500)

            page.evaluate(SEED_JS)
            page.evaluate("SR.generateEvac()")
            page.wait_for_timeout(400)

            n = page.evaluate(COUNT_ROUTES)
            assert n >= 1, f'esperaba >=1 ruta generada, hay {n}'
            types = page.evaluate(ROUTE_TYPES)
            assert types == ['group'], f'las rutas auto deben ser groups, son {types}'

            # seleccionar la flecha completa y borrarla
            page.evaluate("""() => {
              const c = SR.qaCanvas();
              const r = c.getObjects().find(o => o.srCat === 'ruta-auto');
              c.setActiveObject(r); c.renderAll();
            }""")
            active = page.evaluate("SR.qaCanvas().getActiveObject().type")
            assert active == 'group', f'la selección debe ser un group, es {active}'
            page.evaluate("SR.deleteSelected()")
            page.wait_for_timeout(300)
            assert page.evaluate(COUNT_ROUTES) == n - 1, 'Supr no borró la flecha completa'

            # undo restaura
            page.evaluate("SR.undo()")
            page.wait_for_timeout(500)
            assert page.evaluate(COUNT_ROUTES) == n, 'undo no restauró la flecha'

            # guardar + recargar conserva los grupos
            page.evaluate("SR.save()")
            page.wait_for_timeout(1200)
            page.reload(wait_until='networkidle')
            page.wait_for_timeout(1500)
            assert page.evaluate(COUNT_ROUTES) == n, 'recarga perdió rutas'
            assert page.evaluate(ROUTE_TYPES) == ['group'], 'recarga desagrupó las rutas'

            browser.close()
            fatal = [e for e in errors if 'ERR_FAILED' not in e]
            assert not fatal, f'errores JS: {fatal}'
        print(f'SMOKE OK — {n} ruta(s) como group, borrar/undo/guardar/recargar correctos')
    finally:
        plan.delete()


if __name__ == '__main__':
    main()
