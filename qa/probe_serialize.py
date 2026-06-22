"""Carga el canvas_data en un Fabric limpio (sin el editor) y reporta qué
objeto rompe toObject() — el que dispara los 'snapshot error'."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sketchroute.settings')
import django; django.setup()
from apps.processing.services.pipeline import ProcessingPipeline
from playwright.sync_api import sync_playwright

SK = sys.argv[1]
cd = ProcessingPipeline().process(SK)['canvas_data']

PAGE = """<!doctype html><html><head>
<script src="https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js"></script>
</head><body><canvas id="c" width="1320" height="864"></canvas></body></html>"""

with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page()
    pg.set_content(PAGE, wait_until='networkidle')
    res = pg.evaluate("""(cd) => new Promise(resolve => {
        const canvas = new fabric.Canvas('c');
        canvas.loadFromJSON(cd, () => {
            const bad = [];
            canvas.getObjects().forEach((o, idx) => {
                try { o.toObject(['srType']); }
                catch (e) { bad.push({idx, type:o.type, srType:o.srType, err:String(e)}); }
            });
            let whole = 'ok';
            try { JSON.stringify(canvas.toJSON(['srType'])); }
            catch (e) { whole = String(e); }
            resolve({bad, whole, total: canvas.getObjects().length});
        });
    })""", cd)
    b.close()

print('objetos:', res['total'])
print('toJSON global:', res['whole'][:120])
print('objetos que fallan toObject:')
for x in res['bad']:
    print('  ', x)
# tipos de objeto en el canvas_data crudo
from collections import Counter
print('tipos en canvas_data:', dict(Counter(o.get('type') for o in cd['objects'])))
print('text/i-text sin styles:', [o.get('srType') for o in cd['objects'] if o.get('type') in ('text','i-text') and 'styles' not in o])
