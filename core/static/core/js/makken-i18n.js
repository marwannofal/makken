/* Makken English UI Runtime Localizer (activates ONLY when html[lang="en"], CSP-safe). */
(function () {
  'use strict';

  var lang = (document.documentElement.getAttribute('lang') || 'ar').toLowerCase();
  if (lang.indexOf('en') !== 0) {
    return;
  }

  var AR_RE = /[\u0600-\u06FF]/;
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, PRE: 1, CODE: 1 };
  var ATTRS = ['placeholder', 'aria-label', 'title', 'alt', 'data-label', 'data-empty-text'];

  function getDict() {
    return window.MAKKEN_I18N_EN || {};
  }

  function translateText(raw) {
    if (!raw || !AR_RE.test(raw)) return raw;
    var leadingMatch = raw.match(/^\s*/);
    var trailingMatch = raw.match(/\s*$/);
    var leading = leadingMatch ? leadingMatch[0] : '';
    var trailing = trailingMatch ? trailingMatch[0] : '';
    var core = raw.replace(/\s+/g, ' ').trim();
    if (!core) return raw;

    var dict = getDict();
    if (Object.prototype.hasOwnProperty.call(dict, core)) {
      return leading + dict[core] + trailing;
    }

    if (core.slice(-2) === ' *') {
      var baseStar = core.slice(0, -2).trim();
      if (Object.prototype.hasOwnProperty.call(dict, baseStar)) {
        return leading + dict[baseStar] + ' *' + trailing;
      }
    }

    if (core.slice(-1) === ':') {
      var baseColon = core.slice(0, -1).trim();
      if (Object.prototype.hasOwnProperty.call(dict, baseColon)) {
        return leading + dict[baseColon] + ':' + trailing;
      }
    }

    var m;
    if ((m = core.match(/^عدد السجلات:\s*(.+)$/))) return leading + 'Total Records: ' + m[1] + trailing;
    if ((m = core.match(/^نسبة إنجاز الشراكة:\s*(.+)$/))) return leading + 'Partnership Completion: ' + m[1] + trailing;
    if ((m = core.match(/^عدد البنود:\s*(.+)$/))) return leading + 'Clauses: ' + m[1] + trailing;
    if ((m = core.match(/^آخر تحديث:\s*(.+)$/))) return leading + 'Last Updated: ' + m[1] + trailing;
    if ((m = core.match(/^وقت تحديث اللوحة:\s*(.+)$/))) return leading + 'Dashboard updated: ' + m[1] + trailing;
    if ((m = core.match(/^مرحب[\u064b-\u0652]*ا?[\u064b-\u0652]*\s*[،,]\s*(.*)$/))) return leading + (m[1] ? 'Welcome, ' + m[1] : 'Welcome,') + trailing;
    if ((m = core.match(/^تعديل\s+(.+)$/))) return leading + 'Edit ' + translateText(m[1]) + trailing;
    if ((m = core.match(/^حذف\s+(.+)$/))) return leading + 'Delete ' + translateText(m[1]) + trailing;
    if ((m = core.match(/^إيقاف\s+(.+)$/))) return leading + 'Deactivate ' + translateText(m[1]) + trailing;
    if ((m = core.match(/^تفعيل\s+(.+)$/))) return leading + 'Activate ' + translateText(m[1]) + trailing;
    if ((m = core.match(/^المسؤولية:\s*(.+)$/))) return leading + 'Responsibility: ' + translateText(m[1]) + trailing;
    if ((m = core.match(/^(\d+)\s+بند$/))) return leading + m[1] + ' clause(s)' + trailing;

    return raw;
  }

  function isInsideSwitcher(node) {
    var el = node && node.nodeType === 1 ? node : node && node.parentElement;
    return !!(el && el.closest && el.closest('[data-lang-switcher]'));
  }

  function localizeElement(el) {
    if (!el || el.nodeType !== 1 || SKIP_TAGS[el.tagName] || isInsideSwitcher(el)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var attr = ATTRS[i];
      if (el.hasAttribute(attr)) {
        var cur = el.getAttribute(attr);
        var next = translateText(cur);
        if (next !== cur) el.setAttribute(attr, next);
      }
    }
    if (el.tagName === 'INPUT' && (el.type === 'submit' || el.type === 'button') && el.value) {
      var nextVal = translateText(el.value);
      if (nextVal !== el.value) el.value = nextVal;
    }
  }

  function localizeSubtree(root) {
    if (!root) return;
    if (root.nodeType === 3) {
      if (!isInsideSwitcher(root) && (!root.parentElement || !SKIP_TAGS[root.parentElement.tagName])) {
        var next = translateText(root.nodeValue);
        if (next !== root.nodeValue) root.nodeValue = next;
      }
      return;
    }
    if (root.nodeType !== 1 || SKIP_TAGS[root.tagName] || isInsideSwitcher(root)) return;

    localizeElement(root);

    var walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === 1) {
        localizeElement(node);
      } else if (node.nodeType === 3) {
        if (node.parentElement && !SKIP_TAGS[node.parentElement.tagName] && !isInsideSwitcher(node)) {
          var t = translateText(node.nodeValue);
          if (t !== node.nodeValue) node.nodeValue = t;
        }
      }
    }
  }

  window.mkT = translateText;

  function startObserver() {
    localizeSubtree(document.body);
    if (typeof MutationObserver === 'undefined' || !document.body) return;
    var observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var mut = mutations[i];
        if (mut.type === 'childList') {
          for (var j = 0; j < mut.addedNodes.length; j++) {
            localizeSubtree(mut.addedNodes[j]);
          }
        } else if (mut.type === 'characterData' && mut.target) {
          localizeSubtree(mut.target);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startObserver);
  } else {
    startObserver();
  }
})();
