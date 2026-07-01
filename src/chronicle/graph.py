"""Render a time-scrubbable intelligence graph.

Produces a single self-contained HTML file: a vis-network graph with a time
slider that replays the intelligence picture across every ingested snapshot.
Entities that are new in a step glow green, changed ones amber - so you can
literally watch the picture evolve.
"""

from __future__ import annotations

import json
from pathlib import Path

from .store import Store

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Chronicle - longitudinal intelligence</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; background: #0a0a0a; color: #f0f0f0;
         font-family: -apple-system, Segoe UI, Roboto, sans-serif; }
  #bar { padding: 14px 20px; border-bottom: 1px solid #222; }
  #bar h1 { margin: 0 0 4px; font-size: 16px; font-weight: 600; }
  #meta { font-size: 13px; color: #9aa; min-height: 18px; }
  #controls { display: flex; align-items: center; gap: 14px; margin-top: 10px; }
  #slider { flex: 1; }
  #play { background: #1c1c22; color: #f0f0f0; border: 1px solid #333;
          border-radius: 6px; padding: 6px 12px; cursor: pointer; }
  #legend { font-size: 12px; color: #9aa; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
         margin: 0 4px 0 12px; vertical-align: middle; }
  #net { height: calc(100vh - 132px); width: 100%; }
</style>
</head>
<body>
  <div id="bar">
    <h1>Chronicle &mdash; %TITLE%</h1>
    <div id="meta"></div>
    <div id="controls">
      <button id="play">&#9654; Play</button>
      <input id="slider" type="range" min="0" max="0" value="0" step="1">
      <span id="legend">
        <span class="dot" style="background:#2bb673"></span>new
        <span class="dot" style="background:#e8a13a"></span>changed
        <span class="dot" style="background:#5566aa"></span>existing
      </span>
    </div>
  </div>
  <div id="net"></div>
<script>
const STATES = %STATES%;
const COLOR = { new: "#2bb673", changed: "#e8a13a", existing: "#5566aa" };
const BORDER = { new: "#7fffbf", changed: "#ffd27f", existing: "#334" };
const nodes = new vis.DataSet([]);
const edges = new vis.DataSet([]);
const net = new vis.Network(document.getElementById("net"), {nodes, edges}, {
  physics: { barnesHut: { gravitationalConstant: -8000, springLength: 150 } },
  nodes: { shape: "dot", size: 18, font: { color: "#f0f0f0" } },
  edges: { arrows: "to", color: { color: "#556", highlight: "#88a" },
           font: { color: "#8899aa", size: 11, strokeWidth: 0 } }
});

function render(i) {
  const s = STATES[i];
  document.getElementById("meta").textContent =
    `Snapshot ${i+1}/${STATES.length}  \u00b7  ${s.label}  \u00b7  ${s.observed_at}`
    + (s.brief ? `  \u00b7  ${s.brief}` : "");
  nodes.clear(); edges.clear();
  nodes.add(s.nodes.map(n => ({
    id: n.id, label: n.label, title: n.title,
    color: { background: COLOR[n.status] || COLOR.existing,
             border: BORDER[n.status] || BORDER.existing },
    borderWidth: n.status === "existing" ? 1 : 3
  })));
  edges.add(s.edges.map((e, k) => ({
    id: k, from: e.from, to: e.to, label: e.label,
    color: { color: e.status === "new" ? "#2bb673" : "#556" },
    width: e.status === "new" ? 2.5 : 1
  })));
}

const slider = document.getElementById("slider");
slider.max = STATES.length - 1;
slider.addEventListener("input", () => render(parseInt(slider.value)));
render(0);

let timer = null;
const play = document.getElementById("play");
play.addEventListener("click", () => {
  if (timer) { clearInterval(timer); timer = null; play.innerHTML = "&#9654; Play"; return; }
  play.innerHTML = "&#10073;&#10073; Pause";
  timer = setInterval(() => {
    let v = parseInt(slider.value);
    v = v >= STATES.length - 1 ? 0 : v + 1;
    slider.value = v; render(v);
  }, 1400);
});
</script>
</body>
</html>
"""


def render_timescrub_html(store: Store, out_path: str | Path, title: str = "") -> Path:
    states = store.snapshot_states()
    html = (
        _TEMPLATE
        .replace("%STATES%", json.dumps(states))
        .replace("%TITLE%", title or "longitudinal intelligence")
    )
    out = Path(out_path)
    out.write_text(html, encoding="utf-8")
    return out
