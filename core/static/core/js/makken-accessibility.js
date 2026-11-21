(() => {
  'use strict';
  if (window.MakkenAccessibility) return;

  const STORAGE_KEY = 'makken_a11y_v1';

  const DEFAULT_STATE = {
    profile: '',
    readableFont: false,
    dyslexiaFont: false,
    highlightHeadings: false,
    highlightLinks: false,
    highlightButtons: false,
    hideImages: false,
    tooltips: false,
    stopAnimations: false,
    fontSize: 0,
    lineHeight: 0,
    textSpacing: 0,
    colorMode: '',
    readingGuide: false,
    readingMask: false,
    cursor: '',
  };

  const PROFILES = {
    low_vision: {
      label: 'ضعف البصر',
      icon: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
      apply: {fontSize: 2, highlightLinks: true, highlightButtons: true, colorMode: 'high-saturation'},
    },
    seizure_safe: {
      label: 'النوبات والصرع',
      icon: '<path d="M13 2 3 14h8l-1 8 10-12h-8l1-8Z"/>',
      apply: {stopAnimations: true, colorMode: 'low-saturation'},
    },
    color_blind: {
      label: 'ضعف رؤية الألوان',
      icon: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18Z"/>',
      apply: {colorMode: 'high-saturation', highlightLinks: true, highlightButtons: true, highlightHeadings: true},
    },
    adhd: {
      label: 'ADHD',
      icon: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>',
      apply: {readingMask: true, stopAnimations: true},
    },
    dyslexia: {
      label: 'عسر القراءة',
      icon: '<path d="M4 19 10 5l6 14M6.5 14h7M18 11v8m0-8c1.5 0 2.5 1 2.5 2.5S19.5 16 18 16"/>',
      apply: {dyslexiaFont: true, lineHeight: 1, textSpacing: 1},
    },
    learning: {
      label: 'التعلم',
      icon: '<path d="M4 5h12a3 3 0 0 1 3 3v11H7a3 3 0 0 0-3 3V5Z"/><path d="M4 19a3 3 0 0 1 3-3h12"/>',
      apply: {readingGuide: true, highlightHeadings: true, highlightLinks: true},
    },
  };

  const CONTENT_TILES = [
    {key: 'readableFont', label: 'خط قابل للقراءة', icon: '<path d="M6 19 12 5l6 14M8.5 14h7"/>'},
    {key: 'dyslexiaFont', label: 'خط مناسب لعسر القراءة', icon: '<path d="M4 19 9 7l5 12M6 15h6M16 12h4m-2-2v9"/>'},
    {key: 'highlightHeadings', label: 'تمييز العناوين', icon: '<path d="M6 5v14M18 5v14M6 12h12"/>'},
    {key: 'highlightLinks', label: 'تمييز الروابط', icon: '<path d="M10 13a5 5 0 0 0 7.1 0l2.8-2.8a5 5 0 0 0-7.1-7.1L11 4.9M14 11a5 5 0 0 0-7.1 0L4.1 13.8a5 5 0 0 0 7.1 7.1L13 19.1"/>'},
    {key: 'highlightButtons', label: 'تمييز الأزرار', icon: '<rect x="3" y="7" width="18" height="10" rx="4"/><path d="M9 12h6"/>'},
    {key: 'hideImages', label: 'إخفاء الصور', icon: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 3 18 18"/>'},
    {key: 'tooltips', label: 'التلميحات', icon: '<path d="M4 5h16v11H9l-5 4V5Z"/>'},
    {key: 'stopAnimations', label: 'إيقاف الرسوم المتحركة', icon: '<circle cx="12" cy="12" r="9"/><path d="M10 9v6m4-6v6"/>'},
  ];

  const STEPPERS = [
    {key: 'fontSize', label: 'حجم النص', icon: '<path d="M4 7V5h12v2M10 5v14M15 12h6M18 12v7"/>'},
    {key: 'lineHeight', label: 'ارتفاع السطر', icon: '<path d="M6 5v14m0-14-2 2m2-2 2 2m-2 12-2-2m2 2 2-2M12 7h8M12 12h8M12 17h8"/>'},
    {key: 'textSpacing', label: 'تباعد النص', icon: '<path d="M4 12h16M4 12l3-3m-3 3 3 3m13-3-3-3m3 3-3 3M9 6h6"/>'},
  ];

  const COLOR_TILES = [
    {value: 'dark-contrast', label: 'تباين داكن', icon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>'},
    {value: 'light-contrast', label: 'تباين فاتح', icon: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4"/>'},
    {value: 'invert', label: 'عكس الألوان', icon: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/>'},
    {value: 'color-shift', label: 'تغيير الألوان', icon: '<path d="M12 3a9 9 0 1 0 9 9c0-1.5-1-2.5-2.5-2.5H16a2 2 0 0 1-2-2V5.5C14 4 13.5 3 12 3Z"/>'},
    {value: 'high-saturation', label: 'تشبع عالي', icon: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z"/>'},
    {value: 'low-saturation', label: 'تشبع منخفض', icon: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z"/><path d="M12 9v10"/>'},
    {value: 'monochrome', label: 'أحادي اللون', icon: '<circle cx="12" cy="12" r="9"/><path d="M7 17 17 7"/>'},
  ];

  const ORIENTATION_TILES = [
    {kind: 'bool', key: 'readingGuide', label: 'دليل القراءة', icon: '<path d="M3 12h18M3 8h18M3 16h18"/>'},
    {kind: 'bool', key: 'readingMask', label: 'قناع القراءة', icon: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 15h18"/>'},
    {kind: 'cursor', value: 'black', label: 'مؤشر أسود كبير', icon: '<path d="M6 4v16l4-4 3 6 2-1-3-6h6Z"/>'},
    {kind: 'cursor', value: 'white', label: 'مؤشر أبيض كبير', icon: '<path d="M6 4v16l4-4 3 6 2-1-3-6h6Z"/>'},
  ];

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return {...DEFAULT_STATE};
      const parsed = JSON.parse(raw);
      return {...DEFAULT_STATE, ...(parsed && typeof parsed === 'object' ? parsed : {})};
    } catch (_) {
      return {...DEFAULT_STATE};
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {
      // Ignore storage quota / private mode errors
    }
  }

  let state = loadState();
  let fab, badge, backdrop, drawer, guideEl, maskEl, tooltipEl;

  function activeCount(s) {
    let n = 0;
    ['readableFont', 'dyslexiaFont', 'highlightHeadings', 'highlightLinks', 'highlightButtons', 'hideImages', 'tooltips', 'stopAnimations', 'readingGuide', 'readingMask'].forEach(k => { if (s[k]) n++; });
    ['fontSize', 'lineHeight', 'textSpacing'].forEach(k => { if (Number(s[k]) > 0) n++; });
    if (s.colorMode) n++;
    if (s.cursor) n++;
    return n;
  }

  function applyState() {
    const root = document.documentElement;
    [...root.classList].filter(c => c.startsWith('mk-a11y-')).forEach(c => root.classList.remove(c));

    if (state.readableFont) root.classList.add('mk-a11y-readable-font');
    if (state.dyslexiaFont) root.classList.add('mk-a11y-dyslexia-font');
    if (state.highlightHeadings) root.classList.add('mk-a11y-highlight-headings');
    if (state.highlightLinks) root.classList.add('mk-a11y-highlight-links');
    if (state.highlightButtons) root.classList.add('mk-a11y-highlight-buttons');
    if (state.hideImages) root.classList.add('mk-a11y-hide-images');
    if (state.stopAnimations) root.classList.add('mk-a11y-stop-animations');

    if (state.fontSize >= 1 && state.fontSize <= 3) root.classList.add(`mk-a11y-font-${state.fontSize}`);
    if (state.lineHeight >= 1 && state.lineHeight <= 3) root.classList.add(`mk-a11y-line-${state.lineHeight}`);
    if (state.textSpacing >= 1 && state.textSpacing <= 3) root.classList.add(`mk-a11y-space-${state.textSpacing}`);

    if (state.colorMode) root.classList.add(`mk-a11y-${state.colorMode}`);
    if (state.cursor) root.classList.add(`mk-a11y-cursor-${state.cursor}`);

    if (guideEl) guideEl.hidden = !state.readingGuide;
    if (maskEl) maskEl.hidden = !state.readingMask;
    if (tooltipEl && !state.tooltips) tooltipEl.hidden = true;

    syncDrawerUI();
    saveState(state);
  }

  function syncDrawerUI() {
    const count = activeCount(state);
    if (badge) {
      badge.textContent = String(count);
      badge.hidden = count === 0;
    }
    if (!drawer) return;
    drawer.querySelectorAll('[data-a11y-profile]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(state.profile === btn.dataset.a11yProfile));
    });
    drawer.querySelectorAll('[data-a11y-bool]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(Boolean(state[btn.dataset.a11yBool])));
    });
    drawer.querySelectorAll('[data-a11y-step]').forEach(btn => {
      const [key, lvl] = btn.dataset.a11yStep.split(':');
      btn.setAttribute('aria-pressed', String(Number(state[key]) === Number(lvl)));
    });
    drawer.querySelectorAll('[data-a11y-color]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(state.colorMode === btn.dataset.a11yColor));
    });
    drawer.querySelectorAll('[data-a11y-cursor]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(state.cursor === btn.dataset.a11yCursor));
    });
  }

  function resetAll() {
    state = {...DEFAULT_STATE};
    applyState();
  }

  function openDrawer() {
    if (!drawer) return;
    drawer.hidden = false;
    backdrop.hidden = false;
    fab.setAttribute('aria-expanded', 'true');
    drawer.querySelector('[data-a11y-close]')?.focus({preventScroll: true});
  }

  function closeDrawer(returnFocus = false) {
    if (!drawer || drawer.hidden) return;
    drawer.hidden = true;
    backdrop.hidden = true;
    fab.setAttribute('aria-expanded', 'false');
    if (returnFocus) fab.focus({preventScroll: true});
  }

  function makeSection(title, openByDefault, contentBuilder) {
    const sec = document.createElement('section');
    sec.className = 'mk-a11y-section';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'mk-a11y-section-toggle';
    toggle.setAttribute('aria-expanded', String(openByDefault));
    const label = document.createElement('span');
    label.textContent = title;
    const icon = document.createElement('span');
    icon.className = 'mk-a11y-section-icon';
    icon.setAttribute('aria-hidden', 'true');
    const setIcon = isOpen => {
      icon.innerHTML = isOpen
        ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/></svg>'
        : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
    };
    setIcon(openByDefault);
    toggle.append(label, icon);

    const content = document.createElement('div');
    content.className = 'mk-a11y-section-content';
    content.hidden = !openByDefault;
    contentBuilder(content);

    toggle.addEventListener('click', () => {
      const nextOpen = content.hidden;
      content.hidden = !nextOpen;
      toggle.setAttribute('aria-expanded', String(nextOpen));
      setIcon(nextOpen);
    });

    sec.append(toggle, content);
    return sec;
  }

  function svgEl(paths) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
  }

  function buildUI() {
    if (document.querySelector('.mk-a11y-fab')) return;

    // Floating circular accessibility button (bottom-left)
    fab = document.createElement('button');
    fab.type = 'button';
    fab.className = 'mk-a11y-fab';
    fab.setAttribute('aria-label', 'إعدادات إمكانية الوصول');
    fab.setAttribute('aria-haspopup', 'dialog');
    fab.setAttribute('aria-expanded', 'false');
    fab.title = 'إمكانية الوصول (Alt+A)';
    fab.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" aria-hidden="true"><path d="M0 256a256 256 0 1 1 512 0A256 256 0 1 1 0 256zm161.5-86.1c-12.2-5.2-26.3 .4-31.5 12.6s.4 26.3 12.6 31.5l11.9 5.1c17.3 7.4 35.2 12.9 53.6 16.3v50.1c0 4.3-.7 8.6-2.1 12.6l-28.7 86.1c-4.2 12.6 2.6 26.2 15.2 30.4s26.2-2.6 30.4-15.2l24.4-73.2c1.3-3.8 4.8-6.4 8.8-6.4s7.6 2.6 8.8 6.4l24.4 73.2c4.2 12.6 17.8 19.4 30.4 15.2s19.4-17.8 15.2-30.4l-28.7-86.1c-1.4-4.1-2.1-8.3-2.1-12.6V235.5c18.4-3.5 36.3-8.9 53.6-16.3l11.9-5.1c12.2-5.2 17.8-19.3 12.6-31.5s-19.3-17.8-31.5-12.6L338.7 175c-26.1 11.2-54.2 17-82.7 17s-56.5-5.8-82.7-17l-11.9-5.1zM256 160a40 40 0 1 0 0-80 40 40 0 1 0 0 80z"/></svg>';
    badge = document.createElement('span');
    badge.className = 'mk-a11y-fab-badge';
    badge.hidden = true;
    fab.append(badge);
    fab.addEventListener('click', () => (drawer.hidden ? openDrawer() : closeDrawer(true)));

    backdrop = document.createElement('div');
    backdrop.className = 'mk-a11y-backdrop';
    backdrop.hidden = true;
    backdrop.addEventListener('click', () => closeDrawer(true));

    drawer = document.createElement('aside');
    drawer.className = 'mk-a11y-drawer';
    drawer.setAttribute('role', 'dialog');
    drawer.setAttribute('aria-label', 'إعدادات إمكانية الوصول');
    drawer.hidden = true;

    // Header
    const header = document.createElement('header');
    header.className = 'mk-a11y-header';
    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'mk-a11y-header-btn';
    resetBtn.dataset.a11yReset = '1';
    resetBtn.innerHTML = svgEl('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>') + '<span>إعادة تعيين الإعدادات</span>';
    resetBtn.addEventListener('click', resetAll);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'mk-a11y-header-btn';
    closeBtn.dataset.a11yClose = '1';
    closeBtn.innerHTML = svgEl('<path d="M18 6 6 18M6 6l12 12"/>') + '<span>إغلاق</span>';
    closeBtn.addEventListener('click', () => closeDrawer(true));
    header.append(resetBtn, closeBtn);

    const body = document.createElement('div');
    body.className = 'mk-a11y-body';

    // Section 1: Accessibility Profiles
    body.append(makeSection('ملفات تعريف إمكانية الوصول', true, container => {
      const list = document.createElement('div');
      list.className = 'mk-a11y-profiles';
      Object.entries(PROFILES).forEach(([key, prof]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mk-a11y-profile-btn';
        btn.dataset.a11yProfile = key;
        btn.setAttribute('aria-pressed', 'false');
        btn.innerHTML = svgEl(prof.icon) + `<span>${prof.label}</span>`;
        btn.addEventListener('click', () => {
          if (state.profile === key) {
            state = {...DEFAULT_STATE};
          } else {
            state = {...DEFAULT_STATE, ...prof.apply, profile: key};
          }
          applyState();
        });
        list.append(btn);
      });
      container.append(list);
    }));

    // Section 2: Content Adjustments
    body.append(makeSection('تعديلات المحتوى', true, container => {
      const grid = document.createElement('div');
      grid.className = 'mk-a11y-grid';
      CONTENT_TILES.forEach(tile => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mk-a11y-tile';
        btn.dataset.a11yBool = tile.key;
        btn.setAttribute('aria-pressed', 'false');
        btn.innerHTML = svgEl(tile.icon) + `<span>${tile.label}</span>`;
        btn.addEventListener('click', () => {
          state.profile = '';
          state[tile.key] = !state[tile.key];
          if (tile.key === 'readableFont' && state.readableFont) state.dyslexiaFont = false;
          if (tile.key === 'dyslexiaFont' && state.dyslexiaFont) state.readableFont = false;
          applyState();
        });
        grid.append(btn);
      });
      container.append(grid);

      STEPPERS.forEach(stepper => {
        const box = document.createElement('div');
        box.className = 'mk-a11y-stepper';
        const head = document.createElement('div');
        head.className = 'mk-a11y-stepper-head';
        head.innerHTML = svgEl(stepper.icon) + `<span>${stepper.label}</span>`;
        const levels = document.createElement('div');
        levels.className = 'mk-a11y-stepper-levels';
        [1, 2, 3].forEach(lvl => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'mk-a11y-level-btn';
          btn.dataset.a11yStep = `${stepper.key}:${lvl}`;
          btn.setAttribute('aria-pressed', 'false');
          btn.textContent = '+'.repeat(lvl);
          btn.setAttribute('aria-label', `${stepper.label} مستوى ${lvl}`);
          btn.addEventListener('click', () => {
            state.profile = '';
            state[stepper.key] = Number(state[stepper.key]) === lvl ? 0 : lvl;
            applyState();
          });
          levels.append(btn);
        });
        box.append(head, levels);
        container.append(box);
      });
    }));

    // Section 3: Color Adjustments
    body.append(makeSection('تعديلات الألوان', false, container => {
      const grid = document.createElement('div');
      grid.className = 'mk-a11y-grid';
      COLOR_TILES.forEach(tile => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mk-a11y-tile';
        btn.dataset.a11yColor = tile.value;
        btn.setAttribute('aria-pressed', 'false');
        btn.innerHTML = svgEl(tile.icon) + `<span>${tile.label}</span>`;
        btn.addEventListener('click', () => {
          state.profile = '';
          state.colorMode = state.colorMode === tile.value ? '' : tile.value;
          applyState();
        });
        grid.append(btn);
      });
      container.append(grid);
    }));

    // Section 4: Orientation Adjustments
    body.append(makeSection('تعديلات الاتجاه', false, container => {
      const grid = document.createElement('div');
      grid.className = 'mk-a11y-grid';
      ORIENTATION_TILES.forEach(tile => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mk-a11y-tile';
        btn.setAttribute('aria-pressed', 'false');
        btn.innerHTML = svgEl(tile.icon) + `<span>${tile.label}</span>`;
        if (tile.kind === 'bool') {
          btn.dataset.a11yBool = tile.key;
          btn.addEventListener('click', () => {
            state.profile = '';
            state[tile.key] = !state[tile.key];
            applyState();
          });
        } else {
          btn.dataset.a11yCursor = tile.value;
          btn.addEventListener('click', () => {
            state.profile = '';
            state.cursor = state.cursor === tile.value ? '' : tile.value;
            applyState();
          });
        }
        grid.append(btn);
      });
      container.append(grid);
    }));

    // Footer Help
    const footer = document.createElement('footer');
    footer.className = 'mk-a11y-footer';
    const helpBtn = document.createElement('button');
    helpBtn.type = 'button';
    helpBtn.className = 'mk-a11y-help-btn';
    helpBtn.setAttribute('aria-expanded', 'false');
    helpBtn.innerHTML = svgEl('<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4m0 4h.01"/>') + '<span>مساعدة</span>';
    const helpBox = document.createElement('div');
    helpBox.className = 'mk-a11y-help-box';
    helpBox.hidden = true;
    helpBox.textContent = 'تُحفظ تفضيلات إمكانية الوصول تلقائيًا في متصفحك وتستمر عبر جميع صفحات منصة مكّن. يمكنك فتح القائمة أو إغلاقها بسرعة عبر الاختصار Alt+A، أو العودة للوضع الافتراضي عبر زر «إعادة تعيين الإعدادات».';
    helpBtn.addEventListener('click', () => {
      helpBox.hidden = !helpBox.hidden;
      helpBtn.setAttribute('aria-expanded', String(!helpBox.hidden));
    });
    footer.append(helpBtn, helpBox);

    drawer.append(header, body, footer);

    // Reading Guide, Reading Mask & Live Tooltip overlays
    guideEl = document.createElement('div');
    guideEl.className = 'mk-a11y-reading-guide';
    guideEl.setAttribute('aria-hidden', 'true');
    guideEl.hidden = true;

    maskEl = document.createElement('div');
    maskEl.className = 'mk-a11y-reading-mask';
    maskEl.setAttribute('aria-hidden', 'true');
    maskEl.hidden = true;
    const maskTop = document.createElement('div');
    maskTop.className = 'mk-a11y-mask-top';
    const maskBottom = document.createElement('div');
    maskBottom.className = 'mk-a11y-mask-bottom';
    maskEl.append(maskTop, maskBottom);

    tooltipEl = document.createElement('div');
    tooltipEl.className = 'mk-a11y-tooltip-banner';
    tooltipEl.setAttribute('role', 'status');
    tooltipEl.hidden = true;

    document.body.append(guideEl, maskEl, tooltipEl, backdrop, drawer, fab);

    document.addEventListener('pointermove', event => {
      if (state.readingGuide || state.readingMask) {
        document.documentElement.style.setProperty('--mk-a11y-y', `${event.clientY}px`);
      }
    }, {passive: true});

    document.addEventListener('mouseover', event => {
      if (!state.tooltips) return;
      const target = event.target.closest?.('[title], [aria-label]');
      if (!target || target.closest('.mk-a11y-drawer')) {
        tooltipEl.hidden = true;
        return;
      }
      const text = (target.getAttribute('title') || target.getAttribute('aria-label') || '').trim();
      if (text) {
        tooltipEl.textContent = text;
        tooltipEl.hidden = false;
      } else {
        tooltipEl.hidden = true;
      }
    });

    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && drawer && !drawer.hidden) {
        event.preventDefault();
        closeDrawer(true);
      } else if (event.altKey && (event.key === 'a' || event.key === 'A' || event.key === 'ش')) {
        event.preventDefault();
        drawer.hidden ? openDrawer() : closeDrawer(true);
      }
    });

    applyState();
  }

  window.MakkenAccessibility = {
    open: openDrawer,
    close: closeDrawer,
    reset: resetAll,
    getState: () => ({...state}),
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildUI);
  } else {
    buildUI();
  }
})();
