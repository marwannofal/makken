/* Makken Circular Scroll-Progress & Back-to-Top Indicator (CSP-safe, zero inline styles) */
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var RADIUS = 22;
  var CIRCUMFERENCE = 2 * Math.PI * RADIUS;
  var SHOW_THRESHOLD_PX = 8;

  function createIndicator() {
    var existing = document.querySelector("[data-mk-scroll-progress]");
    if (existing) {
      return existing;
    }

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mk-scroll-progress";
    btn.setAttribute("data-mk-scroll-progress", "1");
    btn.setAttribute("aria-label", "العودة إلى أعلى الصفحة");
    btn.setAttribute("title", "العودة إلى أعلى الصفحة");

    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "mk-scroll-progress-ring");
    svg.setAttribute("viewBox", "0 0 50 50");
    svg.setAttribute("aria-hidden", "true");

    var track = document.createElementNS(SVG_NS, "circle");
    track.setAttribute("class", "mk-scroll-progress-track");
    track.setAttribute("cx", "25");
    track.setAttribute("cy", "25");
    track.setAttribute("r", String(RADIUS));

    var fill = document.createElementNS(SVG_NS, "circle");
    fill.setAttribute("class", "mk-scroll-progress-fill");
    fill.setAttribute("cx", "25");
    fill.setAttribute("cy", "25");
    fill.setAttribute("r", String(RADIUS));
    fill.setAttribute("stroke-dasharray", CIRCUMFERENCE.toFixed(2));
    fill.setAttribute("stroke-dashoffset", CIRCUMFERENCE.toFixed(2));

    svg.appendChild(track);
    svg.appendChild(fill);

    var label = document.createElement("span");
    label.className = "mk-scroll-progress-label";
    label.setAttribute("aria-live", "off");
    label.textContent = "0%";

    btn.appendChild(svg);
    btn.appendChild(label);
    document.body.appendChild(btn);

    return btn;
  }

  function initScrollProgress() {
    if (!document.body) {
      return;
    }
    var btn = createIndicator();
    var fill = btn.querySelector(".mk-scroll-progress-fill");
    var label = btn.querySelector(".mk-scroll-progress-label");
    if (!fill || !label) {
      return;
    }

    var rafId = 0;

    function computePercent() {
      var docEl = document.documentElement;
      var scrollTop = window.pageYOffset || docEl.scrollTop || document.body.scrollTop || 0;
      var scrollHeight = Math.max(docEl.scrollHeight, document.body.scrollHeight);
      var maxScroll = scrollHeight - window.innerHeight;
      if (maxScroll <= 0 || scrollTop <= SHOW_THRESHOLD_PX) {
        return { visible: false, pct: 0 };
      }
      var raw = (scrollTop / maxScroll) * 100;
      var pct = Math.max(1, Math.min(100, Math.round(raw)));
      return { visible: true, pct: pct };
    }

    function update() {
      rafId = 0;
      var state = computePercent();
      btn.classList.toggle("is-visible", state.visible);
      btn.setAttribute("aria-hidden", state.visible ? "false" : "true");
      btn.tabIndex = state.visible ? 0 : -1;

      var offset = CIRCUMFERENCE * (1 - state.pct / 100);
      fill.setAttribute("stroke-dashoffset", offset.toFixed(2));
      label.textContent = state.pct + "%";
    }

    function scheduleUpdate() {
      if (!rafId) {
        rafId = window.requestAnimationFrame(update);
      }
    }

    btn.addEventListener("click", function () {
      var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({
        top: 0,
        behavior: reduced ? "auto" : "smooth",
      });
    });

    window.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate, { passive: true });
    window.addEventListener("load", scheduleUpdate, { passive: true });
    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initScrollProgress, { once: true });
  } else {
    initScrollProgress();
  }
})();
