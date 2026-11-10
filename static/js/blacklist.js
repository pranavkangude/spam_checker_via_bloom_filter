/* Blacklist page: add, search, filter, page through, remove. */
BG.ready(function () {
  'use strict';
  var addForm = BG.$('#add-form');
  var addBtn = BG.$('#add-btn');
  var listEl = BG.$('#list');
  var qEl = BG.$('#q'), typeEl = BG.$('#f-type'), labelEl = BG.$('#f-label');
  var PAGE_SIZE = 20;
  var state = { page: 1, q: '', key_type: '', label: '' };
  var canRemove = false;
  var reqId = 0;

  BG.fillSelect(BG.$('#a-type'), BG.KEY_TYPES);
  BG.fillSelect(BG.$('#a-label'), BG.LABELS);
  BG.$('#a-type').value = 'transaction_id';
  BG.$('#a-label').value = 'fraud';
  BG.fillSelect(typeEl, BG.KEY_TYPES, 'All types');
  BG.fillSelect(labelEl, BG.LABELS, 'All labels');

  BG.getFilter().then(function (f) {
    canRemove = f.type === 'counting';
    if (!canRemove) {
      BG.$('#remove-note').appendChild(BG.alert('info', 'Items cannot be removed from this filter.',
        'A Standard filter has no way to switch bits back off. To remove items, create a Counting filter in Settings.'));
    }
  }, function () { /* the list request reports the problem */ }).then(function () { load(); });

  function qs() {
    var p = new URLSearchParams({ page: state.page, page_size: PAGE_SIZE });
    if (state.q) p.set('q', state.q);
    if (state.key_type) p.set('key_type', state.key_type);
    if (state.label) p.set('label', state.label);
    return p.toString();
  }

  function labelTag(l) {
    var cls = l === 'fraud' ? 'badge--blacklisted' : l === 'spam' ? 'badge--fp' : l === 'phishing' ? 'badge--accent' : '';
    return BG.h('span', { class: 'badge ' + cls, text: BG.LABELS[l] || l });
  }

  function removeRow(entry) {
    BG.confirm({
      title: 'Remove this item?',
      message: 'It will no longer be flagged by checks. ' + entry.item_raw,
      confirmText: 'Remove item', tone: 'danger'
    }).then(function (ok) {
      if (!ok) return;
      BG.api('/api/blacklist', { method: 'DELETE', json: { item: entry.item_raw, key_type: entry.key_type } }).then(function () {
        BG.toast('Item removed.', 'success');
        BG.getFilter(true).then(BG.updateChip, function () {});
        load();
      }, function (err) { BG.toast(BG.errorText(err), 'error'); });
    });
  }

  function render(data) {
    BG.clear(listEl);
    var filtered = state.q || state.key_type || state.label;
    if (!data.items.length) {
      if (filtered) {
        listEl.appendChild(BG.empty('search', 'No matches', 'Nothing on the blacklist fits these filters. Try a shorter search or clear the filters.',
          BG.h('button', { class: 'btn btn--secondary', type: 'button', text: 'Clear filters', onclick: function () {
            qEl.value = ''; typeEl.value = ''; labelEl.value = ''; state = { page: 1, q: '', key_type: '', label: '' }; load();
          } })));
      } else {
        listEl.appendChild(BG.empty('list', 'The blacklist is empty', 'Add an item above, import a file, or generate sample keys to get started.',
          BG.h('a', { class: 'btn btn--primary', href: '/import', text: 'Import items' })));
      }
      return;
    }
    var rows = data.items.map(function (e) {
      var removeBtn = BG.h('button', {
        class: 'btn btn--ghost btn--sm', type: 'button', 'aria-label': 'Remove ' + e.item_key,
        title: canRemove ? 'Remove this item' : 'Only Counting filters can remove items',
        onclick: function () { removeRow(e); }
      }, BG.icon('trash', 'icon--sm'), 'Remove');
      if (!canRemove) { removeBtn.disabled = true; }
      return BG.h('tr', null,
        BG.h('td', { class: 'cell-main', 'data-label': 'Item' }, BG.h('span', { class: 'key', text: e.item_key })),
        BG.h('td', { 'data-label': 'Type', text: BG.KEY_TYPES[e.key_type] || e.key_type }),
        BG.h('td', { 'data-label': 'Label' }, labelTag(e.label)),
        BG.h('td', { 'data-label': 'Source', text: e.source }),
        BG.h('td', { 'data-label': 'Added', text: BG.fmtDate(e.added_at) }),
        BG.h('td', { class: 'cell-actions', style: 'text-align:right' }, removeBtn));
    });
    listEl.appendChild(BG.h('div', { class: 'table-wrap' },
      BG.h('table', { class: 'table--stack' },
        BG.h('thead', null, BG.h('tr', null,
          BG.h('th', { scope: 'col', text: 'Item' }), BG.h('th', { scope: 'col', text: 'Type' }), BG.h('th', { scope: 'col', text: 'Label' }),
          BG.h('th', { scope: 'col', text: 'Source' }), BG.h('th', { scope: 'col', text: 'Added' }), BG.h('th', { scope: 'col' }, BG.h('span', { class: 'visually-hidden', text: 'Actions' })))),
        BG.h('tbody', null, rows))));
    var pages = Math.max(1, Math.ceil(data.total / data.page_size));
    listEl.appendChild(BG.h('div', { class: 'table-foot' },
      BG.h('span', { text: BG.fmtInt(data.total) + (data.total === 1 ? ' item' : ' items') + (filtered ? ' match' : '') + ', page ' + data.page + ' of ' + pages }),
      BG.h('div', { class: 'pager' },
        BG.h('button', { class: 'btn btn--secondary btn--sm', type: 'button', text: 'Previous', disabled: data.page <= 1, onclick: function () { state.page--; load(); } }),
        BG.h('button', { class: 'btn btn--secondary btn--sm', type: 'button', text: 'Next', disabled: data.page >= pages, onclick: function () { state.page++; load(); } }))));
  }

  function load() {
    var my = ++reqId;
    if (!listEl.firstChild) listEl.appendChild(BG.h('div', { style: 'padding:24px' }, BG.h('div', { class: 'skeleton', style: 'height:160px' })));
    BG.api('/api/blacklist?' + qs()).then(function (data) {
      if (my !== reqId) return;
      /* last page vanished after a removal: step back */
      if (!data.items.length && data.page > 1) { state.page = Math.max(1, Math.ceil(data.total / data.page_size)); load(); return; }
      render(data);
    }, function (err) {
      if (my !== reqId) return;
      if (err.status === 404) { window.location.assign('/setup'); return; }
      BG.clear(listEl).appendChild(BG.h('div', { style: 'padding:24px' }, BG.alert('danger', 'Could not load the blacklist.', BG.errorText(err))));
    });
  }

  qEl.addEventListener('input', BG.debounce(function () { state.q = qEl.value.trim(); state.page = 1; load(); }, 300));
  typeEl.addEventListener('change', function () { state.key_type = typeEl.value; state.page = 1; load(); });
  labelEl.addEventListener('change', function () { state.label = labelEl.value; state.page = 1; load(); });

  addForm.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(addForm);
    var item = addForm.elements.namedItem('item').value.trim();
    if (!item) { BG.fieldError(addForm, 'item', 'Enter an item to add.'); addForm.elements.namedItem('item').focus(); return; }
    BG.setBusy(addBtn, true);
    BG.api('/api/blacklist', { method: 'POST', json: { item: item, key_type: addForm.elements.key_type.value, label: addForm.elements.label.value } })
      .then(function (res) {
        BG.setBusy(addBtn, false);
        BG.toast('Added ' + res.item_key + ' to the blacklist.', 'success');
        addForm.elements.namedItem('item').value = '';
        addForm.elements.namedItem('item').focus();
        BG.getFilter(true).then(BG.updateChip, function () {});
        state.page = 1;
        load();
      }, function (err) {
        BG.setBusy(addBtn, false);
        if (err.code === 'DUPLICATE') { BG.fieldError(addForm, 'item', 'That item is already on the blacklist.'); return; }
        if (err.field && BG.fieldError(addForm, err.field, err.message)) return;
        BG.toast(BG.errorText(err), 'error');
      });
  });
});
