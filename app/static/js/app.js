/* Gedeeld JavaScript voor alle ingelogde pagina's (ACT-48). */
function toggleTheme() {
    var html = document.documentElement;
    var current = html.getAttribute('data-theme') || 'light';
    var next = current === 'light' ? 'dark' : 'light';
    html.setAttribute('data-theme', next);
    localStorage.setItem('ctp-theme', next);
    updateThemeIcon(next);
}
function updateThemeIcon(theme) {
    var btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.textContent = theme === 'dark' ? '☀' : '🌙';
}
document.addEventListener('DOMContentLoaded', function() {
    updateThemeIcon(document.documentElement.getAttribute('data-theme') || 'light');
});

document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('nav-hamburger-btn');
    var drawer = document.getElementById('mobile-drawer');
    if (!btn || !drawer) return;
    function setOpen(open) {
        drawer.classList.toggle('open', open);
        btn.classList.toggle('is-active', open);
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
        document.body.classList.toggle('nav-drawer-open', open);
        if (!open) btn.focus();
    }
    btn.addEventListener('click', function() { setOpen(!drawer.classList.contains('open')); });
    drawer.querySelectorAll('[data-drawer-close]').forEach(function(el) {
        el.addEventListener('click', function() { setOpen(false); });
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && drawer.classList.contains('open')) setOpen(false);
    });
});

/* Bedrag in nl-NL notatie: "€ 1.234,50"; negatief met minteken alleen bij signed. */
function formatEuro(val, signed) {
    var n = Number(val) || 0;
    var s = Math.abs(n).toLocaleString('nl-NL', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    return '\u20AC\u00A0' + (signed && n < 0 ? '-' : '') + s;
}

function escapeHtml(str) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
}

/* Klap een bewerk-element open/dicht; `shown` is de display-waarde als het zichtbaar is. */
function toggleEdit(id, shown) {
    var el = document.getElementById(id);
    if (!el) return;
    el.style.display = el.style.display === 'none' ? (shown || '') : 'none';
}

/* fetch + JSON met één uniforme foutmelding (gooit Error met leesbare tekst). */
async function fetchJson(url, options) {
    var resp;
    try {
        resp = await fetch(url, options);
    } catch (e) {
        throw new Error('Netwerkfout: probeer het opnieuw.');
    }
    var data = null;
    try { data = await resp.json(); } catch (e) { /* geen JSON */ }
    if (!resp.ok) {
        throw new Error((data && (data.detail || data.error)) || 'Er ging iets mis (' + resp.status + ').');
    }
    return data;
}
