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
const LINE_W = 5;                  // grosor del trazo de la ruta (px)
const ARROW_SIZE = 16;             // apertura de la punta (px)
const CORNER_MARGIN = 28;          // espacio que se deja antes de cada giro (px)
const AUTOSAVE_MS = 2500;          // espera tras editar antes de autoguardar

const OBSTACLES = new Set(['pared', 'mueble', 'zona']);
const EVAC_COLOR = '#16a34a';

// Stack de fuente: usa la CenturyGothic instalada (nombre CSS "Century Gothic",
// CON espacio); si no está, cae a Jost (geométrica casi idéntica, vía Google Fonts).
const FONT_STACK = "'Century Gothic', Jost, Futura, 'Trebuchet MS', sans-serif";

// Color de la flecha según el tipo de caneca.
const CANECA_COLOR = {
  caneca_ordinaria:  '#111827',  // negra
  caneca_reciclable: '#9ca3af',  // blanca → gris (para que se vea)
  caneca_biosani:    '#dc2626',  // roja
  caneca_corto:      '#dc2626',  // roja
};

// Flechas manuales del sidebar: idénticas a las que genera el programa, en cada
// color de ruta. Se arrastran y rotan para reemplazar una flecha mal generada.
const ARROW_TYPES = {
  flecha_evac:  { color: '#16a34a', mode: 'evac' },  // verde (evacuación)
  flecha_negra: { color: '#111827', mode: 'san'  },  // caneca ordinaria
  flecha_gris:  { color: '#9ca3af', mode: 'san'  },  // caneca reciclable
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
    history: [], redoStack: [], loadingHistory: false, suppress: false, dirty: false,
    panning: false, panStart: null, spaceDown: false, nudged: false,
    gridSnap: false, guides: [],
  };

  const PROPS = ['srType', 'srCat', 'srHidden', 'srGapX', 'srGapY', 'srDir', 'srAuto', 'srLen'];

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

    if (savedData) {
      state.loadingHistory = true;
      try {
        canvas.loadFromJSON(savedData, () => {
          ensurePageBg();
          canvas.renderAll(); fit();
          state.loadingHistory = false;
          explodeRouteGroups();
          fixupManualArrows();
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
      state.suppress = true;
      canvas.add(bg);
      state.suppress = false;
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

  function toggleGrid(btnEl) {
    state.gridSnap = !state.gridSnap;
    if (btnEl) btnEl.classList.toggle('active', state.gridSnap);
    setStatus(state.gridSnap ? 'Snap a grilla activado' : 'Snap a grilla desactivado');
  }

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
    canvas.skipTargetFind = drawing && t !== 'erase';
    canvas.defaultCursor = t === 'erase' ? 'crosshair' : (drawing ? 'crosshair' : 'default');
  }

  /* ── Enganche de extremos (snap) ────────────────────────── */

  const SNAP_TYPES = new Set(['pared', 'mueble', 'puerta', 'vano']);
  function collectEndpoints() {
    const pts = [];
    canvas.getObjects().forEach((o) => {
      if (o === state.draft || !SNAP_TYPES.has(o.srType)) return;
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
      if (state.panning) {
        const vpt = canvas.viewportTransform;
        vpt[4] += opt.e.clientX - state.panStart.x;
        vpt[5] += opt.e.clientY - state.panStart.y;
        state.panStart = { x: opt.e.clientX, y: opt.e.clientY };
        canvas.requestRenderAll();
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
  function gapPath(start, s, horizontal, sx, sy) {
    const wt = 4; // mitad del grosor de pared (8px)
    let x1, y1, x2, y2;
    if (horizontal) {
      x1 = start.x; x2 = start.x + sx * s;
      y1 = start.y - wt; y2 = start.y + wt;
    } else {
      x1 = start.x - wt; x2 = start.x + wt;
      y1 = start.y; y2 = start.y + sy * s;
    }
    const p = new fabric.Path(`M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2} L ${x1} ${y2} Z`, {
      stroke: '#000000', strokeWidth: 2, fill: '#ffffff',
    });
    p.srGapX = (x1 + x2) / 2; p.srGapY = (y1 + y2) / 2;
    return p;
  }

  // Puerta: hueco + hoja perpendicular + arco de apertura (dibujo arquitectónico).
  function makeDoor(start, end, s) {
    const dx = end.x - start.x, dy = end.y - start.y;
    const horizontal = Math.abs(dx) >= Math.abs(dy);
    const sx = Math.sign(dx) || 1, sy = Math.sign(dy) || 1;
    const gap = gapPath(start, s, horizontal, sx, sy);
    // bisagra A, tope B, punta de la hoja T (la hoja abre hacia arriba/izquierda)
    const A = { x: start.x, y: start.y };
    const B = horizontal ? { x: start.x + sx * s, y: start.y } : { x: start.x, y: start.y + sy * s };
    const n = horizontal ? { x: 0, y: -1 } : { x: -1, y: 0 };
    const T = { x: A.x + n.x * s, y: A.y + n.y * s };
    const u = { x: (B.x - A.x) / s, y: (B.y - A.y) / s };
    const sweep = (n.x * u.y - n.y * u.x) > 0 ? 1 : 0;
    const leaf = new fabric.Line([A.x, A.y, T.x, T.y], { stroke: '#1f2937', strokeWidth: 3 });
    const arc = new fabric.Path(`M ${T.x} ${T.y} A ${s} ${s} 0 0 ${sweep} ${B.x} ${B.y}`, {
      stroke: '#9ca3af', strokeWidth: 1.5, strokeDashArray: [4, 4], fill: 'transparent',
    });
    return new fabric.Group([gap, leaf, arc], {
      srType: 'puerta', srCat: 'shape',
      srGapX: gap.srGapX, srGapY: gap.srGapY,
      srDir: horizontal ? 'h' : 'v',
    });
  }

  // Vano: abertura simple en la pared (solo el hueco, sin hoja).
  function makeVano(start, end) {
    const dx = end.x - start.x, dy = end.y - start.y;
    const horizontal = Math.abs(dx) >= Math.abs(dy);
    const s = Math.max(Math.abs(dx), Math.abs(dy));
    const v = gapPath(start, s, horizontal, Math.sign(dx) || 1, Math.sign(dy) || 1);
    v.srType = 'vano'; v.srCat = 'shape';
    v.srDir = horizontal ? 'h' : 'v';
    return v;
  }

  // Rectángulo del HUECO de una puerta/vano, aunque el bbox incluya el arco.
  // La puerta nueva es un grupo cuyo hueco queda en el borde inferior (h) o
  // derecho (v) del bbox porque la hoja siempre abre hacia arriba/izquierda.
  // ponytail: asume puerta sin rotar; si se rota el grupo, cae al bbox completo.
  function gapRect(o) {
    const r = o.getBoundingRect(true, true);
    if (o.srType === 'puerta' && o.type === 'group') {
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

  const drugName = () => (typeof PLAN_NAME !== 'undefined' && PLAN_NAME) ? PLAN_NAME : '';
  const titleFor = (mode) => {
    const base = mode === 'evac' ? 'RUTA DE EVACUACIÓN'
      : mode === 'san' ? 'RUTA SANITARIA'
        : 'RUTA DE EVACUACIÓN / SANITARIA';
    const n = drugName();
    return (base + (n ? '  —  ' + n : '')).toUpperCase();
  };

  // Crea el encabezado (logo + título) si aún no existe.
  // Se guarda con el plano; cada parte se crea solo si falta.
  function ensureHeader() {
    const cx = DOC.w / 2;
    const find = (t) => canvas.getObjects().find(o => o.srType === t);

    // logo real — solo si no hay ya uno en el plano
    if (!find('logo')) {
      fabric.Image.fromURL('/static/img/logo.png', (img) => {
        img.set({ left: 28, top: 12, originX: 'left', originY: 'top', srType: 'logo', srCat: 'marca' });
        img.scaleToWidth(72);
        canvas.add(img);
        canvas.requestRenderAll();
      }, { crossOrigin: 'anonymous' });
    }

    // título del plano: centrado arriba. Si no existe, se crea con el nombre de
    // la droguería + la ruta. Si existe pero quedó el viejo "PLANO VECTORIZADO"
    // (que metía el pipeline), se reemplaza por el título correcto.
    const titulo = find('titulo');
    if (!titulo) {
      canvas.add(new fabric.IText(titleFor(null), {
        left: cx, top: 22, originX: 'center', originY: 'top',
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
    else if (o.srCat === 'ruta-manual') o.set({ stroke: v, fill: v });  // línea + cabeza
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
  function setArrowKind(k) {
    const spec = ARROW_TYPES[k];
    const o = canvas.getActiveObject();
    if (!spec || !o || o.srCat !== 'ruta-manual') return;
    o.set({ stroke: spec.color, fill: spec.color });
    o.srType = 'ruta-' + spec.mode;
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
      if (bx) { o.set('left', o.left + bx.d); state.guides.push({ v: bx.x }); }
      if (by) { o.set('top', o.top + by.d); state.guides.push({ h: by.y }); }
      if (bx || by) o.setCoords();
    });

    canvas.on('mouse:up', () => {
      if (state.guides.length) {
        state.guides = [];
        canvas.clearContext(canvas.contextTop);
        canvas.requestRenderAll();
      }
    });

    canvas.on('after:render', () => {
      if (!state.guides.length) return;
      const ctx = canvas.contextTop;
      const t = canvas.viewportTransform;
      canvas.clearContext(ctx);
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
    if (ICON_IMG[type]) {
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

  /* ── Leyenda automática + cartela ───────────────────────── */

  const LEGEND_LABELS = {
    extintor: 'Extintor', botiquin: 'Botiquín', punto_encuentro: 'Punto de encuentro',
    salida_emergencia: 'Salida de emergencia', entrada_salida: 'Entrada / Salida',
    camilla: 'Camilla', bano: 'Baño', norte: 'Norte',
    caneca_ordinaria: 'Caneca ordinaria (negra)', caneca_reciclable: 'Caneca reciclable (blanca)',
    caneca_biosani: 'Caneca biosanitaria (roja)', caneca_corto: 'Caneca cortopunzantes',
  };
  const SAN_ARROW_LABEL = {
    '#111827': 'Ruta sanitaria — ordinaria',
    '#9ca3af': 'Ruta sanitaria — reciclable',
    '#dc2626': 'Ruta sanitaria — biosanitaria',
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
    if (all.some(o => o.srType === 'ruta-evac')) rows.push({ arrow: EVAC_COLOR, label: 'Ruta de evacuación' });
    [...new Set(all.filter(o => o.srType === 'ruta-san').map(o => o.stroke))].forEach(c => {
      if (c) rows.push({ arrow: c, label: SAN_ARROW_LABEL[c] || 'Ruta sanitaria' });
    });
    if (!rows.length) { setStatus('No hay elementos para la leyenda todavía', 'warn'); return; }

    const prev = all.find(o => o.srType === 'leyenda');
    const PADX = 14, ROW_H = 30, ICON = 24, TITLE_H = 34, W = 268;
    const H = TITLE_H + rows.length * ROW_H + 10;
    const parts = [
      new fabric.Rect({ left: 0, top: 0, width: W, height: H, fill: '#ffffff', stroke: '#111827', strokeWidth: 1.5 }),
      new fabric.Text('CONVENCIONES', {
        left: W / 2, top: 10, originX: 'center', fontFamily: FONT_STACK,
        fontSize: 14, fontWeight: 'bold', fill: '#111827',
      }),
    ];
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      const cy = TITLE_H + i * ROW_H + ROW_H / 2;
      if (r.arrow) {
        const a = makeArrowShape(r.arrow, 34);
        a.set({ left: PADX + ICON / 2, top: cy, strokeWidth: 3 });
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
        fontFamily: FONT_STACK, fontSize: 12.5, fill: '#111827',
      }));
    }
    const g = new fabric.Group(parts, {
      srType: 'leyenda', srCat: 'marca',
      left: prev ? prev.left : DOC.w - W - 26,
      top:  prev ? prev.top  : DOC.h - H - 26,
      scaleX: prev ? prev.scaleX : 1, scaleY: prev ? prev.scaleY : 1,
    });
    state.suppress = true;
    if (prev) canvas.remove(prev);
    canvas.add(g);
    state.suppress = false;
    canvas.requestRenderAll();
  }

  // Cartela: datos del documento (abajo-izquierda).
  function buildCartela() {
    const prev = canvas.getObjects().find(o => o.srType === 'cartela');
    const name = drugName() || (typeof PROJECT_NAME !== 'undefined' ? PROJECT_NAME : '');
    const who = (typeof USER_NAME !== 'undefined' && USER_NAME) ? USER_NAME : '____________';
    const hoy = new Date().toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' });
    const lines = [name.toUpperCase(), 'Fecha de elaboración: ' + hoy, 'Elaborado por: ' + who];
    const W = 300, H = 20 + lines.length * 22;
    const parts = [new fabric.Rect({ left: 0, top: 0, width: W, height: H, fill: '#ffffff', stroke: '#111827', strokeWidth: 1.5 })];
    lines.forEach((t, i) => parts.push(new fabric.Text(t, {
      left: 12, top: 12 + i * 22, fontFamily: FONT_STACK,
      fontSize: i === 0 ? 14 : 12.5, fontWeight: i === 0 ? 'bold' : 'normal', fill: '#111827',
    })));
    const g = new fabric.Group(parts, {
      srType: 'cartela', srCat: 'marca',
      left: prev ? prev.left : 26,
      top:  prev ? prev.top  : DOC.h - H - 26,
      scaleX: prev ? prev.scaleX : 1, scaleY: prev ? prev.scaleY : 1,
    });
    state.suppress = true;
    if (prev) canvas.remove(prev);
    canvas.add(g);
    state.suppress = false;
    canvas.requestRenderAll();
  }

  async function makeLegend() {
    await buildLegend();
    buildCartela();
    pushHistory();
    setStatus('Leyenda y cartela generadas — puedes moverlas', 'ok');
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
      const r = gapRect(o);   // solo el hueco — el arco de la puerta no abre paso
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

  function connectEndpoint(pts, goalPt, grid) {
    if (!goalPt || pts.length < 1) return pts;
    const out = pts.slice();
    appendOrthogonal(out, { x: goalPt.x, y: goalPt.y }, grid, true);
    return out;
  }

  function routePointsClear(pts, grid) {
    if (!pts || pts.length < 2) return false;
    for (let i = 1; i < pts.length; i++) {
      if (!axisSegmentClear(grid, pts[i - 1], pts[i])) return false;
    }
    return true;
  }

  function buildSafeRoutePoints(basePts, lane, grid, doorCenters) {
    const base = densify(basePts, 22);
    if (lane) {
      const shifted = offsetPath(base, lane, grid, doorCenters);
      const ortho = orthogonalizePath(shifted, grid);
      if (routePointsClear(ortho, grid)) return ortho;
    }
    return base;
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

  const inRect = (x, y, r, pad) =>
    x >= r.left - pad && x <= r.left + r.width + pad &&
    y >= r.top - pad && y <= r.top + r.height + pad;

  // Crea una punta de flecha (triángulo relleno) en (cx,cy) apuntando en dirección (dx,dy).
  function arrowTip(cx, cy, dx, dy, color, modeKey) {
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    const px = -uy, py = ux;
    const h = ARROW_SIZE;
    const w = h * 0.45;
    return new fabric.Polygon([
      { x: cx, y: cy },
      { x: cx - ux * h + px * w, y: cy - uy * h + py * w },
      { x: cx - ux * h - px * w, y: cy - uy * h - py * w },
    ], {
      fill: color, stroke: color, strokeWidth: 1,
      srType: 'ruta-' + modeKey, srCat: 'ruta-auto',
    });
  }

  // Flecha manual como un solo path: misma geometría que la auto-generada, pero
  // sin grupo separado para que la punta quede centrada y rotada correctamente.
  function makeArrowShape(color, len) {
    const L = len || 72;                   // largo total de la flecha
    const h = ARROW_SIZE, w = h * 0.55;
    const xTip = L / 2;
    const xLine = -L / 2;
    // línea hasta la base de la cabeza + triángulo CERRADO y relleno
    const d = [
      `M ${xLine} 0`,
      `L ${xTip - h} 0`,
      `M ${xTip - h} ${w}`,
      `L ${xTip} 0`,
      `L ${xTip - h} ${-w}`,
      'Z',
    ].join(' ');
    const p = new fabric.Path(d, {
      fill: color,
      stroke: color,
      strokeWidth: LINE_W,
      strokeLineCap: 'round',
      strokeLineJoin: 'round',
      strokeUniform: true,
      originX: 'center',
      originY: 'center',
      centeredScaling: true,
      lockUniScaling: true,
      lockScalingFlip: true,
      lockSkewingX: true,
      lockSkewingY: true,
    });
    // laterales = estirar el largo (se hornea en bakeArrowStretch); sin verticales
    p.setControlsVisibility({ mt: false, mb: false });
    p.srLen = L;
    return p;
  }

  // Si la flecha quedó con escala no uniforme (la estiraron con una manija
  // lateral), se reconstruye con la LÍNEA más larga y la cabeza intacta.
  function bakeArrowStretch(o) {
    const sx = Math.abs(o.scaleX || 1), sy = Math.abs(o.scaleY || 1);
    if (Math.abs(sx - sy) < 0.01) return;     // escala uniforme: nada que corregir
    const newLen = Math.max(28, (o.srLen || 72) * sx / sy);
    const n = makeArrowShape(o.stroke, newLen);
    n.set({
      left: o.left, top: o.top, angle: o.angle || 0,
      scaleX: sy, scaleY: sy, strokeWidth: o.strokeWidth,
    });
    n.srType = o.srType; n.srCat = o.srCat;
    state.suppress = true;
    canvas.remove(o);
    canvas.add(n);
    state.suppress = false;
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

  // Ruta = línea sólida por cada segmento recto + punta de flecha al final de
  // cada segmento.  Entre segmentos se deja CORNER_MARGIN de separación para
  // que las puntas no queden pegadas al giro.
  function makeRoute(points, color, modeKey, phase, placed, items, placedAll) {
    if (points.length < 2) return null;

    // Detectar cambios de dirección (horizontal ↔ vertical) en el path
    const turns = [];
    for (let i = 1; i < points.length - 1; i++) {
      const a = points[i - 1], b = points[i], c = points[i + 1];
      const dx1 = b.x - a.x, dy1 = b.y - a.y;
      const dx2 = c.x - b.x, dy2 = c.y - b.y;
      const h1 = Math.abs(dx1) >= Math.abs(dy1);
      const h2 = Math.abs(dx2) >= Math.abs(dy2);
      if (h1 !== h2) turns.push(i);
    }

    const M = CORNER_MARGIN;
    const parts = [];

    // Construir segmentos: cada tramo entre dos giros consecutivos
    const boundaries = [0, ...turns, points.length - 1];

    for (let s = 0; s < boundaries.length - 1; s++) {
      const si = boundaries[s];
      const ei = boundaries[s + 1];
      if (si >= ei) continue;

      const pStart = points[si];
      const pEnd = points[ei];
      const dx = pEnd.x - pStart.x;
      const dy = pEnd.y - pStart.y;
      const len = Math.hypot(dx, dy);
      if (len < 1) continue;
      const ux = dx / len, uy = dy / len;

      // El último segmento (que llega a la meta) no lleva margen y SIEMPRE se dibuja.
      // Los demás llevan margen al final para separar la punta del giro.
      const isLast = (s === boundaries.length - 2);
      const endMargin = isLast ? 0 : M;
      const lineStart = pStart;
      const lineEnd = { x: pEnd.x - ux * endMargin, y: pEnd.y - uy * endMargin };
      const remain = Math.hypot(lineEnd.x - lineStart.x, lineEnd.y - lineStart.y);

      if (!isLast && remain < 12) continue;

      // no dibujar sobre un icono; salvo el último tramo, que debe llegar a la salida
      if (!isLast && items && items.some(r => inRect((lineStart.x + lineEnd.x) / 2, (lineStart.y + lineEnd.y) / 2, r, 4)))
        continue;

      // Punta siempre en el último segmento; en los demás solo si hay espacio.
      const wantTip = isLast || remain > 20;
      // Si lleva punta, la línea termina en la BASE del triángulo (no en la punta)
      // para que el cap redondo no sobresalga de la cabeza.
      const lineTo = wantTip
        ? { x: lineEnd.x - ux * ARROW_SIZE * 0.9, y: lineEnd.y - uy * ARROW_SIZE * 0.9 }
        : lineEnd;

      // Línea del segmento
      parts.push(new fabric.Line([lineStart.x, lineStart.y, lineTo.x, lineTo.y], {
        stroke: color, strokeWidth: LINE_W, strokeLineCap: 'round',
        srType: 'ruta-' + modeKey, srCat: 'ruta-auto',
      }));

      if (wantTip) {
        // Usar la dirección del último tramo para que la punta apunte exactamente a la meta
        const localDx = (isLast && ei - si >= 1) ? pEnd.x - points[ei - 1].x : dx;
        const localDy = (isLast && ei - si >= 1) ? pEnd.y - points[ei - 1].y : dy;
        parts.push(arrowTip(lineEnd.x, lineEnd.y, localDx, localDy, color, modeKey));
      }
    }

    return parts.length ? parts : null;
  }

  function makeRouteSafe(points, color, modeKey, phase, placed, items, placedAll) {
    if (points.length < 2) return null;

    const turns = [];
    for (let i = 1; i < points.length - 1; i++) {
      const a = points[i - 1], b = points[i], c = points[i + 1];
      const dx1 = b.x - a.x, dy1 = b.y - a.y;
      const dx2 = c.x - b.x, dy2 = c.y - b.y;
      const h1 = Math.abs(dx1) >= Math.abs(dy1);
      const h2 = Math.abs(dx2) >= Math.abs(dy2);
      if (h1 !== h2) turns.push(i);
    }

    const parts = [];
    const boundaries = [0, ...turns, points.length - 1];
    for (let s = 0; s < boundaries.length - 1; s++) {
      const si = boundaries[s];
      const ei = boundaries[s + 1];
      if (si >= ei) continue;

      const pStart = points[si];
      const pEnd = points[ei];
      const dx = pEnd.x - pStart.x;
      const dy = pEnd.y - pStart.y;
      const len = Math.hypot(dx, dy);
      if (len < 1) continue;

      const ux = dx / len, uy = dy / len;
      const isLast = s === boundaries.length - 2;
      const endMargin = isLast ? 0 : CORNER_MARGIN;
      const lineStart = pStart;
      const lineEnd = { x: pEnd.x - ux * endMargin, y: pEnd.y - uy * endMargin };
      const remain = Math.hypot(lineEnd.x - lineStart.x, lineEnd.y - lineStart.y);
      if (!isLast && remain < 12) continue;
      if (!isLast && items && items.some(r => inRect((lineStart.x + lineEnd.x) / 2, (lineStart.y + lineEnd.y) / 2, r, 4))) continue;

      const wantTip = isLast || remain > 20;
      let path = `M ${lineStart.x} ${lineStart.y} L ${lineEnd.x} ${lineEnd.y}`;
      if (wantTip) {
        const localDx = (isLast && ei - si >= 1) ? pEnd.x - points[ei - 1].x : dx;
        const localDy = (isLast && ei - si >= 1) ? pEnd.y - points[ei - 1].y : dy;
        const localLen = Math.hypot(localDx, localDy) || 1;
        const ax = localDx / localLen, ay = localDy / localLen;
        const px = -ay, py = ax;
        const h = ARROW_SIZE, w = h * 0.55;
        const lx = lineEnd.x - ax * h + px * w;
        const ly = lineEnd.y - ay * h + py * w;
        const rx = lineEnd.x - ax * h - px * w;
        const ry = lineEnd.y - ay * h - py * w;
        path += ` M ${lx} ${ly} L ${lineEnd.x} ${lineEnd.y} L ${rx} ${ry}`;
      }

      parts.push(new fabric.Path(path, {
        stroke: color, strokeWidth: LINE_W, fill: 'transparent',
        strokeLineCap: 'round', strokeLineJoin: 'round',
        strokeUniform: true,
        selectable: false, evented: false,
        srType: 'ruta-' + modeKey, srCat: 'ruta-auto',
      }));
    }

    return parts.length ? parts : null;
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
    let goalPoints = goalObjs.map(g => snapGoalToDoor(g.getCenterPoint(), all));
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
    const unreachable = [];     // centros de orígenes/canecas sin ruta a la salida
    const grid = buildGrid();
    const cols = grid.cols;
    // meta = punto real de la salida + su celda libre más cercana (emparejados)
    const goals = goalPoints
      .map(p => ({ p, cell: nearestFree(grid, toCell(p).cx, toCell(p).cy) }))
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
      let best = null, bestPt = null, bestD = Infinity;
      goals.forEach((g) => { const d = heur(sCell, g.cell); if (d < bestD) { bestD = d; best = g.cell; bestPt = g.p; } });
      return best ? { ...j, sCell, goalCell: best, goalPt: bestPt, dist: bestD } : null;
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
      let simple = simplify(cells);
      simple = connectEndpoint(simple, j.goalPt, grid);
      const pts = buildSafeRoutePoints(simple, laneOf[j.color] || 0, grid, doorCenters);
      // Mantener la ruta ortogonal y validada contra la grilla de obstaculos.
      const arrows = makeRouteSafe(pts, j.color, modeKey, null, null, itemRects, null);
      if (!arrows) return;
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
      const r = gapRect(d);
      const w = Math.max(r.width, r.height);
      if (w > bestW) { bestW = w; best = d; }
    });
    return doorCenter(best);
  }

  const clearAll = () => { state.suppress = true; clearRoutes('evac'); clearRoutes('san'); clearWarnings(); state.suppress = false; pushHistory(); setStatus('Rutas eliminadas'); };

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
      state.suppress = true;
      canvas.discardActiveObject();
      cl.set({ left: cl.left + 18, top: cl.top + 18 });
      if (cl.type === 'activeSelection') {
        cl.canvas = canvas;
        cl.forEachObject(o => canvas.add(o));
        cl.setCoords();
      } else {
        canvas.add(cl);
      }
      state.suppress = false;
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
      state.suppress = true;
      canvas.discardActiveObject();
      cl.set({ left: cl.left + 14, top: cl.top + 14 });
      if (cl.type === 'activeSelection') {
        cl.canvas = canvas;
        cl.forEachObject(o => canvas.add(o));
        cl.setCoords();
      } else {
        canvas.add(cl);
      }
      state.suppress = false;
      canvas.setActiveObject(cl);
      canvas.requestRenderAll();
      pushHistory();
      setStatus('Duplicado');
    }, PROPS);   // conserva srType/srCat — sin esto el duplicado pierde su semántica
  }

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
    canvas.loadFromJSON(JSON.parse(str), () => {
      ensurePageBg();   // la hoja no viaja en el snapshot (excludeFromExport)
      fixupManualArrows();
      canvas.renderAll();
      state.loadingHistory = false;
    });
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
  async function doExport(modes) {
    closeExport();
    if (!modes || !modes.length) return;
    canvas.discardActiveObject();

    // (re)generar las rutas de los modos elegidos para que estén frescas
    modes.forEach(m => generate(m));
    // si hay leyenda, refrescarla para que refleje el contenido actual
    if (canvas.getObjects().some(o => o.srType === 'leyenda')) {
      try { await buildLegend(); } catch (e) { console.error('leyenda:', e); }
    }

    // esperar a que la fuente (Century Gothic / Jost) esté cargada antes de rasterizar,
    // si no el texto del PDF saldría con la fuente por defecto.
    setStatus('Generando PDF…');
    try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch (e) {}
    // render a escala real: dims del documento + viewport identidad
    const prevVpt = canvas.viewportTransform.slice();
    const prevW = canvas.getWidth(), prevH = canvas.getHeight();
    canvas.setDimensions({ width: DOC.w, height: DOC.h });
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
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
    canvas.setDimensions({ width: prevW, height: prevH });
    canvas.setViewportTransform(prevVpt);
    canvas.requestRenderAll();
    pdf.save((PLAN_NAME || 'plano') + '.pdf');
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
      else if (e.key === 'Escape') backToSelect();
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

  return {
    init, setTool, deleteSelected, undo, redo,
    zoomIn, zoomOut, zoomReset, toggleGrid, save,
    exportPDF, doExport, closeExport,
    generateEvac, generateSan, clearAll,
    setFont, setTextSize, toggleBold,
    duplicateSelected, setColor, setStrokeW, setOpacity, commitProps,
    bringFront, sendBack, setArrowKind, makeLegend,
  };
})();

function toggleSection(hd) { hd.parentElement.classList.toggle('collapsed'); }
