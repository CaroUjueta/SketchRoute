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
const CLEAR = 20;                  // holgura para abrir el paso en puertas (px)
// Holgura del BLOQUEO duro de paredes/muebles. Antes era CLEAR (20px): dos
// paredes de un pasillo de ~60px lo bloqueaban por completo y todo quedaba
// "sin salida". El A* ya penaliza acercarse a la pared (mapa `near`), así que
// el bloqueo duro solo necesita evitar el solape físico.
const BLOCK_PAD = 8;
const SNAP = 24;                   // radio de enganche entre extremos (px)
const LINE_W = 5;                  // grosor del trazo de la ruta (px)
const ARROW_SIZE = 16;             // apertura de la punta (px)
const SEGMENT_LEN = 46;            // largo de cada tramo recto de la ruta (px)
const SEGMENT_GAP = 20;            // hueco entre tramos (px)
const AUTOSAVE_MS = 2500;          // espera tras editar antes de autoguardar

const OBSTACLES = new Set(['pared', 'mueble', 'zona']);
const EVAC_COLOR = '#16a34a';

// Stack de fuente: usa la CenturyGothic instalada (nombre CSS "Century Gothic",
// CON espacio); si no está, cae a Jost (geométrica casi idéntica, vía Google Fonts).
const FONT_STACK = "'Century Gothic', Jost, Futura, 'Trebuchet MS', sans-serif";

// Color de la flecha según el tipo de caneca.
const RECICLABLE_COLOR = '#ffffff';   // blanca de verdad — ver isWhiteArrow() para el contorno
const CANECA_COLOR = {
  caneca_ordinaria:  '#111827',  // negra
  caneca_reciclable: RECICLABLE_COLOR,
  caneca_biosani:    '#dc2626',  // roja
  caneca_corto:      '#dc2626',  // roja
};

// Una flecha blanca sin contorno es invisible sobre la hoja blanca: se le
// agrega un trazo oscuro de fondo (ver renderRoute/makeArrowShape) SIEMPRE,
// no solo cuando hay halo por superposición.
const isWhiteArrow = (color) => (color || '').toLowerCase() === '#ffffff' || (color || '').toLowerCase() === '#fff';
const WHITE_OUTLINE = '#111827';

// Flechas manuales del sidebar: idénticas a las que genera el programa, en cada
// color de ruta. Se arrastran y rotan para reemplazar una flecha mal generada.
const ARROW_TYPES = {
  flecha_evac:  { color: '#16a34a', mode: 'evac' },  // verde (evacuación)
  flecha_negra: { color: '#111827', mode: 'san'  },  // caneca ordinaria
  flecha_gris:  { color: RECICLABLE_COLOR, mode: 'san'  },  // caneca reciclable (blanca)
  flecha_roja:  { color: '#dc2626', mode: 'san'  },  // biosani / cortopunzantes
};

const LANE_GAP = 44;  // separación deseada entre carriles de distinto color (px)
const LANE_CAP = 40;  // desfase máximo (el adaptativo lo recorta si no cabe)
const TURN_PEN = 14;   // penalización por girar → recorridos rectos (en "L", no diagonales)
const CENTER_W = 1.6;  // peso del centrado (alejarse de paredes)
const DOOR_R = 60;     // radio en el que las rutas convergen al centro de una puerta
const PREF_STEP = 0.35;// costo (casi gratis) de seguir un corredor ya trazado → confluencia

// Una salida es destino de ruta solo si la puso el usuario. (El filtro
// !srAuto se mantiene por compatibilidad con planos guardados antes.)
const isSalida = (o) => (o.srType === 'salida_emergencia' || o.srType === 'entrada_salida') && !o.srAuto;

