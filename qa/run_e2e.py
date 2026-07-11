"""E2E real: croquis sintético → pipeline → editor en navegador headless
(Playwright) → genera rutas evac+sanitaria, señaliza (NTC) y exporta el PDF
final de 2 páginas. Captura screenshots y el PDF en qa/out/.

Corre el JS REAL del editor (Fabric.js, A*, jsPDF), no una reimplementación.
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sketchroute.settings')
django.setup()

from django.core.files import File
from django.test import Client
from django.urls import reverse
from apps.accounts.models import User
from apps.projects.models import Project
from apps.plans.models import Plan
from apps.processing.services.pipeline import ProcessingPipeline

BASE = os.path.dirname(__file__)
OUT = os.path.join(BASE, 'out')
os.makedirs(OUT, exist_ok=True)
PORT = os.environ.get('QA_PORT', '8001')
ORIGIN = f'http://127.0.0.1:{PORT}'

SKETCH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, 'sketches', 'clinica.png')
TAG = os.path.splitext(os.path.basename(SKETCH))[0]


def fobj(**kw):
    base = {'version': '5.3.1', 'originX': 'left', 'originY': 'top'}
    base.update(kw)
    return base


def seed(canvas_data):
    """Coloca lo que pondría el usuario: salida, orígenes de evacuación y
    canecas, ubicados en los centros de los recintos detectados."""
    rooms = []
    for o in canvas_data['objects']:
        if o.get('srType') == 'recinto':
            cx = o['left'] + o.get('width', 0) / 2
            cy = o['top'] + o.get('height', 0) / 2
            rooms.append((o.get('width', 0) * o.get('height', 0), cx, cy))
    rooms.sort(reverse=True)            # de mayor a menor área
    pts = [(cx, cy) for _, cx, cy in rooms]
    if not pts:
        pts = [(660, 432)]
    objs = canvas_data['objects']

    # salida en el recinto más grande (suele ser pasillo/recepción)
    sx, sy = pts[0]
    objs.append(fobj(type='rect', left=sx - 22, top=sy - 22, width=44, height=44,
                     fill='#15803d', stroke='#0f5132', strokeWidth=2,
                     srType='salida_emergencia', srCat='icon'))
    objs.append(fobj(type='text', text='SALIDA', left=sx, top=sy + 26, originX='center',
                     fontSize=16, fontFamily='DM Sans', fill='#15803d', styles={},
                     srType='texto', srCat='text'))

    # orígenes de evacuación (verdes, invisibles en PDF) en varios recintos
    for (ox, oy) in pts[1:4]:
        objs.append(fobj(type='circle', left=ox - 9, top=oy - 9, radius=9,
                         fill='#16a34a', stroke='#ffffff', strokeWidth=2,
                         srType='origen-evac', srCat='marker', srHidden=True))

    # canecas (cada una traza su ruta sanitaria con su color)
    canecas = ['caneca_ordinaria', 'caneca_biosani', 'caneca_reciclable', 'caneca_corto']
    fills = {'caneca_ordinaria': '#1f2937', 'caneca_biosani': '#dc2626',
             'caneca_reciclable': '#9ca3af', 'caneca_corto': '#dc2626'}
    for i, (cx, cy) in enumerate(pts[1:5]):
        t = canecas[i % len(canecas)]
        objs.append(fobj(type='circle', left=cx + 24, top=cy - 16, radius=16,
                         fill=fills[t], stroke='#111827', strokeWidth=2,
                         srType=t, srCat='icon'))
    return len(pts)


def build_plan():
    user = User.objects.get(username='Julian')
    proj = Project.objects.filter(user=user).first() or \
        Project.objects.create(user=user, name='QA E2E', description='')
    print('Procesando', SKETCH, '...')
    res = ProcessingPipeline().process(SKETCH)
    assert res['success'], res['error']
    cd = res['canvas_data']
    nrooms = seed(cd)
    print(f'  detectado: paredes={res["walls"]} puertas={res["doors"]} '
          f'muebles={res["furniture"]} recintos={res["rooms"]} | sembrados en {nrooms} recintos')
    plan = Plan.objects.create(project=proj, name=f'QA {TAG}', canvas_data=cd, is_vectorized=True)
    with open(SKETCH, 'rb') as f:
        plan.original_image.save(f'{TAG}.png', File(f), save=True)
    return user, plan


def session_cookie(user):
    c = Client()
    c.force_login(user)
    return c.cookies['sessionid'].value


def run_browser(plan, sessionid):
    from playwright.sync_api import sync_playwright
    editor_url = ORIGIN + reverse('plan_editor', args=[plan.pk])
    with sync_playwright() as pw:
        # En entornos con Chromium preinstalado (p. ej. CI) se usa ese binario.
        exe = os.environ.get('SR_CHROMIUM') or (
            '/opt/pw-browsers/chromium' if os.path.exists('/opt/pw-browsers/chromium') else None)
        browser = pw.chromium.launch(executable_path=exe)
        ctx = browser.new_context(viewport={'width': 1600, 'height': 1000}, accept_downloads=True)
        ctx.add_cookies([{'name': 'sessionid', 'value': sessionid, 'url': ORIGIN}])
        # Hermético: sin internet, solo el servidor local (fuentes/CDNs colgarían la carga)
        ctx.route('**/*', lambda route: route.continue_()
                  if route.request.url.startswith(ORIGIN) else route.abort())
        page = ctx.new_page()
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(str(e)))

        print('Abriendo editor:', editor_url)
        page.goto(editor_url, wait_until='networkidle')
        page.wait_for_timeout(2500)            # SR.init + loadFromJSON async

        # generar rutas + señalización (JS real del editor)
        page.evaluate("SR.generateEvac()")
        page.wait_for_timeout(400)
        page.evaluate("SR.generateSan()")
        page.wait_for_timeout(400)
        page.evaluate("SR.autoSignal && SR.autoSignal()")
        page.wait_for_timeout(800)

        status = page.eval_on_selector('#ed-status', 'el => el.textContent')
        print('Estado editor:', status)

        page.screenshot(path=os.path.join(OUT, f'{TAG}_editor.png'), full_page=True)
        wrap = page.query_selector('#canvasWrap')
        if wrap:
            wrap.screenshot(path=os.path.join(OUT, f'{TAG}_canvas.png'))

        # exportar el PDF de 2 páginas y capturar la descarga
        with page.expect_download(timeout=15000) as di:
            page.evaluate("SR.doExport(['evac','san'])")
        dl = di.value
        pdf_path = os.path.join(OUT, f'{TAG}_resultado.pdf')
        dl.save_as(pdf_path)
        print('PDF guardado en', pdf_path)

        browser.close()
        if errors:
            print('Errores de consola JS:')
            for e in errors[:15]:
                print('   -', e)
        return pdf_path


def main():
    user, plan = build_plan()
    sid = session_cookie(user)
    try:
        pdf = run_browser(plan, sid)
    finally:
        plan.delete()
    # render del PDF a PNG para inspección
    try:
        import fitz  # PyMuPDF (puede no estar)
        doc = fitz.open(pdf)
        for i, pg in enumerate(doc):
            pix = pg.get_pixmap(dpi=110)
            pix.save(os.path.join(OUT, f'{TAG}_pdf_p{i+1}.png'))
        print('PDF tiene', doc.page_count, 'páginas → PNG por página')
    except Exception as e:
        print('(no se pudo rasterizar el PDF:', e, ')')


if __name__ == '__main__':
    main()
