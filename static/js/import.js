/* Import page: file upload with preview, and the sample key generator. */
BG.ready(function () {
  'use strict';
  var MAX_BYTES = 20 * 1024 * 1024;
  var upForm = BG.$('#upload-form'), genForm = BG.$('#gen-form');
  var upBtn = BG.$('#upload-btn'), genBtn = BG.$('#gen-btn');
  var fileInput = BG.$('#file'), drop = BG.$('#drop');
  var fileInfo = BG.$('#file-info'), colField = BG.$('#column-field'), colSelect = BG.$('#u-column');
  var previewEl = BG.$('#preview'), summaryArea = BG.$('#summary-area');
  var chosen = null;      /* File */
  var isCsv = false;

  BG.fillSelect(BG.$('#u-type'), BG.KEY_TYPES);   BG.$('#u-type').value = 'other';
  BG.fillSelect(BG.$('#u-label'), BG.LABELS);     BG.$('#u-label').value = 'fraud';
  BG.fillSelect(BG.$('#g-type'), BG.KEY_TYPES);   BG.$('#g-type').value = 'transaction_id';
  BG.fillSelect(BG.$('#g-label'), BG.LABELS);     BG.$('#g-label').value = 'fraud';

  /* ---- file choice and preview ------------------------------------------------ */
  function parseCsvLine(line) {
    var out = [], cur = '', q = false;
    for (var i = 0; i < line.length; i++) {
      var ch = line[i];
      if (q) {
        if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; }
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === ',') { out.push(cur); cur = ''; }
      else cur += ch;
    }
    out.push(cur);
    return out;
  }

  function sizeText(bytes) { return BG.fmtBytes(bytes); }

  function setFile(file) {
    var field = drop.closest('.field');
    field.classList.remove('has-error');
    if (!file) { clearFile(); return; }
    var name = file.name || '';
    var ext = name.slice(name.lastIndexOf('.')).toLowerCase();
    if (ext !== '.csv' && ext !== '.txt') { clearFile(); BG.fieldError(upForm, 'file', 'Only .csv and .txt files are accepted.'); return; }
    if (file.size === 0) { clearFile(); BG.fieldError(upForm, 'file', 'That file is empty.'); return; }
    if (file.size > MAX_BYTES) { clearFile(); BG.fieldError(upForm, 'file', 'That file is ' + sizeText(file.size) + '. The limit is 20 MB, so split it into smaller files.'); return; }
    chosen = file;
    isCsv = ext === '.csv';
    BG.$('#file-name').textContent = name;
    BG.$('#file-size').textContent = sizeText(file.size);
    fileInfo.hidden = false;
    drop.hidden = true;
    renderPreview(file);
  }
  function clearFile() {
    chosen = null; isCsv = false;
    fileInput.value = '';
    fileInfo.hidden = true;
    drop.hidden = false;
    colField.hidden = true;
    BG.clear(previewEl);
  }

  function renderPreview(file) {
    BG.clear(previewEl);
    colField.hidden = !isCsv;
    var slice = file.slice(0, 65536);
    var reader = slice.text ? slice.text() : new Promise(function (res, rej) {
      var fr = new FileReader(); fr.onload = function () { res(fr.result); }; fr.onerror = rej; fr.readAsText(slice);
    });
    reader.then(function (text) {
      if (chosen !== file) return;
      text = text.replace(/^﻿/, '');
      var lines = text.split(/\r?\n/);
      if (file.size > 65536) lines.pop();                     /* last line may be cut off */
      lines = lines.filter(function (l) { return l.trim() !== ''; });
      if (!lines.length) { previewEl.appendChild(BG.alert('warning', 'No rows to preview.', 'The first part of the file has no readable lines.')); return; }
      if (isCsv) {
        var header = parseCsvLine(lines[0]).map(function (h) { return h.trim(); });
        var rows = lines.slice(1, 6).map(parseCsvLine);
        var seen = {};
        BG.clear(colSelect);
        header.forEach(function (h, i) {
          var dup = h !== '' && seen[h] !== undefined;
          var unusable = h === '' && i > 0;
          if (h !== '' && seen[h] === undefined) seen[h] = i;
          var o = BG.h('option', { value: h, text: unusable ? 'Column ' + (i + 1) + ' (no name)' : dup ? h + ' (duplicate name)' : (h || 'Column 1 (no name)') });
          if (dup || unusable) o.disabled = true;
          colSelect.appendChild(o);
        });
        colSelect.selectedIndex = 0;
        colSelect.onchange = function () { markPicked(header); };
        previewEl.appendChild(BG.h('div', { class: 'small muted', style: 'margin-bottom:8px', text: 'Preview of the first rows. The highlighted column will be imported.' }));
        previewEl.appendChild(BG.h('div', { class: 'preview-table table-wrap' }, BG.h('table', { id: 'prev-table' },
          BG.h('thead', null, BG.h('tr', null, header.map(function (h, i) { return BG.h('th', { 'data-col': i, text: h || ('Column ' + (i + 1)) }); }))),
          BG.h('tbody', null, rows.map(function (r) { return BG.h('tr', null, header.map(function (_, i) { return BG.h('td', { 'data-col': i, text: r[i] === undefined ? '' : r[i] }); })); })))));
        markPicked(header);
      } else {
        previewEl.appendChild(BG.h('div', { class: 'small muted', style: 'margin-bottom:8px', text: 'Preview of the first lines. Each line becomes one item.' }));
        previewEl.appendChild(BG.h('div', { class: 'preview-table table-wrap' }, BG.h('table', null,
          BG.h('tbody', null, lines.slice(0, 5).map(function (l) { return BG.h('tr', null, BG.h('td', { text: l })); })))));
      }
    }, function () {
      previewEl.appendChild(BG.alert('warning', 'Could not preview this file.', 'You can still import it.'));
    });
  }
  function markPicked(header) {
    var idx = colSelect.selectedIndex;
    BG.$$('#prev-table [data-col]').forEach(function (c) { c.classList.toggle('is-picked', Number(c.getAttribute('data-col')) === idx); });
  }

  fileInput.addEventListener('change', function () { setFile(fileInput.files[0]); });
  BG.$('#file-clear').addEventListener('click', function () { clearFile(); });
  ['dragenter', 'dragover'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('is-over'); }); });
  ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function () { drop.classList.remove('is-over'); }); });
  drop.addEventListener('drop', function (e) {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });

  /* ---- result summary ------------------------------------------------------------ */
  function stat(label, value, good) {
    return BG.h('div', { class: 'stat' + (good ? ' stat--good' : '') },
      BG.h('div', { class: 'stat__label', text: label }), BG.h('div', { class: 'stat__value', text: BG.fmtInt(value) }));
  }
  function showSummary(res, title) {
    var f = res.filter || {};
    var box = BG.h('div', { class: 'card' },
      BG.h('div', { class: 'card__head' }, BG.h('div', null,
        BG.h('h2', { text: title }),
        BG.h('p', { text: 'Finished in ' + res.duration_s + ' s. The filter is now ' + BG.fmtPct(f.fill_ratio) + ' full and holds ' + BG.fmtInt(f.item_count) + ' items.' }))),
      BG.h('div', { class: 'summary' },
        stat('Rows read', res.rows_read),
        stat('Added', res.rows_added, true),
        stat('Already on the list', res.rows_duplicate),
        stat('Skipped as invalid', res.rows_invalid)));
    if (res.rows_invalid > 0) box.appendChild(BG.h('p', { class: 'small muted', style: 'margin-top:16px', text: 'Invalid rows were empty or could not be cleaned for the chosen type, so they were skipped.' }));
    if (f.over_capacity) box.appendChild(BG.h('div', { style: 'margin-top:16px' }, BG.alert('warning', 'The filter is over capacity.', 'Rebuild it with a larger size in Settings to bring false positives back down.')));
    BG.clear(summaryArea).appendChild(box);
    BG.getFilter(true).then(BG.updateChip, function () {});
    summaryArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /* ---- upload ----------------------------------------------------------------------- */
  upForm.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(upForm);
    var holder = BG.clear(BG.$('#upload-alert'));
    if (!chosen) { BG.fieldError(upForm, 'file', 'Choose a .csv or .txt file first.'); return; }
    var fd = new FormData();
    fd.append('file', chosen, chosen.name);
    fd.append('key_type', upForm.elements.key_type.value);
    fd.append('label', upForm.elements.label.value);
    if (isCsv && colSelect.value) fd.append('column', colSelect.value);
    BG.setBusy(upBtn, true);
    BG.api('/api/blacklist/bulk', { method: 'POST', form: fd }).then(function (res) {
      BG.setBusy(upBtn, false);
      showSummary(res, 'Import finished');
      BG.toast('Imported ' + BG.fmtInt(res.rows_added) + ' new items.', 'success');
      clearFile();
    }, function (err) {
      BG.setBusy(upBtn, false);
      if (err.field === 'file' && BG.fieldError(upForm, 'file', err.message)) return;
      if (err.field && BG.fieldError(upForm, err.field, err.message)) return;
      holder.appendChild(BG.alert('danger', 'Nothing was imported.', BG.errorText(err)));
    });
  });

  /* ---- generator ---------------------------------------------------------------------- */
  genForm.addEventListener('submit', function (e) {
    e.preventDefault();
    BG.clearErrors(genForm);
    var holder = BG.clear(BG.$('#gen-alert'));
    var count = BG.parseIntLoose(genForm.elements.count.value);
    var start = BG.parseIntLoose(genForm.elements.start.value);
    var bad = false;
    if (count === null || count < 1 || count > 200000) { BG.fieldError(genForm, 'count', 'Enter a whole number from 1 to 200,000.'); bad = true; }
    if (start === null) { BG.fieldError(genForm, 'start', 'Enter a whole number, 0 or higher.'); bad = true; }
    if (genForm.elements.prefix.value.length > 50) { BG.fieldError(genForm, 'prefix', 'Use at most 50 characters.'); bad = true; }
    if (bad) return;
    BG.setBusy(genBtn, true);
    BG.api('/api/blacklist/generate', { method: 'POST', json: {
      count: count, start: start, prefix: genForm.elements.prefix.value,
      key_type: genForm.elements.key_type.value, label: genForm.elements.label.value
    } }).then(function (res) {
      BG.setBusy(genBtn, false);
      showSummary(res, 'Keys generated');
      BG.toast('Generated ' + BG.fmtInt(res.rows_added) + ' new keys.', 'success');
    }, function (err) {
      BG.setBusy(genBtn, false);
      if (err.field && BG.fieldError(genForm, err.field, err.message)) return;
      holder.appendChild(BG.alert('danger', 'No keys were generated.', BG.errorText(err)));
    });
  });

  /* ---- built-in datasets (C12) ---------------------------------------------------- */
  var dsBox = BG.$('#datasets');
  function datasetCard(d) {
    var limit = BG.h('input', { class: 'input', type: 'text', inputmode: 'numeric', autocomplete: 'off',
      placeholder: 'All rows', 'aria-label': 'Maximum rows to load from ' + d.title, id: 'ds-limit-' + d.name });
    var err = BG.h('div', { class: 'error', role: 'alert' });
    var btn = BG.h('button', { class: 'btn btn--secondary', type: 'button' }, 'Load dataset');
    var body;
    if (d.available) {
      btn.addEventListener('click', function () {
        err.textContent = '';
        var raw = limit.value.trim(), n = null;
        if (raw !== '') {
          n = BG.parseIntLoose(raw);
          if (n === null || n < 1 || n > 200000) { err.textContent = 'Enter a whole number from 1 to 200,000, or leave empty.'; limit.focus(); return; }
        }
        BG.setBusy(btn, true);
        BG.api('/api/datasets/load', { method: 'POST', json: n === null ? { name: d.name } : { name: d.name, limit: n } }).then(function (res) {
          BG.setBusy(btn, false);
          showSummary(res, d.title + ' loaded');
          BG.toast('Added ' + BG.fmtInt(res.rows_added) + ' new items.', 'success');
        }, function (e) { BG.setBusy(btn, false); err.textContent = BG.errorText(e); });
      });
      body = BG.h('div', { class: 'stack stack--sm' },
        BG.h('div', { class: 'field' }, BG.h('label', { for: limit.id, text: 'Rows to load (optional)' }), limit, err),
        BG.h('div', { class: 'row' }, btn));
    } else {
      var links = [BG.h('p', { class: 'small muted', text: 'Not found. Put ' + d.expected_files.join(' or ') + ' in the data folder, then reload this page.' })];
      if (d.download_url) links.push(BG.h('a', { class: 'btn btn--ghost btn--sm', href: d.download_url, target: '_blank', rel: 'noopener noreferrer', text: 'Where to download' }));
      body = BG.h('div', { class: 'stack stack--sm' }, links);
    }
    return BG.h('div', { class: 'ds' },
      BG.h('div', { class: 'row row--between' },
        BG.h('h3', { text: d.title }),
        BG.h('span', { class: 'badge ' + (d.available ? 'badge--clean' : 'badge--invalid'), text: d.available ? 'Ready' : 'Missing' })),
      BG.h('p', { class: 'small muted', text: d.description }),
      body);
  }
  BG.api('/api/datasets').then(function (list) {
    BG.clear(dsBox).appendChild(BG.h('div', { class: 'ds-grid' }, list.map(datasetCard)));
  }, function (e) {
    BG.clear(dsBox).appendChild(BG.alert('danger', 'Could not list the datasets.', BG.errorText(e)));
  });
});
