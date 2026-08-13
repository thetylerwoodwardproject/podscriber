window.PS = window.PS || {};

var SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs) {
  var el = document.createElementNS(SVG_NS, tag);
  for (var k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

// A rect with rounded top corners, square at the baseline (mark spec for columns).
function roundedTopRectPath(x, y, w, h, r) {
  r = Math.min(r, w / 2, Math.max(h, 0));
  return "M" + x + "," + (y + h) +
    "L" + x + "," + (y + r) +
    "Q" + x + "," + y + " " + (x + r) + "," + y +
    "L" + (x + w - r) + "," + y +
    "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
    "L" + (x + w) + "," + (y + h) +
    "Z";
}

function statsTooltip() {
  if (!PS._statsTooltip) {
    PS._statsTooltip = document.createElement("div");
    PS._statsTooltip.className = "stats-tooltip";
    document.body.appendChild(PS._statsTooltip);
  }
  return PS._statsTooltip;
}

function showTooltip(el, text) {
  var tooltip = statsTooltip();
  var rect = el.getBoundingClientRect();
  tooltip.textContent = text;
  tooltip.style.left = (rect.left + rect.width / 2) + "px";
  tooltip.style.top = (rect.top - 6) + "px";
  tooltip.classList.add("visible");
}

function hideTooltip() {
  statsTooltip().classList.remove("visible");
}

function readJsonAttr(el, name) {
  try {
    return JSON.parse(el.getAttribute(name) || "[]");
  } catch (e) {
    return [];
  }
}

// Line + area trend chart — one series, so no legend box (title/subtitle already says what's plotted).
function renderLineChart(container, points) {
  container.innerHTML = "";
  if (!points.length) return;

  var W = 640, H = 180, top = 10, bottom = 138, left = 34, right = 8;
  var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, class: "stats-chart", role: "img" });

  var counts = points.map(function (p) { return p.count; });
  var peak = Math.max.apply(null, counts) || 1;
  var n = points.length;
  var xStep = n > 1 ? (W - left - right) / (n - 1) : 0;
  var xAt = function (i) { return left + i * xStep; };
  var yAt = function (c) { return bottom - (c / peak) * (bottom - top); };

  [0, 0.5, 1].forEach(function (frac) {
    var y = bottom - frac * (bottom - top);
    svg.appendChild(svgEl("line", { class: "grid-line", x1: left, x2: W - right, y1: y, y2: y }));
    var label = svgEl("text", { class: "axis-label", x: left - 6, y: y + 3, "text-anchor": "end" });
    label.textContent = Math.round(peak * frac).toLocaleString();
    svg.appendChild(label);
  });

  var linePoints = points.map(function (p, i) { return xAt(i) + "," + yAt(p.count); });
  var areaD = "M" + linePoints.join(" L") + " L" + xAt(n - 1) + "," + bottom + " L" + xAt(0) + "," + bottom + " Z";
  svg.appendChild(svgEl("path", { class: "area-mark", d: areaD }));
  svg.appendChild(svgEl("path", { class: "line-mark", d: "M" + linePoints.join(" L") }));

  var labelEvery = n > 8 ? 2 : 1;
  points.forEach(function (p, i) {
    if (i % labelEvery === 0 || i === n - 1) {
      var xl = svgEl("text", { class: "axis-label", x: xAt(i), y: bottom + 16, "text-anchor": "middle" });
      xl.textContent = p.label;
      svg.appendChild(xl);
    }
    var hit = svgEl("circle", { cx: xAt(i), cy: yAt(p.count), r: 10, fill: "transparent" });
    hit.addEventListener("mouseenter", function () { showTooltip(hit, p.label + ": " + p.count.toLocaleString() + " downloads"); });
    hit.addEventListener("mouseleave", hideTooltip);
    svg.appendChild(hit);
  });

  // End dot + direct label at the endpoint only — the one point the story is about.
  var lastX = xAt(n - 1), lastY = yAt(points[n - 1].count);
  svg.appendChild(svgEl("circle", { class: "dot-mark", cx: lastX, cy: lastY, r: 5 }));
  var endLabel = svgEl("text", { class: "value-label", x: lastX, y: lastY - 12, "text-anchor": "end" });
  endLabel.textContent = points[n - 1].count.toLocaleString();
  svg.appendChild(endLabel);

  container.appendChild(svg);
}

