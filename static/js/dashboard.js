/* Dashboard: filter overview, counters, memory comparison, recent checks. */
BG.ready(function () {
  'use strict';
  var root = BG.$('#dash');
  var notices = BG.$('#notices');
  var CELLS = 128;

  function stat(label, value, sub) {
    return BG.h('div', { class: 'stat' },
      BG.h('div', { class: 'stat__label', text: label }),
      BG.h('div', { class: 'stat__value', text: value }),
      sub ? BG.h('div', { class: 'stat__sub', text: sub }) : null);
  }

  function dismissedRebuild() { try { return sessionStorage.getItem('bg-rebuilt-dismissed') === '1'; } catch (e) { return false; } }

  function renderNotices(info) {
    BG.clear(notices);
    if (info.over_capacity) {
      notices.appendChild(BG.alert('warning', 'This filter is over capacity.',
        BG.fmtInt(info.item_count) + ' items are stored but it was sized for ' + BG.fmtInt(info.n_capacity) + '. False positives are now above the ' + BG.fmtPct(info.target_fp) + ' target. Rebuild it with a larger size in Settings.'));
    }
    if (info.rebuilt_on_startup && !dismissedRebuild()) {
      notices.appendChild(BG.alert('info', 'The filter was rebuilt on startup.',
        'The saved snapshot was missing or out of date, so BloomGuard rebuilt it from the database. No data was lost.',
        function () { try { sessionStorage.setItem('bg-rebuilt-dismissed', '1'); } catch (e) { /* ignore */ } }));
    }
  }

  function renderHero(info) {
    var pct = BG.fmtPct(info.fill_ratio);
    var grid = BG.bitGrid(CELLS, BG.fillCells(CELLS, info.fill_ratio), { dark: true });
    return BG.h('section', { class: 'hero', 'aria-label': 'Filter overview' },
      BG.h('div', null,
        BG.h('h2', { text: info.name }),
        BG.h('p', { class: 'hero__meta', text: (info.type === 'counting' ? 'Counting filter' : 'Standard filter') + ', ' + BG.fmtInt(info.m_bits) + ' bits, ' + info.k_hashes + ' hash functions' }),
        BG.h('div', { class: 'hero__status' },
          info.over_capacity
            ? BG.h('span', { class: 'badge badge--warning' }, BG.icon('alert'), 'Over capacity')
            : BG.h('span', { class: 'badge' }, BG.icon('check-circle'), 'Within capacity'),
          BG.h('span', { class: 'badge', text: info.type === 'counting' ? 'Items can be removed' : 'Add only' }))),
      BG.h('div', null,
        BG.h('div', { class: 'hero__pct' }, BG.h('b', { text: pct }), 'of bits are switched on'),
        grid,
        BG.h('p', { class: 'bits-caption', text: 'Each square stands for a slice of the filter. A filter fills up as items are added, and the fuller it gets, the more false positives it produces.' })));
  }

  function renderStats(info) {
    var c = info.counters;
    var load = info.n_capacity ? info.item_count / info.n_capacity : 0;
    return BG.h('section', { class: 'card card--flush', style: 'margin-top:24px', 'aria-label': 'Key numbers' },
      BG.h('div', { class: 'stat-row' },
        stat('Items stored', BG.fmtInt(info.item_count), BG.fmtPct(load) + ' of ' + BG.fmtInt(info.n_capacity) + ' planned'),
        stat('Estimated false positives', BG.fmtPct(info.estimated_fp), 'Target ' + BG.fmtPct(info.target_fp)),
        stat('Checks run', BG.fmtInt(c.checks), BG.fmtInt(c.clean) + ' clean'),
        stat('Blacklist hits', BG.fmtInt(c.blacklisted), BG.fmtInt(c.false_positives) + ' false positives caught')));
  }

  function meter(label, bytes, max, cls) {
    return BG.h('div', { class: 'meter' },
      BG.h('div', { class: 'meter__top' }, BG.h('span', { text: label }), BG.h('b', { text: BG.fmtBytes(bytes) })),
      BG.h('div', { class: 'meter__track' },
        BG.h('div', { class: 'meter__bar ' + cls, style: 'width:' + Math.max(1, Math.min(100, (bytes / max) * 100)).toFixed(2) + '%' })));
  }

  function renderMemory(info, calc) {
    var card = BG.h('section', { class: 'card', 'aria-labelledby': 'mem-title' },
      BG.h('div', { class: 'card__head' }, BG.h('div', null,
        BG.h('h3', { id: 'mem-title', text: 'Memory at full capacity' }),
        BG.h('p', { text: 'The filter against a Python set holding the same number of items.' }))));
    if (!calc) {
      card.appendChild(BG.h('p', { class: 'muted', text: 'The comparison is not available right now.' }));
      return card;
    }
    var max = Math.max(calc.bloom_bytes, calc.set_bytes_estimate);
    var ratio = calc.set_bytes_estimate / calc.bloom_bytes;
    card.appendChild(BG.h('div', { class: 'stack stack--sm' },
      meter(info.type === 'counting' ? 'Counting filter' : 'Bloom filter', calc.bloom_bytes, max, ''),
      meter('Python set (estimate)', calc.set_bytes_estimate, max, 'meter__bar--set')));
    card.appendChild(BG.h('p', { class: 'small muted', style: 'margin-top:16px', text: ratio >= 1.05
      ? 'About ' + ratio.toFixed(ratio >= 10 ? 0 : 1) + ' times smaller. The set figure is an estimate for keys of about 15 characters.'
      : 'At this size the filter is not smaller than a set. The set figure is an estimate for keys of about 15 characters.' }));
    return card;
  }

  function renderRecent(items) {
    var card = BG.h('section', { class: 'card', 'aria-labelledby': 'recent-title' },
      BG.h('div', { class: 'card__head' },
        BG.h('div', null, BG.h('h3', { id: 'recent-title', text: 'Recent checks' })),
        BG.h('a', { class: 'btn btn--ghost btn--sm', href: '/history', text: 'View all' })));
    if (!items.length) {
      card.appendChild(BG.empty('search', 'No checks yet', 'Check an item and it will show up here.',
        BG.h('a', { class: 'btn btn--primary', href: '/check', text: 'Check an item' })));
      return card;
    }
    card.appendChild(BG.h('ul', { class: 'recent' }, items.map(function (r) {
      return BG.h('li', null, BG.h('span', { class: 'key', title: r.item_key, text: r.item_key }), BG.verdictBadge(r.verdict));
    })));
    return card;
  }

  function load() {
    Promise.all([
      BG.getFilter(true),
      BG.api('/api/history?page_size=5').catch(function () { return { items: [] }; })
    ]).then(function (res) {
      var info = res[0], hist = res[1];
      BG.updateChip(info);
      renderNotices(info);
      return BG.api('/api/filter/calc', { method: 'POST', json: { n: info.n_capacity, p: info.target_fp, type: info.type } })
        .catch(function () { return null; })
        .then(function (calc) {
          BG.clear(root);
          root.appendChild(renderHero(info));
          root.appendChild(renderStats(info));
          root.appendChild(BG.h('div', { class: 'grid grid--2', style: 'margin-top:24px' }, renderMemory(info, calc), renderRecent(hist.items)));
        });
    }).catch(function (e) {
      if (e.status === 404) { window.location.assign('/setup'); return; }
      BG.clear(root).appendChild(BG.alert('danger', 'Could not load the dashboard.', BG.errorText(e)));
    });
  }
  load();
});
