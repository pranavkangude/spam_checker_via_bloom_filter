/* Experiments page (C9): run a false-positive experiment, chart empirical vs theoretical, reopen saved runs. */
BG.ready(function () {
  'use strict';
  var form = BG.$('#exp-form'), btn = BG.$('#exp-btn');
  var area = BG.$('#exp-result'), hist = BG.$('#exp-history');
  var chart = null, currentId = null;
  var KIND = {
    vary_k: { title: 'Number of hashes', x: 'Hash functions (k)', note: 'The filter size is fixed. Too few hashes leave many bits for a stranger to match; too many fill the array.' },
    vary_ratio: { title: 'Bits per item', x: 'Bits per item (m / n)', note: 'The number of hashes is the best one for each size. More bits per item give a lower rate.' },
    overfill: { title: 'Overfilling', x: 'Items inserted, as a multiple of the plan', note: 'The filter was sized for the planned items. Adding more pushes the rate above the target.' }
  };

  function pct(v) { return (v * 100).toFixed(v < 0.001 ? 4 : 3) + '%'; }

  function render(res) {
    if (chart) { chart.destroy(); chart = null; }
    var info = KIND[res.kind] || { title: res.kind, x: '', note: '' };
    var c = BG.chartColors();
    var pts = res.points, an = res.analysis;
    var canvas = BG.h('canvas', { role: 'img', 'aria-label': 'Line chart of theoretical and measured false-positive rate for each ' + info.x.toLowerCase() });

    var worst = an.reduce(function (m, a) { return Math.max(m, Math.abs(a.z_score)); }, 0);
    var verdict = worst <= 3
      ? 'Every measured rate is within 3 standard errors of the formula.'
      : 'At least one point is more than 3 standard errors from the formula. Try more trials.';

    var tbody = BG.h('tbody');
    pts.forEach(function (p, i) {
      var a = an[i];
      tbody.appendChild(BG.h('tr', null,
        BG.h('td', { class: 'cell-main', 'data-label': 'Setting', text: p.param_label }),
        BG.h('td', { class: 'num', 'data-label': 'Bits (m)', text: BG.fmtInt(p.m_bits) }),
        BG.h('td', { class: 'num', 'data-label': 'Hashes (k)', text: String(p.k_hashes) }),
        BG.h('td', { class: 'num', 'data-label': 'Items', text: BG.fmtInt(p.n_inserted) }),
        BG.h('td', { class: 'num', 'data-label': 'Formula', text: pct(p.theoretical_fp) }),
        BG.h('td', { class: 'num', 'data-label': 'Measured', text: pct(p.empirical_fp) }),
        BG.h('td', { class: 'num', 'data-label': 'False positives', text: BG.fmtInt(p.false_positives) + ' of ' + BG.fmtInt(p.trials) }),
        BG.h('td', { class: 'num', 'data-label': 'z-score', text: a.z_score.toFixed(2) })));
    });
    var heads = ['Setting', 'Bits (m)', 'Hashes (k)', 'Items', 'Formula', 'Measured', 'False positives', 'z-score'];

    var dl = BG.h('button', { class: 'btn btn--secondary', type: 'button', onclick: function () {
      BG.setBusy(dl, true);
      BG.download('/api/experiments/' + res.experiment_id + '/csv', {}, 'experiment-' + res.experiment_id + '.csv')
        .then(function () { BG.setBusy(dl, false); BG.toast('CSV downloaded.', 'success'); },
              function (e) { BG.setBusy(dl, false); BG.toast(BG.errorText(e), 'error'); });
    } }, BG.icon('upload', 'icon--sm'), 'Download CSV');
    dl.querySelector('svg').style.transform = 'rotate(180deg)';

    var sub = [BG.fmtInt(res.n_items) + ' items', BG.fmtInt(res.trials) + ' trials', 'seed ' + res.seed];
    if (res.meta && res.meta.optimal_k) sub.push('best k for this size: ' + res.meta.optimal_k);

    BG.clear(area).appendChild(BG.h('div', { class: 'card stack' },
      BG.h('div', { class: 'card__head', style: 'margin-bottom:0' },
        BG.h('div', null, BG.h('h2', { text: info.title }), BG.h('p', { text: sub.join(' · ') })), dl),
      BG.h('p', { text: info.note }),
      BG.h('div', { class: 'chart-card' }, BG.h('div', { class: 'chart-box' }, canvas)),
      BG.alert(worst <= 3 ? 'success' : 'warning', worst <= 3 ? 'Matches the formula.' : 'Differs from the formula.', verdict),
      BG.h('div', { class: 'table-wrap' }, BG.h('table', { class: 'table--stack' },
        BG.h('thead', null, BG.h('tr', null, heads.map(function (t) { return BG.h('th', { scope: 'col', class: t === 'Setting' ? '' : 'num', text: t }); }))),
        tbody)),
      BG.h('p', { class: 'small muted', text: 'The z-score says how many standard errors the measured rate is from the formula. Values between -3 and 3 are ordinary random variation.' })));

    chart = BG.chart(canvas, { type: 'line', data: {
      labels: pts.map(function (p) { return p.param_label; }),
      datasets: [
        { label: 'Formula', data: pts.map(function (p) { return p.theoretical_fp * 100; }), borderColor: c.ink, backgroundColor: c.ink, borderDash: [6, 4], pointRadius: 3, tension: 0.2 },
        { label: 'Measured', data: pts.map(function (p) { return p.empirical_fp * 100; }), borderColor: c.accent, backgroundColor: c.accent, pointRadius: 4, tension: 0.2 }] },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
          tooltip: { callbacks: { label: function (ctx) { return ctx.dataset.label + ': ' + Number(ctx.parsed.y.toPrecision(3)) + '%'; } } } },
        scales: { x: { grid: { display: false }, title: { display: true, text: info.x } },
          y: { beginAtZero: true, grid: { color: c.line }, title: { display: true, text: 'False-positive rate' },
               ticks: { callback: function (v) { return Number(v.toPrecision(3)) + '%'; } } } } } });
    area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function loadHistory() {
    BG.api('/api/experiments').then(function (list) {
      BG.clear(hist);
      if (!list.length) { hist.appendChild(BG.empty('clock', 'No experiments yet', 'Run one and it will be saved here.')); return; }
      var ul = BG.h('ul', { class: 'run-list' });
      list.slice(0, 8).forEach(function (e) {
        ul.appendChild(BG.h('li', null, BG.h('button', { class: 'run-item', type: 'button', 'aria-current': e.experiment_id === currentId ? 'true' : 'false',
          onclick: function () {
            BG.api('/api/experiments/' + e.experiment_id).then(function (res) { currentId = e.experiment_id; render(res); loadHistory(); },
              function (err) { BG.toast(BG.errorText(err), 'error'); });
          } },
          BG.h('b', { text: (KIND[e.kind] ? KIND[e.kind].title : e.kind) + ' · ' + BG.fmtInt(e.n_items) + ' items' }),
          BG.h('span', { text: BG.fmtDate(e.created_at) + ' · ' + BG.fmtInt(e.trials) + ' trials' }))));
      });
      hist.appendChild(ul);
    }, function (e) { BG.clear(hist).appendChild(BG.alert('danger', 'Could not load saved experiments.', BG.errorText(e))); });
  }
  loadHistory();

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(form);
    var alertBox = BG.clear(BG.$('#exp-alert'));
    var kind = form.querySelector('input[name="kind"]:checked').value;
    var n = BG.parseIntLoose(form.elements.n.value), trials = BG.parseIntLoose(form.elements.trials.value), seed = BG.parseIntLoose(form.elements.seed.value);
    var bad = false;
    if (n === null || n < 1 || n > 200000) { BG.fieldError(form, 'n', 'Enter a whole number from 1 to 200,000.'); bad = true; }
    if (trials === null || trials < 1 || trials > 500000) { BG.fieldError(form, 'trials', 'Enter a whole number from 1 to 500,000.'); bad = true; }
    if (seed === null || seed < 0) { BG.fieldError(form, 'seed', 'Enter a whole number, 0 or higher.'); bad = true; }
    if (bad) return;

    var meter = BG.meter();
    BG.clear(BG.$('#exp-progress')).appendChild(meter);
    BG.setBusy(btn, true);
    BG.runJob('/api/experiments', { kind: kind, n: n, trials: trials, seed: seed }, meter.update).then(function (res) {
      BG.setBusy(btn, false);
      BG.clear(BG.$('#exp-progress'));
      currentId = res.experiment_id;
      render(res);
      loadHistory();
      BG.toast('Experiment finished.', 'success');
    }, function (err) {
      BG.setBusy(btn, false);
      BG.clear(BG.$('#exp-progress'));
      if (err.field && BG.fieldError(form, err.field, err.message)) return;
      alertBox.appendChild(BG.alert(err.code === 'JOB_RUNNING' ? 'warning' : 'danger', err.code === 'JOB_RUNNING' ? 'Another run is in progress.' : 'The experiment did not finish.', BG.errorText(err)));
    });
  });
});