// Vertical column chart (e.g. episode-duration distribution) — categorical buckets, one series.
function renderColumnChart(container, bars) {
  container.innerHTML = "";
  if (!bars.length) return;

  var W = 480, H = 170, top = 14, bottom = 130, marginX = 8;
  var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, class: "stats-chart", role: "img" });

  var counts = bars.map(function (b) { return b.count; });
  var peak = Math.max.apply(null, counts) || 1;
  var slot = (W - marginX * 2) / bars.length;
  var barWidth = Math.min(24, slot - 6);

  svg.appendChild(svgEl("line", { class: "grid-line", x1: marginX, x2: W - marginX, y1: bottom, y2: bottom }));

  bars.forEach(function (b, i) {
    var x = marginX + i * slot + (slot - barWidth) / 2;
    var h = Math.max((b.count / peak) * (bottom - top), b.count > 0 ? 2 : 0);
    var y = bottom - h;
    var path = svgEl("path", { class: "bar-mark", d: roundedTopRectPath(x, y, barWidth, h, 4) });
    path.addEventListener("mouseenter", function () { showTooltip(path, b.label + ": " + b.count.toLocaleString() + " episodes"); });
    path.addEventListener("mouseleave", hideTooltip);
    svg.appendChild(path);

    if (b.count === peak && peak > 0) {
      var vl = svgEl("text", { class: "value-label", x: x + barWidth / 2, y: y - 6, "text-anchor": "middle" });
      vl.textContent = b.count.toLocaleString();
      svg.appendChild(vl);
    }

    var xl = svgEl("text", { class: "axis-label", x: x + barWidth / 2, y: bottom + 16, "text-anchor": "middle" });
    xl.textContent = b.label;
    svg.appendChild(xl);
  });

  container.appendChild(svg);
}

// Ranked horizontal bars for the top-episodes list — plain HTML/CSS reads better here than SVG
// text truncation would for arbitrary-length episode titles.
function renderHBarChart(container, episodes) {
  container.innerHTML = "";
  var top = episodes.slice(0, 6);
  if (!top.length) return;

  var peak = Math.max.apply(null, top.map(function (e) { return e.downloads_all; })) || 1;
  var list = document.createElement("div");
  list.style.cssText = "display:flex;flex-direction:column;gap:10px";

  top.forEach(function (ep) {
    var row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:10px";

    var label = document.createElement("div");
    label.textContent = ep.title;
    label.title = ep.title;
    label.style.cssText = "flex:0 0 160px;font-size:12.5px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap";

    var track = document.createElement("div");
    track.style.cssText = "flex:1;background:var(--faint);border-radius:4px;height:16px;overflow:hidden";
    var fill = document.createElement("div");
    var pct = Math.max((ep.downloads_all / peak) * 100, 2);
    fill.style.cssText = "height:100%;width:" + pct + "%;background:var(--accent);border-radius:0 4px 4px 0";
    track.appendChild(fill);
    track.addEventListener("mouseenter", function () { showTooltip(track, ep.title + ": " + ep.downloads_all.toLocaleString() + " downloads"); });
    track.addEventListener("mouseleave", hideTooltip);

    var value = document.createElement("div");
    value.textContent = ep.downloads_all.toLocaleString();
    value.style.cssText = "flex:0 0 auto;font-size:12px;font-weight:600;color:var(--text);font-variant-numeric:tabular-nums;min-width:44px;text-align:right";

    row.appendChild(label);
    row.appendChild(track);
    row.appendChild(value);
    list.appendChild(row);
  });

  container.appendChild(list);
}

// Re-run after initial load and after the Stats/Analytics page's AJAX refresh swaps in fresh content.
PS.initAnalyticsCharts = function () {
  var weekly = document.getElementById("stats-weekly-chart");
  if (weekly) renderLineChart(weekly, readJsonAttr(weekly, "data-weekly-bars"));

  var duration = document.getElementById("stats-duration-chart");
  if (duration) renderColumnChart(duration, readJsonAttr(duration, "data-bars"));

  var topEpisodes = document.getElementById("stats-top-episodes-chart");
  if (topEpisodes) renderHBarChart(topEpisodes, readJsonAttr(topEpisodes, "data-episodes"));
};

PS.initAnalyticsCharts();

(function () {
  var form = document.getElementById("stats-refresh-form");
  if (!form) return;
  var btn = form.querySelector("button[type=submit]");
  var content = document.getElementById("stats-content");

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    PS.clearInlineError(form);
    btn.disabled = true;
    fetch(form.action, { method: "POST" })
      .then(function (res) {
        return res.text().then(function (html) {
          if (!res.ok) throw new Error("Refresh failed");
          return html;
        });
      })
      .then(function (html) {
        content.innerHTML = html;
        PS.initAnalyticsCharts();
        PS.flashSaved(btn, "Refreshed");
      })
      .catch(function (err) {
        PS.showInlineError(form, err.message);
      })
      .finally(function () {
        btn.disabled = false;
      });
  });
})();
