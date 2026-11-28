/* Pure-SVG CSP-Compliant Responsive Chart Engine for Makken Flexible Analytics */
(function (global) {
  'use strict';

  const PALETTE = [
    '#005b85', '#0ea5e9', '#10b981', '#f59e0b',
    '#6366f1', '#ec4899', '#14b8a6', '#8b5cf6',
    '#ef4444', '#0284c7', '#84cc16', '#f97316'
  ];

  const SVG_NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs, text) {
    const node = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, String(attrs[k]));
      });
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function fmtNum(n) {
    const v = Number(n || 0);
    if (!Number.isFinite(v)) return '0';
    if (Math.abs(v) >= 1000000) return (v / 1000000).toFixed(1) + 'M';
    if (Math.abs(v) >= 10000) return Math.round(v).toLocaleString('en-US');
    return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toFixed(1);
  }

  function truncateLabel(s, maxLen) {
    const str = String(s || '');
    return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str;
  }

  function buildLegend(items) {
    const wrap = document.createElement('div');
    wrap.className = 'fx-chart-legend';
    items.forEach(function (it) {
      const span = document.createElement('span');
      span.className = 'fx-legend-item';
      const dot = document.createElementNS(SVG_NS, 'svg');
      dot.setAttribute('width', '10');
      dot.setAttribute('height', '10');
      dot.appendChild(el('rect', { width: 10, height: 10, rx: 3, fill: it.color }));
      span.appendChild(dot);
      span.appendChild(document.createTextNode(it.label));
      wrap.appendChild(span);
    });
    return wrap;
  }

  function renderChart(container, payload, onPointClick) {
    container.innerHTML = '';
    const labels = payload.labels || [];
    const datasets = payload.datasets || [];
    const chartType = payload.chart_type || 'bar';

    if (!labels.length || !datasets.length) {
      const empty = document.createElement('div');
      empty.className = 'fx-empty';
      empty.textContent = 'لا توجد بيانات مطابقة لعرض هذا الرسم البياني.';
      container.appendChild(empty);
      return;
    }

    const shell = document.createElement('div');
    shell.className = 'fx-chart-shell';

    const W = 620;
    const H = chartType === 'sparkline' ? 110 : 280;
    const svg = el('svg', {
      viewBox: '0 0 ' + W + ' ' + H,
      class: 'fx-chart-svg',
      role: 'img',
      'aria-label': payload.dimension ? payload.dimension.label : 'رسم بياني'
    });

    const firstData = datasets[0].data || [];
    const totalFirst = firstData.reduce(function (a, b) { return a + Math.max(0, Number(b || 0)); }, 0);

    if (chartType === 'pie' || chartType === 'donut') {
      const cx = W / 2;
      const cy = H / 2;
      const r = Math.min(W, H) * 0.4;
      const innerR = chartType === 'donut' ? r * 0.56 : 0;
      let startAngle = -Math.PI / 2;
      const legendItems = [];

      labels.forEach(function (lbl, idx) {
        const val = Math.max(0, Number(firstData[idx] || 0));
        const frac = totalFirst > 0 ? val / totalFirst : 0;
        const angle = frac * Math.PI * 2;
        const endAngle = startAngle + angle;
        const color = PALETTE[idx % PALETTE.length];
        legendItems.push({ label: truncateLabel(lbl, 18) + ' (' + fmtNum(val) + ')', color: color });

        if (frac > 0.999) {
          const circle = el('circle', { cx: cx, cy: cy, r: r, fill: color, class: 'fx-chart-clickable' });
          circle.appendChild(el('title', null, lbl + ': ' + fmtNum(val)));
          if (onPointClick) circle.addEventListener('click', function () { onPointClick(lbl, val); });
          svg.appendChild(circle);
        } else if (frac > 0) {
          const x1 = cx + r * Math.cos(startAngle);
          const y1 = cy + r * Math.sin(startAngle);
          const x2 = cx + r * Math.cos(endAngle);
          const y2 = cy + r * Math.sin(endAngle);
          const largeArc = angle > Math.PI ? 1 : 0;
          let d;
          if (innerR > 0) {
            const ix1 = cx + innerR * Math.cos(endAngle);
            const iy1 = cy + innerR * Math.sin(endAngle);
            const ix2 = cx + innerR * Math.cos(startAngle);
            const iy2 = cy + innerR * Math.sin(startAngle);
            d = [
              'M', x1, y1,
              'A', r, r, 0, largeArc, 1, x2, y2,
              'L', ix1, iy1,
              'A', innerR, innerR, 0, largeArc, 0, ix2, iy2, 'Z'
            ].join(' ');
          } else {
            d = ['M', cx, cy, 'L', x1, y1, 'A', r, r, 0, largeArc, 1, x2, y2, 'Z'].join(' ');
          }
          const path = el('path', { d: d, fill: color, stroke: '#fff', 'stroke-width': 2, class: 'fx-chart-clickable' });
          path.appendChild(el('title', null, lbl + ': ' + fmtNum(val) + ' (' + (frac * 100).toFixed(1) + '%)'));
          if (onPointClick) path.addEventListener('click', function () { onPointClick(lbl, val); });
          svg.appendChild(path);
        }
        startAngle = endAngle;
      });

      if (chartType === 'donut') {
        svg.appendChild(el('text', { x: cx, y: cy - 2, 'text-anchor': 'middle', 'font-size': 20, 'font-weight': 800, fill: '#003b5c' }, fmtNum(totalFirst)));
        svg.appendChild(el('text', { x: cx, y: cy + 16, 'text-anchor': 'middle', 'font-size': 11, fill: '#5a7184' }, 'الإجمالي'));
      }
      shell.appendChild(svg);
      shell.appendChild(buildLegend(legendItems.slice(0, 8)));
      container.appendChild(shell);
      return;
    }

    if (chartType === 'gauge' || chartType === 'progress_ring') {
      const val = Number(firstData[0] || 0);
      const maxVal = Math.max(100, val);
      const pct = Math.max(0, Math.min(1, val / maxVal));
      const ringColor = (pct * 100) >= 50 ? '#0d8a68' : '#c0394d';
      const ringTextColor = (pct * 100) >= 50 ? '#0a664d' : '#8f2536';
      const cx = W / 2;
      const cy = chartType === 'gauge' ? H * 0.72 : H / 2;
      const r = 88;
      if (chartType === 'gauge') {
        svg.appendChild(el('path', {
          d: 'M ' + (cx - r) + ' ' + cy + ' A ' + r + ' ' + r + ' 0 0 1 ' + (cx + r) + ' ' + cy,
          fill: 'none', stroke: '#e2eef5', 'stroke-width': 20, 'stroke-linecap': 'round'
        }));
        const ang = Math.PI * (1 - pct);
        const ex = cx + r * Math.cos(ang);
        const ey = cy - r * Math.sin(ang);
        svg.appendChild(el('path', {
          d: 'M ' + (cx - r) + ' ' + cy + ' A ' + r + ' ' + r + ' 0 0 1 ' + ex + ' ' + ey,
          fill: 'none', stroke: ringColor, 'stroke-width': 20, 'stroke-linecap': 'round'
        }));
        svg.appendChild(el('text', { x: cx, y: cy - 12, 'text-anchor': 'middle', 'font-size': 26, 'font-weight': 800, fill: ringTextColor }, fmtNum(val)));
        svg.appendChild(el('text', { x: cx, y: cy + 16, 'text-anchor': 'middle', 'font-size': 12, fill: '#5a7184' }, truncateLabel(labels[0], 28)));
      } else {
        const circ = 2 * Math.PI * r;
        svg.appendChild(el('circle', { cx: cx, cy: cy, r: r, fill: 'none', stroke: '#e2eef5', 'stroke-width': 18 }));
        svg.appendChild(el('circle', {
          cx: cx, cy: cy, r: r, fill: 'none', stroke: ringColor, 'stroke-width': 18,
          'stroke-dasharray': (circ * pct) + ' ' + circ,
          transform: 'rotate(-90 ' + cx + ' ' + cy + ')'
        }));
        svg.appendChild(el('text', { x: cx, y: cy + 6, 'text-anchor': 'middle', 'font-size': 24, 'font-weight': 800, fill: ringTextColor }, fmtNum(val)));
      }
      shell.appendChild(svg);
      container.appendChild(shell);
      return;
    }

    if (chartType === 'funnel') {
      const maxVal = Math.max.apply(null, firstData.map(function (x) { return Number(x || 0); }).concat([1]));
      const rowH = Math.min(38, (H - 24) / labels.length);
      labels.forEach(function (lbl, idx) {
        const val = Number(firstData[idx] || 0);
        const wBar = Math.max(70, (val / maxVal) * (W - 180));
        const x = (W - wBar) / 2;
        const y = 12 + idx * (rowH + 6);
        const rect = el('rect', { x: x, y: y, width: wBar, height: rowH, rx: 7, fill: PALETTE[idx % PALETTE.length], class: 'fx-chart-clickable' });
        rect.appendChild(el('title', null, lbl + ': ' + fmtNum(val)));
        if (onPointClick) rect.addEventListener('click', function () { onPointClick(lbl, val); });
        svg.appendChild(rect);
        svg.appendChild(el('text', { x: W / 2, y: y + rowH / 2 + 4, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 700, fill: '#fff' }, truncateLabel(lbl, 20) + ' · ' + fmtNum(val)));
      });
      shell.appendChild(svg);
      container.appendChild(shell);
      return;
    }

    if (chartType === 'horizontal_bar') {
      const maxVal = Math.max.apply(null, firstData.map(function (x) { return Number(x || 0); }).concat([1]));
      const padL = 60;
      const padR = 145;
      const usableW = W - padL - padR;
      const step = (H - 24) / labels.length;
      const barH = Math.max(10, Math.min(24, step * 0.64));

      labels.forEach(function (lbl, idx) {
        const val = Number(firstData[idx] || 0);
        const bw = (val / maxVal) * usableW;
        const y = 14 + idx * step;
        const rect = el('rect', { x: W - padR - bw, y: y, width: Math.max(2, bw), height: barH, rx: 5, fill: PALETTE[0], class: 'fx-chart-clickable' });
        rect.appendChild(el('title', null, lbl + ': ' + fmtNum(val)));
        if (onPointClick) rect.addEventListener('click', function () { onPointClick(lbl, val); });
        svg.appendChild(rect);
        svg.appendChild(el('text', { x: W - padR + 8, y: y + barH / 2 + 4, 'text-anchor': 'start', 'font-size': 11, fill: '#0f293a' }, truncateLabel(lbl, 18)));
        svg.appendChild(el('text', { x: W - padR - bw - 6, y: y + barH / 2 + 4, 'text-anchor': 'end', 'font-size': 11, 'font-weight': 700, fill: ringTextColor }, fmtNum(val)));
      });
      shell.appendChild(svg);
      container.appendChild(shell);
      return;
    }

    if (chartType === 'treemap' || chartType === 'heatmap') {
      const maxVal = Math.max.apply(null, firstData.map(function (x) { return Number(x || 0); }).concat([1]));
      const cols = Math.ceil(Math.sqrt(labels.length));
      const rows = Math.ceil(labels.length / cols);
      const cellW = (W - 20) / cols;
      const cellH = (H - 20) / rows;
      labels.forEach(function (lbl, idx) {
        const val = Number(firstData[idx] || 0);
        const rIdx = Math.floor(idx / cols);
        const cIdx = idx % cols;
        const intensity = 0.25 + 0.75 * (val / maxVal);
        const fill = chartType === 'heatmap' ? 'rgba(0, 91, 133, ' + intensity.toFixed(2) + ')' : PALETTE[idx % PALETTE.length];
        const rect = el('rect', {
          x: 10 + cIdx * cellW + 3,
          y: 10 + rIdx * cellH + 3,
          width: cellW - 6,
          height: cellH - 6,
          rx: 8,
          fill: fill,
          class: 'fx-chart-clickable'
        });
        rect.appendChild(el('title', null, lbl + ': ' + fmtNum(val)));
        if (onPointClick) rect.addEventListener('click', function () { onPointClick(lbl, val); });
        svg.appendChild(rect);
        svg.appendChild(el('text', { x: 10 + cIdx * cellW + cellW / 2, y: 10 + rIdx * cellH + cellH / 2 - 2, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: '#fff' }, truncateLabel(lbl, 14)));
        svg.appendChild(el('text', { x: 10 + cIdx * cellW + cellW / 2, y: 10 + rIdx * cellH + cellH / 2 + 14, 'text-anchor': 'middle', 'font-size': 11, fill: '#fff' }, fmtNum(val)));
      });
      shell.appendChild(svg);
      container.appendChild(shell);
      return;
    }

    if (chartType === 'radar') {
      const cx = W / 2;
      const cy = H / 2;
      const r = Math.min(W, H) * 0.36;
      const maxVal = Math.max.apply(null, firstData.map(function (x) { return Number(x || 0); }).concat([1]));
      const count = labels.length;
      [0.33, 0.66, 1].forEach(function (lvl) {
        svg.appendChild(el('circle', { cx: cx, cy: cy, r: r * lvl, fill: 'none', stroke: '#dbe7ef', 'stroke-width': 1 }));
      });
      const pts = [];
      labels.forEach(function (lbl, idx) {
        const ang = (Math.PI * 2 * idx) / count - Math.PI / 2;
        const val = Number(firstData[idx] || 0);
        const rad = (val / maxVal) * r;
        pts.push((cx + rad * Math.cos(ang)).toFixed(1) + ',' + (cy + rad * Math.sin(ang)).toFixed(1));
        const lx = cx + (r + 18) * Math.cos(ang);
        const ly = cy + (r + 18) * Math.sin(ang);
        svg.appendChild(el('text', { x: lx, y: ly, 'text-anchor': 'middle', 'font-size': 10.5, fill: '#0f293a' }, truncateLabel(lbl, 12)));
      });
      svg.appendChild(el('polygon', { points: pts.join(' '), fill: 'rgba(0,91,133,0.22)', stroke: '#005b85', 'stroke-width': 2.5 }));
      shell.appendChild(svg);
      container.appendChild(shell);
      return;
    }

    // Cartesian charts: bar, grouped_bar, stacked_bar, stacked_100_bar, line, smooth_line, area, stacked_area, combo, waterfall, lollipop, scatter, bubble, sparkline
    const padT = 18;
    const padB = chartType === 'sparkline' ? 12 : 48;
    const padL = chartType === 'sparkline' ? 12 : 52;
    const padR = 16;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    const isStacked = chartType === 'stacked_bar' || chartType === 'stacked_100_bar' || chartType === 'stacked_area';
    let maxVal = 1;
    if (chartType === 'stacked_100_bar') {
      maxVal = 100;
    } else if (isStacked) {
      labels.forEach(function (_, idx) {
        let sum = 0;
        datasets.forEach(function (ds) { sum += Math.max(0, Number(ds.data[idx] || 0)); });
        if (sum > maxVal) maxVal = sum;
      });
    } else {
      datasets.forEach(function (ds) {
        (ds.data || []).forEach(function (v) { if (Number(v || 0) > maxVal) maxVal = Number(v || 0); });
      });
    }

    if (chartType !== 'sparkline') {
      for (let g = 0; g <= 4; g++) {
        const gy = padT + (plotH * g) / 4;
        const gv = maxVal * (1 - g / 4);
        svg.appendChild(el('line', { x1: padL, y1: gy, x2: W - padR, y2: gy, stroke: '#e8f0f5', 'stroke-width': 1 }));
        svg.appendChild(el('text', { x: padL - 6, y: gy + 4, 'text-anchor': 'end', 'font-size': 10, fill: '#5a7184' }, fmtNum(gv)));
      }
    }

    const groupStep = plotW / Math.max(1, labels.length);
    const isLineLike = chartType === 'line' || chartType === 'smooth_line' || chartType === 'area' || chartType === 'stacked_area' || chartType === 'sparkline';

    if (isLineLike) {
      datasets.forEach(function (ds, dsIdx) {
        const color = PALETTE[dsIdx % PALETTE.length];
        const coords = labels.map(function (_, idx) {
          const val = Number(ds.data[idx] || 0);
          const x = padL + idx * groupStep + groupStep / 2;
          const y = padT + plotH - (val / maxVal) * plotH;
          return { x: x, y: y, val: val, lbl: labels[idx] };
        });
        const dLine = coords.map(function (c, i) { return (i === 0 ? 'M ' : 'L ') + c.x.toFixed(1) + ' ' + c.y.toFixed(1); }).join(' ');
        if (chartType === 'area' || chartType === 'stacked_area') {
          const dArea = dLine + ' L ' + coords[coords.length - 1].x.toFixed(1) + ' ' + (padT + plotH) + ' L ' + coords[0].x.toFixed(1) + ' ' + (padT + plotH) + ' Z';
          svg.appendChild(el('path', { d: dArea, fill: color, 'fill-opacity': 0.16 }));
        }
        svg.appendChild(el('path', { d: dLine, fill: 'none', stroke: color, 'stroke-width': 2.6, 'stroke-linecap': 'round' }));
        if (chartType !== 'sparkline') {
          coords.forEach(function (c) {
            const dot = el('circle', { cx: c.x, cy: c.y, r: 4.5, fill: color, stroke: '#fff', 'stroke-width': 1.5, class: 'fx-chart-clickable' });
            dot.appendChild(el('title', null, c.lbl + ' (' + ds.label + '): ' + fmtNum(c.val)));
            if (onPointClick) dot.addEventListener('click', function () { onPointClick(c.lbl, c.val); });
            svg.appendChild(dot);
          });
        }
      });
    } else if (chartType === 'scatter' || chartType === 'bubble') {
      labels.forEach(function (lbl, idx) {
        const val = Number(firstData[idx] || 0);
        const x = padL + idx * groupStep + groupStep / 2;
        const y = padT + plotH - (val / maxVal) * plotH;
        const rad = chartType === 'bubble' ? Math.max(6, Math.min(22, 6 + (val / maxVal) * 16)) : 6;
        const dot = el('circle', { cx: x, cy: y, r: rad, fill: PALETTE[idx % PALETTE.length], 'fill-opacity': 0.78, class: 'fx-chart-clickable' });
        dot.appendChild(el('title', null, lbl + ': ' + fmtNum(val)));
        if (onPointClick) dot.addEventListener('click', function () { onPointClick(lbl, val); });
        svg.appendChild(dot);
      });
    } else if (chartType === 'lollipop') {
      labels.forEach(function (lbl, idx) {
        const val = Number(firstData[idx] || 0);
        const x = padL + idx * groupStep + groupStep / 2;
        const y = padT + plotH - (val / maxVal) * plotH;
        svg.appendChild(el('line', { x1: x, y1: padT + plotH, x2: x, y2: y, stroke: PALETTE[0], 'stroke-width': 2.5 }));
        const head = el('circle', { cx: x, cy: y, r: 6.5, fill: PALETTE[0], class: 'fx-chart-clickable' });
        head.appendChild(el('title', null, lbl + ': ' + fmtNum(val)));
        if (onPointClick) head.addEventListener('click', function () { onPointClick(lbl, val); });
        svg.appendChild(head);
      });
    } else {
      // Bar / Grouped Bar / Stacked Bar / Waterfall / Combo
      labels.forEach(function (lbl, idx) {
        const gx = padL + idx * groupStep;
        if (isStacked) {
          let sumGroup = 0;
          datasets.forEach(function (ds) { sumGroup += Math.max(0, Number(ds.data[idx] || 0)); });
          let accH = 0;
          const bw = Math.max(10, Math.min(44, groupStep * 0.6));
          datasets.forEach(function (ds, dsIdx) {
            const raw = Math.max(0, Number(ds.data[idx] || 0));
            const val = chartType === 'stacked_100_bar' ? (sumGroup > 0 ? (raw / sumGroup) * 100 : 0) : raw;
            const bh = (val / maxVal) * plotH;
            const y = padT + plotH - accH - bh;
            const rect = el('rect', { x: gx + (groupStep - bw) / 2, y: y, width: bw, height: Math.max(1, bh), fill: PALETTE[dsIdx % PALETTE.length], class: 'fx-chart-clickable' });
            rect.appendChild(el('title', null, lbl + ' · ' + ds.label + ': ' + fmtNum(raw)));
            if (onPointClick) rect.addEventListener('click', function () { onPointClick(lbl, raw); });
            svg.appendChild(rect);
            accH += bh;
          });
        } else {
          const barDsCount = chartType === 'combo' && datasets.length > 1 ? 1 : datasets.length;
          const totalBarW = Math.min(groupStep * 0.72, 54);
          const singleW = Math.max(6, totalBarW / barDsCount - 2);
          const startX = gx + (groupStep - totalBarW) / 2;
          for (let dsIdx = 0; dsIdx < barDsCount; dsIdx++) {
            const ds = datasets[dsIdx];
            const val = Math.max(0, Number(ds.data[idx] || 0));
            const bh = (val / maxVal) * plotH;
            const y = padT + plotH - bh;
            const rect = el('rect', {
              x: startX + dsIdx * (singleW + 2),
              y: y,
              width: singleW,
              height: Math.max(2, bh),
              rx: 4,
              fill: PALETTE[dsIdx % PALETTE.length],
              class: 'fx-chart-clickable'
            });
            rect.appendChild(el('title', null, lbl + ' · ' + ds.label + ': ' + fmtNum(val)));
            if (onPointClick) rect.addEventListener('click', function () { onPointClick(lbl, val); });
            svg.appendChild(rect);
          }
        }
      });

      if (chartType === 'combo' && datasets.length > 1) {
        const lineDs = datasets[1];
        const pts = labels.map(function (_, idx) {
          const val = Number(lineDs.data[idx] || 0);
          const x = padL + idx * groupStep + groupStep / 2;
          const y = padT + plotH - (val / maxVal) * plotH;
          return (idx === 0 ? 'M ' : 'L ') + x.toFixed(1) + ' ' + y.toFixed(1);
        }).join(' ');
        svg.appendChild(el('path', { d: pts, fill: 'none', stroke: PALETTE[1], 'stroke-width': 2.6 }));
      }
    }

    if (chartType !== 'sparkline') {
      labels.forEach(function (lbl, idx) {
        const x = padL + idx * groupStep + groupStep / 2;
        svg.appendChild(el('text', {
          x: x,
          y: H - 18,
          'text-anchor': 'middle',
          'font-size': 10,
          fill: '#334e68'
        }, truncateLabel(lbl, labels.length > 8 ? 9 : 14)));
      });
    }

    shell.appendChild(svg);
    if (datasets.length > 1 || chartType !== 'sparkline') {
      shell.appendChild(buildLegend(datasets.map(function (ds, idx) {
        return { label: ds.label, color: PALETTE[idx % PALETTE.length] };
      })));
    }
    container.appendChild(shell);
  }

  global.MakkenFlexCharts = { renderChart: renderChart };
})(window);
