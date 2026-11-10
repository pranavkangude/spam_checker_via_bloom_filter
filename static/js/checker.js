/* Check page: one item, verdict, and where it lands in the filter. */
BG.ready(function () {
  'use strict';
  var form = BG.$('#check-form');
  var btn = BG.$('#check-btn');
  var area = BG.$('#result-area');
  var recent = BG.$('#recent');
  var CELLS = 128;
  var filterInfo = null;

  BG.fillSelect(BG.$('#c-type'), BG.KEY_TYPES);
  BG.$('#c-type').value = 'transaction_id';

  BG.$$('input[name="mode"]').forEach(function (r) {
    r.addEventListener('change', function () {
      BG.$('#mode-hint').textContent = form.elements.mode.value === 'bloom_only'
        ? 'Fast but not exact: a hit means "possibly blacklisted" and is not confirmed.'
        : 'Exact answer: the database confirms every hit.';
    });
  });

  BG.getFilter().then(function (f) { filterInfo = f; }, function () { /* the chip shows the problem */ });

  var COPY = {
    CLEAN: ['Clean', 'This item is not on the blacklist. At least one of its positions in the filter is switched off, which proves it was never added.'],
    BLACKLISTED: ['Blacklisted', 'This item is on the blacklist. The filter flagged it and the database confirmed it.'],
    FALSE_POSITIVE: ['False positive', 'This item is not on the blacklist. The filter said it might be, because its positions were all switched on by other items, and the database check corrected it.'],
    POSSIBLY_BLACKLISTED: ['Possibly blacklisted', 'The filter says this item might be on the blacklist. Filter-only mode does not check the database, so this is not confirmed.']
  };

  function stat(label, value) {
    return BG.h('div', { class: 'stat' }, BG.h('div', { class: 'stat__label', text: label }), BG.h('div', { class: 'stat__value', text: value }));
  }
  function bloomText(r) { return r === 'PROBABLE' ? 'Probably present' : r === 'ABSENT' ? 'Definitely absent' : String(r); }
  function exactText(r) { return r === 'FOUND' ? 'Found' : r === 'NOT_FOUND' ? 'Not found' : r === 'SKIPPED' ? 'Not checked' : r === null || r === undefined ? 'Not checked' : String(r); }

  function renderResult(r) {
    var d = BG.VERDICTS[r.verdict] || { cls: '', icon: 'info', text: r.verdict };
    var copy = COPY[r.verdict] || [d.text, ''];
    var children = [
      BG.h('div', { class: 'verdict verdict--' + d.cls },
        BG.h('div', { class: 'verdict__icon' }, BG.icon(d.icon)),
        BG.h('div', { class: 'grow' },
          BG.h('h2', { text: copy[0] }),
          BG.h('p', { text: copy[1] }),
          BG.h('span', { class: 'result-key', title: 'The cleaned form the server compared', text: r.item_key })))
    ];

    /* Where the item lands in the filter */
    if (filterInfo && Array.isArray(r.indexes) && r.indexes.length) {
      var cells = {}, titles = {};
      r.indexes.forEach(function (idx) {
        var cell = Math.min(CELLS - 1, Math.floor(idx * CELLS / filterInfo.m_bits));
        cells[cell] = true;
        titles[cell] = (titles[cell] ? titles[cell] + ', ' : 'bit ') + BG.fmtInt(idx);
      });
      children.push(BG.h('div', { style: 'margin-top:24px' },
        BG.bitGrid(CELLS, Object.keys(cells).map(Number), { probe: true, titles: titles }),
        BG.h('p', { class: 'bits-caption', text: 'The ' + r.k + ' positions this item maps to, drawn on a ' + CELLS + '-square view of the whole filter. ' + r.bits_set + ' of ' + r.k + ' are switched on.' })));
    }

    children.push(BG.h('div', { class: 'result-grid' },
      stat('Filter says', bloomText(r.bloom_result)),
      stat('Database says', exactText(r.exact_result)),
      stat('Label', r.label ? (BG.LABELS[r.label] || r.label) : 'None'),
      stat('Time taken', BG.fmtLatency(r.latency_us))));

    BG.clear(area).appendChild(BG.h('div', { class: 'card' }, children));
  }

  function renderRecent(items) {
    BG.clear(recent);
    if (!items.length) {
      recent.appendChild(BG.empty('clock', 'Nothing checked yet', 'Your last five checks will appear here.'));
      return;
    }
    recent.appendChild(BG.h('ul', { class: 'recent' }, items.map(function (x) {
      return BG.h('li', null, BG.h('span', { class: 'key', title: x.item_key, text: x.item_key }), BG.verdictBadge(x.verdict));
    })));
  }
  function loadRecent() {
    BG.api('/api/history?page_size=5').then(function (h) { renderRecent(h.items); }, function (e) {
      BG.clear(recent).appendChild(BG.alert('danger', 'Could not load recent checks.', BG.errorText(e)));
    });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(form);
    var item = form.elements.namedItem('item').value.trim();
    if (!item) { BG.fieldError(form, 'item', 'Enter an item to check.'); form.elements.namedItem('item').focus(); return; }
    BG.setBusy(btn, true);
    BG.api('/api/check', { method: 'POST', json: { item: item, key_type: form.elements.key_type.value, mode: form.elements.mode.value } })
      .then(function (r) {
        BG.setBusy(btn, false);
        renderResult(r);
        loadRecent();
        BG.getFilter(true).then(function (f) { filterInfo = f; }, function () {});
      }, function (err) {
        BG.setBusy(btn, false);
        if (err.field && BG.fieldError(form, err.field, err.message)) return;
        BG.clear(area).appendChild(BG.alert('danger', 'Could not check that item.', BG.errorText(err)));
      });
  });

  loadRecent();
});
