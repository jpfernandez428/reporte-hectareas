// Menu fijo comun a todas las paginas (pedido del usuario 26-oct-2026):
// Operacion · Ayer · Flota (GPS) · Historial · Ajustes, con la pagina actual
// destacada. La pagina antigua reporte.html NO va en el menu (la
// usa el correo diario actual). Todas las direcciones quedan dentro de la app
// (mismo sitio), asi que en el celular no se sale de la app.
(function () {
  // Reorganizacion (26-oct-2026): una sola app con 5 secciones. Mientras se
  // construyen por etapas, Ayer, Flota, Historial y Ajustes llevan a las
  // paginas actuales (reporte2.html e index.html).
  const ITEMS = [
    { id: 'operacion', texto: 'Operación', href: 'app.html#operacion' },
    { id: 'ayer', texto: 'Ayer', href: 'reporte2.html' },
    { id: 'flota', texto: 'Flota (GPS)', href: 'index.html#flota' },
    { id: 'historial', texto: 'Historial', href: 'index.html' },
    { id: 'ajustes', texto: 'Ajustes', href: 'reporte2.html#equivalencias' },
  ];
  const pagina = () => (location.pathname.split('/').pop() || 'index.html');
  function actual() {
    const p = pagina(), h = location.hash;
    if (p === 'app.html' || p === 'operacion.html') return 'operacion';
    if (p === 'reporte2.html') return h === '#equivalencias' ? 'ajustes' : 'ayer';
    if (p === 'index.html') return h === '#flota' ? 'flota' : 'historial';
    return '';
  }
  function marcar() {
    const a = actual();
    document.querySelectorAll('.menu-global a').forEach(x => x.classList.toggle('actual', x.dataset.id === a));
    const sel = document.querySelector('.menu-global a.actual');
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  function medir() {
    const m = document.querySelector('.menu-global');
    if (!m) return;
    // De borde a borde aunque la pagina tenga margenes propios (index.html).
    m.style.marginLeft = '0px'; m.style.width = '';
    const izq = m.getBoundingClientRect().left, ancho = document.documentElement.clientWidth;
    m.style.boxSizing = 'border-box';
    m.style.width = ancho + 'px';
    m.style.marginLeft = (-izq) + 'px';
    m.style.marginTop = (-(parseFloat(getComputedStyle(document.body).paddingTop) || 0) - (parseFloat(getComputedStyle(document.body).marginTop) || 0)) + 'px';
    document.documentElement.style.setProperty('--alto-menu', m.offsetHeight + 'px');
  }
  window.menuActualizar = marcar;

  const estilo = document.createElement('style');
  estilo.textContent = `
    .menu-global { position: sticky; top: 0; z-index: 30; display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none;
      background: #1f4d2b; padding: calc(7px + env(safe-area-inset-top)) max(10px, env(safe-area-inset-right)) 7px max(10px, env(safe-area-inset-left));
      font-family: -apple-system, Arial, sans-serif; box-shadow: 0 1px 3px rgba(0,0,0,.2); }
    .menu-global::-webkit-scrollbar { display: none; }
    .menu-global a { flex: none; color: #fff; text-decoration: none; font-weight: 600; font-size: 13px; line-height: 1;
      padding: 8px 12px; border-radius: 999px; background: rgba(255,255,255,.1); white-space: nowrap; }
    .menu-global a.actual { background: #fff; color: #1f4d2b; }
    /* Celular: las 5 opciones caben en una linea, repartidas en el ancho. */
    @media (max-width: 520px) {
      .menu-global { gap: 4px; padding-left: max(6px, env(safe-area-inset-left)); padding-right: max(6px, env(safe-area-inset-right)); }
      .menu-global a { flex: 1 1 auto; text-align: center; font-size: 12px; padding: 8px 4px; letter-spacing: -.01em; }
    }
    @media (max-width: 350px) { .menu-global { gap: 3px; } .menu-global a { font-size: 10.5px; padding: 7px 2px; letter-spacing: -.02em; } }`;
  document.head.appendChild(estilo);

  function poner() {
    const nav = document.createElement('nav');
    nav.className = 'menu-global';
    nav.setAttribute('aria-label', 'Páginas');
    nav.innerHTML = ITEMS.map(i => `<a href="${i.href}" data-id="${i.id}">${i.texto}</a>`).join('');
    document.body.insertBefore(nav, document.body.firstChild);
    // En la misma pagina se cambia de vista sin recargar.
    nav.addEventListener('click', ev => {
      const a = ev.target.closest('a');
      if (!a) return;
      const destino = a.getAttribute('href').split('#'), mismaPagina = destino[0] === pagina();
      if (!mismaPagina) return;
      ev.preventDefault();
      if (pagina() === 'index.html' && typeof window.mostrarVista === 'function') {
        window.mostrarVista(destino[1] === 'flota' ? 'flota' : 'reporte');
      } else if (destino[1]) {
        const el = document.getElementById(destino[1]);
        history.replaceState(null, '', '#' + destino[1]);
        if (el) el.scrollIntoView();
      } else {
        history.replaceState(null, '', location.pathname);
        window.scrollTo(0, 0);
      }
      marcar();
    });
    marcar(); medir();
    window.addEventListener('resize', medir);
    window.addEventListener('hashchange', marcar);
  }
  if (document.body) poner(); else document.addEventListener('DOMContentLoaded', poner);
})();
