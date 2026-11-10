/* Setup page: live size calculator and filter creation. */
BG.ready(function () {
  'use strict';
  var form = BG.$('#setup-form');
  var preview = BG.$('#preview-body');
  var createBtn = BG.$('#create-btn');
  var nInput = form.elements.n, pInput = form.elements.p;
  var N_MIN = 1, N_MAX = 50000000, P_MIN = 0.0001, P_MAX = 0.5;
  var seq = 0; /* ignore out-of-order calc responses */

  function selectedType() { return form.querySelector('input[name="type"]:checked').value; }

  /* Local checks give instant feedback; the server has the final say. */
  function readValues() {
    var n = BG.parseIntLoose(nInput.value);
    var p = BG.parsePercent(pInput.value);
    var errors = {};
    if (n === null || n < N_MIN || n > N_MAX) errors.n = 'Enter a whole number from 1 to 50,000,000.';
    if (p === null || p < P_MIN || p > P_MAX) errors.p = 'Enter a percentage between 0.01 and 50.';
    return { n: n, p: p, errors: errors };
  }

  function showFieldErrors(errors) {
    BG.clearErrors(form);
    Object.keys(errors).forEach(function (k) { BG.fieldError(form, k, errors[k]); });
  }

  function renderIdle(text) {
    BG.clear(preview).appendChild(BG.empty('info', 'Waiting for valid numbers', text));
  }

  function renderSkeleton() {
    BG.clear(preview);
    preview.appendChild(BG.h('div', { class: 'stack--sm stack' },
      BG.h('div', { class: 'skeleton', style: 'height:56px' }),
      BG.h('div', { class: 'skeleton', style: 'height:20px' }),
      BG.h('div', { class: 'skeleton', style: 'height:20px' })));
  }

  function stat(label, value, sub) {
    return BG.h('div', { class: 'stat' },
      BG.h('div', { class: 'stat__label', text: label }),
      BG.h('div', { class: 'stat__value', text: value }),
      sub ? BG.h('div', { class: 'stat__sub', text: sub }) : null);
  }

  function meter(label, bytes, max, cls) {
    return BG.h('div', { class: 'meter' },
      BG.h('div', { class: 'meter__top' }, BG.h('span', { text: label }), BG.h('b', { text: BG.fmtBytes(bytes) })),
      BG.h('div', { class: 'meter__track' },
        BG.h('div', { class: 'meter__bar ' + cls, style: 'width:' + Math.max(1, Math.min(100, (bytes / max) * 100)).toFixed(2) + '%' })));
  }

  function render(c) {
    var max = Math.max(c.bloom_bytes, c.set_bytes_estimate);
    var ratio = c.set_bytes_estimate / c.bloom_bytes;
    var verdict;
    if (ratio >= 1.05) verdict = BG.h('p', { class: 'preview__ratio' }, 'The filter is about ', BG.h('b', { text: ratio.toFixed(ratio >= 10 ? 0 : 1) + ' times smaller' }), ' than storing the same items in a Python set.');
    else verdict = BG.h('p', { class: 'preview__ratio' }, 'At these settings the filter is not smaller than a Python set. Raise the expected items or accept a higher false-positive rate to see the saving.');
    BG.clear(preview).appendChild(BG.h('div', null,
      BG.h('div', { class: 'preview__nums' },
        stat('Bits (m)', BG.fmtInt(c.m)),
        stat('Hashes (k)', String(c.k)),
        stat('Bits per item', c.bits_per_item.toFixed(1))),
      BG.h('div', { class: 'stack--sm stack' },
        meter(c.filter_type === 'counting' ? 'Counting filter' : 'Bloom filter', c.bloom_bytes, max, ''),
        meter('Python set (estimate)', c.set_bytes_estimate, max, 'meter__bar--set')),
      verdict,
      BG.h('p', { class: 'small muted', style: 'margin-top:12px', text: 'The set figure is an estimate that assumes keys of about 15 characters.' })));
  }

  var calc = BG.debounce(function () {
    var v = readValues();
    showFieldErrors(v.errors);
    if (Object.keys(v.errors).length) { renderIdle('Fix the highlighted fields to see the filter size.'); return; }
    var my = ++seq;
    renderSkeleton();
    BG.api('/api/filter/calc', { method: 'POST', json: { n: v.n, p: v.p, type: selectedType() } }).then(function (c) {
      if (my === seq) render(c);
    }, function (e) {
      if (my !== seq) return;
      if (e.field && BG.fieldError(form, e.field, e.message)) renderIdle('Fix the highlighted field to see the filter size.');
      else renderIdle(BG.errorText(e));
    });
  }, 250);

  function syncPresets() {
    var n = BG.parseIntLoose(nInput.value), p = BG.parsePercent(pInput.value);
    BG.$$('.preset[data-n]').forEach(function (b) { b.classList.toggle('is-active', Number(b.dataset.n) === n); });
    BG.$$('.preset[data-p]').forEach(function (b) { b.classList.toggle('is-active', BG.parsePercent(b.dataset.p) === p); });
  }

  BG.$$('.preset[data-n]').forEach(function (b) {
    b.addEventListener('click', function () { nInput.value = BG.fmtInt(Number(b.dataset.n)); syncPresets(); calc(); });
  });
  BG.$$('.preset[data-p]').forEach(function (b) {
    b.addEventListener('click', function () { pInput.value = b.dataset.p; syncPresets(); calc(); });
  });
  [nInput, pInput].forEach(function (el) { el.addEventListener('input', function () { syncPresets(); calc(); }); });
  BG.$$('input[name="type"]').forEach(function (el) { el.addEventListener('change', calc); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var v = readValues();
    showFieldErrors(v.errors);
    var name = form.elements.name.value.trim();
    if (!name || name.length > 100) { BG.fieldError(form, 'name', 'Enter a name of 1 to 100 characters.'); return; }
    if (Object.keys(v.errors).length) return;
    var holder = BG.clear(BG.$('#form-alert'));
    BG.setBusy(createBtn, true);
    BG.api('/api/filter', { method: 'POST', json: { name: name, type: selectedType(), n: v.n, p: v.p } }).then(function () {
      BG.flash('Filter created. You can start adding items.', 'success');
      window.location.assign('/');
    }, function (err) {
      BG.setBusy(createBtn, false);
      if (err.status === 409 && err.code === 'CONFLICT') {
        /* A filter already exists (another tab created one first). */
        BG.flash('A filter already exists, so you were taken to the dashboard.', 'info');
        window.location.assign('/');
        return;
      }
      if (err.field && BG.fieldError(form, err.field, err.message)) return;
      holder.appendChild(BG.alert('danger', 'Could not create the filter.', BG.errorText(err)));
    });
  });

  syncPresets();
  calc();
});
