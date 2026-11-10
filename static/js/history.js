/* History page: check log with verdict filter and paging. */
BG.ready(function () {
  'use strict';
  var listEl = BG.$('#list'), chipsEl = BG.$('#verdict-chips'), clearBtn = BG.$('#clear-btn');
  var PAGE_SIZE = 20;
  var state = { page: 1, verdict: '' };
  var reqId = 0;
  var OPTIONS = [['', 'All'], ['CLEAN', 'Clean'], ['BLACKLISTED', 'Blacklisted'], ['FALSE_POSITIVE', 'False positive'], ['POSSIBLY_BLACKLISTED', 'Possibly blacklisted']];

  function renderChips() {
    BG.clear(chipsEl);
    OPTIONS.forEach(function (o) {
      chipsEl.appendChild(BG.h('button', {
        class: 'chip-btn', type: 'button', text: o[1], 'aria-pressed': state.verdict === o[0] ? 'true' : 'false',
        onclick: function () { state.verdict = o[0]; state.page = 1; renderChips(); load(); }
      }));
    });
  }

  function bloomText(r) { return r === 'PROBABLE' ? 'Probably present' : r === 'ABSENT' ? 'Absent' : String(r); }
  function exactText(r) { return r === 'FOUND' ? 'Found' : r === 'NOT_FOUND' ? 'Not found' : (r === null || r === undefined || r === 'SKIPPED') ? 'Not checked' : String(r); }

  function render(data) {
    BG.clear(listEl);
    if (!data.items.length) {
      if (state.verdict) {
        listEl.appendChild(BG.empty('search', 'No checks with this verdict', 'Try a different filter.',
          BG.h('button', { class: 'btn btn--secondary', type: 'button', text: 'Show all', onclick: function () { state.verdict = ''; state.page = 1; renderChips(); load(); } })));
      } else {
        listEl.appendChild(BG.empty('clock', 'No checks yet', 'Run a check and it will be recorded here.',
          BG.h('a', { class: 'btn btn--primary', href: '/check', text: 'Check an item' })));
      }
      clearBtn.disabled = !state.verdict ? true : clearBtn.disabled;
      return;
    }
    clearBtn.disabled = false;
    var rows = data.items.map(function (r) {
      return BG.h('tr', null,
        BG.h('td', { class: 'cell-main', 'data-label': 'Item' }, BG.h('span', { class: 'key', text: r.item_key })),
        BG.h('td', { 'data-label': 'Verdict' }, BG.verdictBadge(r.verdict)),
        BG.h('td', { 'data-label': 'Type', text: BG.KEY_TYPES[r.key_type] || r.key_type }),
        BG.h('td', { 'data-label': 'Mode', text: r.mode === 'bloom_only' ? 'Filter only' : 'Filter and database' }),
        BG.h('td', { 'data-label': 'Filter', text: bloomText(r.bloom_result) }),
        BG.h('td', { 'data-label': 'Database', text: exactText(r.exact_result) }),
        BG.h('td', { class: 'num', 'data-label': 'Time taken', text: BG.fmtLatency(r.latency_us) }),
        BG.h('td', { 'data-label': 'Checked', text: BG.fmtDate(r.checked_at) }));
    });
    listEl.appendChild(BG.h('div', { class: 'table-wrap' }, BG.h('table', { class: 'table--stack' },
      BG.h('thead', null, BG.h('tr', null,
        ['Item', 'Verdict', 'Type', 'Mode', 'Filter', 'Database'].map(function (t) { return BG.h('th', { scope: 'col', text: t }); }),
        BG.h('th', { scope: 'col', class: 'num', text: 'Time taken' }), BG.h('th', { scope: 'col', text: 'Checked' }))),
      BG.h('tbody', null, rows))));
    var pages = Math.max(1, Math.ceil(data.total / data.page_size));
    listEl.appendChild(BG.h('div', { class: 'table-foot' },
      BG.h('span', { text: BG.fmtInt(data.total) + (data.total === 1 ? ' check' : ' checks') + ', page ' + data.page + ' of ' + pages }),
      BG.h('div', { class: 'pager' },
        BG.h('button', { class: 'btn btn--secondary btn--sm', type: 'button', text: 'Previous', disabled: data.page <= 1, onclick: function () { state.page--; load(); } }),
        BG.h('button', { class: 'btn btn--secondary btn--sm', type: 'button', text: 'Next', disabled: data.page >= pages, onclick: function () { state.page++; load(); } }))));
  }

  function load() {
    var my = ++reqId;
    if (!listEl.firstChild) listEl.appendChild(BG.h('div', { style: 'padding:24px' }, BG.h('div', { class: 'skeleton', style: 'height:160px' })));
    var q = new URLSearchParams({ page: state.page, page_size: PAGE_SIZE });
    if (state.verdict) q.set('verdict', state.verdict);
    BG.api('/api/history?' + q.toString()).then(function (data) {
      if (my !== reqId) return;
      if (!data.items.length && data.page > 1) { state.page = Math.max(1, Math.ceil(data.total / data.page_size)); load(); return; }
      render(data);
    }, function (err) {
      if (my !== reqId) return;
      if (err.status === 404) { window.location.assign('/setup'); return; }
      BG.clear(listEl).appendChild(BG.h('div', { style: 'padding:24px' }, BG.alert('danger', 'Could not load the history.', BG.errorText(err))));
    });
  }

  clearBtn.addEventListener('click', function () {
    BG.confirm({
      title: 'Clear the check history?',
      message: 'This deletes every recorded check and resets the check counters on the dashboard. Blacklist entries are not affected.',
      confirmText: 'Clear history', tone: 'danger'
    }).then(function (ok) {
      if (!ok) return;
      BG.setBusy(clearBtn, true);
      BG.api('/api/history', { method: 'DELETE' }).then(function () {
        BG.setBusy(clearBtn, false);
        BG.toast('History cleared.', 'success');
        state.page = 1; state.verdict = ''; renderChips(); BG.clear(listEl); load();
      }, function (err) { BG.setBusy(clearBtn, false); BG.toast(BG.errorText(err), 'error'); });
    });
  });

  renderChips();
  load();
});
