/* ============================================================
   SketchRoute — Biblioteca de iconos.
   Los que tienen foto real se cargan como imágenes; el resto
   usan SVG planos (pictogramas). 64×64 en el canvas.
   Se usa para: sidebar, objetos del canvas y export a PDF.
   ============================================================ */

// Rutas de las imágenes reales para cada tipo de icono.
const ICON_IMG = {
  extintor:           '/static/img/fotos/extintor.jpeg',
  botiquin:           '/static/img/fotos/botiquin.jpeg',
  caneca_ordinaria:   '/static/img/fotos/caneca_ordinaria.jpeg',
  caneca_reciclable:  '/static/img/fotos/caneca_reciclable.jpeg',
  caneca_biosani:     '/static/img/fotos/caneca_biosani.jpeg',
  caneca_corto:       '/static/img/fotos/caneca_corto.jpg',
  logo_systefarma:    '/static/img/logo.png',
};

const SR_ICONS = {

  /* ─── FOTO REAL ──────────────────────────────────────────── */
  // El valor 'img' indica que se carga desde ICON_IMG.

  extintor: 'img',
  botiquin: 'img',
  caneca_ordinaria: 'img',
  caneca_reciclable: 'img',
  caneca_biosani: 'img',
  caneca_corto: 'img',
  logo_systefarma: 'img',

  /* ─── FLECHAS MANUALES (iguales a las generadas, por color) ─────
     Preview = línea + triángulo en el color de ruta. El objeto real del
     canvas lo arma makeArrowShape() (ver ARROW_TYPES en canvas.js). */

  flecha_evac:  `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <line x1="8" y1="32" x2="44" y2="32" stroke="#16a34a" stroke-width="6" stroke-linecap="round"/>
    <polygon points="58,32 42,41 42,23" fill="#16a34a"/>
  </svg>`,

  flecha_negra: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <line x1="8" y1="32" x2="44" y2="32" stroke="#111827" stroke-width="6" stroke-linecap="round"/>
    <polygon points="58,32 42,41 42,23" fill="#111827"/>
  </svg>`,

  flecha_gris:  `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <line x1="8" y1="32" x2="44" y2="32" stroke="#111827" stroke-width="8" stroke-linecap="round"/>
    <line x1="8" y1="32" x2="44" y2="32" stroke="#ffffff" stroke-width="4" stroke-linecap="round"/>
    <polygon points="58,32 42,41 42,23" fill="#ffffff" stroke="#111827" stroke-width="2"/>
  </svg>`,

  flecha_roja:  `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <line x1="8" y1="32" x2="44" y2="32" stroke="#dc2626" stroke-width="6" stroke-linecap="round"/>
    <polygon points="58,32 42,41 42,23" fill="#dc2626"/>
  </svg>`,

  /* ─── SVG PLANO (sin foto aún) ───────────────────────────── */

  punto_encuentro: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect width="64" height="64" rx="2" fill="#15803d"/>
    <g fill="#ffffff">
      <path d="M6 6 h12 l-12 12 z"/>
      <path d="M58 6 h-12 l12 12 z"/>
      <path d="M6 58 h12 l-12 -12 z"/>
      <path d="M58 58 h-12 l12 -12 z"/>
    </g>
    <g fill="#ffffff">
      <circle cx="32" cy="26" r="3.6"/><rect x="28.2" y="31" width="7.6" height="13" rx="2"/>
      <circle cx="22" cy="30" r="3"/><rect x="18.8" y="34" width="6.4" height="11" rx="2"/>
      <circle cx="42" cy="30" r="3"/><rect x="38.8" y="34" width="6.4" height="11" rx="2"/>
    </g>
  </svg>`,

  salida_emergencia: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect width="64" height="64" rx="2" fill="#15803d"/>
    <rect x="42" y="14" width="11" height="34" fill="none" stroke="#ffffff" stroke-width="3"/>
    <g fill="#ffffff">
      <circle cx="18" cy="16" r="4"/>
      <path d="M10 28 l8 -2 l5 4 l7 -3 l1.6 3.6 l-8 3.4 l-4 -2 l-2 5 l5 4 l-2.4 9 l-3.8 -1 l2 -7 l-6 -4 z"/>
    </g>
    <path d="M30 42 h11 M36 36 l6 6 l-6 6" stroke="#ffffff" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`,

  camilla: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="10" y="20" width="44" height="24" rx="4" fill="#eef2f7" stroke="#475467" stroke-width="2"/>
    <rect x="13" y="23" width="10" height="18" rx="2" fill="#cbd5e1"/>
    <line x1="26" y1="20" x2="26" y2="44" stroke="#94a3b8" stroke-width="1.3"/>
    <line x1="10" y1="32" x2="54" y2="32" stroke="#94a3b8" stroke-width="1.3"/>
    <line x1="16" y1="44" x2="16" y2="48" stroke="#475467" stroke-width="2"/>
    <line x1="48" y1="44" x2="48" y2="48" stroke="#475467" stroke-width="2"/>
    <circle cx="16" cy="50" r="2.6" fill="#475467"/>
    <circle cx="48" cy="50" r="2.6" fill="#475467"/>
  </svg>`,

  bano: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="22" y="12" width="20" height="9" rx="2" fill="#eef2f7" stroke="#475467" stroke-width="2"/>
    <path d="M24 22 H40 a3 3 0 0 1 3 3 c0 9 -4 17 -11 17 c-7 0 -11 -8 -11 -17 a3 3 0 0 1 3 -3 z"
          fill="#f8fafc" stroke="#475467" stroke-width="2"/>
    <ellipse cx="32" cy="30" rx="6.5" ry="7.5" fill="#dbe3ee"/>
  </svg>`,

  lavamanos: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <path d="M14 26 H50 a2 2 0 0 1 2 2 c0 12 -8 20 -18 20 c-10 0 -18 -8 -18 -20 a2 2 0 0 1 2 -2 z"
          fill="#f8fafc" stroke="#475467" stroke-width="2"/>
    <ellipse cx="32" cy="27" rx="18" ry="4" fill="#eef2f7" stroke="#475467" stroke-width="2"/>
    <ellipse cx="32" cy="34" rx="9" ry="4" fill="#dbe3ee"/>
    <line x1="27" y1="14" x2="37" y2="14" stroke="#475467" stroke-width="2.4" stroke-linecap="round"/>
    <line x1="32" y1="14" x2="32" y2="18" stroke="#475467" stroke-width="2.4" stroke-linecap="round"/>
    <circle cx="32" cy="12" r="1.8" fill="#475467"/>
  </svg>`,

  entrada_salida: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="13" y="10" width="38" height="44" rx="2" fill="none" stroke="#475467" stroke-width="2.4"/>
    <rect x="13" y="10" width="19" height="44" rx="1" fill="#eef2f7" stroke="#475467" stroke-width="2"/>
    <circle cx="28" cy="32" r="1.8" fill="#475467"/>
    <path d="M51 32 H40 M44 27 l-4 5 l4 5" stroke="#16a34a" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`,

  norte: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <circle cx="32" cy="34" r="22" fill="#ffffff" stroke="#475467" stroke-width="2.4"/>
    <path d="M32 16 L38 40 L32 34 L26 40 Z" fill="#dc2626" stroke="#111827" stroke-width="1.4" stroke-linejoin="round"/>
    <text x="32" y="12" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="bold" fill="#111827">N</text>
  </svg>`,
};

// Inyecta las vistas previas del sidebar.
function paintSidebarIcons() {
  document.querySelectorAll('.ed-icon-preview[data-icon]').forEach(el => {
    const key = el.getAttribute('data-icon');
    const val = SR_ICONS[key];
    if (!val) return;
    if (val === 'img') {
      el.innerHTML = `<img src="${ICON_IMG[key]}" alt="${key}" style="width:100%;height:100%;object-fit:contain;">`;
    } else {
      el.innerHTML = val;
    }
  });
}
