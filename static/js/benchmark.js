/* Benchmark page (C8): run a benchmark job, show charts and a table, list earlier runs. */
BG.ready(function () {
  'use strict';
  var form = BG.$('#bench-form'), btn = BG.$('#bench-btn');
  var area = BG.$('#bench-result'), hist = BG.$('#bench-history');
  var charts = [];
  var currentGroup = null;

  function destroyCharts() { charts.forEach(function (c) { if (c) c.destroy(); }); charts = []; }

  function stat(label, value, sub, good) {
    return BG.h('div', { class: 'stat' + (good ? ' stat--good' : '') },
      BG.h('div', { class: 'stat__label', text: label }),
      BG.h('div', { class: 'stat__value', text: value }),
      sub ? BG.h('div', { class: 'stat__sub', text: sub }) : null);
  }

  function chartCard(title, note, canvasLabel) {
    var canvas = BG.h('canvas', { role: 'img', 'aria-label': canvasLabel });
    return { canvas: canvas, node: BG.h('div', { class: 'chart-card' },
      BG.h('h3', { text: title }), BG.h('p', { class: 'small muted', text: note }),
      BG.h('div', { class: 'chart-box' }, canvas)) };
  }

  function render(rows, created) {
    destroyCharts();
    var std = rows.filter(function (r) { return r.filter_type === 'standard'; });
    var cnt = rows.filter(function (r) { return r.filter_type === 'counting'; });
    var big = std[std.length - 1] || rows[rows.length - 1];
    var c = BG.chartColors();
    var labels = std.map(function (r) { return BG.fmtInt(r.n_items); });

    var mem = chartCard('Memory', 'Bytes used to store the items. Lower is better.', 'Bar chart: memory used by the Bloom filter and a Python set for each size');
    var qry = chartCard('Query time', 'Time to run all the queries, in milliseconds. Lower is better.', 'Bar chart: query time of the Bloom filter and a Python set for each size');
    var ins = chartCard('Build time', 'Time to insert every item, in milliseconds. Lower is better.', 'Bar chart: insert time of the Bloom filter and a Python set for each size');
    var fpc = chartCard('False positives', 'Share of unseen queries wrongly reported as present, against the target.', 'Bar chart: measured false-positive rate for each size');

    var tbody = BG.h('tbody');
    rows.forEach(function (r) {
      tbody.appendChild(BG.h('tr', null,
        BG.h('td', { class: 'cell-main', 'data-label': 'Filter', text: r.filter_type === 'counting' ? 'Counting' : 'Standard' }),
        BG.h('td', { class: 'num', 'data-label': 'Items', text: BG.fmtInt(r.n_items) }),
        BG.h('td', { class: 'num', 'data-label': 'Bits (m)', text: BG.fmtInt(r.m_bits) }),
        BG.h('td', { class: 'num', 'data-label': 'Hashes (k)', text: String(r.k_hashes) }),
        BG.h('td', { class: 'num', 'data-label': 'Filter memory', text: BG.fmtBytes(r.bloom_mem_bytes) }),
        BG.h('td', { class: 'num', 'data-label': 'Set memory', text: BG.fmtBytes(r.set_mem_bytes) }),
        BG.h('td', { class: 'num', 'data-label': 'Memory ratio', text: r.memory_ratio.toFixed(1) + 'x' }),
        BG.h('td', { class: 'num', 'data-label': 'Filter query', text: BG.fmtSeconds(r.bloom_query_s) }),
        BG.h('td', { class: 'num', 'data-label': 'Set query', text: BG.fmtSeconds(r.set_query_s) }),
        BG.h('td', { class: 'num', 'data-label': 'False negatives', text: BG.fmtInt(r.false_negatives) }),
        BG.h('td', { class: 'num', 'data-label': 'False positives', text: BG.fmtPct(r.false_positives / r.n_queries) })));
    });
    var heads = ['Filter', 'Items', 'Bits (m)', 'Hashes (k)', 'Filter memory', 'Set memory', 'Memory ratio', 'Filter query', 'Set query', 'False negatives', 'False positives'];

    BG.clear(area).appendChild(BG.h('div', { class: 'card stack' },
      BG.h('div', { class: 'card__head', style: 'margin-bottom:0' }, BG.h('div', null,
        BG.h('h2', { text: 'Results' }),
        BG.h('p', { text: (created ? 'Run on ' + BG.fmtDate(created) + '. ' : '') + 'Largest size: ' + BG.fmtInt(big.n_items) + ' items, ' + BG.fmtInt(big.n_queries) + ' queries.' }))),
      BG.h('div', { class: 'summary' },
        stat('Memory saved', big.memory_ratio.toFixed(1) + 'x', 'Set uses ' + BG.fmtBytes(big.set_mem_bytes) + ', filter ' + BG.fmtBytes(big.bloom_mem_bytes), true),
        stat('False negatives', BG.fmtInt(big.false_negatives), 'Must always be 0', big.false_negatives === 0),
        stat('False positives', BG.fmtPct(big.false_positives / big.n_queries), 'Measured on unseen items'),
        stat('Filter query time', BG.fmtSeconds(big.bloom_query_s), 'Set: ' + BG.fmtSeconds(big.set_query_s))),
      BG.h('div', { class: 'chart-grid' }, mem.node, qry.node, ins.node, fpc.node),
      BG.h('p', { class: 'small muted', text: 'A Python set is written in C and a Bloom filter here is written in Python, so the set is usually faster to query. The Bloom filter wins on memory, and that gap grows with the number of items.' }),
      BG.h('div', { class: 'table-wrap' }, BG.h('table', { class: 'table--stack' },
        BG.h('thead', null, BG.h('tr', null, heads.map(function (t) { return BG.h('th', { scope: 'col', class: t === 'Filter' ? '' : 'num', text: t }); }))),
        tbody))));

    var bar = function (label, data, color) { return { label: label, data: data, backgroundColor: color, borderRadius: 4, maxBarThickness: 48 }; };
    var ms = function (k) { return std.map(function (r) { return r[k] * 1000; }); };
    var base = function (yTitle, fmt) {
      return { plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, boxHeight: 12 } },
                 tooltip: { callbacks: { label: function (ctx) { return ctx.dataset.label + ': ' + fmt(ctx.parsed.y); } } } },
               scales: { x: { grid: { display: false }, title: { display: true, text: 'Items' } },
                         y: { beginAtZero: true, grid: { color: c.line }, title: { display: true, text: yTitle }, ticks: { callback: function (v) { return fmt(v); } } } } };
    };
    var fmtMs = function (v) { return Number(v.toPrecision(3)) + ' ms'; };
    charts.push(
      BG.chart(mem.canvas, { type: 'bar', data: { labels: labels, datasets: [
        bar('Bloom filter', std.map(function (r) { return r.bloom_mem_bytes; }), c.accent),
        bar('Python set', std.map(function (r) { return r.set_mem_bytes; }), c.ink)] }, options: base('Memory', BG.fmtBytes) }),
      BG.chart(qry.canvas, { type: 'bar', data: { labels: labels, datasets: [
        bar('Bloom filter', ms('bloom_query_s'), c.accent), bar('Python set', ms('set_query_s'), c.ink)] }, options: base('Time', fmtMs) }),
      BG.chart(ins.canvas, { type: 'bar', data: { labels: labels, datasets: [
        bar('Bloom filter', ms('bloom_insert_s'), c.accent), bar('Python set', ms('set_insert_s'), c.ink)] }, options: base('Time', fmtMs) }),
      BG.chart(fpc.canvas, { type: 'bar', data: { labels: labels, datasets: [
        bar('Measured', std.map(function (r) { return r.false_positives / r.n_queries * 100; }), c.accent),
        bar('Target', std.map(function (r) { return r.fp_target * 100; }), c.teal)] }, options: base('Rate', function (v) { return Number(v.toPrecision(3)) + '%'; }) }));
    if (cnt.length) area.firstChild.appendChild(BG.h('p', { class: 'small muted', text: 'The counting filter rows are in the table. They use about eight times the memory of the standard filter, because each position is a 1-byte counter, not a single bit.' }));
    area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /* ---- earlier runs -------------------------------------------------------------------- */
  var runs = [];
  function loadHistory() {
    BG.api('/api/benchmark/runs').then(function (list) {
      runs = list.slice().reverse();                       /* newest first */
      BG.clear(hist);
      if (!runs.length) { hist.appendChild(BG.empty('clock', 'No runs yet', 'Run a benchmark and it will be saved here.')); return; }
      var ul = BG.h('ul', { class: 'run-list' });
      runs.slice(0, 8).forEach(function (g) {
        var sizes = g.rows.filter(function (r) { return r.filter_type === 'standard'; }).map(function (r) { return BG.fmtInt(r.n_items); }).join(', ');
        var b = BG.h('button', { class: 'run-item', type: 'button', 'data-group': g.run_group, 'aria-current': g.run_group === currentGroup ? 'true' : 'false',
          onclick: function () { currentGroup = g.run_group; render(g.rows, g.created_at); loadHistory(); } },
          BG.h('b', { text: BG.fmtDate(g.created_at) }), BG.h('span', { text: 'Sizes: ' + (sizes || '-') }));
        ul.appendChild(BG.h('li', null, b));
      });
      hist.appendChild(ul);
    }, function (e) { BG.clear(hist).appendChild(BG.alert('danger', 'Could not load earlier runs.', BG.errorText(e))); });
  }
  loadHistory();

  /* ---- run -------------------------------------------------------------------------------- */
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(form);
    var alertBox = BG.clear(BG.$('#bench-alert'));
    var sizes = BG.parseIntList(form.elements.sizes.value);
    var queries = BG.parseIntLoose(form.elements.queries.value);
    var fp = BG.parsePercent(form.elements.fp.value);
    var seed = BG.parseIntLoose(form.elements.seed.value);
    var bad = false;
    if (!sizes || sizes.some(function (n) { return n < 1; })) { BG.fieldError(form, 'sizes', 'Enter whole numbers separated by spaces, such as 1,000 10,000.'); bad = true; }
    else if (sizes.length > 6) { BG.fieldError(form, 'sizes', 'Use at most 6 sizes.'); bad = true; }
    else if (Math.max.apply(null, sizes) > 200000) { BG.fieldError(form, 'sizes', 'Each size can be at most 200,000 on the web.'); bad = true; }
    if (queries === null || queries < 1 || queries > 500000) { BG.fieldError(form, 'queries', 'Enter a whole number from 1 to 500,000.'); bad = true; }
    if (fp === null || fp < 0.0001 || fp > 0.5) { BG.fieldError(form, 'fp', 'Enter a rate from 0.01% to 50%, such as 1%.'); bad = true; }
    if (seed === null || seed < 0) { BG.fieldError(form, 'seed', 'Enter a whole number, 0 or higher.'); bad = true; }
    if (bad) return;
    sizes.sort(function (a, b) { return a - b; });

    var meter = BG.meter();
    BG.clear(BG.$('#bench-progress')).appendChild(meter);
    BG.setBusy(btn, true);
    BG.runJob('/api/benchmark', {
      sizes: sizes, queries: queries, fp: fp, seed: seed,
      repeats: Number(form.elements.repeats.value), include_counting: form.elements.include_counting.checked
    }, meter.update).then(function (res) {
      BG.setBusy(btn, false);
      BG.clear(BG.$('#bench-progress'));
      currentGroup = res.run_group;
      render(res.rows, null);
      loadHistory();
      BG.toast('Benchmark finished.', 'success');
    }, function (err) {
      BG.setBusy(btn, false);
      BG.clear(BG.$('#bench-progress'));
      if (err.field && BG.fieldError(form, err.field, err.message)) return;
      alertBox.appendChild(BG.alert(err.code === 'JOB_RUNNING' ? 'warning' : 'danger', err.code === 'JOB_RUNNING' ? 'Another run is in progress.' : 'The benchmark did not finish.', BG.errorText(err)));
    });
  });
});
