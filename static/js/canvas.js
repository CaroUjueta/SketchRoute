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
const SNAP = 16;                   // radio de enganche entre extremos (px)
const LINE_W = 7;                  // grosor del trazo de la flecha (px)
const ARROW_GAP = 96;              // separación entre flechas → a lo largo de la ruta (px)
const ARROW_LEN = 32;              // largo de la cola de cada flecha (px)
const ARROW_SIZE = 12;             // apertura de la punta (px)
const ARROW_MINDIST = 46;          // distancia mínima entre flechas (anti-encimado)
const AUTOSAVE_MS = 2500;          // espera tras editar antes de autoguardar

const OBSTACLES = new Set(['pared', 'mueble']);
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
const PREF_STEP = 0.35;// costo (casi gratis) de seguir el tronco del mismo color → fusión
const AVOID_PEN = 5;   // penalización por cruzar una ruta de OTRO color → menos cruces

const isSalida = (o) => o.srType === 'salida_emergencia' || o.srType === 'entrada_salida';

const SR = (() => {
  let canvas = null;

  const state = {
    tool: 'select', zoom: 1,
    isDown: false, draft: null, start: null, snapPts: [],
    history: [], redoStack: [], loadingHistory: false, suppress: false, dirty: false,
  };

  const PROPS = ['srType', 'srCat', 'srHidden', 'srGapX', 'srGapY'];

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

    paintSidebarIcons();
    bindCanvasEvents();
    bindDragDrop();
    bindBackgroundUpload();
    bindKeyboard();
    canvas.on('selection:created', syncTextBar);
    canvas.on('selection:updated', syncTextBar);
    canvas.on('selection:cleared', syncTextBar);
    window.addEventListener('resize', fit);

    if (savedData) {
      state.loadingHistory = true;
      canvas.loadFromJSON(savedData, () => {
        canvas.renderAll(); fit();
        state.loadingHistory = false;
        ensureTitle();
        pushHistory(true);
        setStatus('Plano cargado');
      });
    } else {
      fit();
      ensureTitle();
      pushHistory(true);
    }
  }

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
    document.querySelectorAll('.ed-tool').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    else if (tool === 'select') {
      const sb = document.getElementById('tool-select');
      if (sb) sb.classList.add('active');
    }
    const drawing = tool !== 'select';
    canvas.selection = !drawing;
    canvas.skipTargetFind = drawing;
    canvas.defaultCursor = drawing ? 'crosshair' : 'default';
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
          fill: 'rgba(124,148,190,0.06)', stroke: '#94a3b8',
          strokeWidth: 1.5, strokeDashArray: [6, 4], strokeUniform: true,
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
        // prioridad: enganchar a un extremo cercano; si no, snap ortogonal
        let end = snapPoint(p, state.snapPts);
        if (end === p) end = orthoSnap(state.start, p);
        state.draft.set({ x2: end.x, y2: end.y });
      }
      canvas.requestRenderAll();
    });

    canvas.on('mouse:up', () => {
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

    canvas.on('object:added',    () => pushHistory());
    canvas.on('object:modified', () => pushHistory());
    canvas.on('object:removed',  () => pushHistory());
  }

  /* ── Constructores ──────────────────────────────────────── */

  // Puerta orientada según el arrastre: bisagra en `start`, hoja hacia el eje
  // dominante del arrastre y arco de barrido de 90° hacia la esquina.
  function makeDoor(start, end, s) {
    const sx = Math.sign(end.x - start.x) || 1;
    const sy = Math.sign(end.y - start.y) || 1;
    const hx = start.x + sx * s, hy = start.y;        // extremo de la hoja
    const ax = start.x, ay = start.y + sy * s;        // extremo del arco
    const sweep = (sx * sy > 0) ? 1 : 0;
    const path = `M ${start.x} ${start.y} L ${hx} ${hy} M ${hx} ${hy} A ${s} ${s} 0 0 ${sweep} ${ax} ${ay}`;
    const door = new fabric.Path(path, {
      stroke: '#1f2937', strokeWidth: 2,
      fill: 'transparent', srType: 'puerta', srCat: 'shape',
    });
    // centro REAL del hueco de paso (entre la bisagra y el extremo del arco),
    // no el centro del recuadro del arco → para que las rutas crucen por ahí.
    door.srGapX = (start.x + ax) / 2;
    door.srGapY = (start.y + ay) / 2;
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

  /* ── Título del mapa ────────────────────────────────────── */

  const drugName = () => (typeof PLAN_NAME !== 'undefined' && PLAN_NAME) ? PLAN_NAME : '';
  const titleFor = (mode) => {
    const base = mode === 'evac' ? 'RUTA DE EVACUACIÓN'
      : mode === 'san' ? 'RUTA SANITARIA'
        : 'RUTA DE EVACUACIÓN / SANITARIA';
    const n = drugName();
    return base + (n ? '  —  ' + n : '');
  };

  // Crea el título arriba del mapa si aún no existe (se guarda con el plano).
  function ensureTitle() {
    if (canvas.getObjects().some(o => o.srType === 'titulo')) return;
    const t = new fabric.IText(titleFor(null), {
      left: DOC.w / 2, top: 20, originX: 'center', originY: 'top',
      fontFamily: 'Syne', fontWeight: 'bold', fontSize: 32, fill: '#111827',
      textAlign: 'center', srType: 'titulo', srCat: 'title',
    });
    canvas.add(t);
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

    const rectCells = (r, pad, fn) => {
      const x0 = Math.max(0, Math.floor((r.left - pad) / GRID));
      const x1 = Math.min(cols - 1, Math.floor((r.left + r.width + pad) / GRID));
      const y0 = Math.max(0, Math.floor((r.top - pad) / GRID));
      const y1 = Math.min(rows - 1, Math.floor((r.top + r.height + pad) / GRID));
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
    //    El desbloqueo debe ser MÁS ancho que la banda que infla la pared
    //    (CLEAR + grosor), si no el hueco no atraviesa y A* no puede pasar.
    const OPEN_PAD = CLEAR + 6;
    canvas.getObjects().forEach((o) => {
      if (o.srType !== 'puerta' && o.srType !== 'vano') return;
      rectCells(o.getBoundingRect(true, true), OPEN_PAD, (i) => { blocked[i] = 0; });
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

  // `ownColor` + `usedColor` (Map celda→color): premia seguir el mismo color
  // (fusión) y penaliza cruzar otro color (menos cruces).
  function astar(grid, start, goal, ownColor, usedColor) {
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
        if (usedColor) {
          const oc = usedColor.get(nI);
          if (oc === ownColor) step = Math.min(step, PREF_STEP);   // mismo color → fusión
          else if (oc) step += AVOID_PEN;                          // otro color → evitar cruce
        }
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

  function sampleAlong(points, spacing, offset) {
    const res = [];
    let next = offset, dist = 0;
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i], b = points[i + 1];
      const seg = Math.hypot(b.x - a.x, b.y - a.y);
      const ang = Math.atan2(b.y - a.y, b.x - a.x);
      while (next <= dist + seg) {
        const t = (next - dist) / seg;
        res.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, ang });
        next += spacing;
      }
      dist += seg;
    }
    return res;
  }

  // Una flecha "→" (cola + dos alas) como un solo trazo alineado, en (cx,cy)→ang.
  function arrowGlyph(cx, cy, ang, color) {
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
    });
  }

  const inRect = (x, y, r, pad) =>
    x >= r.left - pad && x <= r.left + r.width + pad &&
    y >= r.top - pad && y <= r.top + r.height + pad;

  // Ruta = flechas "→" a intervalos (línea segmentada direccional, sin barra).
  // `placed` evita encimar flechas del mismo color; `items` evita ponerlas
  // encima de un icono.
  function makeRoute(points, color, modeKey, phase, placed, items) {
    const samples = sampleAlong(points, ARROW_GAP, ARROW_GAP * 0.5);
    const n = points.length;
    if (n >= 2) {
      const a = points[n - 2], b = points[n - 1];
      samples.push({ x: b.x, y: b.y, ang: Math.atan2(b.y - a.y, b.x - a.x) });
    }
    if (!samples.length && n >= 2) {
      const a = points[0], b = points[n - 1];
      samples.push({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, ang: Math.atan2(b.y - a.y, b.x - a.x) });
    }
    const minD2 = ARROW_MINDIST * ARROW_MINDIST;
    const parts = [];
    samples.forEach(s => {
      if (items && items.some(r => inRect(s.x, s.y, r, 6))) return;   // no sobre iconos
      if (placed) {
        if (placed.some(p => (p.x - s.x) ** 2 + (p.y - s.y) ** 2 < minD2)) return;
        placed.push({ x: s.x, y: s.y });
      }
      parts.push(arrowGlyph(s.x, s.y, s.ang, color));
    });
    if (!parts.length) return null;
    return new fabric.Group(parts, { srType: 'ruta-' + modeKey, srCat: 'ruta-auto' });
  }

  function clearRoutes(modeKey) {
    canvas.getObjects().filter(o => o.srType === 'ruta-' + modeKey).forEach(o => canvas.remove(o));
  }

  function generate(modeKey) {
    const all = canvas.getObjects();
    const goals = all.filter(isSalida);
    if (!goals.length) { setStatus('Coloca una salida (Salida Emerg. o Entrada/Salida)', 'warn'); return; }

    // jobs = { center, color }
    let jobs;
    if (modeKey === 'evac') {
      const origins = all.filter(o => o.srType === 'origen-evac');
      if (!origins.length) { setStatus('Coloca al menos un origen verde', 'warn'); return; }
      jobs = origins.map(o => ({ center: o.getCenterPoint(), color: EVAC_COLOR }));
    } else {
      const canecas = all.filter(o => typeof o.srType === 'string' && o.srType.startsWith('caneca_'));
      if (!canecas.length) { setStatus('Coloca al menos una caneca', 'warn'); return; }
      jobs = canecas.map(o => ({ center: o.getCenterPoint(), color: CANECA_COLOR[o.srType] || '#dc2626' }));
    }

    state.suppress = true;
    clearRoutes(modeKey);
    const grid = buildGrid();
    const cols = grid.cols;
    const goalCells = goals.map(g => nearestFree(grid, toCell(g.getCenterPoint()).cx, toCell(g.getCenterPoint()).cy)).filter(Boolean);
    const doorCenters = all.filter(o => o.srType === 'puerta' || o.srType === 'vano')
      .map(o => (typeof o.srGapX === 'number') ? { x: o.srGapX, y: o.srGapY } : o.getCenterPoint());

    // preparar: celda de inicio + meta más cercana
    const prepared = jobs.map(j => {
      const sCell = nearestFree(grid, toCell(j.center).cx, toCell(j.center).cy);
      if (!sCell) return null;
      let best = null, bestD = Infinity, gi = -1;
      goalCells.forEach((gc, i) => { const d = heur(sCell, gc); if (d < bestD) { bestD = d; best = gc; gi = i; } });
      return best ? { ...j, sCell, goalCell: best, goalIdx: gi, dist: bestD } : null;
    }).filter(Boolean);

    // tronco primero (más lejano), para que los cercanos se fusionen a él
    prepared.sort((a, b) => b.dist - a.dist);

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
    let drawn = 0;
    prepared.forEach(j => {
      let cells = astar(grid, j.sCell, j.goalCell, j.color, usedColor);
      if (!cells || cells.length < 2) return;

      // truncar al primer punto ya cubierto por una ruta del MISMO color (fusión)
      let cut = cells.length;
      for (let i = 1; i < cells.length; i++) {
        if (usedColor.get(cells[i].cy * cols + cells[i].cx) === j.color) { cut = i + 1; break; }
      }
      cells = cells.slice(0, cut);
      if (cells.length < 2) return;

      cells.forEach(c => usedColor.set(c.cy * cols + c.cx, j.color));
      const pts = offsetPath(densify(simplify(cells), 22), laneOf[j.color] || 0, grid, doorCenters);
      const list = placedByColor[j.color] || (placedByColor[j.color] = []);
      const route = makeRoute(pts, j.color, modeKey, null, list, itemRects);
      if (route) { canvas.add(route); drawn++; }
    });

    state.suppress = false;
    pushHistory();
    setStatus(
      drawn ? `${drawn} ruta(s) generada(s)` : 'No se encontró ruta (¿hay un pasillo libre hasta la salida?)',
      drawn ? 'ok' : 'err'
    );
  }

  const generateEvac = () => generate('evac');
  const generateSan  = () => generate('san');
  const clearAll = () => { state.suppress = true; clearRoutes('evac'); clearRoutes('san'); state.suppress = false; pushHistory(); setStatus('Rutas eliminadas'); };

  /* ── Selección / borrado ────────────────────────────────── */

  function deleteSelected() {
    const objs = canvas.getActiveObjects();
    if (!objs.length) return;
    objs.forEach(o => canvas.remove(o));
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    pushHistory();
  }

  /* ── Historial ──────────────────────────────────────────── */

  function snapshot() { return JSON.stringify(canvas.toJSON(PROPS)); }
  function pushHistory(initial = false) {
    if (state.loadingHistory || state.suppress) return;
    const snap = snapshot();
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
    generateEvac, generateSan, clearAll,
    setFont, setTextSize, toggleBold,
  };
})();

function toggleSection(hd) { hd.parentElement.classList.toggle('collapsed'); }
