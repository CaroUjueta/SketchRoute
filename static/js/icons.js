/* ============================================================
   SketchRoute — Biblioteca de iconos (fuente única de verdad)
   Estilo: señalética técnica plana (pictogramas sobrios). SVG 64×64.
   Se usa para: sidebar, objetos del canvas y export a PDF.
   ============================================================ */

const SR_ICONS = {

  /* ─── SEGURIDAD / EVACUACIÓN (señales ISO) ───────────────── */

  extintor: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect width="64" height="64" rx="2" fill="#b91c1c"/>
    <g fill="#ffffff">
      <rect x="26" y="23" width="13" height="28" rx="1"/>
      <rect x="29" y="15" width="4" height="8"/>
      <rect x="24" y="11" width="13" height="5" rx="1"/>
      <path d="M37 13 h7 v3 h-4 v4 h-3 z"/>
    </g>
    <rect x="29" y="31" width="7" height="10" fill="#b91c1c"/>
  </svg>`,

  botiquin: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect width="64" height="64" rx="2" fill="#15803d"/>
    <rect x="28" y="16" width="8" height="32" fill="#ffffff"/>
    <rect x="16" y="28" width="32" height="8" fill="#ffffff"/>
  </svg>`,

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

  /* ─── CANECAS (misma forma, color de código + símbolo) ───── */

  caneca_ordinaria: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="15" y="15" width="34" height="6" rx="1.5" fill="#0b0f1a"/>
    <rect x="27" y="11" width="10" height="4" rx="1" fill="#0b0f1a"/>
    <path d="M18 21 H46 L43 55 H21 Z" fill="#1f2937"/>
    <path d="M27 28 V49 M32 28 V49 M37 28 V49" stroke="#374151" stroke-width="2"/>
  </svg>`,

  caneca_reciclable: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="15" y="15" width="34" height="6" rx="1.5" fill="#d1d5db" stroke="#9ca3af" stroke-width="1"/>
    <rect x="27" y="11" width="10" height="4" rx="1" fill="#d1d5db" stroke="#9ca3af" stroke-width="1"/>
    <path d="M18 21 H46 L43 55 H21 Z" fill="#f8fafc" stroke="#9ca3af" stroke-width="1.4"/>
    <g fill="none" stroke="#15803d" stroke-width="2.3" stroke-linecap="round">
      <path d="M26 32 A8 8 0 0 1 39 34"/>
      <path d="M40 44 A8 8 0 0 1 27 42"/>
    </g>
    <g fill="#15803d">
      <path d="M39 29 l2 5 l-5 -1 z"/>
      <path d="M27 47 l-2 -5 l5 1 z"/>
    </g>
  </svg>`,

  caneca_biosani: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="15" y="15" width="34" height="6" rx="1.5" fill="#991b1b"/>
    <rect x="27" y="11" width="10" height="4" rx="1" fill="#991b1b"/>
    <path d="M18 21 H46 L43 55 H21 Z" fill="#dc2626"/>
    <g fill="none" stroke="#ffffff" stroke-width="2.1">
      <circle cx="32" cy="33" r="4"/>
      <circle cx="27.5" cy="42" r="4"/>
      <circle cx="36.5" cy="42" r="4"/>
    </g>
    <circle cx="32" cy="39" r="2" fill="#ffffff"/>
  </svg>`,

  caneca_corto: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="15" y="15" width="34" height="6" rx="1.5" fill="#991b1b"/>
    <rect x="27" y="11" width="10" height="4" rx="1" fill="#991b1b"/>
    <path d="M18 21 H46 L43 55 H21 Z" fill="#dc2626"/>
    <g fill="none" stroke="#ffffff" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round">
      <path d="M32 29 L41 45 H23 Z"/>
    </g>
    <line x1="32" y1="35" x2="32" y2="40" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round"/>
    <circle cx="32" cy="43" r="1.4" fill="#ffffff"/>
  </svg>`,

  /* ─── ESTRUCTURA (planta técnica) ────────────────────────── */

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

  entrada_salida: `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="13" y="10" width="38" height="44" rx="2" fill="none" stroke="#475467" stroke-width="2.4"/>
    <rect x="13" y="10" width="19" height="44" rx="1" fill="#eef2f7" stroke="#475467" stroke-width="2"/>
    <circle cx="28" cy="32" r="1.8" fill="#475467"/>
    <path d="M51 32 H40 M44 27 l-4 5 l4 5" stroke="#16a34a" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`,
};

// Inyecta las vistas previas del sidebar (mismas SVG que van al canvas).
function paintSidebarIcons() {
  document.querySelectorAll('.ed-icon-preview[data-icon]').forEach(el => {
    const key = el.getAttribute('data-icon');
    if (SR_ICONS[key]) el.innerHTML = SR_ICONS[key];
  });
}
