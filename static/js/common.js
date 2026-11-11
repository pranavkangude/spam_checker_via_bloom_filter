/* BloomGuard shared helpers (Member C).
   Exposes one global, BG. All dynamic text goes in through textContent / createTextNode,
   never innerHTML, because blacklist entries are arbitrary user text. */
(function () {
  'use strict';
  var BG = (window.BG = {});

  /* ---- tiny DOM helpers ------------------------------------------------- */
  BG.$ = function (sel, root) { return (root || document).querySelector(sel); };
  BG.$$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  BG.h = function (tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2), v);
        else if (v === true) el.setAttribute(k, '');
        else el.setAttribute(k, String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  };
  function append(el, kid) {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { append(el, k); }); return; }
    el.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  BG.clear = function (el) { while (el.firstChild) el.removeChild(el.firstChild); return el; };

  BG.icon = function (name, cls) {
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon' + (cls ? ' ' + cls : ''));
    svg.setAttribute('aria-hidden', 'true');
    var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-' + name);
    svg.appendChild(use);
    return svg;
  };

  BG.ready = function (fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  };

  /* ---- formatting -------------------------------------------------------- */
  BG.fmtInt = function (n) { return (typeof n === 'number' && isFinite(n)) ? n.toLocaleString('en-US') : '-'; };
  BG.fmtBytes = function (n) {
    if (typeof n !== 'number' || !isFinite(n)) return '-';
    if (n < 1024) return Math.round(n) + ' B';
    var units = ['KB', 'MB', 'GB', 'TB'], i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < units.length - 1);
    return (n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2)) + ' ' + units[i];
  };
  /* fraction (0.01) -> "1.00%". Tiny values read "<0.01%". */
  BG.fmtPct = function (frac) {
    if (typeof frac !== 'number' || !isFinite(frac)) return '-';
    var p = frac * 100;
    if (p === 0) return '0%';
    if (p < 0.01) return '<0.01%';
    if (p >= 10) return p.toFixed(1) + '%';
    return p.toFixed(2) + '%';
  };
  BG.fmtLatency = function (us) {
    if (typeof us !== 'number') return '-';
    return us < 1000 ? us + ' µs' : (us / 1000).toFixed(2) + ' ms';
  };
  /* "2026-11-09 15:07:12" (UTC from SQLite) -> local date and time */
  BG.fmtDate = function (s) {
    if (!s) return '-';
    var d = new Date(String(s).replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return String(s);
    return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  };
  BG.debounce = function (fn, ms) {
    var t;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  };

  BG.KEY_TYPES = {
    transaction_id: 'Transaction ID', email: 'Email', url: 'URL', ip: 'IP address', phone: 'Phone number', other: 'Other'
  };
  BG.LABELS = { fraud: 'Fraud', spam: 'Spam', phishing: 'Phishing', other: 'Other' };
  BG.VERDICTS = {
    CLEAN: { text: 'Clean', cls: 'clean', icon: 'check-circle' },
    BLACKLISTED: { text: 'Blacklisted', cls: 'blacklisted', icon: 'x-circle' },
    FALSE_POSITIVE: { text: 'False positive', cls: 'fp', icon: 'alert' },
    POSSIBLY_BLACKLISTED: { text: 'Possibly blacklisted', cls: 'possible', icon: 'alert' },
    INVALID: { text: 'Invalid', cls: 'invalid', icon: 'x-circle' }
  };
  BG.verdictBadge = function (v) {
    var d = BG.VERDICTS[v] || { text: String(v), cls: '', icon: 'info' };
    return BG.h('span', { class: 'badge badge--' + d.cls }, BG.icon(d.icon), d.text);
  };
  BG.fillSelect = function (select, map, firstOption) {
    BG.clear(select);
    if (firstOption) select.appendChild(BG.h('option', { value: '', text: firstOption }));
    Object.keys(map).forEach(function (k) { select.appendChild(BG.h('option', { value: k, text: map[k] })); });
  };

  /* ---- API ---------------------------------------------------------------- */
  function ApiError(status, code, message, field, requestId) {
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.message = message;
    this.field = field || null;
    this.requestId = requestId || null;
  }
  ApiError.prototype = Object.create(Error.prototype);
  BG.ApiError = ApiError;

  /* opts: { method, json, form }. Resolves with parsed JSON (or null for 204). */
  BG.api = function (path, opts) {
    opts = opts || {};
    var init = { method: opts.method || 'GET', headers: { Accept: 'application/json' } };
    if (opts.json !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.json);
    } else if (opts.form) {
      init.body = opts.form;
    }
    return fetch(path, init).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (res.ok) return res.status === 204 ? null : data;
        var err = data && data.error ? data.error : {};
        var msg = err.message;
        if (!msg) {
          msg = res.status >= 500 ? 'The server hit a problem.' : 'The request failed (' + res.status + ').';
        }
        throw new ApiError(res.status, err.code || 'HTTP_' + res.status, msg, err.field, err.request_id);
      });
    }, function () {
      throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Check that it is running, then try again.');
    });
  };

  /* Save a response as a file (used for CSV downloads). opts as for BG.api. */
  BG.download = function (path, opts, fallbackName) {
    opts = opts || {};
    var init = { method: opts.method || 'GET', headers: {} };
    if (opts.json !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.json); }
    else if (opts.form) init.body = opts.form;
    return fetch(path, init).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (text) {
          var data = null;
          try { data = JSON.parse(text); } catch (e) { data = null; }
          var err = data && data.error ? data.error : {};
          throw new ApiError(res.status, err.code || 'HTTP_' + res.status, err.message || 'The download failed (' + res.status + ').', err.field, err.request_id);
        });
      }
      var name = fallbackName || 'download';
      var m = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') || '');
      if (m) name = m[1];
      return res.blob().then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      });
    }, function () {
      throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Check that it is running, then try again.');
    });
  };

  /* A sentence the user can act on, for any error. */
  BG.errorText = function (e) {
    if (!(e instanceof ApiError)) return 'Something unexpected happened. Reload the page and try again.';
    if (e.code === 'DATABASE_BUSY') return 'The database is busy. Try again in a moment.';
    if (e.code === 'INTERNAL_ERROR') return 'Something went wrong on the server' + (e.requestId ? ' (reference ' + e.requestId + ')' : '') + '. Try again.';
    return e.message;
  };

  /* ---- toasts --------------------------------------------------------------- */
  BG.toast = function (message, type, ms) {
    type = type || 'info';
    var box = BG.$('#toasts');
    if (!box) return;
    var iconName = type === 'success' ? 'check-circle' : type === 'error' ? 'x-circle' : 'info';
    var node = BG.h('div', { class: 'toast toast--' + type, role: type === 'error' ? 'alert' : 'status' },
      BG.icon(iconName),
      BG.h('div', { class: 'toast__text', text: message }),
      BG.h('button', { class: 'toast__close', type: 'button', 'aria-label': 'Dismiss', onclick: function () { remove(); } }, BG.icon('x', 'icon--sm'))
    );
    var timer;
    function remove() {
      clearTimeout(timer);
      node.classList.add('is-leaving');
      setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 200);
    }
    box.appendChild(node);
    while (box.children.length > 4) box.removeChild(box.firstChild);
    timer = setTimeout(remove, ms || (type === 'error' ? 7000 : 4500));
  };

  /* A message that survives one page change (for "Filter created" after a redirect). */
  BG.flash = function (message, type) {
    try { sessionStorage.setItem('bg-flash', JSON.stringify({ message: message, type: type || 'success' })); } catch (e) { /* storage blocked */ }
  };
  function showFlash() {
    try {
      var raw = sessionStorage.getItem('bg-flash');
      if (!raw) return;
      sessionStorage.removeItem('bg-flash');
      var f = JSON.parse(raw);
      BG.toast(f.message, f.type);
    } catch (e) { /* ignore */ }
  }

  /* ---- confirm dialog ------------------------------------------------------- */
  /* opts: { title, message, confirmText, tone: 'danger'|'primary', typeToConfirm: 'RESET' } -> Promise<boolean> */
  BG.confirm = function (opts) {
    return new Promise(function (resolve) {
      var dlg = BG.h('dialog', { class: 'modal', 'aria-labelledby': 'dlg-title' });
      var input = null, okBtn;
      var tone = opts.tone === 'danger' ? 'btn--danger' : 'btn--primary';
      var body = BG.h('div', { class: 'modal__body' },
        BG.h('h2', { id: 'dlg-title', text: opts.title }),
        BG.h('p', { text: opts.message })
      );
      if (opts.typeToConfirm) {
        input = BG.h('input', { class: 'input input--mono', type: 'text', autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Type ' + opts.typeToConfirm + ' to confirm' });
        body.appendChild(BG.h('div', { class: 'field' },
          BG.h('label', { class: 'hint' }, 'Type ', BG.h('b', { text: opts.typeToConfirm }), ' to confirm'), input));
      }
      var cancel = BG.h('button', { class: 'btn btn--secondary', type: 'button', text: 'Cancel', onclick: function () { dlg.close('cancel'); } });
      okBtn = BG.h('button', { class: 'btn ' + tone, type: 'button', text: opts.confirmText || 'Confirm', onclick: function () { dlg.close('ok'); } });
      if (input) {
        okBtn.disabled = true;
        input.addEventListener('input', function () { okBtn.disabled = input.value.trim() !== opts.typeToConfirm; });
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !okBtn.disabled) { e.preventDefault(); dlg.close('ok'); } });
      }
      dlg.appendChild(body);
      dlg.appendChild(BG.h('div', { class: 'modal__foot' }, cancel, okBtn));
      dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close('cancel'); });
      dlg.addEventListener('close', function () {
        var ok = dlg.returnValue === 'ok';
        if (dlg.parentNode) dlg.parentNode.removeChild(dlg);
        resolve(ok);
      });
      document.body.appendChild(dlg);
      dlg.showModal();
      (input || cancel).focus();
    });
  };

  /* ---- forms ------------------------------------------------------------------ */
  BG.setBusy = function (btn, on) {
    if (!btn) return;
    btn.classList.toggle('is-busy', !!on);
    btn.disabled = !!on;
    btn.setAttribute('aria-busy', on ? 'true' : 'false');
  };
  /* Show an error under the field with the given input name/id; returns true if a field matched. */
  BG.fieldError = function (form, name, message) {
    var input = form.querySelector('[name="' + name + '"]');
    if (!input) return false;
    var field = input.closest('.field');
    if (!field) return false;
    field.classList.add('has-error');
    var err = field.querySelector('.error');
    if (!err) { err = BG.h('div', { class: 'error', role: 'alert' }); field.appendChild(err); }
    err.textContent = message;
    input.setAttribute('aria-invalid', 'true');
    return true;
  };
  BG.clearErrors = function (form) {
    BG.$$('.field.has-error', form).forEach(function (f) { f.classList.remove('has-error'); });
    BG.$$('[aria-invalid]', form).forEach(function (i) { i.removeAttribute('aria-invalid'); });
  };
  /* Parse "1,000,000" / "1 000" into an integer, or null. */
  BG.parseIntLoose = function (s) {
    var t = String(s).replace(/[,_\s]/g, '');
    return /^\d+$/.test(t) ? parseInt(t, 10) : null;
  };
  /* Percent text ("1", "0.5") -> fraction (0.01, 0.005), or null. */
  BG.parsePercent = function (s) {
    var t = String(s).trim().replace('%', '');
    if (!/^\d*\.?\d+$/.test(t) && !/^\d+\.$/.test(t)) return null;
    var v = Number(t);
    return isFinite(v) ? Number((v / 100).toPrecision(12)) : null;
  };

  /* ---- alerts and empty states --------------------------------------------------- */
  BG.alert = function (type, title, text, dismissible) {
    var iconName = type === 'success' ? 'check-circle' : type === 'danger' ? 'x-circle' : type === 'warning' ? 'alert' : 'info';
    var node = BG.h('div', { class: 'alert alert--' + type, role: type === 'danger' ? 'alert' : 'status' },
      BG.icon(iconName),
      BG.h('div', { class: 'alert__body' }, title ? BG.h('b', { text: title + (text ? ' ' : '') }) : null, text || null)
    );
    if (dismissible) {
      node.appendChild(BG.h('button', { class: 'alert__close', type: 'button', 'aria-label': 'Dismiss', onclick: function () { node.remove(); if (typeof dismissible === 'function') dismissible(); } }, BG.icon('x', 'icon--sm')));
    }
    return node;
  };
  BG.empty = function (iconName, title, text, action) {
    return BG.h('div', { class: 'empty' },
      BG.h('div', { class: 'empty__icon' }, BG.icon(iconName, 'icon--lg')),
      BG.h('h3', { text: title }),
      text ? BG.h('p', { text: text }) : null,
      action || null
    );
  };

  /* ---- the bit grid (signature element) -------------------------------------------- */
  /* cells: number of cells; on: array of cell indexes that are lit; opts.dark, opts.probe, opts.titles{cell:text} */
  BG.bitGrid = function (cells, on, opts) {
    opts = opts || {};
    var lit = {};
    on.forEach(function (i) { lit[i] = true; });
    var grid = BG.h('div', { class: 'bits' + (opts.dark ? ' bits--dark' : '') + (opts.probe ? ' bits--probe' : ''), 'aria-hidden': 'true' });
    for (var i = 0; i < cells; i++) {
      var cell = BG.h('span', { class: 'bit' + (lit[i] ? ' is-on' : '') });
      if (lit[i] && opts.titles && opts.titles[i]) cell.title = opts.titles[i];
      grid.appendChild(cell);
    }
    return grid;
  };
  /* Which cells to light for a fill ratio: spread across the grid like a real bit array, not a progress bar. */
  BG.fillCells = function (cells, ratio) {
    var count = Math.round(ratio * cells);
    if (ratio > 0 && count === 0) count = 1;
    if (count > cells) count = cells;
    var out = [], step = 53; /* coprime with 128, so every cell is visited once */
    for (var i = 0; i < count; i++) out.push((i * step) % cells);
    return out;
  };

  /* ---- active filter (cached) -------------------------------------------------------- */
  var filterPromise = null;
  BG.getFilter = function (force) {
    if (!filterPromise || force) filterPromise = BG.api('/api/filter');
    return filterPromise;
  };

  function updateChip(info) {
    var name = BG.$('#chip-name'), dot = BG.$('#chip-dot');
    if (!name || !dot) return;
    if (info) {
      name.textContent = info.name + ' (' + (info.type === 'counting' ? 'Counting' : 'Standard') + ')';
      dot.className = 'chip__dot' + (info.over_capacity ? ' is-warn' : '');
    } else {
      name.textContent = 'No filter';
      dot.className = 'chip__dot is-off';
    }
  }

  /* ---- navigation behaviour ------------------------------------------------------------ */
  function initNav() {
    var nav = BG.$('#nav');
    if (!nav) return;
    var toggle = BG.$('#nav-toggle'), btn = BG.$('#lab-btn'), menu = BG.$('#lab-menu');

    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    });
    function closeMenu() { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
    function openMenu() { menu.hidden = false; btn.setAttribute('aria-expanded', 'true'); }
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (menu.hidden) openMenu(); else closeMenu();
    });
    document.addEventListener('click', function (e) { if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) closeMenu(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !menu.hidden) { closeMenu(); btn.focus(); }
    });
    menu.addEventListener('focusout', function (e) { if (!menu.contains(e.relatedTarget) && e.relatedTarget !== btn) closeMenu(); });
  }

  BG.ready(function () {
    initNav();
    showFlash();
    if (BG.$('#filter-chip')) {
      BG.getFilter().then(updateChip, function () { updateChip(null); });
    }
  });
  BG.updateChip = updateChip;
})();
