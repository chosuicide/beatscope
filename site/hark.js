/* Page behaviors for Hark's component library: the nav, the theme toggle, tables, line charts and images. style-gates: data */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;
  root.classList.add("js");
  var LOGO = '<svg width="SIZE" height="SIZE" viewBox="0 0 36 36" fill="none" aria-hidden="true"><path fill="currentColor" d="M25.096 30c-.072 0-.12-.048-.168-.12-4.776-6.384-12.216-10.8-20.736-11.688C4.048 18.168 4 18.096 4 18s.048-.168.192-.192c8.52-.888 15.96-5.304 20.736-11.688.048-.072.096-.12.168-.12s.096.024.168.072A15.02 15.02 0 0 1 31.12 18a15.02 15.02 0 0 1-5.856 11.928c-.072.048-.096.072-.168.072"/></svg>';

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function each(a, f) { return (a || []).map(f).join(""); }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function niceBounds(vals) {
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var step = Math.pow(10, Math.floor(Math.log10(Math.max(hi - lo, 1e-9))));
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    return hi === lo ? [lo - step, hi + step] : [lo, hi];
  }
  function fmtNum(v) { return Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }); }
  function chartSVG(pts, opt, W) {
    W = Math.max(320, Math.round(W || 960));
    var L = 40, R = W - 40, T = 30, Bt = 210;
    var stagger = pts.length > 1 && (R - L) / (pts.length - 1) < 96;
    var nameY = function (i) { return 236 + (stagger && i % 2 ? 16 : 0); };
    var valueY = function (i, py) { return stagger && i % 2 ? Math.min(py + 22, Bt - 4) : py - 13; };
    var H = (opt.numbered ? 268 : 248) + (stagger ? 16 : 0);
    var bounds = niceBounds(pts.length ? pts.map(function (p) { return +p[1]; }) : [0, 1]), lo = bounds[0], hi = bounds[1];
    var x = function (i) { return L + (R - L) * (pts.length < 2 ? 0.5 : i / (pts.length - 1)); };
    var y = function (v) { return Bt - (Bt - T) * (v - lo) / (hi - lo || 1); };
    var unit = opt.unit ? " " + opt.unit : "";
    var line = pts.map(function (p, i) { return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(p[1]).toFixed(1); }).join(" ");
    var svg = '<g class="pf-grid">' + [30, 120, 210].map(function (gy) { return '<line x1="' + L + '" y1="' + gy + '" x2="' + R + '" y2="' + gy + '"></line>'; }).join("") + "</g>" +
      '<text class="pf-axis" x="0" y="34">' + fmtNum(hi) + '</text><text class="pf-axis" x="0" y="124">' + fmtNum((lo + hi) / 2) + '</text><text class="pf-axis" x="0" y="214">' + fmtNum(lo) + "</text>" +
      '<path class="pf-fill" d="' + line + " L" + R + "," + Bt + " L" + L + "," + Bt + ' Z"></path><path class="pf-line" d="' + line + '"></path>';
    pts.forEach(function (p, i) {
      var anchor = i === 0 ? ' text-anchor="start"' : i === pts.length - 1 ? ' text-anchor="end"' : "";
      svg += '<circle class="pf-dot" cx="' + x(i) + '" cy="' + y(p[1]) + '" r="4.5"></circle>' +
        '<text class="pf-alt" x="' + x(i) + '" y="' + valueY(i, y(p[1])) + '"' + anchor + ">" + esc(fmtNum(p[1]) + unit) + "</text>" +
        '<text class="pf-name" x="' + x(i) + '" y="' + nameY(i) + '"' + anchor + ">" + esc(p[0]) + "</text>";
      if (i && opt.numbered) svg += '<text class="pf-num" x="' + ((x(i - 1) + x(i)) / 2) + '" y="' + (H - 10) + '">' + pad2(i) + "</text>";
    });
    return ((opt.caption ? '<p class="chart__cap">' + esc(opt.caption) + "</p>" : "") +
      '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(opt.label || opt.caption || "Line chart") + '">' + svg + "</svg>");
  }

  function contentWidth(el) {
    var cs = getComputedStyle(el);
    return el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  }
  function drawCharts() {
    [].slice.call(doc.querySelectorAll(".chart[data-points]")).forEach(function (p) {
      var pts = p.getAttribute("data-points").split(",").map(function (x) { var m = x.split(":"); return [m[0].trim(), +m[1]]; });
      p.innerHTML = chartSVG(pts, { caption: p.getAttribute("data-caption"), unit: p.getAttribute("data-unit"),
        label: p.getAttribute("aria-label"), numbered: p.hasAttribute("data-numbered") }, contentWidth(p));
    });
  }
  function autoNav() {
    var sections = [].slice.call(doc.querySelectorAll("section[data-nav]"));
    var header = doc.querySelector("header.nav[data-auto]");
    if (header) {
      header.innerHTML = '<nav class="seg" aria-label="Sections">' +
        each(sections, function (s) { return '<a href="#' + esc(s.id) + '">' + esc(s.getAttribute("data-nav")) + "</a>"; }) + "</nav>" +
        '<button class="theme-btn" id="theme-btn" type="button" aria-label="Switch to dark theme"></button>';
    }
    [].slice.call(doc.querySelectorAll(".foot nav[data-auto]")).forEach(function (n) {
      n.innerHTML = '<a href="#top">Top</a>' + each(sections, function (s) { return '<a href="#' + esc(s.id) + '">' + esc(s.getAttribute("data-nav")) + "</a>"; });
    });
    drawCharts();
    window.addEventListener("resize", function () { clearTimeout(drawCharts.t); drawCharts.t = setTimeout(drawCharts, 150); }, { passive: true });
    [].slice.call(doc.querySelectorAll(".table-wrap table")).forEach(function (t) {
      var names = [].map.call(t.querySelectorAll("thead th"), function (th) { return th.textContent.trim(); });
      [].slice.call(t.querySelectorAll("tbody tr")).forEach(function (tr) {
        [].slice.call(tr.children).forEach(function (c, i) {
          if (c.tagName !== "TD") return;
          if (!c.textContent.trim() && !c.querySelector("img, svg")) c.classList.add("is-empty");
          else if (names[i] && !c.hasAttribute("data-label")) c.setAttribute("data-label", names[i]);
        });
      });
    });
    [].slice.call(doc.querySelectorAll(".compare table")).forEach(function (t) {
      t.parentNode.style.setProperty("--compare-cols", t.querySelectorAll("thead th").length);
      [].slice.call(t.querySelectorAll(".compare__media .chip")).forEach(function (chip) {
        chip.closest("th").appendChild(chip);
      });
      [].slice.call(t.querySelectorAll("tbody tr")).forEach(function (tr) {
        var head = tr.querySelector("th"), label = head ? head.textContent.trim() : "";
        [].slice.call(tr.querySelectorAll("td")).forEach(function (td) {
          if (label && !td.hasAttribute("data-label")) td.setAttribute("data-label", label);
        });
      });
    });
    [].slice.call(doc.querySelectorAll(".step__figure img, .band img")).forEach(function (im) {
      var mark = function () { if (im.naturalHeight > im.naturalWidth) im.parentNode.classList.add("is-portrait"); };
      if (im.complete) mark(); else im.addEventListener("load", mark);
    });
    [].slice.call(doc.querySelectorAll(".hark-mark:empty")).forEach(function (m) { m.innerHTML = LOGO.replace(/SIZE/g, m.getAttribute("data-size") || "20"); });
  }

  function behaviors() {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var btn = doc.getElementById("theme-btn"), mq = window.matchMedia("(prefers-color-scheme: dark)");
    try { var saved = localStorage.getItem("hark-theme"); if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved); } catch (e) { /* storage blocked: follow the system theme */ }
    function current() { var t = root.getAttribute("data-theme"); return t === "light" || t === "dark" ? t : (mq.matches ? "dark" : "light"); }
    function label() { if (btn) btn.setAttribute("aria-label", current() === "dark" ? "Switch to light theme" : "Switch to dark theme"); }
    if (btn) btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("hark-theme", next); } catch (e) { /* storage blocked: the choice lasts this visit */ }
      label();
    });
    label();

    var seg = doc.querySelector(".seg");
    if (seg) {
      var links = [].slice.call(seg.querySelectorAll("a"));
      var targets = links.map(function (a) { return doc.getElementById(a.getAttribute("href").slice(1)); });
      var active = -2;
      var reveal = function (i) {
        if (i < 0) return;
        var a = links[i];
        var l = a.offsetLeft - 8, r = a.offsetLeft + a.offsetWidth + 8;
        if (l < seg.scrollLeft || r > seg.scrollLeft + seg.clientWidth) seg.scrollTo({ left: l, behavior: reduce ? "auto" : "smooth" });
      };
      var sync = function (force) {
        var line = window.innerHeight * 0.32, cur = -1;
        targets.forEach(function (t, i) { if (t && t.getBoundingClientRect().top <= line) cur = i; });
        if (cur === active && !force) return;
        active = cur;
        links.forEach(function (a, i) { if (i === cur) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); });
        reveal(cur);
      };
      var ticking = false;
      window.addEventListener("scroll", function () {
        if (ticking) return; ticking = true;
        window.requestAnimationFrame(function () { sync(false); ticking = false; });
      }, { passive: true });
      window.addEventListener("resize", function () { sync(true); }, { passive: true });
      if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(function () { sync(true); });
      sync(true);
    }

    [].slice.call(doc.querySelectorAll(".chart")).forEach(function (chart) {
      if (reduce || !("IntersectionObserver" in window)) { chart.classList.add("is-in"); return; }
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) { chart.classList.add("is-in"); io.disconnect(); } });
      }, { threshold: 0.3 });
      io.observe(chart);
    });
  }

  function start() {
    autoNav();
    behaviors();
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
  else start();
})();
