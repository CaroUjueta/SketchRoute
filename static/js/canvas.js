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
const CLEAR = 11;                  // holgura alrededor de obstáculos (px)
const SNAP = 16;                   // radio de enganche entre extremos (px)
const ARROW_GAP = 150;             // separación entre flechitas (px)
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

const LANE_GAP = 8;   // separación entre carriles de distinto color (px)
const LANE_CAP = 7;   // desfase máximo respecto al centro del pasillo (px)

const isSalida = (o) => o.srType === 'salida_emergencia' || o.srType === 'entrada_salida';

const SR = (() => {
  let canvas = null;

  const state = {
    tool: 'select', zoom: 1,
    isDown: false, draft: null, start: null, snapPts: [],
    history: [], redoStack: [], loadingHistory: false, suppress: false, dirty: false,
  };

  const PROPS = ['srType', 'srCat', 'srHidden'];

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
    window.addEventListener('resize', fit);

    if (savedData) {
      state.loadingHistory = true;
      canvas.loadFromJSON(savedData, () => {
        canvas.renderAll(); fit();
        state.loadingHistory = false;
        pushHistory(true);
        setStatus('Plano cargado');
      });
    } else {
      fit();
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
    return new fabric.Path(path, {
      stroke: '#1f2937', strokeWidth: 2,
      fill: 'transparent', srType: 'puerta', srCat: 'shape',
    });
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
    ], { srType: 'vano', srCat: 'shape' });
  }

  function addText(x, y) {
    const t = new fabric.IText('Texto', {
      left: x, top: y, fontFamily: 'DM Sans, sans-serif',
      fontSize: 22, fill: '#111827', srType: 'texto', srCat: 'text',
    });
    canvas.add(t);
    canvas.setActiveObject(t);
    t.enterEditing(); t.selectAll();
    backToSelect();
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

    // 2) abrir el paso donde hay puertas o vanos (único cruce permitido)
    canvas.getObjects().forEach((o) => {
      if (o.srType !== 'puerta' && o.srType !== 'vano') return;
      rectCells(o.getBoundingRect(true, true), 2, (i) => { blocked[i] = 0; });
    });

    return { cols, rows, blocked };
  }

  // Desplaza la polilínea perpendicularmente (carriles paralelos por color).
  function offsetPath(pts, d) {
    if (!d || pts.length < 2) return pts;
    return pts.map((p, i) => {
      const prev = pts[i - 1] || p, next = pts[i + 1] || p;
      const dx = next.x - prev.x, dy = next.y - prev.y;
      const len = Math.hypot(dx, dy) || 1;
      return { x: p.x + (-dy / len) * d, y: p.y + (dx / len) * d };
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

  function astar(grid, start, goal) {
    const { cols, rows, blocked } = grid;
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
      for (const [nx, ny] of [[cx+1,cy],[cx-1,cy],[cx,cy+1],[cx,cy-1]]) {
        if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
        const nI = ny * cols + nx;
        if (blocked[nI]) continue;
        const ng = g[cur] + 1;
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

  // Ruta estilo "rayita-flechita": línea de guiones + puntas espaciadas.
  function makeRoute(points, color, modeKey) {
    const parts = [new fabric.Polyline(points, {
      stroke: color, strokeWidth: 3.5, fill: 'transparent',
      strokeDashArray: [9, 7], strokeLineCap: 'round', strokeLineJoin: 'round',
      objectCaching: false,
    })];
    const samples = sampleAlong(points, ARROW_GAP, ARROW_GAP * 0.5);
    const n = points.length;
    if (n >= 2) {
      const a = points[n - 2], b = points[n - 1];
      samples.push({ x: b.x, y: b.y, ang: Math.atan2(b.y - a.y, b.x - a.x) });
    }
    samples.forEach(s => parts.push(new fabric.Triangle({
      left: s.x, top: s.y, originX: 'center', originY: 'center',
      width: 11, height: 13, fill: color, angle: s.ang * 180 / Math.PI + 90,
    })));
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

    // asignar un carril a cada color presente (para no encimar rutas)
    const colorsUsed = [...new Set(prepared.map(j => j.color))];
    const laneOf = {};
    colorsUsed.forEach((col, i) => {
      const off = (i - (colorsUsed.length - 1) / 2) * LANE_GAP;
      laneOf[col] = Math.max(-LANE_CAP, Math.min(LANE_CAP, off));
    });

    const usedByGroup = {};
    let drawn = 0;
    prepared.forEach(j => {
      const key = j.goalIdx + '|' + j.color;     // fusiona por destino + color
      const used = usedByGroup[key] || (usedByGroup[key] = new Set());
      let cells = astar(grid, j.sCell, j.goalCell);
      if (!cells || cells.length < 2) return;

      // truncar al primer punto ya cubierto por otra ruta del grupo
      let cut = cells.length;
      for (let i = 1; i < cells.length; i++) {
        if (used.has(cells[i].cy * cols + cells[i].cx)) { cut = i + 1; break; }
      }
      cells = cells.slice(0, cut);
      if (cells.length < 2) return;

      cells.forEach(c => used.add(c.cy * cols + c.cx));
      const pts = offsetPath(simplify(cells), laneOf[j.color] || 0);
      canvas.add(makeRoute(pts, j.color, modeKey));
      drawn++;
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

  function exportPDF() {
    setStatus('Generando PDF…');
    canvas.discardActiveObject();
    const hidden = canvas.getObjects().filter(o => o.srHidden);
    hidden.forEach(o => (o.visible = false));

    const prevZoom = state.zoom;
    applyZoom(1);
    const dataURL = canvas.toDataURL({ format: 'png', multiplier: 2, backgroundColor: '#ffffff' });
    applyZoom(prevZoom);

    hidden.forEach(o => (o.visible = true));
    canvas.requestRenderAll();

    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: [216, 330] });
    const pw = pdf.internal.pageSize.getWidth();
    const ph = pdf.internal.pageSize.getHeight();
    pdf.addImage(dataURL, 'PNG', 0, 0, pw, ph);
    pdf.save((PLAN_NAME || 'plano') + '.pdf');
    setStatus('PDF exportado', 'ok');
  }

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
    zoomIn, zoomOut, zoomReset, save, exportPDF,
    generateEvac, generateSan, clearAll,
  };
})();

function toggleSection(hd) { hd.parentElement.classList.toggle('collapsed'); }
