/* Settings page: current filter, rebuild, reset. */
BG.ready(function () {
  'use strict';
  var current = BG.$('#current');
  var form = BG.$('#rebuild-form');
  var rebuildBtn = BG.$('#rebuild-btn');
  var N_MAX = 50000000, P_MIN = 0.0001, P_MAX = 0.5;

  function pctText(frac) { return String(Number((frac * 100).toPrecision(10))); }

  function render(info) {
    BG.clear(current).appendChild(BG.h('dl', { class: 'kv' },
      BG.h('dt', { text: 'Name' }), BG.h('dd', { text: info.name }),
      BG.h('dt', { text: 'Type' }), BG.h('dd', { text: info.type === 'counting' ? 'Counting (items can be removed)' : 'Standard (items cannot be removed)' }),
      BG.h('dt', { text: 'Items stored' }), BG.h('dd', { text: BG.fmtInt(info.item_count) + ' of ' + BG.fmtInt(info.n_capacity) + ' planned' }),
      BG.h('dt', { text: 'Target false-positive rate' }), BG.h('dd', { text: BG.fmtPct(info.target_fp) }),
      BG.h('dt', { text: 'Size' }), BG.h('dd', { text: BG.fmtInt(info.m_bits) + ' bits, ' + info.k_hashes + ' hashes, ' + BG.fmtBytes(info.memory_bytes) })));
    if (info.over_capacity) {
      current.appendChild(BG.h('div', { style: 'margin-top:16px' },
        BG.alert('warning', 'The filter is over capacity.', 'It holds more items than it was sized for, so false positives are above target. Rebuild with a larger item count.')));
    }
    if (!form.elements.n.value) form.elements.n.value = BG.fmtInt(Math.max(info.n_capacity, info.item_count));
    if (!form.elements.p.value) form.elements.p.value = pctText(info.target_fp);
  }

  BG.getFilter().then(render, function (e) {
    BG.clear(current).appendChild(BG.alert('danger', 'Could not load the filter.', BG.errorText(e)));
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(form);
    var holder = BG.clear(BG.$('#rebuild-alert'));
    var n = BG.parseIntLoose(form.elements.n.value), p = BG.parsePercent(form.elements.p.value);
    var bad = false;
    if (n === null || n < 1 || n > N_MAX) { BG.fieldError(form, 'n', 'Enter a whole number from 1 to 50,000,000.'); bad = true; }
    if (p === null || p < P_MIN || p > P_MAX) { BG.fieldError(form, 'p', 'Enter a percentage between 0.01 and 50.'); bad = true; }
    if (bad) return;
    BG.setBusy(rebuildBtn, true);
    BG.api('/api/filter/rebuild', { method: 'POST', json: { n: n, p: p } }).then(function (res) {
      BG.setBusy(rebuildBtn, false);
      var info = res.filter;
      BG.getFilter(true).then(function (f) { render(f); BG.updateChip(f); }, function () { render(info); BG.updateChip(info); });
      BG.toast('Rebuilt with ' + BG.fmtInt(res.reinserted) + ' items in ' + res.duration_s + ' s.', 'success');
    }, function (err) {
      BG.setBusy(rebuildBtn, false);
      if (err.field && BG.fieldError(form, err.field, err.message)) return;
      holder.appendChild(BG.alert('danger', 'Could not rebuild.', BG.errorText(err)));
    });
  });

  BG.$('#reset-btn').addEventListener('click', function () {
    var btn = this;
    BG.confirm({
      title: 'Reset everything?',
      message: 'This deletes the filter, every blacklist entry, the check history and the import records. You will have to set up a new filter.',
      confirmText: 'Reset everything', tone: 'danger', typeToConfirm: 'RESET'
    }).then(function (ok) {
      if (!ok) return;
      BG.setBusy(btn, true);
      BG.api('/api/filter', { method: 'DELETE', json: { confirm: 'RESET' } }).then(function () {
        BG.flash('Everything was reset. Create a new filter to continue.', 'success');
        window.location.assign('/setup');
      }, function (err) {
        BG.setBusy(btn, false);
        BG.toast(BG.errorText(err), 'error');
      });
    });
  });
});
