/* ============================================================
   SketchRoute — Editor de planos (módulo SR)
   Canvas oficio horizontal (330 × 216 mm) sobre Fabric.js 5.

   Flujo: dibujás el mapa (paredes/muebles/puertas) y colocás los
   elementos. Las flechas se generan solas:
     · Evacuación: orígenes verdes (invisibles en PDF) → salida.
     · Sanitaria : cada caneca (visible) → salida, con SU color.
   Ruteo con A* en grilla → ángulos de 90°, sin cruzar paredes.
   Rutas que van al mismo destino se fusionan.
   ============================================================ */

const DOC  = { w: 1320, h: 864 };  // ratio oficio horizontal (330×216 mm)
const GRID = 10;                   // px por celda de la grilla de ruteo
const CLEAR = 20;                  // holgura alrededor de obstáculos (px)
const SNAP = 24;                   // radio de enganche entre extremos (px)
const LINE_W = 3;                  // grosor del trazo de la flecha (px) — bien delgaditas
const ARROW_GAP = 100;             // separación entre flechas → a lo largo de la ruta (px)
const ARROW_LEN = 58;              // largo de la cola de cada flecha (px) — largas
const ARROW_SIZE = 11;             // apertura de la punta (px)
const ARROW_MINDIST = 48;          // distancia mínima entre flechas del mismo color
const ARROW_MINGLOBAL = 30;        // distancia mínima entre flechas de CUALQUIER color (anti-encimado en cruces)
const AUTOSAVE_MS = 2500;          // espera tras editar antes de autoguardar

const OBSTACLES = new Set(['pared', 'mueble', 'zona']);
const EVAC_COLOR = '#16a34a';

// Color de la flecha según el tipo de caneca.
const CANECA_COLOR = {
  caneca_ordinaria:  '#111827',  // negra
  caneca_reciclable: '#9ca3af',  // blanca → gris (para que se vea)
  caneca_biosani:    '#dc2626',  // roja
  caneca_corto:      '#dc2626',  // roja
};

const LANE_GAP = 44;  // separación deseada entre carriles de distinto color (px)
const LANE_CAP = 40;  // desfase máximo (el adaptativo lo recorta si no cabe)
const TURN_PEN = 14;   // penalización por girar → recorridos rectos (en "L", no diagonales)
const CENTER_W = 1.6;  // peso del centrado (alejarse de paredes)
const DOOR_R = 60;     // radio en el que las rutas convergen al centro de una puerta
const PREF_STEP = 0.35;// costo (casi gratis) de seguir un corredor ya trazado → confluencia

// Una salida es destino de ruta solo si la puso el usuario; las señales de
// dirección que coloca la señalización automática (srAuto) NO son destinos.
const isSalida = (o) => (o.srType === 'salida_emergencia' || o.srType === 'entrada_salida') && !o.srAuto;