const SR = (() => {
  let canvas = null;

  const state = {
    tool: 'select', zoom: 1,
    isDown: false, draft: null, start: null, snapPts: [],
    history: [], redoStack: [], loadingHistory: false, suppress: false, dirty: false, conflict: false,
    panning: false, panStart: null, spaceDown: false, nudged: false,
    gridSnap: false, guides: [],
  };

  const PROPS = ['srType', 'srCat', 'srHidden', 'srGapX', 'srGapY', 'srDir', 'srDirX', 'srDirY', 'srAuto', 'srLen'];

  // Silencia historial/autosave mientras corre fn; el finally garantiza que un
  // throw no deje state.suppress colgado (historial congelado en silencio).
  function withSuppress(fn) {
    state.suppress = true;
    try { return fn(); } finally { state.suppress = false; }
  }

  // Único punto de limpieza del estado transitorio: drafts a medias, previews,
  // cadena de paredes, guías y pan. Se llama al cambiar de herramienta, con
  // Escape y al perder el foco de la ventana — evita objetos y guías fantasma.
  function resetTransient() {
    if (state.draft) { withSuppress(() => canvas.remove(state.draft)); state.draft = null; }
    clearRoutePreview();
    state.routePts = [];
    state.rDrag = false; state.rMoved = false; state.freePts = [];
    endWallChain();
    state.isDown = false;
    state.suppress = false;
    state.panning = false; state.spaceDown = false;
    if (state.guides.length) { state.guides = []; canvas.clearContext(canvas.contextTop); }
    applyToolFlags();
    canvas.requestRenderAll();
  }

  /* ── Inicialización ─────────────────────────────────────── */

  function init(savedData) {
    canvas = new fabric.Canvas('floorCanvas', {
      width: DOC.w, height: DOC.h,
      backgroundColor: '#ffffff',
      preserveObjectStacking: true,
      selection: true,
      targetFindTolerance: 10,   // facilita clicar líneas finas para moverlas
      perPixelTargetFind: false,
      fireMiddleClick: true,     // pan con botón medio
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
    bindSmartGuides();
    const syncBars = () => { syncTextBar(); syncPropBar(); };
    canvas.on('selection:created', syncBars);
    canvas.on('selection:updated', syncBars);
    canvas.on('selection:cleared', syncBars);
    bindUppercase();
    window.addEventListener('resize', fit);
    // Al perder el foco (cambio de pestaña/ventana) el keyup de Space nunca
    // llega y el pan quedaba pegado; también limpia drafts y guías fantasma.
    window.addEventListener('blur', resetTransient);
    document.addEventListener('visibilitychange', () => { if (document.hidden) resetTransient(); });

    if (savedData) {
      state.loadingHistory = true;
      try {
        canvas.loadFromJSON(savedData, () => {
          ensurePageBg();
          canvas.renderAll(); fit();
          state.loadingHistory = false;
          // Planos viejos con rutas auto como paths sueltos cargan tal cual;
          // el primer "Generar" los reemplaza por grupos (clearRoutes cubre ambos).
          splitLegacyRouteGroups();
          migrateReciclableColor();
          fixupManualArrows();
          fixupWallCaps();
          ensureHeader();
          pushHistory(true);
          updateEmptyHint();
          setStatus('Plano cargado');
        });
      } catch (e) {
        console.error('loadFromJSON falló:', e);
        setStatus('Error al cargar plano', 'error');
        ensurePageBg();
        fit();
        state.loadingHistory = false;
        ensureHeader();
        pushHistory(true);
      }
    } else {
      ensurePageBg();
      fit();
      ensureHeader();
      pushHistory(true);
      updateEmptyHint();
    }
  }

  /* ── Croquis original como referencia ───────────────────────
     Desactivado por solicitud del usuario — la imagen de fondo
     no debe aparecer en el editor; solo el resultado vectorizado. */

  /* ── Vista / zoom ───────────────────────────────────────── */

  // "Hoja" blanca del documento: con viewportTransform el elemento canvas ya no
  // coincide con el documento, así que la página se dibuja como un Rect de fondo.
  // excludeFromExport → no entra al JSON (autosave/historial); se recrea al cargar.
  function ensurePageBg() {
    canvas.backgroundColor = '';
    let bg = canvas.getObjects().find(o => o.srCat === 'page');
    if (!bg) {
      bg = new fabric.Rect({
        left: 0, top: 0, width: DOC.w, height: DOC.h, fill: '#ffffff',
        selectable: false, evented: false, excludeFromExport: true,
        hoverCursor: 'default', srCat: 'page',
        shadow: new fabric.Shadow({ color: 'rgba(0,0,0,0.35)', blur: 18, offsetY: 4 }),
      });
      withSuppress(() => canvas.add(bg));
    }
    canvas.sendToBack(bg);
  }

  function applyZoom(z, point) {
    state.zoom = Math.min(Math.max(z, 0.05), 4);
    const p = point || new fabric.Point(canvas.getWidth() / 2, canvas.getHeight() / 2);
    canvas.zoomToPoint(p, state.zoom);
    canvas.requestRenderAll();
  }
  function fit() {
    const wrap = document.getElementById('canvasWrap');
    if (!wrap) return;
    canvas.setDimensions({ width: wrap.clientWidth, height: wrap.clientHeight });
    const cw = canvas.getWidth(), ch = canvas.getHeight();
    state.zoom = Math.min((cw - 48) / DOC.w, (ch - 48) / DOC.h);
    canvas.setViewportTransform([state.zoom, 0, 0, state.zoom,
      (cw - DOC.w * state.zoom) / 2, (ch - DOC.h * state.zoom) / 2]);
    canvas.calcOffset();
    canvas.requestRenderAll();
  }
  const zoomIn    = () => applyZoom(state.zoom * 1.15);
  const zoomOut   = () => applyZoom(state.zoom / 1.15);
  const zoomReset = () => fit();

  // Patrón de cuadrícula para la hoja (solo visual: excludeFromExport en la
  // página → no sale en el PDF ni se guarda).
  function gridPattern() {
    const t = document.createElement('canvas');
    t.width = t.height = GRID_SNAP_PX;
    const c = t.getContext('2d');
    c.fillStyle = '#ffffff'; c.fillRect(0, 0, t.width, t.height);
    c.strokeStyle = '#dbeafe'; c.lineWidth = 1;
    c.beginPath();
    c.moveTo(0.5, 0); c.lineTo(0.5, t.height);
    c.moveTo(0, 0.5); c.lineTo(t.width, 0.5);
    c.stroke();
    return new fabric.Pattern({ source: t, repeat: 'repeat' });
  }

  function toggleGrid(btnEl) {
    state.gridSnap = !state.gridSnap;
    if (btnEl) btnEl.classList.toggle('active', state.gridSnap);
    const bg = canvas.getObjects().find(o => o.srCat === 'page');
    if (bg) {
      bg.set('fill', state.gridSnap ? gridPattern() : '#ffffff');
      bg.dirty = true;
      canvas.requestRenderAll();
    }
    setStatus(state.gridSnap ? 'Cuadrícula activada (los objetos se enganchan a ella)' : 'Cuadrícula desactivada');
  }

  /* ── Herramientas ───────────────────────────────────────── */

  function setTool(tool, btnEl) {
    resetTransient();
    state.tool = tool;
    document.querySelectorAll('.ed-tool').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    else if (tool === 'select') {
      const sb = document.getElementById('tool-select');
      if (sb) sb.classList.add('active');
    }

    if (tool === 'erase') {
      const selected = canvas.getActiveObjects();
      if (selected.length > 0) {
        withSuppress(() => selected.forEach(o => canvas.remove(o)));
        canvas.discardActiveObject();
        pushHistory();
        setStatus(`${selected.length} elemento(s) borrado(s)`);
      }
    }

    applyToolFlags();
    canvas.discardActiveObject();
    canvas.requestRenderAll();
  }
  const backToSelect = () => setTool('select', null);

  // Flags de interacción según herramienta (se re-aplican al soltar el pan).
  function applyToolFlags() {
    const t = state.tool;
    const drawing = t !== 'select';
    canvas.selection = !drawing;
    // en modo pared también se pueden seleccionar objetos existentes
    canvas.skipTargetFind = drawing && t !== 'erase' && t !== 'wall';
    canvas.defaultCursor = t === 'erase' ? 'crosshair' : (drawing ? 'crosshair' : 'default');
  }

  /* ── Enganche de extremos (snap) ────────────────────────── */

  const SNAP_TYPES = new Set(['pared', 'mueble', 'puerta', 'vano']);
  function collectEndpoints(skipObj) {
    const pts = [];
    canvas.getObjects().forEach((o) => {
      if (o === state.draft || o === skipObj || !SNAP_TYPES.has(o.srType)) return;
      if (o.type === 'line') {
        // extremos REALES de la línea (el bounding rect incluye el grosor del
        // trazo, y ese medio-grosor de error dejaba las esquinas descuadradas)
        const m = o.calcTransformMatrix();
        const lp = o.calcLinePoints();
        pts.push(
          fabric.util.transformPoint(new fabric.Point(lp.x1, lp.y1), m),
          fabric.util.transformPoint(new fabric.Point(lp.x2, lp.y2), m),
        );
      } else {
        // puerta / vano: las cuatro esquinas del hueco (no del bbox con arco)
        const r = gapRect(o);
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

  // Proyecta el punto sobre la pared más cercana (≤14px): las puertas se
  // dibujan ENGANCHADAS a la pared, centradas en su eje.
  function wallAt(p, thr) {
    let best = null, bd = thr || 14;
    canvas.getObjects().forEach(o => {
      if (o.srType !== 'pared' || o.type !== 'line') return;
      const m = o.calcTransformMatrix();
      const lp = o.calcLinePoints();
      const a = fabric.util.transformPoint(new fabric.Point(lp.x1, lp.y1), m);
      const b = fabric.util.transformPoint(new fabric.Point(lp.x2, lp.y2), m);
      const dx = b.x - a.x, dy = b.y - a.y;
      const len2 = dx * dx + dy * dy || 1;
      const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
      const q = { x: a.x + dx * t, y: a.y + dy * t };
      const d = Math.hypot(q.x - p.x, q.y - p.y);
      if (d < bd) {
        bd = d;
        const len = Math.sqrt(len2);
        best = {
          q,
          dir: Math.abs(dx) >= Math.abs(dy) ? 'h' : 'v',
          ux: dx / len, uy: dy / len, // vector unitario a lo largo de la pared, cualquier ángulo
        };
      }
    });
    return best;
  }

  /* ── Extremos editables de paredes ──────────────────────── */

  const lineEndAbs = (o) => {
    const m = o.calcTransformMatrix();
    const lp = o.calcLinePoints();
    return [
      fabric.util.transformPoint(new fabric.Point(lp.x1, lp.y1), m),
      fabric.util.transformPoint(new fabric.Point(lp.x2, lp.y2), m),
    ];
  };

  function makeEndControl(idx) {
    return new fabric.Control({
      cursorStyle: 'crosshair',
      actionName: 'moveEnd',
      // Zona de agarre grande: así "mover la pared entera" queda reservado
      // al tercio central, y agarrar cerca de cualquier esquina siempre
      // arranca una pared nueva (o mueve el extremo con Alt).
      sizeX: 40,
      sizeY: 40,
      // Arrastrar desde la esquina arranca una pared nueva (sin buscar el
      // pixel exacto lejos del extremo); Alt+arrastre mueve el extremo
      // como antes.
      mouseDownHandler: (eventData, transform, x, y) => {
        if (eventData.e.altKey) return false;
        const obj = transform.target;
        const from = lineEndAbs(obj)[idx];
        canvas.discardActiveObject();
        state.tool = 'wall';
        applyToolFlags();
        document.querySelectorAll('.ed-tool').forEach(b => b.classList.remove('active'));
        const wb = document.getElementById('tool-wall');
        if (wb) wb.classList.add('active');
        state.chain = { x: from.x, y: from.y };
        setStatus('Clic en el punto final de la pared (Esc cancela)');
        canvas.requestRenderAll();
        return true;
      },
      positionHandler: (dim, finalMatrix, obj) => {
        const ends = lineEndAbs(obj);
        return fabric.util.transformPoint(
          new fabric.Point(ends[idx].x, ends[idx].y),
          obj.canvas.viewportTransform,
        );
      },
      actionHandler: (eventData, transform, x, y) => {
        const obj = transform.target;
        const ends = lineEndAbs(obj);
        const others = collectEndpoints(obj);
        let p = snapPoint({ x, y }, others);
        state.guides = [];
        if (p === undefined || (p.x === x && p.y === y)) {
          // sin enganche total: alinear por eje con extremos de otras paredes
          p = { x, y };
          let bx = null, by = null;
          others.forEach(q => {
            if (Math.abs(q.x - p.x) < 7 && (!bx || Math.abs(q.x - p.x) < Math.abs(bx - p.x))) bx = q.x;
            if (Math.abs(q.y - p.y) < 7 && (!by || Math.abs(q.y - p.y) < Math.abs(by - p.y))) by = q.y;
          });
          if (bx !== null) { p.x = bx; state.guides.push({ v: bx }); }
          if (by !== null) { p.y = by; state.guides.push({ h: by }); }
          // ortogonal contra el otro extremo de la MISMA pared
          const other = ends[1 - idx];
          if (Math.abs(p.x - other.x) < 9) p.x = other.x;
          if (Math.abs(p.y - other.y) < 9) p.y = other.y;
        }
        ends[idx] = p;
        obj.set({
          x1: ends[0].x, y1: ends[0].y, x2: ends[1].x, y2: ends[1].y,
          originX: 'center', originY: 'center',
          left: (ends[0].x + ends[1].x) / 2, top: (ends[0].y + ends[1].y) / 2,
        });
        obj.setCoords();
        return true;
      },
      render: (ctx, left, top) => {
        ctx.save();
        ctx.fillStyle = '#2563eb'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(left, top, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        ctx.restore();
      },
    });
  }
  const LINE_CONTROLS = { e0: makeEndControl(0), e1: makeEndControl(1) };

  function armWallControls(o) {
    o.controls = LINE_CONTROLS;   // solo las 2 manijas de extremo
    o.hasBorders = false;
  }

  // Normaliza paredes/muebles al cargar: cap cuadrado, anclaje al centro
  // (necesario para editar extremos) y manijas de extremos.
  function fixupWallCaps() {
    canvas.getObjects().forEach(o => {
      if ((o.srType !== 'pared' && o.srType !== 'mueble') || o.type !== 'line') return;
      if (o.strokeLineCap !== 'square') o.set('strokeLineCap', 'square');
      if (o.originX !== 'center') {
        const c = o.getCenterPoint();
        o.set({ originX: 'center', originY: 'center', left: c.x, top: c.y });
        o.setCoords();
      }
      armWallControls(o);
    });
  }

  /* ── Eventos de dibujo ──────────────────────────────────── */

  function bindCanvasEvents() {

    // Pan: espacio sostenido o botón medio del mouse.
    canvas.on('mouse:down', (opt) => {
      if (state.spaceDown || opt.e.button === 1) {
        state.panning = true;
        state.panStart = { x: opt.e.clientX, y: opt.e.clientY };
        canvas.setCursor('grabbing');
        return;
      }
      const t = state.tool;
      if (t === 'select') return;

      if (t === 'erase') {
        const active = canvas.getActiveObjects();
        if (active.length > 0) {
          withSuppress(() => active.forEach(o => canvas.remove(o)));
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

      // modo pared: clic sobre un objeto existente lo selecciona en vez de
      // dibujar encima (salvo que estés terminando una pared con clic-clic)
      if (t === 'wall' && opt.target && opt.target.srCat !== 'page' && !state.chain) return;

      const p = canvas.getPointer(opt.e);
      // sticky tool: los objetos puntuales vuelven a Seleccionar tras colocar;
      // Shift sostenido mantiene la herramienta para colocar varios seguidos.
      const sticky = () => { if (!opt.e.shiftKey) backToSelect(); };
      if (t === 'text')        { addText(p.x, p.y); sticky(); return; }
      if (t === 'origen-evac') { placeMarker(p.x, p.y); sticky(); return; }
      if (t === 'place')       { if (state.placeType) { addIcon(state.placeType, p.x, p.y); sticky(); } return; }
      if (t === 'ruta') {
        // se decide en mouse:up si fue clic (vértice) o arrastre (mano alzada)
        state.rDrag = true; state.rMoved = false; state.freePts = [p];
        return;
      }

      state.snapPts = collectEndpoints();
      let sp;
      state.wallDir = null;
      if (t === 'rect') {
        sp = p;
      } else if (t === 'door' || t === 'vano') {
        const w = wallAt(p);                       // enganchar a la pared
        sp = w ? w.q : snapPoint(p, state.snapPts);
        state.wallDir = w ? { x: w.ux, y: w.uy } : null;   // vector real de la pared, cualquier ángulo
      } else {
        sp = snapPoint(p, state.snapPts);
      }
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
        // cap cuadrado: dos paredes que se encuentran en un extremo forman
        // esquina a inglete perfecta (el redondo dejaba "colitas" salidas).
        // Si hay cadena activa, la pared arranca donde terminó la anterior.
        const from = state.chain || sp;
        state.start = from;
        clearWallPreview();
        state.draft = new fabric.Line([from.x, from.y, sp.x, sp.y], {
          stroke: '#1f2937', strokeWidth: 8, strokeLineCap: 'square',
          srType: 'pared', srCat: 'shape',
        });
      } else if (t === 'furniture') {
        state.draft = new fabric.Line([sp.x, sp.y, sp.x, sp.y], {
          stroke: '#6b7280', strokeWidth: 2, strokeLineCap: 'square',
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
      if (state.panning) {
        const vpt = canvas.viewportTransform;
        vpt[4] += opt.e.clientX - state.panStart.x;
        vpt[5] += opt.e.clientY - state.panStart.y;
        state.panStart = { x: opt.e.clientX, y: opt.e.clientY };
        canvas.requestRenderAll();
        return;
      }
      // preview de pared encadenada (mouse suelto, esperando el próximo clic)
      if (state.tool === 'wall' && state.chain && !state.isDown) {
        const p0 = canvas.getPointer(opt.e);
        let end = snapPoint(p0, collectEndpoints());
        if (end === p0) end = orthoSnap(state.chain, p0);
        clearWallPreview();
        withSuppress(() => {
          state.wallPreview = new fabric.Line([state.chain.x, state.chain.y, end.x, end.y], {
            stroke: '#94a3b8', strokeWidth: 3, strokeDashArray: [7, 6],
            selectable: false, evented: false, srCat: 'temp',
          });
          canvas.add(state.wallPreview);
        });
        canvas.requestRenderAll();
        return;
      }
      if (state.tool === 'ruta') {
        const p = canvas.getPointer(opt.e);
        if (state.rDrag) {
          state.freePts.push(p);
          if (!state.rMoved && Math.hypot(p.x - state.freePts[0].x, p.y - state.freePts[0].y) > 12) state.rMoved = true;
          if (state.rMoved) {
            // preview del trazo libre: una sola polilínea temporal
            clearRoutePreview();
            const spec = ROUTE_KINDS[state.routeKind];
            const pl = new fabric.Polyline(state.freePts.map(q => ({ x: q.x, y: q.y })), {
              fill: 'transparent', stroke: spec.color, strokeWidth: 2, strokeDashArray: [6, 5],
              selectable: false, evented: false, srCat: 'temp', objectCaching: false,
            });
            withSuppress(() => canvas.add(pl));
            state.routePreview = [pl];
            canvas.requestRenderAll();
          }
        } else if ((state.routePts || []).length) {
          const last = state.routePts[state.routePts.length - 1];
          const c = Math.abs(p.x - last.x) >= Math.abs(p.y - last.y) ? { x: p.x, y: last.y } : { x: last.x, y: p.y };
          drawRoutePreview(c);
        }
        return;
      }
      if (!state.isDown || !state.draft) return;
      const p = canvas.getPointer(opt.e);

      if (state.tool === 'rect') {
        state.draft.set({
          width:  Math.abs(p.x - state.start.x),
          height: Math.abs(p.y - state.start.y),
          left:   Math.min(p.x, state.start.x),
          top:    Math.min(p.y, state.start.y),
        });
      } else if ((state.tool === 'door' || state.tool === 'vano') && state.wallDir) {
        // deslizar a lo largo de la pared enganchada (cualquier ángulo, no solo h/v)
        const dir = state.wallDir;
        const t = (p.x - state.start.x) * dir.x + (p.y - state.start.y) * dir.y;
        const end = { x: state.start.x + dir.x * t, y: state.start.y + dir.y * t };
        state.draft.set({ x2: end.x, y2: end.y });
      } else {
        let end = snapPoint(p, state.snapPts);
        if (end === p) end = orthoSnap(state.start, p);
        state.draft.set({ x2: end.x, y2: end.y });
      }
      canvas.requestRenderAll();
    });

    canvas.on('mouse:up', (opt) => {
      if (state.panning) {
        state.panning = false;
        canvas.setViewportTransform(canvas.viewportTransform); // recalcula coords de selección
        return;
      }
      if (state.tool === 'ruta' && state.rDrag) {
        state.rDrag = false;
        const p = canvas.getPointer(opt.e);
        if (state.rMoved) {
          state.routePts = rdp(state.freePts, 10);   // mano alzada → simplificar
          finalizeRoute();
        } else {
          state.routePts = state.routePts || [];
          state.routePts.push(p);                    // clic → vértice
          drawRoutePreview(null);
        }
        return;
      }
      if (!state.isDown) return;
      state.isDown = false;
      state.suppress = false;
      const d = state.draft;
      const t = state.tool;
      state.draft = null;
      if (!d) return;

      if (t === 'door' || t === 'vano') {
        const s = Math.hypot(d.x2 - d.x1, d.y2 - d.y1);
        canvas.remove(d);
        if (s >= 14) {
          const start = { x: d.x1, y: d.y1 }, end = { x: d.x2, y: d.y2 };
          canvas.add(t === 'door' ? makeDoor(start, end) : makeVano(start, end));
        }
        pushHistory();
        return;
      }
      const tiny = (t === 'rect')
        ? (d.width < 6 && d.height < 6)
        : (Math.hypot(d.x2 - d.x1, d.y2 - d.y1) < 8);
      if (tiny) {
        canvas.remove(d);
        if (t === 'wall' && !state.chain) {
          // primer clic de una cadena de paredes
          state.chain = { x: d.x1, y: d.y1 };
          setStatus('Clic en el punto final de la pared (Esc cancela)');
          return;
        }
        pushHistory();
        return;
      }

      if (t === 'wall' || t === 'furniture') {
        // Quirk de fabric.Line: la línea dibujada queda corrida strokeWidth/2
        // en el eje perpendicular (por eso las esquinas no casaban). Se
        // reconstruye anclada a su centro geométrico → extremos exactos.
        withSuppress(() => {
          canvas.remove(d);
          const nl = new fabric.Line([d.x1, d.y1, d.x2, d.y2], {
            stroke: d.stroke, strokeWidth: d.strokeWidth, strokeLineCap: 'square',
            srType: d.srType, srCat: d.srCat,
            originX: 'center', originY: 'center',
            left: (d.x1 + d.x2) / 2, top: (d.y1 + d.y2) / 2,
          });
          armWallControls(nl);
          canvas.add(nl);
        });
        if (t === 'wall') {
          // cada pared es independiente: la próxima empieza donde el usuario
          // haga clic, sin encadenarse al final de esta
          endWallChain();
        }
      }
      pushHistory();
    });

    canvas.on('mouse:dblclick', () => { if (state.tool === 'ruta') finalizeRoute(); });

    // Alt+arrastre duplica: deja una copia en el lugar original (estilo Figma).
    canvas.on('mouse:down', () => { state.altCloned = false; });
    canvas.on('object:moving', (opt) => {
      if (state.altCloned || !opt.e || !opt.e.altKey) return;
      const o = opt.target;
      if (!o || o.srCat === 'page' || o.type === 'activeSelection') return;
      state.altCloned = true;
      o.clone((cl) => { withSuppress(() => canvas.add(cl)); canvas.requestRenderAll(); pushHistory(); }, PROPS);
    });

    // Puertas esclavas: al moverlas se deslizan A LO LARGO de su pared;
    // a más de 30px de cualquier pared quedan libres (para cambiarlas de pared).
    canvas.on('object:moving', (opt) => {
      const o = opt.target;
      if (!o || (o.srType !== 'puerta' && o.srType !== 'vano')) return;
      const g = gapRect(o);
      const gc = { x: g.left + g.width / 2, y: g.top + g.height / 2 };
      const w = wallAt(gc, 30);
      if (!w) return;
      o.set({ left: o.left + (w.q.x - gc.x), top: o.top + (w.q.y - gc.y) });
      o.setCoords();
    });

    // Zoom con la rueda, centrado en el cursor.
    canvas.on('mouse:wheel', (opt) => {
      const e = opt.e;
      applyZoom(state.zoom * Math.pow(0.999, e.deltaY), new fabric.Point(e.offsetX, e.offsetY));
      e.preventDefault();
      e.stopPropagation();
    });

    // al terminar de estirar una flecha manual, hornear el estiramiento
    canvas.on('object:modified', (e) => {
      const o = e.target;
      if (o && o.srCat === 'ruta-manual') { try { bakeArrowStretch(o); } catch (ex) { console.error(ex); } }
    });

    canvas.on('object:added',   updateEmptyHint);
    canvas.on('object:removed', updateEmptyHint);

    const safePush = () => { try { pushHistory(); } catch (e) { console.error('pushHistory:', e); } };
    canvas.on('object:added',    safePush);
    canvas.on('object:modified', safePush);
    canvas.on('object:removed',  safePush);
  }

  /* ── Constructores ──────────────────────────────────────── */

  // Hueco en la pared (rectángulo blanco + borde) — lo comparten puerta y vano.
  // `dir` es el vector unitario a lo largo de la pared (cualquier ángulo, no solo h/v).
  function gapPath(start, s, dir) {
    const wt = 4; // mitad del grosor de pared (8px)
    const perp = { x: -dir.y * wt, y: dir.x * wt };
    const a1 = { x: start.x + perp.x, y: start.y + perp.y };
    const a2 = { x: start.x - perp.x, y: start.y - perp.y };
    const b1 = { x: a1.x + dir.x * s, y: a1.y + dir.y * s };
    const b2 = { x: a2.x + dir.x * s, y: a2.y + dir.y * s };
    const p = new fabric.Path(`M ${a1.x} ${a1.y} L ${b1.x} ${b1.y} L ${b2.x} ${b2.y} L ${a2.x} ${a2.y} Z`, {
      stroke: '#000000', strokeWidth: 2, fill: '#ffffff',
    });
    p.srGapX = start.x + dir.x * s / 2; p.srGapY = start.y + dir.y * s / 2;
    return p;
  }

  // Puerta: hueco + hoja perpendicular + arco de apertura (dibujo arquitectónico).
  function makeDoor(start, end) {
    const dx = end.x - start.x, dy = end.y - start.y;
    const s = Math.hypot(dx, dy) || 1;
    const dir = { x: dx / s, y: dy / s };
    const gap = gapPath(start, s, dir);
    // bisagra A, tope B, punta de la hoja T (la hoja abre hacia la izquierda del sentido de trazo)
    const A = { x: start.x, y: start.y };
    const B = { x: end.x, y: end.y };
    const n = { x: dir.y, y: -dir.x };
    const T = { x: A.x + n.x * s, y: A.y + n.y * s };
    const sweep = (n.x * dir.y - n.y * dir.x) > 0 ? 1 : 0;
    const leaf = new fabric.Line([A.x, A.y, T.x, T.y], { stroke: '#1f2937', strokeWidth: 3 });
    const arc = new fabric.Path(`M ${T.x} ${T.y} A ${s} ${s} 0 0 ${sweep} ${B.x} ${B.y}`, {
      stroke: '#9ca3af', strokeWidth: 1.5, strokeDashArray: [4, 4], fill: 'transparent',
    });
    return new fabric.Group([gap, leaf, arc], {
      srType: 'puerta', srCat: 'shape',
      srGapX: gap.srGapX, srGapY: gap.srGapY,
      srDirX: dir.x, srDirY: dir.y, srLen: s,
    });
  }

  // Vano: abertura simple en la pared (solo el hueco, sin hoja).
  function makeVano(start, end) {
    const dx = end.x - start.x, dy = end.y - start.y;
    const s = Math.hypot(dx, dy) || 1;
    const dir = { x: dx / s, y: dy / s };
    const v = gapPath(start, s, dir);
    v.srType = 'vano'; v.srCat = 'shape';
    v.srDirX = dir.x; v.srDirY = dir.y; v.srLen = s;
    return v;
  }

  // Rectángulo del HUECO de una puerta/vano, aunque el bbox incluya el arco.
  // El hueco es el primer hijo del grupo (gapPath, marcado con srGapX); su
  // bbox absoluto ya incluye la transformación del grupo, así que funciona
  // también con la puerta rotada o escalada.
  function gapRect(o) {
    const r = o.getBoundingRect(true, true);
    if (o.srType === 'puerta' && o.type === 'group') {
      const kids = o._objects || [];
      const gap = kids.find(ch => ch.srGapX !== undefined) || kids[0];
      if (gap && gap.getBoundingRect) {
        try { return gap.getBoundingRect(true, true); } catch (e) { /* cae al fallback */ }
      }
      // fallback geométrico (puerta sin rotar): el hueco queda en el borde
      // inferior (h) o derecho (v) porque la hoja abre hacia arriba/izquierda
      const horizontal = o.srDir ? o.srDir === 'h' : r.width >= r.height;
      if (Math.abs(o.angle || 0) > 1) return r;
      return horizontal
        ? { left: r.left, top: r.top + r.height - 9, width: r.width, height: 9 }
        : { left: r.left + r.width - 9, top: r.top, width: 9, height: r.height };
    }
    return r;
  }

  function addText(x, y) {
    const t = new fabric.IText('Texto', {
      left: x, top: y, fontFamily: FONT_STACK,
      fontSize: 22, fill: '#111827', srType: 'texto', srCat: 'text',
    });
    canvas.add(t);
    canvas.setActiveObject(t);
    t.enterEditing(); t.selectAll();
    backToSelect();
    syncTextBar();
  }

  /* ── Encabezado del mapa (logo + título) ────────────────── */

  // Recorta el logo en círculo UNA vez sobre un canvas offscreen del mismo
  // tamaño que el PNG original (358×358) y lo cachea como data URL. Antes se
  // aplicaba un clipPath circular en vivo sobre la imagen dentro del grupo:
  // fabric cachea los objetos con clipPath en un canvas offscreen dimensionado
  // según el zoom del momento, así que al hacer zoom después se veía
  // pixelado. Con el círculo ya "horneado" en la imagen, no hace falta
  // clipPath y se ve nítido a cualquier zoom, igual que el resto de iconos.
  let _circularLogoURL = null;
  function getCircularLogoURL(cb) {
    if (_circularLogoURL) { cb(_circularLogoURL); return; }
    const src = new Image();
    src.crossOrigin = 'anonymous';
    src.onload = () => {
      const size = Math.max(src.width, src.height);
      const c = document.createElement('canvas');
      c.width = size; c.height = size;
      const ctx = c.getContext('2d');
      ctx.beginPath();
      ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
      ctx.closePath();
      ctx.clip();
      ctx.drawImage(src, (size - src.width) / 2, (size - src.height) / 2);
      _circularLogoURL = c.toDataURL('image/png');
      cb(_circularLogoURL);
    };
    src.src = '/static/img/logo.png';
  }

  // Arma el grupo logo redondo + "SYSTEFARMA" debajo, reutilizado tanto para
  // soltarlo como ícono desde el panel como para el encabezado automático de
  // un plano nuevo.
  function buildLogoGroup(widthPx, fontSize, cb) {
    getCircularLogoURL((url) => {
      fabric.Image.fromURL(url, (img) => {
        img.scaleToWidth(widthPx);
        img.set({ left: 0, top: 0, originX: 'center', originY: 'center' });
        const label = new fabric.Text('SYSTEFARMA', {
          left: 0, top: img.getScaledHeight() / 2 + 5, originX: 'center', originY: 'top',
          fontFamily: FONT_STACK, fontWeight: 'bold', fontSize, fill: '#111827',
        });
        cb(new fabric.Group([img, label]));
      }, { crossOrigin: 'anonymous' });
    });
  }

  const drugName = () => (typeof PLAN_NAME !== 'undefined' && PLAN_NAME) ? PLAN_NAME : '';

  const TITLE_MAX_W = DOC.w - 200; // margen a cada lado, deja espacio al logo

  // Un solo string — el ancho fijo del fabric.Textbox (ver más abajo) es
  // quien decide cuántas líneas hacen falta, con el texto REALMENTE
  // renderizado (no una medición aparte que podía divergir de la fuente
  // final una vez cargada). Nombres largos bajan a 2+ líneas solos.
  const titleFor = (mode) => {
    const base = (mode === 'evac' ? 'RUTA DE EVACUACIÓN'
      : mode === 'san' ? 'RUTA SANITARIA'
        : 'RUTA DE EVACUACIÓN / SANITARIA').toUpperCase();
    const n = drugName().toUpperCase();
    return n ? base + '  —  ' + n : base;
  };

  // Crea el encabezado (logo + título) si aún no existe.
  // Se guarda con el plano; cada parte se crea solo si falta.
  function ensureHeader() {
    const cx = DOC.w / 2;
    const find = (t) => canvas.getObjects().find(o => o.srType === t);

    // logo real + "systefarma" debajo — solo si no hay ya uno en el plano
    if (!find('logo')) {
      buildLogoGroup(96, 15, (g) => {
        g.set({ left: 28, top: 12, originX: 'left', originY: 'top', srType: 'logo', srCat: 'marca' });
        canvas.add(g);
        canvas.requestRenderAll();
      });
    }

    // título del plano: centrado arriba. Si no existe, se crea con el nombre de
    // la droguería + la ruta. Si existe pero quedó el viejo "PLANO VECTORIZADO"
    // (que metía el pipeline), se reemplaza por el título correcto.
    let titulo = find('titulo');
    // migrar planos viejos: el título era un fabric.IText de una sola línea
    // (o con un \n metido a mano) que no reajustaba el wrap si la fuente
    // real terminaba siendo más ancha que la medida al crearlo — se veía
    // cortado por el borde de la hoja. Se reconstruye como Textbox de ancho
    // fijo, que SIEMPRE envuelve el texto a como quepa de verdad.
    if (titulo && titulo.type !== 'textbox') {
      const prevText = (titulo.text || '').replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
      const isPlaceholder = /PLANO VECTORIZADO/i.test(prevText);
      canvas.remove(titulo);
      titulo = null;
      if (!isPlaceholder) {
        const nt = new fabric.Textbox(prevText, {
          left: cx, top: 22, originX: 'center', originY: 'top', width: TITLE_MAX_W,
          fontFamily: FONT_STACK, fontWeight: 'bold', fontSize: 38, fill: '#111827',
          textAlign: 'center', srType: 'titulo', srCat: 'title',
        });
        canvas.add(nt);
        titulo = nt;
      }
    }

    if (!titulo) {
      canvas.add(new fabric.Textbox(titleFor(null), {
        left: cx, top: 22, originX: 'center', originY: 'top', width: TITLE_MAX_W,
        fontFamily: FONT_STACK, fontWeight: 'bold', fontSize: 38, fill: '#111827',
        textAlign: 'center', srType: 'titulo', srCat: 'title',
      }));
    } else if (/PLANO VECTORIZADO/i.test(titulo.text || '')) {
      titulo.set({ text: titleFor(null), left: cx });
      titulo.setCoords && titulo.setCoords();
    }
    // migrar planos viejos: el nombre de fuente sin espacio no matcheaba con la
    // CenturyGothic del sistema → reasignar el stack correcto.
    if (titulo && /CenturyGothic/.test(titulo.fontFamily || '')) {
      titulo.set('fontFamily', FONT_STACK);
    }

    // Jost carga async por Google Fonts (editor.html): el Textbox recalcula
    // el wrap con la fuente real en cada render, así que solo hace falta
    // forzar un repintado una vez que termine de cargar.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => canvas.requestRenderAll());
    }
  }

  // Migra flechas "reciclable" guardadas con el gris viejo (#9ca3af) al
  // blanco real, agregando el contorno oscuro que las hace visibles sobre
  // la hoja (blanco sin contorno = invisible). Reconstruye cada tramo
  // gris con un Path hermano (mismo path/transform, solo el trazo cambia)
  // insertado justo antes para que quede detrás.
  function migrateReciclableColor() {
    const OLD_GRAY = '#9ca3af';
    canvas.getObjects().forEach(o => {
      if (o.type !== 'group') return;
      if (o.srCat !== 'ruta-auto' && o.srCat !== 'ruta-manual') return;
      const kids = o.getObjects();
      if (!kids.some(k => k.stroke === OLD_GRAY)) return;
      const newKids = [];
      kids.forEach(k => {
        if (k.stroke === OLD_GRAY) {
          newKids.push(new fabric.Path(k.path, {
            left: k.left, top: k.top, angle: k.angle || 0,
            scaleX: k.scaleX, scaleY: k.scaleY, originX: k.originX, originY: k.originY,
            stroke: WHITE_OUTLINE, strokeWidth: (k.strokeWidth || LINE_W) + 2,
            fill: 'transparent', strokeLineCap: k.strokeLineCap, strokeLineJoin: k.strokeLineJoin,
            strokeUniform: true,
          }));
          k.set('stroke', RECICLABLE_COLOR);
        }
        newKids.push(k);
      });
      o._objects = newKids;
      o.dirty = true;
      if (o.srCat === 'ruta-manual') o.srColor = RECICLABLE_COLOR;
    });
    canvas.requestRenderAll();
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

  const isTextObj = (o) => o && (o.type === 'i-text' || o.type === 'text' || o.type === 'textbox');

  function syncTextBar() {
    const bar = document.getElementById('textBar');
    if (!bar) return;
    const o = canvas.getActiveObject();
    if (!isTextObj(o)) { bar.hidden = true; return; }
    bar.hidden = false;
    const f = document.getElementById('txtFont');
    const s = document.getElementById('txtSize');
    const b = document.getElementById('txtBold');
    if (f) f.value = o.fontFamily || FONT_STACK;
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

  /* ── Barra de propiedades contextual ────────────────────── */

  function syncPropBar() {
    const bar = document.getElementById('propBar');
    if (!bar) return;
    const objs = canvas.getActiveObjects();
    const first = objs[0];
    // sin selección, o texto (usa su propia barra) → oculta
    if (!first || isTextObj(first)) { bar.hidden = true; return; }
    bar.hidden = false;
    const colorEl  = document.getElementById('propColor');
    const strokeEl = document.getElementById('propStroke');
    const opEl     = document.getElementById('propOpacity');
    const isIcon = first.srCat === 'icon' || first.type === 'image';
    if (colorEl) {
      colorEl.style.display = isIcon ? 'none' : '';
      const c = first.stroke || first.fill;
      if (typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c)) colorEl.value = c;
    }
    if (strokeEl) {
      strokeEl.style.display = isIcon ? 'none' : '';
      strokeEl.value = String(Math.round(first.strokeWidth || 1));
    }
    if (opEl) opEl.value = String(Math.round((first.opacity == null ? 1 : first.opacity) * 100));
    const arrowRow = document.getElementById('propArrowKind');
    if (arrowRow) arrowRow.hidden = !(objs.length === 1 && first.srCat === 'ruta-manual');
  }

  function forSelection(fn) {
    const objs = canvas.getActiveObjects().filter(o => o.srCat !== 'page');
    if (!objs.length) return;
    objs.forEach(fn);
    canvas.requestRenderAll();
  }
  const setColor   = (v) => forSelection(o => {
    if (o.srCat === 'icon' || o.type === 'image') return;
    if (isTextObj(o)) o.set('fill', v);
    else if (o.srCat === 'ruta-manual') {
      if (o.type === 'group') o.forEachObject(ch => { ch.set('stroke', v); if (ch.fill && ch.fill !== 'transparent') ch.set('fill', v); });
      else o.set({ stroke: v, fill: v });
    }
    else if (o.stroke) o.set('stroke', v);
    else o.set('fill', v);
  });
  const setStrokeW = (v) => forSelection(o => { if (o.stroke) o.set('strokeWidth', parseFloat(v) || 1); });
  const setOpacity = (v) => forSelection(o => o.set('opacity', Math.min(1, Math.max(0.05, parseFloat(v) / 100))));
  const commitProps = () => pushHistory();   // los sliders empujan historial al soltar, no por pixel
  function bringFront() {
    canvas.getActiveObjects().forEach(o => canvas.bringToFront(o));
    canvas.requestRenderAll(); pushHistory();
  }
  function sendBack() {
    canvas.getActiveObjects().slice().reverse().forEach(o => canvas.sendToBack(o));
    ensurePageBg();   // la hoja blanca siempre queda debajo
    canvas.requestRenderAll(); pushHistory();
  }

  // Fase 2: reclasificar una flecha manual (evacuación ↔ sanitaria por color).
  // Se reconstruye entera vía makeArrowShape (como bakeArrowStretch) en vez de
  // recolorear los hijos en el lugar: si el nuevo color es blanco (reciclable)
  // hace falta agregar el contorno oscuro, y si se sale del blanco hace falta
  // quitarlo — parchar strokes uno por uno no puede cambiar cuántos hijos tiene.
  function setArrowKind(k) {
    const spec = ARROW_TYPES[k];
    const o = canvas.getActiveObject();
    if (!spec || !o || o.srCat !== 'ruta-manual') return;
    if (o.type === 'group') {
      const len = o.srLen || SEGMENT_LEN;
      const n = makeArrowShape(spec.color, len);
      n.set({ left: o.left, top: o.top, angle: o.angle || 0, scaleX: o.scaleX, scaleY: o.scaleY });
      n.srType = 'ruta-' + spec.mode; n.srCat = 'ruta-manual';
      withSuppress(() => { canvas.remove(o); canvas.add(n); });
      n.setCoords();
      canvas.setActiveObject(n);
    } else {
      o.set({ stroke: spec.color, fill: spec.color });
      o.srType = 'ruta-' + spec.mode;
    }
    canvas.requestRenderAll(); pushHistory();
    setStatus(spec.mode === 'evac' ? 'Flecha → ruta de evacuación' : 'Flecha → ruta sanitaria');
  }

  /* ── Guías inteligentes (estilo Canva) ──────────────────── */

  const GUIDE_THR = 6;        // px de pantalla para enganchar
  const GRID_SNAP_PX = 12;    // grilla opcional

  function bindSmartGuides() {
    canvas.on('object:moving', (opt) => {
      const o = opt.target;
      state.guides = [];
      if (!o || o.srCat === 'page') return;
      if (state.gridSnap) {
        const r0 = o.getBoundingRect(true, true);
        o.set({
          left: o.left + Math.round(r0.left / GRID_SNAP_PX) * GRID_SNAP_PX - r0.left,
          top:  o.top  + Math.round(r0.top  / GRID_SNAP_PX) * GRID_SNAP_PX - r0.top,
        });
      }
      const thr = GUIDE_THR / (canvas.getZoom() || 1);
      const r = o.getBoundingRect(true, true);
      const mx = [r.left, r.left + r.width / 2, r.left + r.width];
      const my = [r.top, r.top + r.height / 2, r.top + r.height];
      const act = new Set(canvas.getActiveObjects());
      let bx = null, by = null;
      // ponytail: scan O(n²) por evento de arrastre; con <200 objetos sobra — índice espacial si algún día lagea
      canvas.getObjects().forEach(t => {
        if (t === o || act.has(t) || !t.visible || t === state.draft) return;
        if (t.srCat === 'page' || t.srCat === 'temp' || t.srCat === 'ruta-auto' || t.srCat === 'aviso') return;
        const tr = t.getBoundingRect(true, true);
        [tr.left, tr.left + tr.width / 2, tr.left + tr.width].forEach(x =>
          mx.forEach(m => { const d = x - m; if (Math.abs(d) < thr && (!bx || Math.abs(d) < Math.abs(bx.d))) bx = { d, x }; }));
        [tr.top, tr.top + tr.height / 2, tr.top + tr.height].forEach(y =>
          my.forEach(m => { const d = y - m; if (Math.abs(d) < thr && (!by || Math.abs(d) < Math.abs(by.d))) by = { d, y }; }));
      });
      // centro de la hoja como candidato (estilo Canva)
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      if (Math.abs(DOC.w / 2 - cx) < thr && (!bx || Math.abs(DOC.w / 2 - cx) < Math.abs(bx.d))) bx = { d: DOC.w / 2 - cx, x: DOC.w / 2 };
      if (Math.abs(DOC.h / 2 - cy) < thr && (!by || Math.abs(DOC.h / 2 - cy) < Math.abs(by.d))) by = { d: DOC.h / 2 - cy, y: DOC.h / 2 };
      if (bx) { o.set('left', o.left + bx.d); state.guides.push({ v: bx.x }); }
      if (by) { o.set('top', o.top + by.d); state.guides.push({ h: by.y }); }
      if (bx || by) o.setCoords();
    });

    // Rotación libre por defecto; con Shift apretado, snap a 0/15/30/45/90…
    // (antes el snap corría siempre dentro de ±5° de cada múltiplo de 15°,
    // así que al arrastrar el ángulo se "pegaba" duro y después saltaba de
    // golpe al salir de esa zona — se sentía errático incluso sin querer
    // encajar en un ángulo redondo).
    canvas.on('object:rotating', (opt) => {
      const o = opt.target;
      if (!o || !(opt.e && opt.e.shiftKey)) return;
      const snap = Math.round(o.angle / 15) * 15;
      if (Math.abs(o.angle - snap) < 5) o.angle = ((snap % 360) + 360) % 360;
    });

    const dropGuides = () => {
      if (state.guides.length) {
        state.guides = [];
        canvas.clearContext(canvas.contextTop);
        canvas.requestRenderAll();
      }
    };
    canvas.on('mouse:up', dropGuides);
    // si el arrastre termina fuera del canvas, mouse:up nunca llega
    canvas.upperCanvasEl.addEventListener('mouseleave', dropGuides);

    canvas.on('after:render', () => {
      if (!state.guides.length) {
        // borrar los píxeles del frame anterior aunque ya no haya guías
        if (state.guidesDirty) { canvas.clearContext(canvas.contextTop); state.guidesDirty = false; }
        return;
      }
      const ctx = canvas.contextTop;
      const t = canvas.viewportTransform;
      canvas.clearContext(ctx);
      state.guidesDirty = true;
      ctx.save();
      ctx.strokeStyle = '#ec4899';
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      state.guides.forEach(g => {
        ctx.beginPath();
        if (g.v !== undefined) { const x = g.v * t[0] + t[4]; ctx.moveTo(x, 0); ctx.lineTo(x, canvas.getHeight()); }
        else { const y = g.h * t[3] + t[5]; ctx.moveTo(0, y); ctx.lineTo(canvas.getWidth(), y); }
        ctx.stroke();
      });
      ctx.restore();
    });
  }

  // Flecha manual: misma forma/color que las generadas; sobrevive a "Generar"
  // (srCat 'ruta-manual') y respeta el modo en el PDF (srType 'ruta-evac/san').
  function addArrow(type, x, y) {
    const spec = ARROW_TYPES[type];
    const g = makeArrowShape(spec.color);
    g.set({ left: x, top: y, originX: 'center', originY: 'center' });
    g.srType = 'ruta-' + spec.mode; g.srCat = 'ruta-manual';
    canvas.add(g);
    backToSelect();
    canvas.setActiveObject(g);
    canvas.requestRenderAll();
    pushHistory();
    setStatus('Flecha agregada — rótala para orientarla');
  }

  function addIcon(type, x, y) {
    if (ARROW_TYPES[type]) { addArrow(type, x, y); return; }
    if (type === 'logo_systefarma') {
      buildLogoGroup(78, 14, (g) => {
        g.set({ left: x, top: y, originX: 'center', originY: 'center' });
        g.srType = type; g.srCat = 'icon';
        canvas.add(g);
        backToSelect();
        canvas.setActiveObject(g);
        canvas.requestRenderAll();
        pushHistory();
        setStatus('Elemento agregado');
      });
    } else if (ICON_IMG[type]) {
      fabric.Image.fromURL(ICON_IMG[type], (img) => {
        img.set({ left: x, top: y, originX: 'center', originY: 'center' });
        img.scaleToWidth(54);
        img.srType = type; img.srCat = 'icon';
        canvas.add(img);
        backToSelect();
        canvas.setActiveObject(img);
        canvas.requestRenderAll();
        pushHistory();
        setStatus('Elemento agregado');
      }, { crossOrigin: 'anonymous' });
    } else {
      const svg = SR_ICONS[type];
      if (!svg) return;
      fabric.loadSVGFromString(svg, (objects, options) => {
        const obj = fabric.util.groupSVGElements(objects, options);
        obj.set({ left: x, top: y, originX: 'center', originY: 'center' });
        obj.scaleToWidth(54);
        obj.srType = type; obj.srCat = 'icon';
        canvas.add(obj);
        backToSelect();
        canvas.setActiveObject(obj);
        canvas.requestRenderAll();
        pushHistory();
        setStatus('Elemento agregado');
      });
    }
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

  /* ── Herramienta RUTA (polilínea por clics o mano alzada) ── */

  const ROUTE_KINDS = {
    evac:       { color: '#16a34a', mode: 'evac' },
    ordinaria:  { color: '#111827', mode: 'san' },
    reciclable: { color: RECICLABLE_COLOR, mode: 'san' },
    biosani:    { color: '#dc2626', mode: 'san' },
  };

  function setRouteTool(kind, btnEl) {
    state.routeKind = ROUTE_KINDS[kind] ? kind : 'evac';
    setTool('ruta', btnEl);
    setStatus('Ruta: clic por cada punto (Enter/doble clic termina) o dibujá a mano alzada');
  }

  // Colocar un icono con un clic (alternativa al drag & drop del sidebar).
  function setPlaceTool(type, btnEl) {
    state.placeType = type;
    setTool('place', btnEl);
    setStatus('Tocá el punto del plano donde va el elemento');
  }

  function clearWallPreview() {
    if (!state.wallPreview) return;
    withSuppress(() => canvas.remove(state.wallPreview));
    state.wallPreview = null;
  }
  function endWallChain() {
    state.chain = null;
    clearWallPreview();
    canvas.requestRenderAll();
  }

  function clearRoutePreview() {
    withSuppress(() => (state.routePreview || []).forEach(o => canvas.remove(o)));
    state.routePreview = [];
  }

  function drawRoutePreview(cursor) {
    clearRoutePreview();
    const pts = state.routePts;
    if (!pts.length) return;
    const spec = ROUTE_KINDS[state.routeKind];
    const all = cursor ? pts.concat([cursor]) : pts;
    const segs = [];
    for (let i = 1; i < all.length; i++) {
      segs.push(new fabric.Line([all[i-1].x, all[i-1].y, all[i].x, all[i].y], {
        stroke: spec.color, strokeWidth: 2, strokeDashArray: [6, 5],
        selectable: false, evented: false, srCat: 'temp',
      }));
    }
    withSuppress(() => segs.forEach(o => canvas.add(o)));
    state.routePreview = segs;
    canvas.requestRenderAll();
  }

  // Douglas-Peucker mínimo para el trazo a mano alzada.
  function rdp(pts, eps) {
    if (pts.length < 3) return pts;
    const a = pts[0], b = pts[pts.length - 1];
    let maxD = 0, idx = 0;
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    for (let i = 1; i < pts.length - 1; i++) {
      const d = Math.abs(dy * pts[i].x - dx * pts[i].y + b.x * a.y - b.y * a.x) / len;
      if (d > maxD) { maxD = d; idx = i; }
    }
    if (maxD <= eps) return [a, b];
    return rdp(pts.slice(0, idx + 1), eps).slice(0, -1).concat(rdp(pts.slice(idx), eps));
  }

  // Endereza cualquier secuencia de puntos a tramos H/V y funde los colineales.
  function toOrtho(pts) {
    if (pts.length < 2) return pts;
    const out = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      const last = out[out.length - 1], p = pts[i];
      const dx = p.x - last.x, dy = p.y - last.y;
      const q = Math.abs(dx) >= Math.abs(dy) ? { x: p.x, y: last.y } : { x: last.x, y: p.y };
      if (Math.hypot(q.x - last.x, q.y - last.y) < 6) continue;
      out.push(q);
    }
    // fundir tramos colineales consecutivos
    const merged = [out[0]];
    for (let i = 1; i < out.length; i++) {
      const prev2 = merged[merged.length - 2], prev = merged[merged.length - 1], p = out[i];
      if (prev2 && ((prev2.y === prev.y && prev.y === p.y) || (prev2.x === prev.x && prev.x === p.x))) {
        merged[merged.length - 1] = p;
      } else merged.push(p);
    }
    return merged;
  }

  function finalizeRoute() {
    const pts = state.routePts || [];
    clearRoutePreview();
    state.routePts = [];
    if (pts.length < 2) { canvas.requestRenderAll(); return; }
    const spec = ROUTE_KINDS[state.routeKind];
    const ortho = toOrtho(pts);
    const arrows = renderRoute(ortho, spec.color, spec.mode);
    if (!arrows) return;
    // manual: cada flechita sobrevive a "Generar" y es reclasificable
    arrows.forEach(a => a.set({ srCat: 'ruta-manual', srAuto: false }));
    withSuppress(() => arrows.forEach(a => canvas.add(a)));
    canvas.requestRenderAll();
    pushHistory();
    backToSelect();   // vuelve a Seleccionar (como los objetos puntuales)
    setStatus('Ruta dibujada — cada flecha se mueve o borra por separado', 'ok');
  }

  /* ── Leyenda automática ──────────────────────────────────── */

  const LEGEND_LABELS = {
    extintor: 'Extintor', botiquin: 'Botiquín', punto_encuentro: 'Punto de encuentro',
    salida_emergencia: 'Salida', entrada_salida: 'Entrada / Salida',
    camilla: 'Camilla', bano: 'Baño', lavamanos: 'Lavamanos', norte: 'Norte',
    caneca_ordinaria: 'Ordinaria', caneca_reciclable: 'Reciclable',
    caneca_biosani: 'Biosanitaria', caneca_corto: 'Cortopunzantes',
  };
  const SAN_ARROW_LABEL = {
    '#111827': 'Ordinaria',
    [RECICLABLE_COLOR]: 'Reciclable',
    '#dc2626': 'Biosanitaria',
  };

  function loadThumb(type) {
    return new Promise((res) => {
      if (typeof ICON_IMG !== 'undefined' && ICON_IMG[type]) {
        fabric.Image.fromURL(ICON_IMG[type], img => res(img), { crossOrigin: 'anonymous' });
      } else if (typeof SR_ICONS !== 'undefined' && SR_ICONS[type] && SR_ICONS[type] !== 'img') {
        fabric.loadSVGFromString(SR_ICONS[type], (objs, opt) => res(fabric.util.groupSVGElements(objs, opt)));
      } else res(null);
    });
  }

  // Escanea el plano y arma el cuadro de CONVENCIONES con lo que haya.
  async function buildLegend() {
    const all = canvas.getObjects();
    const rows = [];
    Object.keys(LEGEND_LABELS).forEach(t => {
      if (all.some(o => o.srType === t)) rows.push({ type: t, label: LEGEND_LABELS[t] });
    });
    if (all.some(o => o.srType === 'ruta-evac')) rows.push({ arrow: EVAC_COLOR, label: 'Evacuación' });
    [...new Set(all.filter(o => o.srType === 'ruta-san').map(o => o.stroke))].forEach(c => {
      if (c) rows.push({ arrow: c, label: SAN_ARROW_LABEL[c] || 'Sanitaria' });
    });
    if (!rows.length) { setStatus('No hay elementos para la leyenda todavía', 'warn'); return; }

    const prev = all.find(o => o.srType === 'leyenda');
    const PADX = 14, ROW_H = 34, ICON = 26, TITLE_H = 36, W = 230;
    const H = TITLE_H + rows.length * ROW_H + 10;
    const parts = [
      new fabric.Rect({ left: 0, top: 0, width: W, height: H, fill: '#ffffff', stroke: '#111827', strokeWidth: 1.5 }),
      new fabric.Text('CONVENCIONES', {
        left: W / 2, top: 10, originX: 'center', fontFamily: FONT_STACK,
        fontSize: 16, fontWeight: 'bold', fill: '#111827',
      }),
    ];
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      const cy = TITLE_H + i * ROW_H + ROW_H / 2;
      if (r.arrow) {
        const a = makeArrowShape(r.arrow, 34);
        a.forEachObject(ch => ch.set('strokeWidth', 3));
        a.set({ left: PADX + ICON / 2, top: cy });
        parts.push(a);
      } else {
        const img = await loadThumb(r.type);
        if (img) {
          img.scaleToWidth(ICON);
          if (img.getScaledHeight() > ICON) img.scaleToHeight(ICON);
          img.set({ left: PADX + ICON / 2, top: cy, originX: 'center', originY: 'center' });
          parts.push(img);
        }
      }
      parts.push(new fabric.Text(r.label, {
        left: PADX + ICON + 10, top: cy, originY: 'center',
        fontFamily: FONT_STACK, fontSize: 15, fill: '#111827',
      }));
    }
    const g = new fabric.Group(parts, {
      srType: 'leyenda', srCat: 'marca',
      left: prev ? prev.left : DOC.w - W - 26,
      top:  prev ? prev.top  : DOC.h - H - 26,
      scaleX: prev ? prev.scaleX : 1, scaleY: prev ? prev.scaleY : 1,
    });
    withSuppress(() => { if (prev) canvas.remove(prev); canvas.add(g); });
    canvas.requestRenderAll();
  }

  async function makeLegend() {
    await buildLegend();
    pushHistory();
    setStatus('Leyenda generada — podés moverla', 'ok');
  }

  /* ════════════ GENERADOR DE RUTAS (A* + fusión) ═══════════ */

  // Test punto-en-polígono (ray casting) para el bloqueo de obstáculos rotados.
  function pointInPoly(x, y, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i].x, yi = poly[i].y, xj = poly[j].x, yj = poly[j].y;
      const hit = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
      if (hit) inside = !inside;
    }
    return inside;
  }

  // Rectángulo rotado inflado por `pad` (aprox.: infla en espacio local antes
  // de rotar, no es un Minkowski exacto pero es más que suficiente para bloqueo).
  function rotatedRectPoly(o, pad) {
    const w = o.getScaledWidth() + pad * 2, h = o.getScaledHeight() + pad * 2;
    const c = o.getCenterPoint();
    const rad = (o.angle || 0) * Math.PI / 180;
    const cos = Math.cos(rad), sin = Math.sin(rad);
    const hw = w / 2, hh = h / 2;
    return [{ x: -hw, y: -hh }, { x: hw, y: -hh }, { x: hw, y: hh }, { x: -hw, y: hh }]
      .map(p => ({ x: c.x + p.x * cos - p.y * sin, y: c.y + p.x * sin + p.y * cos }));
  }

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

    // 1) bloquear paredes y muebles (con holgura + medio grosor).
    //    Una 'zona' rectangular rotada infla mucho su AABB; para esas se prueba
    //    punto-en-polígono contra el rectángulo real en vez de bloquear todo el
    //    bounding box (las paredes/muebles son Line: su AABB rotado ya es ajustado).
    canvas.getObjects().forEach((o) => {
      if (!OBSTACLES.has(o.srType)) return;
      const pad = BLOCK_PAD + (o.strokeWidth || 0) / 2;
      const r = o.getBoundingRect(true, true);
      const rotated = o.type === 'rect' && Math.abs(((o.angle || 0) % 90 + 90) % 90) > 1;
      if (!rotated) { rectCells(r, pad, (i) => { blocked[i] = 1; }); return; }
      const poly = rotatedRectPoly(o, pad);
      rectCells(r, pad, (i) => {
        const cx = i % cols, cy = (i / cols) | 0;
        const c = cellCenter(cx, cy);
        if (pointInPoly(c.x, c.y, poly)) blocked[i] = 1;
      });
    });

    // 2) abrir el paso donde hay puertas o vanos (único cruce permitido).
    //    Anisotrópico: estrecho A LO LARGO de la pared (el paso queda del ancho
    //    de la puerta → se cruza por la abertura, centrado) y amplio EN PERPENDICULAR
    //    (CLEAR + grosor) para atravesar la pared.
    const OPEN_PAD = CLEAR + 8;
    canvas.getObjects().forEach((o) => {
      if (o.srType !== 'puerta' && o.srType !== 'vano') return;
      const r = gapRect(o);   // solo el hueco — el arco de la puerta no abre paso
      const padAlong = 1;                       // a lo largo de la abertura (estrecho)
      if (typeof o.srDirX === 'number') {
        // puerta a cualquier ángulo: desbloquear un rectángulo orientado según
        // la dirección real de la pared, no solo horizontal/vertical.
        const dir = { x: o.srDirX, y: o.srDirY };
        const perp = { x: -dir.y, y: dir.x };
        const c = { x: o.srGapX, y: o.srGapY };
        const halfLen = (o.srLen || Math.max(r.width, r.height)) / 2 + 1;
        const along = { x: dir.x * halfLen, y: dir.y * halfLen };
        const across = { x: perp.x * OPEN_PAD, y: perp.y * OPEN_PAD };
        const corners = [
          { x: c.x + along.x + across.x, y: c.y + along.y + across.y },
          { x: c.x - along.x + across.x, y: c.y - along.y + across.y },
          { x: c.x - along.x - across.x, y: c.y - along.y - across.y },
          { x: c.x + along.x - across.x, y: c.y + along.y - across.y },
        ];
        const xs = corners.map(p => p.x), ys = corners.map(p => p.y);
        const x0 = Math.max(0, Math.floor(Math.min(...xs) / GRID));
        const x1 = Math.min(cols - 1, Math.floor(Math.max(...xs) / GRID));
        const y0 = Math.max(0, Math.floor(Math.min(...ys) / GRID));
        const y1 = Math.min(rows - 1, Math.floor(Math.max(...ys) / GRID));
        for (let cy = y0; cy <= y1; cy++)
          for (let cx = x0; cx <= x1; cx++) {
            const px = cx * GRID + GRID / 2, py = cy * GRID + GRID / 2;
            if (pointInPoly(px, py, corners)) blocked[cy * cols + cx] = 0;
          }
        return;
      }
      const horizontal = o.srDir ? o.srDir === 'h' : (r.width >= r.height);
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

  function axisSegmentClear(grid, a, b) {
    const { cols, rows, blocked } = grid;
    const dx = b.x - a.x, dy = b.y - a.y;
    if (Math.abs(dx) >= 1 && Math.abs(dy) >= 1) return false;
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy) / (GRID / 2)));
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const cx = Math.floor((a.x + dx * t) / GRID);
      const cy = Math.floor((a.y + dy * t) / GRID);
      if (cx < 0 || cy < 0 || cx >= cols || cy >= rows) return false;
      if (blocked[cy * cols + cx]) return false;
    }
    return true;
  }

  function appendAxis(out, p, grid) {
    const last = out[out.length - 1];
    if (!last) { out.push(p); return true; }
    if (Math.hypot(p.x - last.x, p.y - last.y) < 1) return true;
    if (!grid || axisSegmentClear(grid, last, p)) {
      out.push(p);
      return true;
    }
    return false;
  }

  function appendOrthogonal(out, p, grid, requireClear = true) {
    const last = out[out.length - 1];
    if (!last) { out.push(p); return true; }
    if (Math.abs(p.x - last.x) < 1 || Math.abs(p.y - last.y) < 1) {
      return appendAxis(out, p, grid);
    }

    const elbowA = { x: last.x, y: p.y };
    const elbowB = { x: p.x, y: last.y };
    const aClear = (!grid || axisSegmentClear(grid, last, elbowA))
      && (!grid || axisSegmentClear(grid, elbowA, p));
    const bClear = (!grid || axisSegmentClear(grid, last, elbowB))
      && (!grid || axisSegmentClear(grid, elbowB, p));

    if (aClear) {
      appendAxis(out, elbowA, grid);
      appendAxis(out, p, grid);
      return true;
    }
    if (bClear) {
      appendAxis(out, elbowB, grid);
      appendAxis(out, p, grid);
      return true;
    }
    if (!requireClear) {
      // ningún codo queda despejado: igual conectamos (el mejor de los dos,
      // el más corto) para no cortar la ruta antes de llegar al destino.
      const lenA = Math.hypot(elbowA.x - last.x, elbowA.y - last.y) + Math.hypot(p.x - elbowA.x, p.y - elbowA.y);
      const lenB = Math.hypot(elbowB.x - last.x, elbowB.y - last.y) + Math.hypot(p.x - elbowB.x, p.y - elbowB.y);
      appendAxis(out, lenA <= lenB ? elbowA : elbowB, grid);
      appendAxis(out, p, grid);
    }
    return !requireClear;
  }

  function orthogonalizePath(pts, grid) {
    if (pts.length < 2) return pts;
    const out = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      if (!appendOrthogonal(out, pts[i], grid, true)) return null;
    }
    return out;
  }

  // Conecta el último punto de la ruta con la salida real (un solo salto: el
  // A* ya trajo la ruta hasta la celda libre más cercana a la puerta, así que
  // de ahí al ícono suele ser corto). Un `via` intermedio aquí multiplicaba
  // un codo extra por cada carril/color que converge en la misma salida,
  // formando un enredo de flechas cruzadas cuando hay varias rutas. Si el
  // salto directo queda bloqueado, se traza igual (mejor llegar exacto al
  // ícono que cortar la ruta antes de la salida).
  function connectEndpoint(pts, goalPt, grid) {
    if (!goalPt || pts.length < 1) return pts;
    const out = pts.slice();
    if (!appendOrthogonal(out, { x: goalPt.x, y: goalPt.y }, grid, true)) {
      appendOrthogonal(out, { x: goalPt.x, y: goalPt.y }, grid, false);
    }
    return out;
  }

  function routePointsClear(pts, grid) {
    if (!pts || pts.length < 2) return false;
    for (let i = 1; i < pts.length; i++) {
      if (!axisSegmentClear(grid, pts[i - 1], pts[i])) return false;
    }
    return true;
  }

  // Descarta vértices pegados al anterior (deja el primero y el último):
  // orthogonalizePath a veces mete un codo minúsculo justo en un giro, que
  // segmentedPathParts/arrowHeadD dibuja como una muesca — un tramo casi sin
  // largo con una cabeza de flecha degenerada — en vez de un giro limpio.
  function dropTinySegments(pts, minLen) {
    if (pts.length < 3) return pts;
    const out = [pts[0]];
    for (let i = 1; i < pts.length - 1; i++) {
      const last = out[out.length - 1];
      if (Math.hypot(pts[i].x - last.x, pts[i].y - last.y) < minLen) continue;
      out.push(pts[i]);
    }
    out.push(pts[pts.length - 1]);
    return out;
  }

  // Devuelve { pts, collapsed }. El desfase de carril SIEMPRE se ortogonaliza
  // (las rutas van solo en ángulos rectos, nunca en diagonal); si no valida,
  // reintenta con un desfase menor antes de resignarse a 0 —así dos rutas que
  // comparten pasillo angosto no vuelven a quedar 100% pegadas.
  // `collapsed` avisa al renderer que dibuje con halo para distinguirlas.
  function buildSafeRoutePoints(basePts, lane, grid, doorCenters) {
    const base = densify(basePts, 22);
    if (!lane) return { pts: base, collapsed: false };
    for (const factor of [1, 0.6, 0.3]) {
      const shifted = offsetPath(base, lane * factor, grid, doorCenters);
      // `shifted` viene densificado (un punto cada ~22px): ortogonalizar eso tal
      // cual produciría un codo por cada micro-tramo (mini-escalera). Se reduce
      // primero con Douglas-Peucker para que quede un codo limpio por giro real.
      const reduced = rdp(shifted, 3);
      const ortho = dropTinySegments(orthogonalizePath(reduced, grid) || [], 10);
      if (routePointsClear(ortho, grid)) return { pts: ortho, collapsed: factor < 0.99 };
    }
    return { pts: base, collapsed: true };
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

  function doorCenter(o) {
    if (o.srType === 'puerta' && o.type === 'group') {
      // centro VIVO del hueco (srGapX queda viejo si movieron la puerta)
      const g = gapRect(o);
      return { x: g.left + g.width / 2, y: g.top + g.height / 2 };
    }
    return (typeof o.srGapX === 'number') ? { x: o.srGapX, y: o.srGapY } : o.getCenterPoint();
  }

  function snapGoalToDoor(goal, all) {
    let best = null, bestD = Infinity;
    all.forEach(o => {
      if (o.srType !== 'puerta' && o.srType !== 'vano') return;
      const p = doorCenter(o);
      const d = Math.hypot(p.x - goal.x, p.y - goal.y);
      if (d < bestD) { bestD = d; best = p; }
    });
    return best && bestD < 170 ? best : goal;
  }

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

  // Línea de visión entre dos puntos (en px): libre si ninguna celda muestreada
  // a lo largo del segmento está bloqueada. A diferencia de axisSegmentClear,
  // funciona con segmentos en cualquier ángulo (no solo H/V).
  function losClear(grid, a, b) {
    const { cols, rows, blocked } = grid;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.hypot(dx, dy);
    const steps = Math.max(1, Math.ceil(dist / (GRID / 2)));
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const cx = Math.floor((a.x + dx * t) / GRID);
      const cy = Math.floor((a.y + dy * t) / GRID);
      if (cx < 0 || cy < 0 || cx >= cols || cy >= rows) return false;
      if (blocked[cy * cols + cx]) return false;
    }
    return true;
  }

  // String-pulling: desde cada punto, salta al más lejano con línea de visión
  // directa. Convierte la "escalera" de celdas del A* en tramos más largos y
  // rectos, con diagonales donde el espacio lo permite (en pasillos angostos
  // no encuentra atajos y el resultado queda igual de ortogonal que antes).
  function smoothPath(pts, grid) {
    if (!grid || pts.length <= 2) return pts;
    const out = [pts[0]];
    let i = 0;
    while (i < pts.length - 1) {
      let j = pts.length - 1;
      while (j > i + 1 && !losClear(grid, pts[i], pts[j])) j--;
      out.push(pts[j]);
      i = j;
    }
    return out;
  }

  // ¿Se puede ir de `a` a `b` en línea recta o con un solo codo a 90°, sin
  // cruzar obstáculos? (mismo criterio que usa appendOrthogonal, pero sin
  // mutar nada — solo para decidir si vale la pena saltar hasta `b`).
  function orthoReachable(grid, a, b) {
    if (Math.abs(a.x - b.x) < 1 || Math.abs(a.y - b.y) < 1) return axisSegmentClear(grid, a, b);
    const elbowA = { x: a.x, y: b.y }, elbowB = { x: b.x, y: a.y };
    const aClear = axisSegmentClear(grid, a, elbowA) && axisSegmentClear(grid, elbowA, b);
    const bClear = axisSegmentClear(grid, a, elbowB) && axisSegmentClear(grid, elbowB, b);
    return aClear || bClear;
  }

  // Como smoothPath, pero las rutas de evacuación/señalización van SIEMPRE en
  // ángulos rectos (0°/90°/180°/270°): en vez de saltar en línea recta a lo
  // Bresenham (que mete diagonales), salta al punto más lejano alcanzable con
  // un único codo ortogonal e inserta ese codo (vía appendOrthogonal).
  function smoothPathOrtho(pts, grid) {
    if (!grid || pts.length <= 2) return pts;
    const out = [pts[0]];
    let i = 0;
    while (i < pts.length - 1) {
      let j = pts.length - 1;
      while (j > i + 1 && !orthoReachable(grid, pts[i], pts[j])) j--;
      appendOrthogonal(out, pts[j], grid, true);
      i = j;
    }
    return out;
  }

  // Recorta el arranque de la ruta `dist` px (para que la flecha nazca un poco
  // separada del marcador/icono de origen, en vez de salir de su centro exacto).
  function trimPathStart(pts, dist) {
    if (pts.length < 2 || dist <= 0) return pts;
    let remain = dist;
    const out = pts.slice();
    while (out.length > 1 && remain > 0) {
      const a = out[0], b = out[1];
      const segLen = Math.hypot(b.x - a.x, b.y - a.y);
      if (segLen <= remain) { remain -= segLen; out.shift(); continue; }
      const t = remain / segLen;
      out[0] = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
      remain = 0;
    }
    return out;
  }

  // Flecha manual (retoque): usa EXACTAMENTE la misma función de troceado
  // que las rutas generadas (segmentedPathParts + arrowHeadD, ver más abajo)
  // sobre un segmento recto local, para que no haya ninguna diferencia de
  // forma entre una flecha suelta y un tramo de ruta auto-generada.
  function makeArrowShape(color, len) {
    // por defecto, EXACTAMENTE el largo de un tramo de ruta generada
    // (SEGMENT_LEN) — antes eran 72px, más larga que cualquier flechita
    // de una ruta auto (46px), así que se veía "más grande"/distinta
    // aunque la forma fuera idéntica.
    const L = len || SEGMENT_LEN;          // largo total de la flecha
    const midHeadH = ARROW_SIZE * 0.65;
    const tipLen = midHeadH;                // ver nota en renderRoute: hueco = alcance real de la cabeza
    const xTip = L / 2, xStart = -L / 2;
    const { dashes, tipDir, tipAt } = segmentedPathParts(
      [{ x: xStart, y: 0 }, { x: xTip, y: 0 }], tipLen
    );

    const white = isWhiteArrow(color);
    const outlineOpts = { stroke: WHITE_OUTLINE, strokeWidth: LINE_W + 2, fill: 'transparent', strokeLineCap: 'round', strokeLineJoin: 'round', strokeUniform: true };
    const opts = { stroke: color, strokeWidth: LINE_W, fill: 'transparent', strokeLineCap: 'round', strokeLineJoin: 'round', strokeUniform: true };
    const parts = [];
    if (!dashes.length) {
      // tramo demasiado corto para un hueco: una sola línea + punta (igual
      // que renderRoute cuando la ruta completa no da para más de un dash)
      const d = `M ${xStart} 0 L ${tipAt.x} ${tipAt.y}`;
      const headD = arrowHeadD(tipAt, tipDir, midHeadH);
      if (white) parts.push(new fabric.Path(d + ' ' + headD, outlineOpts));
      parts.push(new fabric.Path(d, opts));
    } else {
      dashes.forEach((seg, i) => {
        const last = i === dashes.length - 1;
        const headD = last ? arrowHeadD(tipAt, tipDir, midHeadH) : arrowHeadD(seg.tip, seg.dir, midHeadH);
        if (white) parts.push(new fabric.Path(seg.d + ' ' + headD, outlineOpts));
        parts.push(new fabric.Path(seg.d, opts));
        if (!last) parts.push(new fabric.Path(headD, opts));
      });
    }
    parts.push(new fabric.Path(arrowHeadD(tipAt, tipDir, midHeadH), opts));

    const g = new fabric.Group(parts, {
      originX: 'center',
      originY: 'center',
      centeredScaling: true,
      lockUniScaling: true,
      lockScalingFlip: true,
      lockSkewingX: true,
      lockSkewingY: true,
    });
    // laterales = estirar el largo (se hornea en bakeArrowStretch); sin verticales
    g.setControlsVisibility({ mt: false, mb: false });
    g.srLen = L;
    g.srColor = color;   // color real — con blanco, _objects[0] es el contorno, no el color
    return g;
  }

  // Si la flecha quedó con escala no uniforme (la estiraron con una manija
  // lateral), se reconstruye con la LÍNEA más larga y la cabeza intacta.
  function bakeArrowStretch(o) {
    const sx = Math.abs(o.scaleX || 1), sy = Math.abs(o.scaleY || 1);
    if (Math.abs(sx - sy) < 0.01) return;     // escala uniforme: nada que corregir
    const newLen = Math.max(28, (o.srLen || SEGMENT_LEN) * sx / sy);
    const color = o.srColor || o.stroke
      || (o._objects && o._objects.find(ch => ch.stroke !== WHITE_OUTLINE) || {}).stroke
      || EVAC_COLOR;
    const n = makeArrowShape(color, newLen);
    n.set({
      left: o.left, top: o.top, angle: o.angle || 0,
      scaleX: sy, scaleY: sy,
    });
    n.srType = o.srType; n.srCat = o.srCat;
    withSuppress(() => { canvas.remove(o); canvas.add(n); });
    n.setCoords();
    if (canvas.getActiveObject() === o || !canvas.getActiveObject()) canvas.setActiveObject(n);
    canvas.requestRenderAll();
    pushHistory();
  }

  // Repara flechas manuales al cargar: re-aplica manijas y hornea estiramientos.
  function fixupManualArrows() {
    canvas.getObjects().slice().forEach(o => {
      if (o.srCat !== 'ruta-manual') return;
      o.setControlsVisibility({ mt: false, mb: false });
      bakeArrowStretch(o);
    });
  }

  // Punto a una distancia `dist` recorriendo la polilínea `pts` (sin suavizar
  // esquinas). Devuelve también el índice del tramo original en el que cae,
  // para poder incluir los vértices intermedios de un tramo de flecha.
  function pointAtDistance(pts, dist) {
    let acc = 0;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      const segLen = Math.hypot(b.x - a.x, b.y - a.y);
      if (dist <= acc + segLen || i === pts.length - 1) {
        const t = segLen < 1e-6 ? 0 : Math.max(0, Math.min(1, (dist - acc) / segLen));
        return { point: { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }, segIndex: i };
      }
      acc += segLen;
    }
    return { point: pts[pts.length - 1], segIndex: pts.length - 1 };
  }

  // Dirección de avance en `dist`, mirando hacia atrás una distancia fija en
  // vez de usar el último vértice crudo del polígono: cerca de esquinas,
  // uniones con la puerta o desfases de carril puede haber "leves" de un par
  // de px que, tomados solos, apuntan en cualquier ángulo — mirar `lookback`
  // px atrás promedia esos quiebres y da una flecha bien orientada.
  function dirAtDistance(pts, dist, lookback) {
    const a = pointAtDistance(pts, Math.max(0, dist - lookback)).point;
    const b = pointAtDistance(pts, dist).point;
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    return { x: dx / len, y: dy / len };
  }

  const ARROW_LOOKBACK = 14;     // px hacia atrás para calcular la orientación de una punta

  // Trocea la ruta `points` en tramos rectos de largo `SEGMENT_LEN` separados
  // por huecos de `SEGMENT_GAP`, dejando `tipLen` libre al final para la punta
  // de flecha. Cada tramo sigue los vértices originales que atraviesa (no es
  // una cuerda recta) para no cortar a través de paredes en los giros.
  function segmentedPathParts(points, tipLen) {
    const pts = points;
    let total = 0;
    for (let i = 1; i < pts.length; i++) total += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);

    const usable = Math.max(0, total - tipLen);
    const dashes = [];
    let start = 0;
    while (start < usable - 0.5) {
      let end = Math.min(start + SEGMENT_LEN, usable);
      // si lo que sobra después de este tramo es muy corto para su propio
      // hueco+tramo, en vez de cortarlo y dejarlo en blanco (antes quedaba
      // una raya "flotando" separada de la punta final) se lo comemos: este
      // tramo llega directo hasta `usable`, pegado a donde arranca la cabeza.
      if (usable - end < SEGMENT_GAP + SEGMENT_LEN * 0.4) end = usable;
      const from = pointAtDistance(pts, start);
      const to = pointAtDistance(pts, end);
      const way = [from.point];
      for (let i = from.segIndex; i < to.segIndex; i++) way.push(pts[i]);
      way.push(to.point);
      const clean = way.filter((p, i) => i === 0 || Math.hypot(p.x - way[i - 1].x, p.y - way[i - 1].y) > 0.5);
      if (clean.length < 2) { start = end + SEGMENT_GAP; continue; }
      let d = `M ${clean[0].x} ${clean[0].y} `;
      for (let i = 1; i < clean.length; i++) d += `L ${clean[i].x} ${clean[i].y} `;
      dashes.push({ d, dir: dirAtDistance(pts, end, ARROW_LOOKBACK), tip: clean[clean.length - 1] });
      start = end + SEGMENT_GAP;
    }

    return { dashes, tipDir: dirAtDistance(pts, total, ARROW_LOOKBACK), tipAt: pts[pts.length - 1] };
  }

  // `d` de un triángulo de punta de flecha en `tipAt`, apuntando en `dir`.
  function arrowHeadD(tipAt, dir, h) {
    const w = h * 0.55;
    const px = -dir.y, py = dir.x;
    const lx = tipAt.x - dir.x * h + px * w, ly = tipAt.y - dir.y * h + py * w;
    const rx = tipAt.x - dir.x * h - px * w, ry = tipAt.y - dir.y * h - py * w;
    return `M ${lx} ${ly} L ${tipAt.x} ${tipAt.y} L ${rx} ${ry}`;
  }

  // Ruta = varios tramos rectos separados por un hueco, cada uno con su
  // propia puntita (---->  ---->  --->), y una punta de flecha grande en la
  // salida real. `opts.halo` agrega un trazo blanco de fondo por tramo para
  // distinguir rutas superpuestas.
  // Devuelve UN grupo POR FLECHA (tramo + puntita): cada flechita se
  // selecciona/mueve/borra por separado, no la ruta completa ni un path suelto.
  function renderRoute(points, color, modeKey, opts = {}) {
    if (points.length < 2) return null;
    // el hueco reservado para la punta final debe ser EXACTAMENTE su alcance
    // (midHeadH) — si es mayor, el trazo se queda corto y la cabeza flota
    // separada del final de la raya en vez de quedar pegada.
    const midHeadH = ARROW_SIZE * 0.65;
    const tipLen = midHeadH;
    const { dashes, tipDir, tipAt } = segmentedPathParts(points, tipLen);

    const lineWidth = opts.halo ? Math.max(2, LINE_W - 1) : LINE_W;
    const white = isWhiteArrow(color);
    const stroke = {
      strokeWidth: lineWidth, fill: 'transparent',
      strokeLineCap: 'round', strokeLineJoin: 'round', strokeUniform: true,
    };
    const arrows = dashes.map((seg, i) => {
      const parts = [];
      // blanca de verdad = invisible sobre la hoja: contorno oscuro SIEMPRE,
      // en vez del halo blanco que solo se usa para distinguir superposición.
      if (opts.halo && !white) {
        parts.push(new fabric.Path(seg.d, {
          ...stroke, stroke: '#ffffff', strokeWidth: LINE_W + 4, opacity: 0.85,
        }));
      }
      const last = i === dashes.length - 1;
      const headD = last ? arrowHeadD(tipAt, tipDir, midHeadH) : arrowHeadD(seg.tip, seg.dir, midHeadH);
      if (white) {
        // un solo Path combinando tramo+cabeza (2 subtrazos) para no romper
        // el conteo de hijos por flecha que asume splitLegacyRouteGroups
        parts.push(new fabric.Path(seg.d + ' ' + headD, { ...stroke, stroke: WHITE_OUTLINE, strokeWidth: lineWidth + 2 }));
      }
      parts.push(new fabric.Path(seg.d, { ...stroke, stroke: color }));
      // puntita intermedia, o la punta grande de salida en el último tramo
      parts.push(new fabric.Path(
        // misma cabeza en todas las flechas (antes la última era más grande
        // y se veía inconsistente)
        headD,
        { ...stroke, stroke: color },
      ));
      return new fabric.Group(parts, {
        srType: 'ruta-' + modeKey, srCat: 'ruta-auto', srAuto: true,
        subTargetCheck: false,
      });
    });
    return arrows.length ? arrows : null;
  }

  function clearRoutes(modeKey) {
    // solo borra las auto-generadas; las flechas manuales (srCat 'ruta-manual') se conservan
    canvas.getObjects()
      .filter(o => o.srType === 'ruta-' + modeKey && o.srCat === 'ruta-auto')
      .forEach(o => canvas.remove(o));
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
      fontFamily: FONT_STACK, fontSize: 14, fontWeight: 'bold', fill: '#dc2626',
    });
    const g = new fabric.Group([ring, tag], {
      originX: 'center', originY: 'center',
      left: center.x, top: center.y,
      selectable: false, evented: false,
      srType: 'aviso-conexion', srCat: 'aviso', srHidden: true,
    });
    canvas.add(g);
  }

  // Migración: una versión intermedia guardaba la RUTA COMPLETA como un solo
  // grupo (todas las flechas juntas al seleccionar). Se parte en grupos por
  // flecha. Estructura de hijos por flecha: [halo?][tramo][puntita].
  function splitLegacyRouteGroups() {
    canvas.getObjects().slice().forEach(o => {
      if (o.type !== 'group') return;
      if (o.srCat !== 'ruta-auto' && o.srCat !== 'ruta-manual') return;
      const kids = o.getObjects();
      const hasHalo = kids.length && (kids[0].stroke === '#ffffff' || kids[0].stroke === WHITE_OUTLINE);
      const per = hasHalo ? 3 : 2;
      if (kids.length <= per) return;              // ya es una sola flecha
      if (kids.length % per !== 0) return;         // estructura desconocida: no tocar
      const { srType, srCat } = o;
      o._restoreObjectsState();                    // hijos a coordenadas absolutas
      withSuppress(() => {
        canvas.remove(o);
        for (let i = 0; i < kids.length; i += per) {
          const parts = kids.slice(i, i + per);
          parts.forEach(p => { if (p.setCoords) p.setCoords(); });
          canvas.add(new fabric.Group(parts, {
            srType, srCat, srAuto: srCat === 'ruta-auto', subTargetCheck: false,
          }));
        }
      });
    });
    canvas.requestRenderAll();
  }

  function generate(modeKey) {
    const all = canvas.getObjects();
    // Metas (salidas): las que puso el usuario; si no hay, se usa la puerta más
    // ancha como salida automática hacia la calle (sin colocar ícono).
    const goalObjs = all.filter(isSalida);
    // goalPoints = el ícono real que puso el usuario (ahí debe terminar la
    // flecha); goalViaPoints = el centro de la puerta más cercana, usado solo
    // para elegir una celda de meta despejada para el A* (evita que el
    // pathfinding se vaya lejos si el ícono cae justo sobre el hueco/pared).
    let goalPoints = goalObjs.map(g => g.getCenterPoint());
    let goalViaPoints = goalObjs.map(g => snapGoalToDoor(g.getCenterPoint(), all));
    if (!goalPoints.length) {
      const auto = autoExitPoint();
      if (!auto) { setStatus('Coloca una salida o una puerta', 'warn'); return; }
      goalPoints = [auto];
      goalViaPoints = [auto];
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

    const unreachable = [];     // centros de orígenes/canecas sin ruta a la salida
    let drawn = 0;
    state.suppress = true;
    try {
    clearRoutes(modeKey);
    clearWarnings();
    const grid = buildGrid();
    const cols = grid.cols;
    // meta = punto real de la salida + su celda libre más cercana (celda
    // calculada desde `via`, el centro de la puerta, no desde el ícono).
    const goals = goalPoints
      .map((p, i) => ({ p, via: goalViaPoints[i], cell: nearestFree(grid, toCell(goalViaPoints[i]).cx, toCell(goalViaPoints[i]).cy) }))
      .filter(g => g.cell);
    // las salidas también convergen el carril a su centro (como las puertas),
    // para que la ruta termine sobre la salida y no en un carril paralelo.
    const doorCenters = goalPoints.concat(
      all.filter(o => o.srType === 'puerta' || o.srType === 'vano').map(doorCenter)
    );

    // preparar: celda de inicio + meta más cercana
    const prepared = jobs.map(j => {
      const sCell = nearestFree(grid, toCell(j.center).cx, toCell(j.center).cy);
      if (!sCell) { unreachable.push(j.center); return null; }
      let best = null, bestPt = null, bestVia = null, bestD = Infinity;
      goals.forEach((g) => { const d = heur(sCell, g.cell); if (d < bestD) { bestD = d; best = g.cell; bestPt = g.p; bestVia = g.via; } });
      return best ? { ...j, sCell, goalCell: best, goalPt: bestPt, goalVia: bestVia, dist: bestD } : null;
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

    const usedColor = new Map();     // celda → color que la ocupa (fusión / evitar cruces)
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
      // string-pulling sobre las celdas del A* → menos escalera, diagonales
      // donde hay espacio libre; luego se conecta al punto real de la meta.
      let simple = smoothPathOrtho(simplify(cells), grid);
      simple = connectEndpoint(simple, j.goalPt, grid);
      const { pts, collapsed } = buildSafeRoutePoints(simple, laneOf[j.color] || 0, grid, doorCenters);
      // el desfase de carril mete un punto cada ~22px con un offset que puede
      // vibrar de un punto al siguiente (más pasillos/puertas cerca = más
      // ruido) — un segundo string-pulling atajos la parte "temblorosa" en
      // línea recta donde el espacio esté libre, sin eso las flechas por
      // tramos exponen cada micro-zigzag con su propia punta.
      const clean = smoothPathOrtho(pts, grid);
      // la flecha nace un poco separada del marcador/icono de origen, no en su centro exacto
      const trimmed = trimPathStart(clean, 16);
      const arrows = renderRoute(trimmed, j.color, modeKey, { halo: collapsed });
      if (!arrows) return;
      arrows.forEach(a => canvas.add(a));
      drawn++;
    });

    unreachable.forEach(c => markUnreachable(c));
    } finally { state.suppress = false; }
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
      const r = gapRect(d);
      const w = Math.max(r.width, r.height);
      if (w > bestW) { bestW = w; best = d; }
    });
    return doorCenter(best);
  }

  // "Borrar todas las flechas": generadas + manuales.
  const clearAll = () => {
    withSuppress(() => {
      canvas.getObjects()
        .filter(o => o.srCat === 'ruta-auto' || o.srCat === 'ruta-manual')
        .forEach(o => canvas.remove(o));
      clearWarnings();
    });
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    pushHistory();
    setStatus('Todas las flechas eliminadas');
  };

  // Solo las generadas automáticamente (evac + sanitaria); las manuales quedan.
  const clearGenerated = () => {
    withSuppress(() => { clearRoutes('evac'); clearRoutes('san'); clearWarnings(); });
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    pushHistory();
    setStatus('Rutas generadas eliminadas');
  };

  /* ── Selección / borrado ────────────────────────────────── */

  /* ── Portapapeles interno (Ctrl+C / X / V) ──────────────── */

  let clipboard = null;
  function copySelected() {
    const ao = canvas.getActiveObject();
    if (!ao || ao.srCat === 'page') return;
    ao.clone((cl) => { clipboard = cl; setStatus('Copiado — Ctrl+V para pegar'); }, PROPS);
  }
  function pasteClipboard() {
    if (!clipboard) return;
    clipboard.clone((cl) => {
      withSuppress(() => {
        canvas.discardActiveObject();
        cl.set({ left: cl.left + 18, top: cl.top + 18 });
        if (cl.type === 'activeSelection') {
          cl.canvas = canvas;
          cl.forEachObject(o => canvas.add(o));
          cl.setCoords();
        } else {
          canvas.add(cl);
        }
      });
      clipboard.set({ left: cl.left, top: cl.top });   // pegados sucesivos en cascada
      canvas.setActiveObject(cl);
      canvas.requestRenderAll();
      pushHistory();
      setStatus('Pegado');
    }, PROPS);
  }

  function duplicateSelected() {
    const ao = canvas.getActiveObject();
    if (!ao || ao.srCat === 'page') return;
    ao.clone((cl) => {
      withSuppress(() => {
        canvas.discardActiveObject();
        cl.set({ left: cl.left + 14, top: cl.top + 14 });
        if (cl.type === 'activeSelection') {
          cl.canvas = canvas;
          cl.forEachObject(o => canvas.add(o));
          cl.setCoords();
        } else {
          canvas.add(cl);
        }
      });
      canvas.setActiveObject(cl);
      canvas.requestRenderAll();
      pushHistory();
      setStatus('Duplicado');
    }, PROPS);   // conserva srType/srCat — sin esto el duplicado pierde su semántica
  }

  function deleteSelected() {
    const objs = canvas.getActiveObjects();
    if (!objs.length) return;
    withSuppress(() => objs.forEach(o => canvas.remove(o)));
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    pushHistory();
  }

  /* ── Historial ──────────────────────────────────────────── */

  function snapshot() {
    try { return JSON.stringify(canvas.toJSON(PROPS)); }
    catch (e) { console.error('snapshot error:', e); return null; }
  }
  // La serialización completa del canvas es costosa: los cambios en ráfaga
  // (arrastres, cadenas de paredes) se agrupan en un solo snapshot.
  let histTimer = null;
  function pushHistory(initial = false) {
    if (state.loadingHistory || state.suppress) return;
    if (initial) { commitHistory(true); return; }
    clearTimeout(histTimer);
    histTimer = setTimeout(() => commitHistory(false), 120);
  }
  function commitHistory(initial) {
    clearTimeout(histTimer); histTimer = null;
    const snap = snapshot();
    if (snap === null) return;
    if (state.history.length && state.history[state.history.length - 1] === snap) return;
    state.history.push(snap);
    if (state.history.length > 40) state.history.shift();
    state.redoStack = [];
    if (!initial) { state.dirty = true; setSaveState('dirty'); scheduleAutoSave(); }
  }
  // Antes de undo/redo hay que materializar el snapshot pendiente.
  function flushHistory() { if (histTimer) commitHistory(false); }
  function loadSnapshot(str) {
    resetTransient();
    state.loadingHistory = true;
    canvas.loadFromJSON(JSON.parse(str), () => {
      ensurePageBg();   // la hoja no viaja en el snapshot (excludeFromExport)
      fixupManualArrows();
      fixupWallCaps();
      // loadFromJSON no emite selection:cleared → las barras quedarían
      // mostrando propiedades de un objeto que ya no existe.
      canvas.discardActiveObject();
      syncTextBar(); syncPropBar();
      canvas.renderAll();
      state.loadingHistory = false;
    });
  }
  function undo() { flushHistory(); if (state.history.length <= 1) return; state.redoStack.push(state.history.pop()); loadSnapshot(state.history[state.history.length - 1]); }
  function redo() { if (!state.redoStack.length) return; const s = state.redoStack.pop(); state.history.push(s); loadSnapshot(s); }

  /* ── Guardar ────────────────────────────────────────────── */

  let autoTimer = null;
  function scheduleAutoSave() {
    clearTimeout(autoTimer);
    autoTimer = setTimeout(() => saveData(true), AUTOSAVE_MS);
  }

  // updated_at que el editor conoce; si el servidor tiene otro, alguien más guardó.
  // Se lee en el primer guardado (canvas.js carga antes de que exista PLAN_UPDATED).
  let lastSaved = null;

  function saveData(silent) {
    if (lastSaved === null && typeof PLAN_UPDATED !== 'undefined' && PLAN_UPDATED) lastSaved = PLAN_UPDATED;
    clearTimeout(autoTimer);
    if (state.conflict) {
      // conflicto real: no pisar el trabajo de otra pestaña; ofrecer recargar
      if (!silent && confirm('Este plano fue modificado en otra pestaña.\n¿Recargar para ver la última versión? (Se pierde lo no guardado aquí)')) location.reload();
      return;
    }
    // no autoguardar a mitad de una multi-selección (coords relativas); reintenta luego
    const ao = canvas.getActiveObject();
    if (silent && ao && ao.type === 'activeSelection') { scheduleAutoSave(); return; }
    if (!silent) canvas.discardActiveObject().requestRenderAll();
    setSaveState('saving');
    fetch(SAVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify({ canvas_data: canvas.toJSON(PROPS), last_saved: lastSaved }),
    })
      .then(r => {
        if (r.status === 409) {
          state.conflict = true;
          setSaveState('conflict');
          setStatus('Este plano fue modificado en otra pestaña — recargá la página antes de seguir', 'err');
          return null;
        }
        return r.json();
      })
      .then(d => {
        if (!d) return;
        if (d.ok) {
          state.dirty = false;
          if (d.updated_at) lastSaved = d.updated_at;
          setSaveState('saved');
          if (!silent) setStatus('Guardado ' + (d.saved_at || ''), 'ok');
        } else { setSaveState('error'); if (!silent) setStatus('Error al guardar', 'err'); }
      })
      .catch(() => {
        setSaveState('error');
        setStatus(silent ? 'Sin conexión — reintentando…' : 'Error de conexión', 'err');
        if (silent) scheduleAutoSave();
      });
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
      if (!o.visible || o.srCat === 'page') return;
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
      if (o.srHidden) return true;                              // puntitos verdes / avisos
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
    const url = canvas.toDataURL({ format: 'png', multiplier: 3, left: cl, top: ct, width: cw, height: ch, backgroundColor: '#ffffff' });

    temps.forEach(o => canvas.remove(o));
    toHide.forEach(o => (o.visible = true));
    if (title) title.set({ text: prevText, left: DOC.w / 2 });
    canvas.renderAll();
    return { url, w: cw, h: ch };
  }

  // Genera el PDF: una página por modo (['evac'], ['san'] o ambos).
  async function doExport(modes) {
    closeExport();
    if (!modes || !modes.length) return;
    canvas.discardActiveObject();

    // Generación automática DESACTIVADA: el PDF muestra exactamente lo que
    // hay en el lienzo (antes se regeneraban rutas A* aquí y aparecían
    // flechas que el usuario nunca dibujó).
    // si hay leyenda, refrescarla para que refleje el contenido actual
    if (canvas.getObjects().some(o => o.srType === 'leyenda')) {
      try { await buildLegend(); } catch (e) { console.error('leyenda:', e); }
    }
    // leyenda siempre DENTRO de la hoja en el PDF
    ['leyenda'].forEach(t => {
      const o = canvas.getObjects().find(x => x.srType === t);
      if (!o) return;
      const r = o.getBoundingRect(true, true);
      let dx = 0, dy = 0;
      if (r.left < 8) dx = 8 - r.left;
      if (r.top < 8) dy = 8 - r.top;
      if (r.left + r.width > DOC.w - 8) dx = DOC.w - 8 - (r.left + r.width);
      if (r.top + r.height > DOC.h - 8) dy = DOC.h - 8 - (r.top + r.height);
      if (dx || dy) { o.set({ left: o.left + dx, top: o.top + dy }); o.setCoords(); }
    });

    // esperar a que la fuente (Century Gothic / Jost) esté cargada antes de rasterizar,
    // si no el texto del PDF saldría con la fuente por defecto.
    setStatus('Generando PDF…');
    try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch (e) {}
    // render a escala real: dims del documento + viewport identidad
    const prevVpt = canvas.viewportTransform.slice();
    const prevW = canvas.getWidth(), prevH = canvas.getHeight();
    canvas.setDimensions({ width: DOC.w, height: DOC.h });
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    const { jsPDF } = window.jspdf;
    let pdf = null;
    // los temporales del render no van al historial
    withSuppress(() => modes.forEach((mode) => {
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
    }));

    canvas.setDimensions({ width: prevW, height: prevH });
    canvas.setViewportTransform(prevVpt);
    canvas.requestRenderAll();
    const modeTag = modes.map(m => m === 'evac' ? 'EVACUACION' : 'SANITARIA').join('_');
    const nameTag = (PLAN_NAME || 'plano').trim().replace(/\s+/g, '-').toUpperCase();
    const dateTag = new Date().toISOString().slice(0, 10);
    pdf.save(`RUTA_${modeTag}_${nameTag}_${dateTag}.pdf`);
    setStatus('PDF exportado (' + modes.length + ' pág.)', 'ok');
  }
  const exportWith = doExport;

  /* ── Teclado ────────────────────────────────────────────── */

  const NUDGE = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

  function bindKeyboard() {
    document.addEventListener('keydown', (e) => {
      const ao = canvas.getActiveObject();
      if (ao && ao.isEditing) return;
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      if (e.code === 'Space') {
        e.preventDefault();
        if (!state.spaceDown) {
          state.spaceDown = true;
          canvas.selection = false;
          canvas.skipTargetFind = true;
          canvas.defaultCursor = 'grab';
        }
        return;
      }
      if (NUDGE[e.key] && ao) {
        e.preventDefault();
        const d = e.shiftKey ? 10 : 1;
        ao.set({ left: ao.left + NUDGE[e.key][0] * d, top: ao.top + NUDGE[e.key][1] * d });
        ao.setCoords();
        state.nudged = true;   // un solo pushHistory al soltar la tecla
        canvas.requestRenderAll();
        return;
      }
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
      else if (e.ctrlKey && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicateSelected(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 'c') { e.preventDefault(); copySelected(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 'x') { e.preventDefault(); copySelected(); deleteSelected(); }
      else if (e.ctrlKey && e.key.toLowerCase() === 'v') { e.preventDefault(); pasteClipboard(); }
      else if (e.ctrlKey && e.key === '0') { e.preventDefault(); fit(); }
      else if (e.ctrlKey && e.key === '1') { e.preventDefault(); applyZoom(1); }
      else if (e.key === 'Enter' && state.tool === 'ruta') { e.preventDefault(); finalizeRoute(); }
      else if (e.key === 'Escape') {
        // Escalonado (estilo Figma): 1) cancela lo que está a medias,
        // 2) deselecciona, 3) vuelve a Seleccionar.
        if (state.tool === 'ruta' && (state.routePts || []).length) {
          if (state.routePts.length >= 2) finalizeRoute();
          else { clearRoutePreview(); state.routePts = []; canvas.requestRenderAll(); }
          return;   // sigue en la herramienta ruta
        }
        if (state.tool === 'wall' && state.chain) { endWallChain(); return; }  // corta la cadena
        if (canvas.getActiveObject()) { canvas.discardActiveObject(); canvas.requestRenderAll(); return; }
        backToSelect();
      }
      else if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        // atajos de una tecla para herramientas (tooltips en los botones)
        const k = e.key.toLowerCase();
        const TOOL_KEYS = { v: 'select', w: 'wall', m: 'furniture', d: 'vano', b: 'door', z: 'rect', t: 'text', e: 'erase' };
        if (TOOL_KEYS[k]) setTool(TOOL_KEYS[k], document.getElementById('tool-' + TOOL_KEYS[k]));
        else if (k === 'r') setRouteTool('evac', document.getElementById('route-evac'));
      }
    });
    document.addEventListener('keyup', (e) => {
      if (e.code === 'Space') {
        state.spaceDown = false;
        state.panning = false;
        applyToolFlags();
      }
      if (state.nudged && NUDGE[e.key]) { state.nudged = false; pushHistory(); }
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

  /* ── Guía de inicio (plano vacío) ───────────────────────── */

  const SKIP_HINT = new Set(['logo', 'titulo']);
  function updateEmptyHint() {
    const el = document.getElementById('emptyHint');
    if (!el) return;
    el.hidden = canvas.getObjects().some(o => o.srCat !== 'page' && !SKIP_HINT.has(o.srType));
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

  // Chip persistente del estado de guardado (topbar). A diferencia de
  // setStatus (mensajes efímeros), este siempre refleja el estado real.
  const SAVE_STATES = {
    saved:    { text: 'Guardado ✓',        cls: 'ok'   },
    saving:   { text: 'Guardando…',        cls: ''     },
    dirty:    { text: 'Sin guardar',       cls: 'warn' },
    error:    { text: 'Error al guardar',  cls: 'err'  },
    conflict: { text: 'Conflicto — recargá', cls: 'err' },
  };
  function setSaveState(kind) {
    const el = document.getElementById('ed-save');
    if (!el) return;
    if (state.conflict) kind = 'conflict';   // el conflicto no se pisa con otros estados
    const s = SAVE_STATES[kind] || SAVE_STATES.saved;
    el.textContent = s.text;
    el.className = 'ed-status ed-save' + (s.cls ? ' ed-status--' + s.cls : '');
  }

  // Aviso al cerrar/recargar con cambios sin guardar.
  window.addEventListener('beforeunload', (e) => {
    if (!state.dirty || state.conflict) return;
    e.preventDefault();
    e.returnValue = '';
  });

  return {
    init, setTool, deleteSelected, undo, redo,
    zoomIn, zoomOut, zoomReset, toggleGrid, save,
    exportPDF, doExport, closeExport,
    generateEvac, generateSan, clearAll, clearGenerated,
    setFont, setTextSize, toggleBold,
    duplicateSelected, setColor, setStrokeW, setOpacity, commitProps,
    bringFront, sendBack, setArrowKind, makeLegend, setRouteTool, setPlaceTool,
    qaCanvas: () => canvas,   // solo para tests (qa/smoke_editor.py)
  };
})();

function toggleSection(hd) { hd.parentElement.classList.toggle('collapsed'); }
