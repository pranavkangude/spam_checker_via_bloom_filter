/* Shared by the Lab pages (Benchmark, Experiments): background jobs and chart styling. */
(function () {
  'use strict';

  /* POST a job, then poll /api/jobs/<id> until it ends. Resolves with the job result.
     onProgress({label, done, total}) is called on every poll. */
  BG.runJob = function (path, body, onProgress) {
    return BG.api(path, { method: 'POST', json: body }).then(function (job) {
      return new Promise(function (resolve, reject) {
        function poll() {
          BG.api('/api/jobs/' + encodeURIComponent(job.job_id)).then(function (j) {
            if (onProgress) onProgress(j.progress || { label: '', done: 0, total: 0 });
            if (j.status === 'done') resolve(j.result);
            else if (j.status === 'error') reject(new BG.ApiError(500, j.error.code, j.error.message));
            else setTimeout(poll, 500);
          }, reject);
        }
        poll();
      });
    });
  };

  /* A progress meter node. update(p) sets the label and the bar. */
  BG.meter = function () {
    var label = BG.h('span', { text: 'Starting...' }), count = BG.h('b', { text: '' });
    var bar = BG.h('div', { class: 'meter__bar', style: 'width:4px' });
    var node = BG.h('div', { class: 'meter', role: 'status' },
      BG.h('div', { class: 'meter__top' }, label, count),
      BG.h('div', { class: 'meter__track' }, bar));
    node.update = function (p) {
      var pct = p.total ? Math.round(100 * p.done / p.total) : 0;
      label.textContent = p.label && p.label !== 'starting' ? 'Running ' + p.label : 'Starting...';
      count.textContent = p.total ? p.done + ' of ' + p.total : '';
      bar.style.width = Math.max(pct, 2) + '%';
    };
    return node;
  };

  /* Chart.js styling that matches the design tokens. */
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  BG.chartColors = function () {
    return { accent: css('--accent') || '#4F46E5', teal: css('--teal') || '#14B8A6', ink: css('--ink') || '#0F172A',
             muted: css('--muted') || '#64748B', line: css('--line') || '#E2E8F0' };
  };
  BG.chart = function (canvas, config) {
    var c = BG.chartColors();
    if (typeof Chart === 'undefined') return null;
    Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
    Chart.defaults.font.size = 13;
    Chart.defaults.color = c.muted;
    config.options = config.options || {};
    config.options.responsive = true;
    config.options.maintainAspectRatio = false;
    config.options.animation = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 300 };
    return new Chart(canvas, config);
  };

  BG.fmtSeconds = function (s) {
    if (typeof s !== 'number') return '-';
    if (s < 1) return (s * 1000).toFixed(s < 0.01 ? 2 : 1) + ' ms';
    return s.toFixed(2) + ' s';
  };

  /* Read a list of whole numbers: "1,000 10,000" or "1000, 5000; 20,000". A token such as 1,000
     is one number (thousands separator); any other comma separates numbers. Returns an array or null. */
  BG.parseIntList = function (text) {
    var tokens = String(text).split(/[\s;]+/).filter(Boolean), parts = [];
    tokens.forEach(function (t) {
      t = t.replace(/,+$/, '');
      if (/^\d{1,3}(,\d{3})+$/.test(t)) parts.push(t);
      else t.split(',').forEach(function (x) { if (x !== '') parts.push(x); });
    });
    if (!parts.length) return null;
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var n = BG.parseIntLoose(parts[i]);
      if (n === null) return null;
      out.push(n);
    }
    return out;
  };
})();
