/* Check page, Batch tab (C13): paste or upload many items, see a summary, download the results. */
BG.ready(function () {
  'use strict';
  var MAX_BATCH = 100000, MAX_BYTES = 20 * 1024 * 1024, SHOWN = 100;
  var tabSingle = BG.$('#tab-single'), tabBatch = BG.$('#tab-batch');
  var panelSingle = BG.$('#panel-single'), panelBatch = BG.$('#panel-batch');
  var form = BG.$('#batch-form'), btn = BG.$('#batch-btn'), resultArea = BG.$('#batch-result');
  var textEl = BG.$('#b-text'), fileEl = BG.$('#b-file');
  var last = null;                         /* what was sent, so the CSV download can send it again */

  BG.fillSelect(BG.$('#b-type'), BG.KEY_TYPES);
  BG.$('#b-type').value = 'transaction_id';

  /* ---- tabs ------------------------------------------------------------------------- */
  function selectTab(which) {
    var batch = which === 'batch';
    tabSingle.setAttribute('aria-selected', batch ? 'false' : 'true');
    tabBatch.setAttribute('aria-selected', batch ? 'true' : 'false');
    tabSingle.tabIndex = batch ? -1 : 0;
    tabBatch.tabIndex = batch ? 0 : -1;
    panelSingle.hidden = batch;
    panelBatch.hidden = !batch;
  }
  tabSingle.addEventListener('click', function () { selectTab('single'); });
  tabBatch.addEventListener('click', function () { selectTab('batch'); });
  [tabSingle, tabBatch].forEach(function (t) {
    t.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Home' && e.key !== 'End') return;
      e.preventDefault();
      var toBatch = (t === tabSingle && (e.key === 'ArrowRight' || e.key === 'End')) || (t === tabBatch && e.key === 'End');
      selectTab(toBatch ? 'batch' : 'single');
      (toBatch ? tabBatch : tabSingle).focus();
    });
  });
  if (new URLSearchParams(window.location.search).get('tab') === 'batch') selectTab('batch');

  /* ---- source switch and live count ----------------------------------------------------- */
  function source() { return form.querySelector('input[name="source"]:checked').value; }
  function lines() {
    return textEl.value.split(/\r?\n/).filter(function (l) { return l.trim() !== ''; });
  }
  function updateCount() {
    var n = lines().length;
    var hint = BG.$('#b-count');
    hint.textContent = BG.fmtInt(n) + (n === 1 ? ' item' : ' items') + (n > MAX_BATCH ? '. That is over the limit of 100,000 per batch.' : '');
  }
  function showColumn() {
    var f = fileEl.files[0];
    BG.$('#column-field').hidden = !(source() === 'file' && f && /\.csv$/i.test(f.name));
  }
  BG.$$('input[name="source"]').forEach(function (r) {
    r.addEventListener('change', function () {
      var file = source() === 'file';
      BG.$('#paste-field').hidden = file;
      BG.$('#file-field').hidden = !file;
      showColumn();
    });
  });
  textEl.addEventListener('input', updateCount);
  fileEl.addEventListener('change', showColumn);
  updateCount();

  /* ---- results --------------------------------------------------------------------------- */
  function stat(label, value, good) {
    return BG.h('div', { class: 'stat' + (good ? ' stat--good' : '') },
      BG.h('div', { class: 'stat__label', text: label }), BG.h('div', { class: 'stat__value', text: BG.fmtInt(value) }));
  }

  function renderRows(tbody, results, verdict) {
    BG.clear(tbody);
    var shown = 0;
    for (var i = 0; i < results.length && shown < SHOWN; i++) {
      var r = results[i];
      if (verdict && r.verdict !== verdict) continue;
      shown++;
      tbody.appendChild(BG.h('tr', null,
        BG.h('td', { class: 'num', 'data-label': 'Row', text: String(r.row) }),
        BG.h('td', { class: 'cell-main', 'data-label': 'Item' }, BG.h('span', { class: 'key', title: r.item.length > 80 ? r.item : null, text: r.item === '' ? '(empty)' : (r.item.length > 80 ? r.item.slice(0, 80) + '...' : r.item) })),
        BG.h('td', { 'data-label': 'Verdict' }, BG.verdictBadge(r.verdict)),
        BG.h('td', { 'data-label': 'Label', text: r.label ? (BG.LABELS[r.label] || r.label) : '-' }),
        BG.h('td', { 'data-label': 'Note', text: r.note || '' })));
    }
    return shown;
  }

  function render(data) {
    var s = data.summary, bloomOnly = data.mode === 'bloom_only';
    var stats = [stat('Items checked', s.total), stat('Clean', s.clean, true)];
    if (bloomOnly) stats.push(stat('Possibly blacklisted', s.possibly_blacklisted));
    else stats.push(stat('Blacklisted', s.blacklisted), stat('False positives', s.false_positive));
    stats.push(stat('Invalid', s.invalid));

    var present = {};
    data.results.forEach(function (r) { present[r.verdict] = true; });
    var order = ['CLEAN', 'BLACKLISTED', 'FALSE_POSITIVE', 'POSSIBLY_BLACKLISTED', 'INVALID'].filter(function (v) { return present[v]; });
    var active = '';
    var tbody = BG.h('tbody');
    var foot = BG.h('div', { class: 'table-foot' });
    var chips = BG.h('div', { class: 'chips', role: 'group', 'aria-label': 'Filter results by verdict' });

    function refresh() {
      var total = active ? data.results.filter(function (r) { return r.verdict === active; }).length : data.results.length;
      var shown = renderRows(tbody, data.results, active);
      foot.textContent = total > shown
        ? 'Showing the first ' + BG.fmtInt(shown) + ' of ' + BG.fmtInt(total) + ' rows. Download the CSV to see them all.'
        : 'Showing all ' + BG.fmtInt(total) + (total === 1 ? ' row.' : ' rows.');
      BG.$$('.chip-btn', chips).forEach(function (c) { c.setAttribute('aria-pressed', c.dataset.v === active ? 'true' : 'false'); });
    }
    [''].concat(order).forEach(function (v) {
      chips.appendChild(BG.h('button', { class: 'chip-btn', type: 'button', 'data-v': v,
        text: v ? (BG.VERDICTS[v] ? BG.VERDICTS[v].text : v) : 'All', onclick: function () { active = v; refresh(); } }));
    });

    var dl = BG.h('button', { class: 'btn btn--secondary', type: 'button', onclick: function () { download(dl); } },
      BG.icon('upload', 'icon--sm'), 'Download CSV');
    dl.querySelector('svg').style.transform = 'rotate(180deg)';

    BG.clear(resultArea).appendChild(BG.h('div', { class: 'card card--flush' },
      BG.h('div', { style: 'padding:24px 24px 0' },
        BG.h('div', { class: 'card__head' },
          BG.h('div', null, BG.h('h2', { text: 'Batch results' }), BG.h('p', { text: 'Finished in ' + data.duration_s + ' s.' })),
          dl),
        BG.h('div', { class: 'summary' }, stats)),
      BG.h('div', { class: 'toolbar', style: 'margin-top:24px;border-top:1px solid var(--line)' }, chips),
      BG.h('div', { class: 'table-wrap' }, BG.h('table', { class: 'table--stack' },
        BG.h('thead', null, BG.h('tr', null,
          BG.h('th', { scope: 'col', class: 'num', text: 'Row' }), BG.h('th', { scope: 'col', text: 'Item' }),
          BG.h('th', { scope: 'col', text: 'Verdict' }), BG.h('th', { scope: 'col', text: 'Label' }), BG.h('th', { scope: 'col', text: 'Note' }))),
        tbody)),
      foot));
    refresh();
    resultArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function request(query) {
    if (last.kind === 'json') return { json: { items: last.items, key_type: last.key_type, mode: last.mode } };
    var fd = new FormData();
    fd.append('file', last.file, last.file.name);
    fd.append('key_type', last.key_type);
    fd.append('mode', last.mode);
    if (last.column) fd.append('column', last.column);
    return { form: fd };
  }

  function download(button) {
    if (!last) return;
    var opts = request();
    opts.method = 'POST';
    BG.setBusy(button, true);
    BG.download('/api/check/batch?format=csv', opts, 'bloomguard-batch-results.csv').then(function () {
      BG.setBusy(button, false);
      BG.toast('Results downloaded.', 'success');
    }, function (err) { BG.setBusy(button, false); BG.toast(BG.errorText(err), 'error'); });
  }

  /* ---- submit ------------------------------------------------------------------------------- */
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(form);
    BG.clear(BG.$('#batch-alert'));
    var keyType = form.elements.key_type.value;
    var mode = form.querySelector('input[name="bmode"]:checked').value;
    var req;
    if (source() === 'paste') {
      var items = lines();
      if (!items.length) { BG.fieldError(form, 'text', 'Enter at least one item.'); textEl.focus(); return; }
      if (items.length > MAX_BATCH) { BG.fieldError(form, 'text', 'A batch holds at most 100,000 items. Remove some, or split the list.'); return; }
      last = { kind: 'json', items: items, key_type: keyType, mode: mode };
    } else {
      var f = fileEl.files[0];
      if (!f) { BG.fieldError(form, 'file', 'Choose a .csv or .txt file first.'); return; }
      if (!/\.(csv|txt)$/i.test(f.name)) { BG.fieldError(form, 'file', 'Only .csv and .txt files are accepted.'); return; }
      if (f.size > MAX_BYTES) { BG.fieldError(form, 'file', 'That file is ' + BG.fmtBytes(f.size) + '. The limit is 20 MB.'); return; }
      last = { kind: 'file', file: f, key_type: keyType, mode: mode, column: /\.csv$/i.test(f.name) ? form.elements.column.value.trim() : '' };
    }
    req = request();
    req.method = 'POST';
    BG.setBusy(btn, true);
    BG.api('/api/check/batch', req).then(function (data) {
      BG.setBusy(btn, false);
      render(data);
    }, function (err) {
      BG.setBusy(btn, false);
      last = null;
      if (err.field && BG.fieldError(form, err.field === 'items' ? 'text' : err.field, err.message)) return;
      BG.$('#batch-alert').appendChild(BG.alert('danger', 'The batch was not checked.', BG.errorText(err)));
    });
  });
});