const SR = (() => {
  let canvas = null;

  const state = {
    tool: 'select', zoom: 1,
    isDown: false, draft: null, start: null, snapPts: [],
    history: [], redoStack: [], loadingHistory: false, suppress: false, dirty: false,
    evacTurns: [],   // giros de la última ruta de evacuación (para señales NTC)
  };

  const PROPS = ['srType', 'srCat', 'srHidden', 'srGapX', 'srGapY', 'srDir', 'srAuto'];

  /* ── Inicialización ─────────────────────────────────────── */

  function init(savedData) {
    canvas = new fabric.Canvas('floorCanvas', {
      width: DOC.w, height: DOC.h,
      backgroundColor: '#ffffff',
      preserveObjectStacking: true,
      selection: true,
      targetFindTolerance: 10,   // facilita clicar líneas finas para moverlas
      perPixelTargetFind: false,
    });

    /* Monkey-patch _onMouseUp para que un error en _finalizeCurrentTransform
       (por ej. en 'object:modified' → pushHistory o en setCoords()) no impida
       que _currentTransform se limpie.  Si _currentTransform queda colgado,
       el objeto sigue pegado al cursor. */
    {
      const orig = canvas._onMouseUp;
      canvas._onMouseUp = function (e) {
        try { orig(e); }
        catch (ex) { console.error('_onMouseUp error:', ex); }
        canvas._currentTransform = null;
      };
    }

    paintSidebarIcons();
    bindCanvasEvents();
    bindDragDrop();
    // bindBackgroundUpload(); // eliminado — el upload de croquis va solo por el sidebar
    bindKeyboard();
    canvas.on('selection:created', syncTextBar);
    canvas.on('selection:updated', syncTextBar);
    canvas.on('selection:cleared', syncTextBar);
    bindUppercase();
    window.addEventListener('resize', fit);

    if (savedData) {
      state.loadingHistory = true;
      try {
        canvas.loadFromJSON(savedData, () => {
          canvas.renderAll(); fit();
          state.loadingHistory = false;
          explodeRouteGroups();
          ensureHeader();
          pushHistory(true);
          setStatus('Plano cargado');
        });
      } catch (e) {
        console.error('loadFromJSON falló:', e);
        setStatus('Error al cargar plano', 'error');
        fit();
        state.loadingHistory = false;
        ensureHeader();
        pushHistory(true);
      }
    } else {
      fit();
      ensureHeader();
      pushHistory(true);
    }
  }

  /* ── Croquis original como referencia ───────────────────────
     Desactivado por solicitud del usuario — la imagen de fondo
     no debe aparecer en el editor; solo el resultado vectorizado. */

  /* ── Vista / zoom ───────────────────────────────────────── */

  function applyZoom(z) {
    state.zoom = Math.min(Math.max(z, 0.2), 3);
    canvas.setZoom(state.zoom);
    canvas.setWidth(DOC.w * state.zoom);
    canvas.setHeight(DOC.h * state.zoom);
    canvas.calcOffset();
    canvas.requestRenderAll();
  }
  function fit() {
    const wrap = document.getElementById('canvasWrap');
    if (!wrap) return;
    applyZoom(Math.min((wrap.clientWidth - 48) / DOC.w, (wrap.clientHeight - 48) / DOC.h));
  }
  const zoomIn    = () => applyZoom(state.zoom * 1.15);
  const zoomOut   = () => applyZoom(state.zoom / 1.15);
  const zoomReset = () => fit();

  /* ── Herramientas ───────────────────────────────────────── */

  function setTool(tool, btnEl) {
    state.tool = tool;
    state.isDown = false;
    state.suppress = false;
    document.querySelectorAll('.ed-tool').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    else if (tool === 'select') {
      const sb = document.getElementById('tool-select');
      if (sb) sb.classList.add('active');
    }

    if (tool === 'erase') {
      const selected = canvas.getActiveObjects();
      if (selected.length > 0) {
        state.suppress = true;
        selected.forEach(o => canvas.remove(o));
        state.suppress = false;
        canvas.discardActiveObject();
        canvas.requestRenderAll();
        pushHistory();
        setStatus(`${selected.length} elemento(s) borrado(s)`);
        canvas.selection = false;
        canvas.skipTargetFind = false;
        canvas.defaultCursor = 'crosshair';
        return;
      }
    }

    const drawing = tool !== 'select';
    canvas.selection = !drawing;
    canvas.skipTargetFind = drawing && tool !== 'erase';
    canvas.defaultCursor = tool === 'erase' ? 'crosshair' : (drawing ? 'crosshair' : 'default');
    canvas.discardActiveObject();
    canvas.requestRenderAll();
  }
  const backToSelect = () => setTool('select', null);

  /* ── Enganche de extremos (snap) ────────────────────────── */

  const SNAP_TYPES = new Set(['pared', 'mueble', 'puerta', 'vano']);
  function collectEndpoints() {
    const pts = [];
    canvas.getObjects().forEach((o) => {
      if (o === state.draft || !SNAP_TYPES.has(o.srType)) return;
      const r = o.getBoundingRect(true, true);
      if (o.type === 'line') {
        // extremos reales de la línea (asumiendo trazo horizontal o vertical)
        if (r.width >= r.height) {
          const y = r.top + r.height / 2;
          pts.push({ x: r.left, y }, { x: r.left + r.width, y });
        } else {
          const x = r.left + r.width / 2;
          pts.push({ x, y: r.top }, { x, y: r.top + r.height });
        }
      } else {
        // puerta / vano: las cuatro esquinas del recuadro
        pts.push(
          { x: r.left, y: r.top }, { x: r.left + r.width, y: r.top },
          { x: r.left, y: r.top + r.height }, { x: r.left + r.width, y: r.top + r.height },
        );
      }
    });
    return pts;
  }
  function snapPoint(p, pts) {
    let best = null, bd = SNAP;
    for (const q of pts) {
      const d = Math.hypot(q.x - p.x, q.y - p.y);
      if (d < bd) { bd = d; best = q; }
    }
    return best || p;
  }
  function orthoSnap(s, p) {
    let x = p.x, y = p.y;
    if (Math.abs(p.x - s.x) < 12) x = s.x;
    if (Math.abs(p.y - s.y) < 12) y = s.y;
    return { x, y };
  }

  /* ── Eventos de dibujo ──────────────────────────────────── */

  function bindCanvasEvents() {

    canvas.on('mouse:down', (opt) => {
      const t = state.tool;
      if (t === 'select') return;

      if (t === 'erase') {
        const active = canvas.getActiveObjects();
        if (active.length > 0) {
          state.suppress = true;
          active.forEach(o => canvas.remove(o));
          state.suppress = false;
          canvas.discardActiveObject();
          canvas.requestRenderAll();
          pushHistory();
          setStatus(`${active.length} elemento(s) borrado(s)`);
        } else if (opt.target) {
          canvas.remove(opt.target);
          canvas.requestRenderAll();
          pushHistory();
          setStatus('Elemento borrado');
        }
        return;
      }

      const p = canvas.getPointer(opt.e);
      if (t === 'text')        { addText(p.x, p.y); return; }
      if (t === 'origen-evac') { placeMarker(p.x, p.y); return; }

      state.snapPts = collectEndpoints();
      const sp = (t === 'rect') ? p : snapPoint(p, state.snapPts);
      state.isDown = true;
      state.start = sp;
      state.suppress = true;

      if (t === 'rect') {
        state.draft = new fabric.Rect({
          left: sp.x, top: sp.y, width: 1, height: 1,
          fill: 'rgba(107,114,128,0.10)', stroke: '#6b7280',
          strokeWidth: 2, strokeUniform: true,
          srType: 'zona', srCat: 'shape',
        });
      } else if (t === 'wall') {
        state.draft = new fabric.Line([sp.x, sp.y, sp.x, sp.y], {
          stroke: '#1f2937', strokeWidth: 8, strokeLineCap: 'round',
          srType: 'pared', srCat: 'shape',
        });
      } else if (t === 'furniture') {
        state.draft = new fabric.Line([sp.x, sp.y, sp.x, sp.y], {
          stroke: '#6b7280', strokeWidth: 2, strokeLineCap: 'round',
          srType: 'mueble', srCat: 'shape',
        });
      } else if (t === 'door' || t === 'vano') {
        state.draft = new fabric.Line([sp.x, sp.y, sp.x, sp.y], {
          stroke: '#9ca3af', strokeWidth: 1.5, strokeDashArray: [4, 4], srCat: 'temp',
        });
      }
      if (state.draft) canvas.add(state.draft);
    });

    canvas.on('mouse:move', (opt) => {
      if (!state.isDown || !state.draft) return;
      const p = canvas.getPointer(opt.e);

      if (state.tool === 'rect') {
        state.draft.set({
          width:  Math.abs(p.x - state.start.x),
          height: Math.abs(p.y - state.start.y),
          left:   Math.min(p.x, state.start.x),
          top:    Math.min(p.y, state.start.y),
        });
      } else {
        let end = snapPoint(p, state.snapPts);
        if (end === p) end = orthoSnap(state.start, p);
        state.draft.set({ x2: end.x, y2: end.y });
      }
      canvas.requestRenderAll();
    });

    canvas.on('mouse:up', (opt) => {
      if (!state.isDown) return;
      state.isDown = false;
      state.suppress = false;
      const d = state.draft;
      const t = state.tool;
      state.draft = null;
      if (!d) return;

      if (t === 'door' || t === 'vano') {
        const s = Math.max(Math.abs(d.x2 - d.x1), Math.abs(d.y2 - d.y1));
        canvas.remove(d);
        if (s >= 14) {
          const start = { x: d.x1, y: d.y1 }, end = { x: d.x2, y: d.y2 };
          canvas.add(t === 'door' ? makeDoor(start, end, s) : makeVano(start, end));
        }
        pushHistory();
        return;
      }
      const tiny = (t === 'rect')
        ? (d.width < 6 && d.height < 6)
        : (Math.hypot(d.x2 - d.x1, d.y2 - d.y1) < 8);
      if (tiny) canvas.remove(d);
      pushHistory();
    });

    const safePush = () => { try { pushHistory(); } catch (e) { console.error('pushHistory:', e); } };
    canvas.on('object:added',    safePush);
    canvas.on('object:modified', safePush);
    canvas.on('object:removed',  safePush);
  }

  /* ── Constructores ──────────────────────────────────────── */

  // Puerta como rectángulo del vano (blanco + borde negro), sin arco.
  function makeDoor(start, end, s) {
    const dx = end.x - start.x, dy = end.y - start.y;
    const sx = Math.sign(dx) || 1, sy = Math.sign(dy) || 1;
    const wt = 4; // mitad del grosor de pared (8px)
    let x1, y1, x2, y2;
    if (Math.abs(dx) >= Math.abs(dy)) {
      // pared horizontal: rectángulo se extiende en X, 8px en Y
      x1 = start.x; x2 = start.x + sx * s;
      y1 = start.y - wt; y2 = start.y + wt;
    } else {
      // pared vertical: rectángulo se extiende en Y, 8px en X
      x1 = start.x - wt; x2 = start.x + wt;
      y1 = start.y; y2 = start.y + sy * s;
    }
    const path = `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2} L ${x1} ${y2} Z`;
    const door = new fabric.Path(path, {
      stroke: '#000000', strokeWidth: 2,
      fill: '#ffffff', srType: 'puerta', srCat: 'shape',
    });
    door.srGapX = (x1 + x2) / 2;
    door.srGapY = (y1 + y2) / 2;
    door.srDir = Math.abs(dx) >= Math.abs(dy) ? 'h' : 'v';
    return door;
  }

  // Vano: abertura básica = dos jambas + umbral punteado (sin arco).
  function makeVano(start, end) {
    const dx = end.x - start.x, dy = end.y - start.y;
    const len = Math.hypot(dx, dy) || 1;
    const px = -dy / len, py = dx / len;   // perpendicular a la abertura
    const j = 7;                            // medio largo de las jambas
    const jamb = (cx, cy) => new fabric.Line(
      [cx + px * j, cy + py * j, cx - px * j, cy - py * j],
      { stroke: '#1f2937', strokeWidth: 6, strokeLineCap: 'round' });
    return new fabric.Group([
      jamb(start.x, start.y),
      jamb(end.x, end.y),
      new fabric.Line([start.x, start.y, end.x, end.y],
        { stroke: '#9ca3af', strokeWidth: 1.5, strokeDashArray: [5, 4] }),
    ], {
      srType: 'vano', srCat: 'shape',
      srGapX: (start.x + end.x) / 2, srGapY: (start.y + end.y) / 2,   // centro del hueco
      srDir: Math.abs(end.x - start.x) >= Math.abs(end.y - start.y) ? 'h' : 'v',
    });
  }

  function addText(x, y) {
    const t = new fabric.IText('Texto', {
      left: x, top: y, fontFamily: 'DM Sans',
      fontSize: 22, fill: '#111827', srType: 'texto', srCat: 'text',
    });
    canvas.add(t);
    canvas.setActiveObject(t);
    t.enterEditing(); t.selectAll();
    backToSelect();
    syncTextBar();
  }

  /* ── Encabezado del mapa (logo + marca + título) ────────── */

  // Emblema placeholder (cruz de farmacia). Reemplazable por el logo real.
  const LOGO_SVG = `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="4" y="4" width="56" height="56" rx="12" fill="#0f766e"/>
    <rect x="28" y="15" width="8" height="34" fill="#ffffff"/>
    <rect x="15" y="28" width="34" height="8" fill="#ffffff"/>
  </svg>`;

  const drugName = () => (typeof PLAN_NAME !== 'undefined' && PLAN_NAME) ? PLAN_NAME : '';
  const titleFor = (mode) => {
    const base = mode === 'evac' ? 'RUTA DE EVACUACIÓN'
      : mode === 'san' ? 'RUTA SANITARIA'
        : 'RUTA DE EVACUACIÓN / SANITARIA';
    const n = drugName();
    return (base + (n ? '  —  ' + n : '')).toUpperCase();
  };

  // Crea el encabezado (logo, "SYSTEFARMA" y título) si aún no existe.
  // Se guarda con el plano; cada parte se crea solo si falta.
  function ensureHeader() {
    const cx = DOC.w / 2;
    const find = (t) => canvas.getObjects().find(o => o.srType === t);

    // (logo y marca retirados) — eliminarlos de planos que los tuvieran
    const logo = find('logo'); if (logo) canvas.remove(logo);
    const marca = find('marca'); if (marca) canvas.remove(marca);

    // título del plano: centrado arriba. Si no existe, se crea con el nombre de
    // la droguería + la ruta. Si existe pero quedó el viejo "PLANO VECTORIZADO"
    // (que metía el pipeline), se reemplaza por el título correcto.
    const titulo = find('titulo');
    if (!titulo) {
      canvas.add(new fabric.IText(titleFor(null), {
        left: cx, top: 22, originX: 'center', originY: 'top',
        fontFamily: 'Syne', fontWeight: 'bold', fontSize: 38, fill: '#111827',
        textAlign: 'center', srType: 'titulo', srCat: 'title',
      }));
    } else if (/PLANO VECTORIZADO/i.test(titulo.text || '')) {
      titulo.set({ text: titleFor(null), left: cx });
      titulo.setCoords && titulo.setCoords();
    }
  }

  // Mantiene en MAYÚSCULAS el título y la marca aunque se editen a mano.
  function bindUppercase() {
    canvas.on('text:changed', (e) => {
      const o = e.target;
      if (!o || (o.srType !== 'titulo' && o.srType !== 'marca')) return;
      const up = (o.text || '').toUpperCase();
      if (o.text !== up) o.set('text', up);
    });
  }

  /* ── Formato de texto ───────────────────────────────────── */

  const isTextObj = (o) => o && (o.type === 'i-text' || o.type === 'text');

  function syncTextBar() {
    const bar = document.getElementById('textBar');
    if (!bar) return;
    const o = canvas.getActiveObject();
    if (!isTextObj(o)) { bar.hidden = true; return; }
    bar.hidden = false;
    const f = document.getElementById('txtFont');
    const s = document.getElementById('txtSize');
    const b = document.getElementById('txtBold');
    if (f) f.value = o.fontFamily || 'DM Sans';
    if (s) s.value = String(Math.round(o.fontSize) || 22);
    if (b) b.classList.toggle('active', o.fontWeight === 'bold' || o.fontWeight === 700);
  }

  function setFont(family) {
    const o = canvas.getActiveObject();
    if (!isTextObj(o)) return;
    o.set('fontFamily', family);
    canvas.requestRenderAll(); pushHistory();
  }
  function setTextSize(v) {
    const o = canvas.getActiveObject();
    if (!isTextObj(o)) return;
    o.set('fontSize', parseInt(v, 10) || 22);
    canvas.requestRenderAll(); pushHistory();
  }
  function toggleBold() {
    const o = canvas.getActiveObject();
    if (!isTextObj(o)) return;
    const bold = (o.fontWeight === 'bold' || o.fontWeight === 700);
    o.set('fontWeight', bold ? 'normal' : 'bold');
    canvas.requestRenderAll(); pushHistory(); syncTextBar();
  }

  function addIcon(type, x, y) {
    const svg = SR_ICONS[type];
    if (!svg) return;
    fabric.loadSVGFromString(svg, (objects, options) => {
      const obj = fabric.util.groupSVGElements(objects, options);
      obj.set({ left: x, top: y, originX: 'center', originY: 'center' });
      obj.scaleToWidth(54);
      obj.srType = type; obj.srCat = 'icon';
      canvas.add(obj);
      backToSelect();              // un clic basta para volver a seleccionar
      canvas.setActiveObject(obj);
      canvas.requestRenderAll();
      pushHistory();
      setStatus('Elemento agregado');
    });
  }

  // Cosito de origen de evacuación: invisible en el PDF.
  function placeMarker(x, y) {
    const c = new fabric.Circle({
      left: x, top: y, radius: 9, originX: 'center', originY: 'center',
      fill: EVAC_COLOR, stroke: '#ffffff', strokeWidth: 2, opacity: 0.92,
      srType: 'origen-evac', srCat: 'marker', srHidden: true,
    });
    canvas.add(c);
    pushHistory();
    setStatus('Origen colocado (no sale en el PDF)', 'ok');
  }

  /* ════════════ GENERADOR DE RUTAS (A* + fusión) ═══════════ */

  function buildGrid() {
    const cols = Math.ceil(DOC.w / GRID), rows = Math.ceil(DOC.h / GRID);
    const blocked = new Uint8Array(cols * rows);

    const rectCells = (r, pad, fn) => rectCellsXY(r, pad, pad, fn);
    const rectCellsXY = (r, padX, padY, fn) => {
      const x0 = Math.max(0, Math.floor((r.left - padX) / GRID));
      const x1 = Math.min(cols - 1, Math.floor((r.left + r.width + padX) / GRID));
      const y0 = Math.max(0, Math.floor((r.top - padY) / GRID));
      const y1 = Math.min(rows - 1, Math.floor((r.top + r.height + padY) / GRID));
      for (let cy = y0; cy <= y1; cy++)
        for (let cx = x0; cx <= x1; cx++) fn(cy * cols + cx);
    };

    // 1) bloquear paredes y muebles (con holgura + medio grosor)
    canvas.getObjects().forEach((o) => {
      if (!OBSTACLES.has(o.srType)) return;
      const pad = CLEAR + (o.strokeWidth || 0) / 2;
      rectCells(o.getBoundingRect(true, true), pad, (i) => { blocked[i] = 1; });
    });

    // 2) abrir el paso donde hay puertas o vanos (único cruce permitido).
    //    Anisotrópico: estrecho A LO LARGO de la pared (el paso queda del ancho
    //    de la puerta → se cruza por la abertura, centrado) y amplio EN PERPENDICULAR
    //    (CLEAR + grosor) para atravesar la pared.
    const OPEN_PAD = CLEAR + 8;
    canvas.getObjects().forEach((o) => {
      if (o.srType !== 'puerta' && o.srType !== 'vano') return;
      const r = o.getBoundingRect(true, true);
      const horizontal = o.srDir ? o.srDir === 'h' : (r.width >= r.height);
      const padAlong = 1;                       // a lo largo de la abertura (estrecho)
      const padX = horizontal ? padAlong : OPEN_PAD;
      const padY = horizontal ? OPEN_PAD : padAlong;
      rectCellsXY(r, padX, padY, (i) => { blocked[i] = 0; });
    });

    // 3) "cercanía a pared": cuántas celdas bloqueadas/bordes rodean a cada celda.
    //    A* la usa para penalizar el borde y preferir el CENTRO del pasillo.
    const near = new Uint8Array(cols * rows);
    for (let cy = 0; cy < rows; cy++) {
      for (let cx = 0; cx < cols; cx++) {
        const i = cy * cols + cx;
        if (blocked[i]) continue;
        let c = 0;
        for (let dy = -2; dy <= 2; dy++)
          for (let dx = -2; dx <= 2; dx++) {
            if (!dx && !dy) continue;
            const nx = cx + dx, ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= cols || ny >= rows || blocked[ny * cols + nx]) c++;
          }
        near[i] = c;
      }
    }

    return { cols, rows, blocked, near };
  }

  // Espacio libre (px) desde (x,y) en una dirección, hasta topar pared/borde.
  function freeDist(grid, x, y, dirx, diry, max) {
    const { cols, rows, blocked } = grid;
    let dist = 0;
    while (dist < max) {
      const cx = Math.floor((x + dirx * dist) / GRID), cy = Math.floor((y + diry * dist) / GRID);
      if (cx < 0 || cy < 0 || cx >= cols || cy >= rows || blocked[cy * cols + cx]) break;
      dist += GRID / 2;
    }
    return dist;
  }

  // Inserta puntos intermedios para poder variar el desfase a lo largo del trazo.
  function densify(pts, step) {
    if (pts.length < 2) return pts;
    const out = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      const k = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / step));
      for (let j = 1; j <= k; j++) { const t = j / k; out.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }); }
    }
    return out;
  }

  // Desplaza la polilínea perpendicularmente, pero:
  //  · ADAPTÁNDOSE al espacio (recoge el desfase donde el pasillo es angosto), y
  //  · CONVERGIENDO al centro cerca de una puerta (las rutas "se cierran" para
  //    pasar por la mitad del hueco y se vuelven a abrir después).
  function offsetPath(pts, d, grid, doorCenters) {
    if (!d || pts.length < 2) return pts;
    const s = Math.sign(d), want = Math.abs(d);
    return pts.map((p, i) => {
      const prev = pts[i - 1] || p, next = pts[i + 1] || p;
      const dx = next.x - prev.x, dy = next.y - prev.y;
      const len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len * s, ny = dx / len * s;       // normal en el sentido del desfase

      // converger al centro al acercarse a una puerta/vano
      let target = want;
      if (doorCenters && doorCenters.length) {
        let dd = Infinity;
        for (const c of doorCenters) dd = Math.min(dd, Math.hypot(c.x - p.x, c.y - p.y));
        target = want * Math.min(1, dd / DOOR_R);
      }
      let eff = target;
      if (grid) {
        const free = freeDist(grid, p.x, p.y, nx, ny, want + LINE_W * 2);
        eff = Math.min(eff, free - LINE_W / 2 - GRID);
      }
      eff = Math.max(0, eff);
      return { x: p.x + nx * eff, y: p.y + ny * eff };
    });
  }

  const cellCenter = (cx, cy) => ({ x: (cx + 0.5) * GRID, y: (cy + 0.5) * GRID });
  const toCell = (p) => ({ cx: Math.floor(p.x / GRID), cy: Math.floor(p.y / GRID) });
  const heur = (a, b) => Math.abs(a.cx - b.cx) + Math.abs(a.cy - b.cy);

  function nearestFree(grid, cx, cy) {
    const { cols, rows, blocked } = grid;
    const inb = (x, y) => x >= 0 && y >= 0 && x < cols && y < rows;
    if (inb(cx, cy) && !blocked[cy * cols + cx]) return { cx, cy };
    for (let r = 1; r < 40; r++)
      for (let dx = -r; dx <= r; dx++)
        for (let dy = -r; dy <= r; dy++) {
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
          const nx = cx + dx, ny = cy + dy;
          if (inb(nx, ny) && !blocked[ny * cols + nx]) return { cx: nx, cy: ny };
        }
    return null;
  }

  // `shared` (Set/Map de celdas ya usadas por CUALQUIER ruta): premia seguir un
  // corredor existente → todas las rutas confluyen por los mismos pasillos (luego
  // se separan por carril de color), evitando cruces y serpenteos.
  function astar(grid, start, goal, shared) {
    const { cols, rows, blocked, near } = grid;
    const N = cols * rows;
    const idx = (c) => c.cy * cols + c.cx;
    const sI = idx(start), gI = idx(goal);
    const g = new Float64Array(N).fill(Infinity);
    const came = new Int32Array(N).fill(-1);
    g[sI] = 0;
    const heap = [[heur(start, goal), sI]];
    const hpush = (n) => { heap.push(n); let i = heap.length - 1;
      while (i > 0) { const p = (i - 1) >> 1; if (heap[p][0] <= heap[i][0]) break;
        [heap[p], heap[i]] = [heap[i], heap[p]]; i = p; } };
    const hpop = () => { const top = heap[0], last = heap.pop();
      if (heap.length) { heap[0] = last; let i = 0;
        for (;;) { let l = 2*i+1, r = 2*i+2, s = i;
          if (l < heap.length && heap[l][0] < heap[s][0]) s = l;
          if (r < heap.length && heap[r][0] < heap[s][0]) s = r;
          if (s === i) break; [heap[s], heap[i]] = [heap[i], heap[s]]; i = s; } }
      return top; };

    while (heap.length) {
      const cur = hpop()[1];
      if (cur === gI) break;
      const cx = cur % cols, cy = (cur / cols) | 0;
      // dirección con la que se llegó a `cur` (para penalizar giros)
      const pc = came[cur];
      const pdx = pc === -1 ? 0 : Math.sign(cx - (pc % cols));
      const pdy = pc === -1 ? 0 : Math.sign(cy - ((pc / cols) | 0));
      for (const [nx, ny] of [[cx+1,cy],[cx-1,cy],[cx,cy+1],[cx,cy-1]]) {
        if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
        const nI = ny * cols + nx;
        if (blocked[nI]) continue;
        // costo = 1 + centrado (alejarse de paredes) + penalización por girar.
        // Si la celda ya la usa una ruta del mismo color, es casi gratis seguirla
        // (prioriza fusionarse con el tronco existente).
        const turn = (pc !== -1 && (Math.sign(nx - cx) !== pdx || Math.sign(ny - cy) !== pdy)) ? TURN_PEN : 0;
        let step = 1 + (near ? near[nI] * CENTER_W : 0) + turn;
        // seguir un corredor ya trazado (de cualquier color) es casi gratis →
        // las rutas confluyen por los mismos pasillos en vez de esquivarse.
        if (shared && shared.has(nI)) step = Math.min(step, PREF_STEP);
        const ng = g[cur] + step;
        if (ng < g[nI]) { g[nI] = ng; came[nI] = cur; hpush([ng + heur({ cx: nx, cy: ny }, goal), nI]); }
      }
    }
    if (came[gI] === -1 && sI !== gI) return null;
    const path = []; let c = gI;
    while (c !== -1) { path.push({ cx: c % cols, cy: (c / cols) | 0 }); c = came[c]; }
    return path.reverse();
  }

  function simplify(cells) {
    if (cells.length <= 2) return cells.map(c => cellCenter(c.cx, c.cy));
    const dir = (a, b) => [Math.sign(b.cx - a.cx), Math.sign(b.cy - a.cy)];
    const out = [cells[0]];
    for (let i = 1; i < cells.length - 1; i++) {
      const [px, py] = dir(cells[i - 1], cells[i]);
      const [nx, ny] = dir(cells[i], cells[i + 1]);
      if (px !== nx || py !== ny) out.push(cells[i]);
    }
    out.push(cells[cells.length - 1]);
    return out.map(c => cellCenter(c.cx, c.cy));
  }

  // Una flecha "→" (cola + dos alas) como un solo trazo alineado, en (cx,cy)→ang.
  // Es un objeto INDEPENDIENTE (se puede mover/rotar/borrar por separado).
  function arrowGlyph(cx, cy, ang, color, modeKey) {
    const ux = Math.cos(ang), uy = Math.sin(ang), px = -uy, py = ux;
    const L = ARROW_LEN, h = ARROW_SIZE;
    const x1 = cx - ux * L / 2, y1 = cy - uy * L / 2;          // inicio de la cola
    const xt = cx + ux * L / 2, yt = cy + uy * L / 2;          // vértice de la punta
    const wlx = xt - ux * h + px * h, wly = yt - uy * h + py * h;
    const wrx = xt - ux * h - px * h, wry = yt - uy * h - py * h;
    const d = `M ${x1} ${y1} L ${xt} ${yt} M ${wlx} ${wly} L ${xt} ${yt} L ${wrx} ${wry}`;
    return new fabric.Path(d, {
      stroke: color, strokeWidth: LINE_W, fill: 'transparent',
      strokeLineCap: 'round', strokeLineJoin: 'round',
      srType: 'ruta-' + modeKey, srCat: 'ruta-auto',
    });
  }

  const inRect = (x, y, r, pad) =>
    x >= r.left - pad && x <= r.left + r.width + pad &&
    y >= r.top - pad && y <= r.top + r.height + pad;

  // Ruta = flechas "→" a intervalos. Cada flecha se orienta según el AVANCE
  // general (mira hacia adelante en la ruta), no el tramo inmediato — así nunca
  // apunta "al revés" por un micro-retroceso del desfase.
  // `placed` evita encimar flechas del mismo color; `items` evita ponerlas
  // encima de un icono.
  function makeRoute(points, color, modeKey, phase, placed, items, placedAll) {
    if (points.length < 2) return null;
    let total = 0;
    for (let i = 0; i < points.length - 1; i++) total += Math.hypot(points[i + 1].x - points[i].x, points[i + 1].y - points[i].y);

    const pointAt = (target) => {
      let dist = 0;
      for (let i = 0; i < points.length - 1; i++) {
        const a = points[i], b = points[i + 1];
        const seg = Math.hypot(b.x - a.x, b.y - a.y) || 1e-6;
        if (dist + seg >= target) { const t = (target - dist) / seg; return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }; }
        dist += seg;
      }
      return points[points.length - 1];
    };

    // look-ahead amplio: orienta la flecha por el avance real y salta los
    // cambios bruscos de desfase (así ninguna flecha "se devuelve").
    // El ángulo se fuerza al eje dominante → siempre ortogonal (↑↓←→), nunca diagonal.
    const LA = 40;
    const dirAt = (d) => {
      const a = pointAt(Math.max(0, d - LA * 0.25)), b = pointAt(Math.min(total, d + LA));
      const dx = b.x - a.x, dy = b.y - a.y;
      if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? 0 : Math.PI;     // horizontal
      return dy >= 0 ? Math.PI / 2 : -Math.PI / 2;                        // vertical
    };
    // flechas regulares a lo largo del recorrido (forman el "camino"), todas
    // orientadas al eje dominante (ortogonales) y por el avance real.
    const marks = [];
    for (let d = ARROW_GAP * 0.6; d < total - 6; d += ARROW_GAP) {
      const p = pointAt(d);
      marks.push({ x: p.x, y: p.y, ang: dirAt(d) });
    }
    // flecha final, en la meta
    const end = points[points.length - 1];
    marks.push({ x: end.x, y: end.y, ang: dirAt(total) });

    const minD2 = ARROW_MINDIST * ARROW_MINDIST;
    const minG2 = ARROW_MINGLOBAL * ARROW_MINGLOBAL;
    const parts = [];   // flechas individuales (cada una es un objeto aparte)
    marks.forEach(s => {
      if (items && items.some(r => inRect(s.x, s.y, r, 6))) return;   // no sobre iconos
      if (placed && placed.some(p => (p.x - s.x) ** 2 + (p.y - s.y) ** 2 < minD2)) return;          // mismo color
      if (placedAll && placedAll.some(p => (p.x - s.x) ** 2 + (p.y - s.y) ** 2 < minG2)) return;    // cualquier color (cruces)
      if (placed) placed.push({ x: s.x, y: s.y });
      if (placedAll) placedAll.push({ x: s.x, y: s.y });
      parts.push(arrowGlyph(s.x, s.y, s.ang, color, modeKey));
    });
    return parts;
  }

  function clearRoutes(modeKey) {
    canvas.getObjects().filter(o => o.srType === 'ruta-' + modeKey).forEach(o => canvas.remove(o));
  }

  /* ── Avisos de conectividad (P3) ────────────────────────────
     Cuando un origen/caneca no tiene ruta hasta la salida (recinto
     cerrado sin puerta/vano), en vez de fallar en silencio marcamos el
     punto con un aviso rojo. srHidden → no sale en el PDF. */
  function clearWarnings() {
    canvas.getObjects().filter(o => o.srType === 'aviso-conexion').forEach(o => canvas.remove(o));
  }

  function markUnreachable(center) {
    const ring = new fabric.Circle({
      left: center.x, top: center.y, radius: 20, originX: 'center', originY: 'center',
      fill: 'rgba(220,38,38,0.10)', stroke: '#dc2626', strokeWidth: 2.5,
      strokeDashArray: [5, 4],
    });
    const tag = new fabric.Text('⚠ sin salida — agrega puerta/vano', {
      left: center.x, top: center.y + 24, originX: 'center', originY: 'top',
      fontFamily: 'DM Sans', fontSize: 14, fontWeight: 'bold', fill: '#dc2626',
    });
    const g = new fabric.Group([ring, tag], {
      originX: 'center', originY: 'center',
      left: center.x, top: center.y,
      selectable: false, evented: false,
      srType: 'aviso-conexion', srCat: 'aviso', srHidden: true,
    });
    canvas.add(g);
  }

  // Convierte rutas guardadas como grupo (versión antigua) en flechas sueltas,
  // para poder mover/borrar cada una por separado.
  function explodeRouteGroups() {
    canvas.getObjects().slice().forEach(o => {
      if (o.type !== 'group' || o.srCat !== 'ruta-auto') return;
      const srType = o.srType;
      const children = o.getObjects();
      o._restoreObjectsState();          // devuelve los hijos a coordenadas absolutas
      canvas.remove(o);
      children.forEach(ch => { ch.srType = srType; ch.srCat = 'ruta-auto'; if (ch.setCoords) ch.setCoords(); canvas.add(ch); });
    });
    canvas.requestRenderAll();
  }

  function generate(modeKey) {
    const all = canvas.getObjects();
    // Metas (salidas): las que puso el usuario; si no hay, se usa la puerta más
    // ancha como salida automática hacia la calle (sin colocar ícono).
    const goalObjs = all.filter(isSalida);
    let goalPoints = goalObjs.map(g => g.getCenterPoint());
    if (!goalPoints.length) {
      const auto = autoExitPoint();
      if (!auto) { setStatus('Coloca una salida o una puerta', 'warn'); return; }
      goalPoints = [auto];
    }

    // jobs = { center, color }
    let jobs;
    if (modeKey === 'evac') {
      // Orígenes: los que puso el usuario; si no hay, se generan desde el
      // centro de cada recinto (sin colocar puntos verdes visibles).
      const origins = all.filter(o => o.srType === 'origen-evac');
      if (origins.length) {
        jobs = origins.map(o => ({ center: o.getCenterPoint(), color: EVAC_COLOR }));
      } else {
        const rooms = all.filter(o => o.srType === 'recinto');
        if (!rooms.length) { setStatus('No hay recintos para trazar rutas', 'warn'); return; }
        jobs = rooms.map(r => ({ center: r.getCenterPoint(), color: EVAC_COLOR }));
      }
    } else {
      const canecas = all.filter(o => typeof o.srType === 'string' && o.srType.startsWith('caneca_'));
      if (!canecas.length) { setStatus('Coloca al menos una caneca', 'warn'); return; }
      jobs = canecas.map(o => ({ center: o.getCenterPoint(), color: CANECA_COLOR[o.srType] || '#dc2626' }));
    }

    state.suppress = true;
    clearRoutes(modeKey);
    clearWarnings();
    if (modeKey === 'evac') state.evacTurns = [];   // se recalculan abajo (señales NTC)
    const unreachable = [];     // centros de orígenes/canecas sin ruta a la salida
    const grid = buildGrid();
    const cols = grid.cols;
    const goalCells = goalPoints.map(p => nearestFree(grid, toCell(p).cx, toCell(p).cy)).filter(Boolean);
    const doorCenters = all.filter(o => o.srType === 'puerta' || o.srType === 'vano')
      .map(o => (typeof o.srGapX === 'number') ? { x: o.srGapX, y: o.srGapY } : o.getCenterPoint());

    // preparar: celda de inicio + meta más cercana
    const prepared = jobs.map(j => {
      const sCell = nearestFree(grid, toCell(j.center).cx, toCell(j.center).cy);
      if (!sCell) { unreachable.push(j.center); return null; }
      let best = null, bestD = Infinity, gi = -1;
      goalCells.forEach((gc, i) => { const d = heur(sCell, gc); if (d < bestD) { bestD = d; best = gc; gi = i; } });
      return best ? { ...j, sCell, goalCell: best, goalIdx: gi, dist: bestD } : null;
    }).filter(Boolean);

    // agrupar por color (cada color forma un árbol coherente) y, dentro de cada
    // color, tronco primero (el más lejano), para que los cercanos se fusionen a él
    prepared.sort((a, b) => (a.color === b.color) ? (b.dist - a.dist) : a.color.localeCompare(b.color));

    // asignar un carril (desfase perpendicular) a cada color presente, para que
    // rutas de distinto color que comparten pasillo no queden una encima de otra.
    const colorsUsed = [...new Set(prepared.map(j => j.color))];
    const laneOf = {};
    colorsUsed.forEach((col, i) => {
      const off = (i - (colorsUsed.length - 1) / 2) * LANE_GAP;
      laneOf[col] = Math.max(-LANE_CAP, Math.min(LANE_CAP, off));
    });

    // recuadros de iconos: las flechas no se dibujan encima de ellos
    const itemRects = all.filter(o => o.srCat === 'icon').map(o => o.getBoundingRect(true, true));

    const usedColor = new Map();     // celda → color que la ocupa (fusión / evitar cruces)
    const placedByColor = {};        // posiciones de flechas por color (anti-encimado)
    const placedAll = [];            // posiciones de TODAS las flechas (anti-encimado en cruces)
    let drawn = 0;
    prepared.forEach(j => {
      let cells = astar(grid, j.sCell, j.goalCell, usedColor);
      if (!cells || cells.length < 2) { unreachable.push(j.center); return; }

      // truncar al primer punto ya cubierto por una ruta del MISMO color (fusión)
      let cut = cells.length;
      for (let i = 1; i < cells.length; i++) {
        if (usedColor.get(cells[i].cy * cols + cells[i].cx) === j.color) { cut = i + 1; break; }
      }
      cells = cells.slice(0, cut);
      if (cells.length < 2) return;

      cells.forEach(c => usedColor.set(c.cy * cols + c.cx, j.color));
      const simple = simplify(cells);
      // guardar los giros de evacuación → ahí van las señales de dirección (NTC)
      if (modeKey === 'evac') {
        for (let i = 1; i < simple.length - 1; i++) state.evacTurns.push(simple[i]);
      }
      const pts = offsetPath(densify(simple, 22), laneOf[j.color] || 0, grid, doorCenters);
      const list = placedByColor[j.color] || (placedByColor[j.color] = []);
      const arrows = makeRoute(pts, j.color, modeKey, null, list, itemRects, placedAll);
      arrows.forEach(a => canvas.add(a));
      if (arrows.length) drawn++;
    });

    unreachable.forEach(c => markUnreachable(c));

    state.suppress = false;
    pushHistory();
    if (drawn && !unreachable.length) {
      setStatus(`${drawn} ruta(s) generada(s)`, 'ok');
    } else if (drawn && unreachable.length) {
      setStatus(`${drawn} ruta(s); ${unreachable.length} sin salida — revisa puertas/vanos (marcado en rojo)`, 'warn');
    } else {
      setStatus('Ninguna ruta: cada recinto necesita una puerta/vano hacia la salida (marcado en rojo)', 'err');
    }
  }

  const generateEvac = () => generate('evac');
  const generateSan  = () => generate('san');

  // Salida "virtual" automática = centro del hueco de la puerta más ancha
  // (la principal hacia la calle). Se usa cuando el usuario no colocó una
  // salida a mano, para poder generar las flechas sin pasos manuales.
  function autoExitPoint() {
    const doors = canvas.getObjects().filter(o => o.srType === 'puerta' || o.srType === 'vano');
    if (!doors.length) return null;
    let best = null, bestW = -1;
    doors.forEach(d => {
      const r = d.getBoundingRect(true, true);
      const w = Math.max(r.width, r.height);
      if (w > bestW) { bestW = w; best = d; }
    });
    return (typeof best.srGapX === 'number')
      ? { x: best.srGapX, y: best.srGapY } : best.getCenterPoint();
  }

  const clearAll = () => { state.suppress = true; clearRoutes('evac'); clearRoutes('san'); clearWarnings(); state.suppress = false; pushHistory(); setStatus('Rutas eliminadas'); };

  /* ════════════ SEÑALIZACIÓN AUTOMÁTICA (NTC) ══════════════
     Coloca extintores por cobertura (NTC 2885 ~15 m) y señales de
     evacuación en los giros de la ruta. Lo automático queda con srAuto=true
     para distinguirlo de lo que el usuario pone a mano (y poder rehacerlo). */

  // Radio de cobertura del extintor en px. Calibrable: con la escala real del
  // plano, 15 m ≈ PLAN_SCALE(px/cm) * 1500. Default razonable para el lienzo.
  const COVERAGE_PX = (typeof PLAN_SCALE !== 'undefined' && PLAN_SCALE > 1)
    ? PLAN_SCALE * 1500 : 230;

  // Coloca un icono sin tocar la herramienta/selección activa (uso interno).
  function spawnIcon(type, x, y, size, auto) {
    const svg = SR_ICONS[type];
    if (!svg) return;
    fabric.loadSVGFromString(svg, (objects, options) => {
      const obj = fabric.util.groupSVGElements(objects, options);
      obj.set({ left: x, top: y, originX: 'center', originY: 'center' });
      obj.scaleToWidth(size);
      obj.srType = type; obj.srCat = 'icon';
      if (auto) obj.srAuto = true;
      canvas.add(obj);
      canvas.requestRenderAll();
    });
  }

  // Huella del edificio: bounding box de paredes/recintos. Los extintores solo
  // se colocan aquí dentro → no quedan flotando fuera del plano.
  function buildingFootprint() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, found = false;
    canvas.getObjects().forEach((o) => {
      if (o.srType !== 'pared' && o.srType !== 'recinto') return;
      const r = o.getBoundingRect(true, true);
      minX = Math.min(minX, r.left); minY = Math.min(minY, r.top);
      maxX = Math.max(maxX, r.left + r.width); maxY = Math.max(maxY, r.top + r.height);
      found = true;
    });
    if (!found) return { left: 0, top: 0, right: DOC.w, bottom: DOC.h };
    return { left: minX + CLEAR, top: minY + CLEAR, right: maxX - CLEAR, bottom: maxY - CLEAR };
  }

  function placeExtinguishersByCoverage(grid, radius) {
    const fp = buildingFootprint();
    const spacing = radius * 1.4;            // solapa círculos → cobertura completa
    const minD2 = (spacing * 0.7) ** 2;
    const spots = [];
    for (let y = fp.top + spacing / 2; y < fp.bottom; y += spacing) {
      for (let x = fp.left + spacing / 2; x < fp.right; x += spacing) {
        const fc = nearestFree(grid, Math.floor(x / GRID), Math.floor(y / GRID));
        if (!fc) continue;
        const p = cellCenter(fc.cx, fc.cy);
        // dentro de la huella y con área transitable cerca (no en muros/afuera)
        if (p.x < fp.left || p.x > fp.right || p.y < fp.top || p.y > fp.bottom) continue;
        if (Math.hypot(p.x - x, p.y - y) > spacing) continue;
        if (spots.some(s => (s.x - p.x) ** 2 + (s.y - p.y) ** 2 < minD2)) continue;
        spots.push(p);
      }
    }
    spots.forEach(p => spawnIcon('extintor', p.x, p.y, 40, true));
    return spots.length;
  }

  function placeEvacDirectionSigns() {
    const turns = state.evacTurns || [];
    const minD2 = 70 * 70;
    const spots = [];
    turns.forEach(p => {
      if (!spots.some(s => (s.x - p.x) ** 2 + (s.y - p.y) ** 2 < minD2)) spots.push(p);
    });
    spots.forEach(p => spawnIcon('salida_emergencia', p.x, p.y, 34, true));
    return spots.length;
  }

  function autoSignal() {
    // Las señales de dirección van en los giros de la ruta de evacuación. Si
    // todavía no se generó la ruta, generarla ahora para poder señalizar los
    // giros en un solo clic (antes quedaba sin señales hasta generar la ruta).
    if (!state.evacTurns || !state.evacTurns.length) {
      generate('evac');
    }
    state.suppress = true;
    // rehacer: quitar la señalización automática previa (no la manual)
    canvas.getObjects().filter(o => o.srAuto).forEach(o => canvas.remove(o));
    const grid = buildGrid();
    const ext = placeExtinguishersByCoverage(grid, COVERAGE_PX);
    const dirs = placeEvacDirectionSigns();
    state.suppress = false;
    pushHistory();
    const hint = dirs ? '' : ' (genera la ruta de evacuación para señalizar los giros)';
    setStatus(
      `Señalización: ${ext} extintor(es), ${dirs} señal(es) de evacuación` + hint,
      (ext || dirs) ? 'ok' : 'warn',
    );
  }

  /* ── Selección / borrado ────────────────────────────────── */

  function deleteSelected() {
    const objs = canvas.getActiveObjects();
    if (!objs.length) return;
    state.suppress = true;
    objs.forEach(o => canvas.remove(o));
    state.suppress = false;
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    pushHistory();
  }

  /* ── Historial ──────────────────────────────────────────── */

  function snapshot() {
    try { return JSON.stringify(canvas.toJSON(PROPS)); }
    catch (e) { console.error('snapshot error:', e); return null; }
  }
  function pushHistory(initial = false) {
    if (state.loadingHistory || state.suppress) return;
    const snap = snapshot();
    if (snap === null) return;
    if (state.history.length && state.history[state.history.length - 1] === snap) return;
    state.history.push(snap);
    if (state.history.length > 60) state.history.shift();
    state.redoStack = [];
    if (!initial) { state.dirty = true; setStatus('Cambios sin guardar', 'warn'); scheduleAutoSave(); }
  }
  function loadSnapshot(str) {
    state.loadingHistory = true;
    canvas.loadFromJSON(JSON.parse(str), () => { canvas.renderAll(); state.loadingHistory = false; });
  }
  function undo() { if (state.history.length <= 1) return; state.redoStack.push(state.history.pop()); loadSnapshot(state.history[state.history.length - 1]); }
  function redo() { if (!state.redoStack.length) return; const s = state.redoStack.pop(); state.history.push(s); loadSnapshot(s); }

  /* ── Guardar ────────────────────────────────────────────── */

  let autoTimer = null;
  function scheduleAutoSave() {
    clearTimeout(autoTimer);
    autoTimer = setTimeout(() => saveData(true), AUTOSAVE_MS);
  }

  function saveData(silent) {
    clearTimeout(autoTimer);
    // no autoguardar a mitad de una multi-selección (coords relativas); reintenta luego
    const ao = canvas.getActiveObject();
    if (silent && ao && ao.type === 'activeSelection') { scheduleAutoSave(); return; }
    if (!silent) { setStatus('Guardando…'); canvas.discardActiveObject().requestRenderAll(); }
    fetch(SAVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify({ canvas_data: canvas.toJSON(PROPS) }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.ok) { state.dirty = false; setStatus(silent ? 'Autoguardado ✓' : 'Guardado ' + (d.saved_at || ''), 'ok'); }
        else setStatus('Error al guardar', 'err');
      })
      .catch(() => { setStatus(silent ? 'Sin conexión — reintentando…' : 'Error de conexión', 'err'); if (silent) scheduleAutoSave(); });
  }
  const save = () => saveData(false);

  /* ── Exportar PDF ───────────────────────────────────────── */

  // Abre el diálogo de exportación.
  function exportPDF() {
    const m = document.getElementById('exportModal');
    if (m) m.hidden = false;
    else exportWith(['evac', 'san']);   // sin modal (fallback)
  }
  const closeExport = () => { const m = document.getElementById('exportModal'); if (m) m.hidden = true; };

  // Recuadro que envuelve todo el contenido visible del lienzo.
  function contentBBox() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    canvas.getObjects().forEach((o) => {
      if (!o.visible) return;
      const r = o.getBoundingRect(true, true);
      minX = Math.min(minX, r.left); minY = Math.min(minY, r.top);
      maxX = Math.max(maxX, r.left + r.width); maxY = Math.max(maxY, r.top + r.height);
    });
    if (minX === Infinity) return { left: 0, top: 0, width: DOC.w, height: DOC.h };
    return { left: minX, top: minY, width: maxX - minX, height: maxY - minY };
  }

  // Render del lienzo: solo las rutas del modo, con marco y recorte
  // al contenido (para llenar la hoja). Devuelve { url, w, h } del recorte.
  function renderPNG(mode) {
    const title = canvas.getObjects().find(o => o.srType === 'titulo');
    const prevText = title ? title.text : null;
    if (title) title.set({ text: titleFor(mode), left: DOC.w / 2 });

    const toHide = canvas.getObjects().filter((o) => {
      if (o.srHidden) return true;                              // puntitos verdes
      if (o.srType === 'ruta-evac' && mode !== 'evac') return true;
      if (o.srType === 'ruta-san'  && mode !== 'san')  return true;
      return false;
    });
    toHide.forEach(o => (o.visible = false));

    // marco alrededor del contenido (temporal, solo para el PDF)
    const bb = contentBBox();
    const pad = 30;
    const frame = new fabric.Rect({
      left: bb.left - pad, top: bb.top - pad, width: bb.width + 2 * pad, height: bb.height + 2 * pad,
      fill: 'transparent', stroke: '#9ca3af', strokeWidth: 2,
    });
    const temps = [frame];
    temps.forEach(o => canvas.add(o));
    canvas.renderAll();

    // recortar al marco (+ margen), llenando así la hoja al insertar en el PDF
    const m = 16;
    const cl = Math.max(0, frame.left - m), ct = Math.max(0, frame.top - m);
    const cw = Math.min(DOC.w - cl, frame.width + 2 * m), ch = Math.min(DOC.h - ct, frame.height + 2 * m);
    const url = canvas.toDataURL({ format: 'png', multiplier: 2, left: cl, top: ct, width: cw, height: ch, backgroundColor: '#ffffff' });

    temps.forEach(o => canvas.remove(o));
    toHide.forEach(o => (o.visible = true));
    if (title) title.set({ text: prevText, left: DOC.w / 2 });
    canvas.renderAll();
    return { url, w: cw, h: ch };
  }

  // Genera el PDF: una página por modo (['evac'], ['san'] o ambos).
  function doExport(modes) {
    closeExport();
    if (!modes || !modes.length) return;
    canvas.discardActiveObject();

    // (re)generar las rutas de los modos elegidos para que estén frescas
    modes.forEach(m => generate(m));

    setStatus('Generando PDF…');
    const prevZoom = state.zoom;
    applyZoom(1);
    state.suppress = true;   // los temporales del render no van al historial

    const { jsPDF } = window.jspdf;
    let pdf = null;
    modes.forEach((mode) => {
      const { url, w, h } = renderPNG(mode);
      if (!pdf) pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: [216, 330] });
      else pdf.addPage([216, 330], 'landscape');
      const pw = pdf.internal.pageSize.getWidth();
      const ph = pdf.internal.pageSize.getHeight();
      // encajar el recorte en la hoja respetando proporción (centrado)
      const ia = w / h, pa = pw / ph;
      let dw, dh;
      if (ia > pa) { dw = pw; dh = pw / ia; } else { dh = ph; dw = ph * ia; }
      pdf.addImage(url, 'PNG', (pw - dw) / 2, (ph - dh) / 2, dw, dh);
    });

    state.suppress = false;
    applyZoom(prevZoom);
    canvas.requestRenderAll();
    pdf.save((PLAN_NAME || 'plano') + '.pdf');
    setStatus('PDF exportado (' + modes.length + ' pág.)', 'ok');
  }
  const exportWith = doExport;

  /* ── Teclado ────────────────────────────────────────────── */

  function bindKeyboard() {
    document.addEventListener('keydown', (e) => {
      const ao = canvas.getActiveObject();
      if (ao && ao.isEditing) return;
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
      else if (e.ctrlKey && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
      else if (e.key === 'Escape') backToSelect();
    });
  }

  /* ── Drag & drop de iconos ──────────────────────────────── */

  function bindDragDrop() {
    document.querySelectorAll('.ed-icon-item[draggable="true"]').forEach(item => {
      item.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', item.getAttribute('data-type'));
        e.dataTransfer.effectAllowed = 'copy';
      });
    });
    const el = canvas.upperCanvasEl;
    el.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    el.addEventListener('drop', (e) => {
      e.preventDefault();
      const type = e.dataTransfer.getData('text/plain');
      if (!type) return;
      const p = canvas.getPointer(e);
      if (type === 'area_label') addText(p.x, p.y);
      else addIcon(type, p.x, p.y);
    });
  }

  /* ── Croquis de fondo ───────────────────────────────────── */

  function bindBackgroundUpload() {
    const input = document.getElementById('bg-upload');
    if (!input) return;
    input.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        fabric.Image.fromURL(ev.target.result, (img) => {
          const scale = Math.min(DOC.w / img.width, DOC.h / img.height);
          img.set({ scaleX: scale, scaleY: scale, opacity: 0.7 });
          canvas.setBackgroundImage(img, () => { canvas.requestRenderAll(); pushHistory(); setStatus('Croquis cargado como fondo'); });
        });
      };
      reader.readAsDataURL(file);
      input.value = '';
    });
  }

  /* ── Estado ─────────────────────────────────────────────── */

  let statusTimer = null;
  function setStatus(msg, type = '') {
    const el = document.getElementById('ed-status');
    if (!el) return;
    el.textContent = msg;
    el.className = 'ed-status' + (type ? ' ed-status--' + type : '');
    clearTimeout(statusTimer);
    if (type === 'ok') statusTimer = setTimeout(() => { el.textContent = 'Listo'; el.className = 'ed-status'; }, 2800);
  }

  return {
    init, setTool, deleteSelected, undo, redo,
    zoomIn, zoomOut, zoomReset, save,
    exportPDF, doExport, closeExport,
    generateEvac, generateSan, clearAll, autoSignal,
    setFont, setTextSize, toggleBold,
  };
})();

function toggleSection(hd) { hd.parentElement.classList.toggle('collapsed'); }
