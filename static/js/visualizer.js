/* Visualizer page (C10): a small teaching Bloom filter drawn as a grid of bits. */
BG.ready(function () {
  'use strict';
  var gridBox = BG.$('#vz-grid'), resultBox = BG.$('#vz-result'), wordsBox = BG.$('#vz-words');
  var form = BG.$('#vz-form'), input = BG.$('#vz-item');
  var st = { m: 128, k: 3, bits: '', words: [] };
  var owners = {};                                    /* bit index -> first word that set it */

  function cols(m) { return m <= 32 ? 16 : 32; }

  /* Draw the grid. opts: { isNew: [idx], hit: [idx], miss: [idx] } */
  function draw(opts) {
    opts = opts || {};
    var mark = function (list) { var o = {}; (list || []).forEach(function (i) { o[i] = true; }); return o; };
    var isNew = mark(opts.isNew), hit = mark(opts.hit), miss = mark(opts.miss);
    gridBox.style.setProperty('--cols', cols(st.m));
    BG.clear(gridBox);
    for (var i = 0; i < st.m; i++) {
      var on = st.bits.charAt(i) === '1';
      var cls = 'bit' + (on ? ' is-on' : '') + (isNew[i] ? ' is-new' : '') + (hit[i] ? ' is-hit' : '') + (miss[i] ? ' is-miss' : '');
      var title = 'Bit ' + i + ': ' + (on ? 'on' : 'off') + (on && owners[i] ? ', first set by "' + owners[i] + '"' : '');
      gridBox.appendChild(BG.h('span', { class: cls, title: title }));
    }
    var set = 0;
    for (var j = 0; j < st.bits.length; j++) if (st.bits.charAt(j) === '1') set++;
    var ratio = st.m ? set / st.m : 0;
    BG.$('#vz-sub').textContent = st.m + ' bits, ' + st.k + (st.k === 1 ? ' hash' : ' hashes') + ' per word. Hover a bit to see which word set it.';
    var s = BG.$('#vz-stats');
    BG.clear(s);
    [['Words added', BG.fmtInt(st.words.length)], ['Bits on', set + ' of ' + st.m], ['Filled', BG.fmtPct(ratio)]].forEach(function (p) {
      s.appendChild(BG.h('div', { class: 'stat' }, BG.h('div', { class: 'stat__label', text: p[0] }), BG.h('div', { class: 'stat__value', text: p[1] })));
    });
  }

  function drawWords() {
    BG.clear(wordsBox);
    if (!st.words.length) { wordsBox.appendChild(BG.h('p', { class: 'small muted', text: 'Nothing yet. Add a word to switch on its bits.' })); return; }
    st.words.forEach(function (w) { wordsBox.appendChild(BG.h('span', { class: 'vz-word', text: w })); });
  }

  /* Owners are only known for words this page has seen; rebuild them from server state by asking nothing:
     the first word to touch a bit is shown once a query or false-positive result reports it. */
  function learn(map) { Object.keys(map || {}).forEach(function (i) { owners[i] = map[i]; }); }

  function indexRows(indexes, values) {
    var tb = BG.h('tbody');
    indexes.forEach(function (idx, n) {
      var on = values ? values[n] === 1 : st.bits.charAt(idx) === '1';
      tb.appendChild(BG.h('tr', null,
        BG.h('td', { class: 'num', 'data-label': 'Hash', text: String(n + 1) }),
        BG.h('td', { class: 'num cell-main', 'data-label': 'Bit', text: String(idx) }),
        BG.h('td', { 'data-label': 'Value' }, BG.h('span', { class: 'badge ' + (on ? 'badge--accent' : 'badge--invalid'), text: on ? 'On (1)' : 'Off (0)' })),
        BG.h('td', { 'data-label': 'Set by', text: on && owners[idx] ? owners[idx] : '-' })));
    });
    return BG.h('div', { class: 'table-wrap' }, BG.h('table', { class: 'table--stack' },
      BG.h('thead', null, BG.h('tr', null, ['Hash', 'Bit', 'Value', 'Set by'].map(function (t) { return BG.h('th', { scope: 'col', class: t === 'Hash' || t === 'Bit' ? 'num' : '', text: t }); }))),
      tb));
  }

  function show(type, title, text, indexes, values) {
    BG.clear(resultBox);
    resultBox.appendChild(BG.alert(type, title, text));
    if (indexes && indexes.length) resultBox.appendChild(indexRows(indexes, values));
  }

  function fail(err) {
    if (err.field === 'item' && BG.fieldError(form, 'item', err.message)) return;
    show('danger', 'That did not work.', BG.errorText(err));
  }

  function word() {
    BG.clearErrors(form);
    var v = input.value.trim();
    if (!v) { BG.fieldError(form, 'item', 'Type a word first.'); input.focus(); return null; }
    return v;
  }

  /* ---- actions ------------------------------------------------------------------------- */
  function insert() {
    var v = word(); if (v === null) return;
    var btn = BG.$('#vz-insert');
    BG.setBusy(btn, true);
    BG.api('/api/visualizer/insert', { method: 'POST', json: { item: v } }).then(function (r) {
      BG.setBusy(btn, false);
      var before = st.bits;
      var fresh = r.indexes.filter(function (i) { return before.charAt(i) !== '1'; });
      if (!r.duplicate) {
        st.words.push(r.item);
        r.indexes.forEach(function (i) { if (!owners[i]) owners[i] = r.item; });
      }
      st.bits = r.bits;
      draw({ isNew: fresh, hit: r.indexes });
      drawWords();
      show(r.duplicate ? 'info' : 'success', r.duplicate ? '"' + r.item + '" was already added.' : '"' + r.item + '" added.',
        r.duplicate ? 'Adding it again changes nothing.' : fresh.length + ' of its ' + r.indexes.length + ' bits were off and are now on. Bits already on stay on.', r.indexes);
      input.value = ''; input.focus();
    }, function (e) { BG.setBusy(btn, false); fail(e); });
  }

  function query() {
    var v = word(); if (v === null) return;
    var btn = BG.$('#vz-query');
    BG.setBusy(btn, true);
    BG.api('/api/visualizer/query', { method: 'POST', json: { item: v } }).then(function (r) {
      BG.setBusy(btn, false);
      learn(r.explained_by);
      st.bits = r.bits;
      var hit = [], miss = [];
      r.indexes.forEach(function (i, n) { (r.bit_values[n] ? hit : miss).push(i); });
      draw({ hit: hit, miss: miss });
      var title = r.result === 'ABSENT' ? 'Definitely not present' : r.false_positive ? 'False positive: reported present, but never added' : 'Probably present';
      show(r.result === 'ABSENT' ? 'success' : r.false_positive ? 'warning' : 'info', title, r.message, r.indexes, r.bit_values);
    }, function (e) { BG.setBusy(btn, false); fail(e); });
  }

  function findFp() {
    var btn = BG.$('#vz-fp');
    BG.setBusy(btn, true);
    BG.api('/api/visualizer/find-false-positive', { method: 'POST', json: {} }).then(function (r) {
      BG.setBusy(btn, false);
      st.bits = r.bits;
      if (!r.found) { draw(); show('info', 'No false positive found.', r.message); return; }
      learn(r.explained_by);
      draw({ hit: r.indexes });
      show('warning', '"' + r.item + '" is a false positive.', r.message, r.indexes);
    }, function (e) { BG.setBusy(btn, false); fail(e); });
  }

  function reset(m, k, quiet) {
    return BG.api('/api/visualizer/reset', { method: 'POST', json: { m: m, k: k } }).then(function (r) {
      st = { m: r.m, k: r.k, bits: r.bits, words: [] };
      owners = {};
      draw(); drawWords(); BG.clear(resultBox);
      if (!quiet) BG.toast('Filter reset.', 'success');
    }, function (e) { BG.toast(BG.errorText(e), 'error'); });
  }

  form.addEventListener('submit', function (e) { e.preventDefault(); insert(); });
  BG.$('#vz-query').addEventListener('click', query);
  BG.$('#vz-fp').addEventListener('click', findFp);
  BG.$('#vz-reset').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target;
    var go = function () { reset(Number(f.elements.m.value), Number(f.elements.k.value)); };
    if (st.words.length) BG.confirm({ title: 'Reset the demo filter?', message: 'The ' + st.words.length + ' words you added will be removed. Your real blacklist is not affected.', confirmText: 'Reset' }).then(function (ok) { if (ok) go(); });
    else go();
  });

  /* ---- initial state (the demo filter survives page reloads on the server) --------------- */
  BG.api('/api/visualizer/state').then(function (r) {
    st = { m: r.m, k: r.k, bits: r.bits, words: r.words || [] };
    BG.$('#vz-m').value = String(r.m); BG.$('#vz-k').value = String(r.k);
    draw(); drawWords();
  }, function (e) { show('danger', 'Could not load the visualizer.', BG.errorText(e)); });
});
