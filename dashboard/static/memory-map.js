/* Memory Map — interactive view of the kenkeep knowledge base.
   Obsidian-style: hover highlights a node's neighborhood; click opens a
   detail panel with the node's full body and related links.

   Three layout axes, controlled from the toolbar:
   - layout: force-directed (default) or a hierarchy via force-graph's
     dagMode ('td' top-down, 'lr' left-right, 'radialout' concentric).
   - 3D toggle: swaps the 2D canvas renderer (force-graph) for the WebGL
     sibling (3d-force-graph). Same data, same dagMode, orbit/rotate.
   Both libraries share an identical data API, so /api/memory-map feeds
   either one unchanged. */
(function () {
  // Kind colors for nodes with no project. Keep these distinct from the
  // project colors in config/projects.yml so a generic node never reads as
  // belonging to a project.
  const COL = { map: '#818cf8', practice: '#f472b6' };
  const LAYERS = ['L1', 'L2', 'L3'];
  // Dot size. Radius is sqrt(1 + degree) * NODE_R, so a hub reads bigger than a
  // leaf without the area swamping the canvas. 7.2 is 3x the original 2.4: at
  // the zoomed-out fit the old dots were too small to pick out. NODE_RING_GAP
  // spaces the layer rings and scales with it, or they'd sit inside the fill.
  const NODE_R = 8.4;
  const NODE_RING_GAP = 3.4;
  // 3D sphere size, kept in step with NODE_R (was 4).
  const NODE_REL_SIZE_3D = 12;
  // layout key -> dagMode value (null = plain force-directed). 'layers'
  // stratifies by nesting layer (pinned bands), handled in render().
  const DAG = { force: null, layers: null, td: 'td', lr: 'lr', radialout: 'radialout' };

  const el = document.getElementById('mm-graph');
  const empty = document.getElementById('mm-empty');
  const statsEl = document.getElementById('mm-stats');
  const filterEl = document.getElementById('mm-filter');
  const panel = document.getElementById('mm-panel');
  const modeBtns = Array.prototype.slice.call(document.querySelectorAll('.mm-mode'));
  const layerBtns = Array.prototype.slice.call(document.querySelectorAll('.mm-layer'));
  const threeDBtn = document.getElementById('mm-3d');

  let Graph = null;
  let graphData = null;
  // The dataset currently mounted in the graph. Equals graphData normally; when
  // an agent is isolated it's the filtered subgraph from computeView(), so the
  // force engine lays out only those nodes and their structure becomes legible
  // instead of staying scattered across the full graph.
  let view = null;
  let nodeById = {};
  let adj = {};
  let mainHubIds = new Set();
  let labelRects = [];
  let hoverId = null;
  let selectedId = null;
  let query = '';
  // Curation-strip highlight: the set of node ids a clicked curation day added,
  // and the cell currently driving it (null when no day is selected).
  let pulseIds = null;
  let curCell = null;
  const mode = { layout: 'force', threeD: false };
  const activeLayers = new Set(LAYERS);
  // Clicked agent swatch: highlights that project's nodes and dims the rest.
  // null = no agent selected (everything reads normally). Hovering or selecting
  // a node still wins over this, so neighborhood inspection keeps working.
  let activeProject = null;

  fetch('/api/memory-map', { cache: 'no-store' })
    .then((r) => r.json())
    .then(init)
    .catch((err) => {
      // A fetch/parse/render failure is NOT the same as "kenkeep not
      // installed" — say so honestly instead of pointing at bootstrap.
      empty.innerHTML =
        '<p>Couldn’t load the memory map.</p>' +
        '<p class="mm-muted">' + escapeHtml(String(err && err.message || err)) +
        ' — try a hard refresh; if it persists the dashboard server may be ' +
        'running stale code.</p>';
      empty.hidden = false;
      document.getElementById('mm-results-count').textContent = 'Knowledge could not be loaded';
      document.getElementById('mm-review-content').textContent = 'Review sources could not be loaded.';
    });

  function init(data) {
    const exampleNote = document.getElementById('mm-example-note');
    if (exampleNote && data.stats && data.stats.example) exampleNote.hidden = false;
    if (!data.stats.installed || !data.nodes.length) {
      renderReview(data.review, data.curation);
      document.getElementById('mm-results-count').textContent = 'No knowledge items available';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    // graphData first: the legend and the stats line both count nodes, so they
    // must be able to see them.
    graphData = data;
    renderStats();
    renderProjectLegend(data.projects);
    // Disable toggles for layers with no nodes (e.g. before L2/L3 install).
    const L = layerCounts(data.nodes);
    layerBtns.forEach((btn) => {
      if (!(L[btn.dataset.layer] || 0)) btn.classList.add('is-empty');
    });

    data.nodes.forEach((n) => { nodeById[n.id] = n; adj[n.id] = new Set(); });
    data.links.forEach((l) => {
      const sid = l.source.id || l.source;
      const tid = l.target.id || l.target;
      adj[sid].add(tid); adj[tid].add(sid);
    });

    const hubs = data.nodes.slice().sort((a, b) => b.deg - a.deg);
    mainHubIds = new Set(hubs.filter((n) => !n.project).slice(0, 3).map((n) => n.id));
    (data.projects || []).forEach((p) => { const hub = hubs.find((n) => n.project === p.name); if (hub) mainHubIds.add(hub.id); });
    wireControls();
    render();
    renderCuration(data.curation);
    renderReview(data.review, data.curation);

    const resize = () => { if (Graph) Graph.width(el.clientWidth).height(el.clientHeight); };
    window.addEventListener('resize', resize);
  }

  // Count layers from the nodes themselves (robust if stats.layers is absent,
  // e.g. a server still on pre-aggregator code) using the id-derived layer.
  function layerCounts(nodes) {
    const L = { L1: 0, L2: 0, L3: 0 };
    nodes.forEach((n) => { const k = layerOf(n); L[k] = (L[k] || 0) + 1; });
    return L;
  }

  // The stats line describes what you are looking at, so it reports the isolated
  // agent's counts while one is selected -- otherwise the header would claim 257
  // nodes over a view showing 24.
  function renderStats() {
    if (!graphData) return;
    const s = graphData.stats;
    if (!activeProject) {
      const L = layerCounts(graphData.nodes);
      statsEl.innerHTML =
        '<span><b>' + s.total + '</b> nodes</span>' +
        '<span><b>' + (L.L1 || 0) + '</b> L1</span>' +
        '<span><b>' + (L.L2 || 0) + '</b> L2</span>' +
        '<span><b>' + (L.L3 || 0) + '</b> L3</span>' +
        '<span><b>' + s.edges + '</b> links</span>' +
        (s.lineage ? '<span><b>' + s.lineage + '</b> lineage</span>' : '');
      return;
    }
    const v = computeView();
    const own = v.nodes.filter((n) => v._own.has(n.id));
    const L = layerCounts(own);
    const context = v.nodes.length - own.length;
    const inner = v.links.filter((l) => {
      const sid = l.source.id || l.source, tid = l.target.id || l.target;
      return v._own.has(sid) && v._own.has(tid);
    }).length;
    statsEl.innerHTML =
      '<span class="mm-stat-iso">isolating <b>' + escapeHtml(activeProject) +
      '</b></span>' +
      '<span><b>' + own.length + '</b> nodes</span>' +
      (L.L2 ? '<span><b>' + L.L2 + '</b> L2</span>' : '') +
      (L.L3 ? '<span><b>' + L.L3 + '</b> L3</span>' : '') +
      (L.L1 ? '<span><b>' + L.L1 + '</b> L1</span>' : '') +
      '<span><b>' + inner + '</b> internal links</span>' +
      (context ? '<span class="mm-muted"><b>' + context +
        '</b> linked from elsewhere</span>' : '') +
      '<span class="mm-muted">esc to clear</span>';
  }

  // Tear down whatever graph is mounted and build the one the current mode
  // asks for. Switching between force/hierarchy is just a dagMode swap, but
  // 2D<->3D means a different library, so we always rebuild from scratch.
  function render() {
    if (!graphData) return;
    view = computeView();
    renderResults();
    if (Graph && Graph._destructor) { try { Graph._destructor(); } catch (e) { /* noop */ } }
    el.innerHTML = '';
    // dagMode pins nodes by writing fx/fy/fz onto the node objects, and a
    // given instance only clears the pins it set. Those node objects are
    // shared across every rebuild AND across the 2D/3D instances, so a prior
    // hierarchy's pins would otherwise "stick": Force would keep the last
    // tree's shape and 2D/3D would inherit each other's layout. Wipe them on
    // every build; dagMode re-applies its own pins when a hierarchy is active.
    graphData.nodes.forEach((n) => { delete n.fx; delete n.fy; delete n.fz; });
    // Node objects keep the x/y/z the FULL graph gave them, and an isolated
    // subgraph has too few links to pull them back together -- charge only
    // pushes apart. The camera then fits a 3000-unit-wide cloud of 15 dots.
    // Reseeding the mounted nodes near the origin lets the sim lay the subset
    // out on its own scale, which is the whole point of isolating it.
    if (view._own) {
      const spread = 30 + Math.sqrt(view.nodes.length) * 12;
      view.nodes.forEach((n) => {
        n.x = (Math.random() - 0.5) * spread; n.vx = 0;
        n.y = (Math.random() - 0.5) * spread; n.vy = 0;
        if (mode.threeD) { n.z = (Math.random() - 0.5) * spread; n.vz = 0; }
      });
    }
    if (mode.layout === 'layers') applyLayerPins();
    const dag = DAG[mode.layout];
    try {
      Graph = mode.threeD ? build3d(dag) : build2d(dag);
    } catch (error) {
      if (!mode.threeD) throw error;
      mode.threeD = false;
      threeDBtn.classList.remove('is-on');
      threeDBtn.setAttribute('aria-pressed', 'false');
      document.getElementById('mm-view-note').textContent = '3D is unavailable in this browser. Showing the 2D map.';
      el.replaceChildren();
      Graph = build2d(dag);
    }
    Graph.width(el.clientWidth).height(el.clientHeight);
    // Refit once the engine has had a few ticks to lay things out.
    // Refit once the engine has had a few ticks to lay things out. When an agent
    // is isolated, fit to that agent's OWN nodes rather than the whole mounted
    // view, so the dimmed context neighbors don't pull the camera back out.
    const own = view._own;
    const renderedGraph = Graph;
    const fit = (ms) => {
      if (Graph !== renderedGraph || selectedId) return;
      try {
        // fitToIds, not zoomToFit, for an isolated set: 2D zoomToFit on two
        // adjacent nodes scales to an absurd factor and pushes them off the
        // canvas. fitToIds clamps the zoom and centers on the set's bbox.
        if (own && own.size) fitToIds(Array.from(own), ms);
        else Graph.zoomToFit(ms, mode.threeD ? 80 : 64);
      } catch (e) { /* noop */ }
    };
    setTimeout(() => fit(600), 450);
    // The 450ms fit lands mid-layout and the simulation keeps expanding after
    // it, which left an isolated subgraph framed as a speck. Fit again when the
    // engine actually stops -- that is the first moment the positions are final.
    let settled = false;   // once only, or a later cooldown would yank a
    if (Graph.onEngineStop) {   // camera the user has since moved
      Graph.onEngineStop(() => { if (settled) return; settled = true; fit(500); });
    }
  }

  // The dataset to lay out: everything, or one agent's subgraph when isolated.
  //
  // An isolated view keeps the agent's own nodes PLUS every node directly linked
  // to one of them, whatever project those belong to. Dropping to the agent's
  // nodes alone would cut exactly the edges that answer "how is this related to
  // the rest" -- the lineage links up to root rollups, and shared practices two
  // agents both point at. Those neighbors stay dimmed (see inProject), so they
  // read as context rather than as part of the agent.
  function computeView() {
    // A selected curation day isolates exactly like an agent does: mount only
    // that night's nodes plus one hop of context and re-lay them out. Dimming
    // 15 dots inside 364 was technically a highlight and practically invisible.
    if (!activeProject && !pulseIds) return graphData;
    const own = pulseIds
      ? new Set(pulseIds)
      : new Set(graphData.nodes
        .filter((n) => n.project === activeProject).map((n) => n.id));
    const keep = new Set(own);
    graphData.links.forEach((l) => {
      const s = l.source.id || l.source, t = l.target.id || l.target;
      if (own.has(s)) keep.add(t);
      if (own.has(t)) keep.add(s);
    });
    return {
      nodes: graphData.nodes.filter((n) => keep.has(n.id)),
      links: graphData.links.filter((l) => {
        const s = l.source.id || l.source, t = l.target.id || l.target;
        return keep.has(s) && keep.has(t);
      }),
      _own: own,
    };
  }

  // 'layers' layout: stratify nodes into bands by nesting layer (L1 top ->
  // L3 base in 2D; stacked z-planes in 3D), pinning the cross-axis and letting
  // force spread the rest. This is the "what exists at each layer" view.
  function applyLayerPins() {
    const present = LAYERS.filter((Lr) => view.nodes.some((n) => layerOf(n) === Lr));
    const gap = 200;
    view.nodes.forEach((n) => {
      const idx = present.indexOf(layerOf(n));
      if (idx < 0) return;
      const pos = (idx - (present.length - 1) / 2) * gap;
      if (mode.threeD) { n.fz = pos; } else { n.fy = pos; }
    });
  }

  function build2d(dag) {
    const g = ForceGraph()(el)
      .graphData(view)
      .backgroundColor('#0f1117')
      // Keep repainting every frame. We drive highlight state (selectedId)
      // from DOM events force-graph can't see — the close button, Escape,
      // and related-link clicks — so its default redraw-pausing would leave
      // the canvas showing a stale frame after the engine cools down.
      .autoPauseRedraw(false)
      .nodeRelSize(4)
      .nodeVal((n) => 1 + n.deg)
      .onRenderFramePre(() => { labelRects = []; })
      .nodeCanvasObject(drawNode)
      .nodePointerAreaPaint(paintArea)
      .linkColor(linkColor)
      .linkWidth(linkWidth)
      .linkLineDash((l) => (l.class === 'lineage' ? [3, 3] : null))
      .linkDirectionalParticles(linkParticles)
      .linkDirectionalParticleSpeed(0.008)
      .linkDirectionalParticleWidth(2.2)
      .linkDirectionalParticleColor(particleColor)
      .onNodeHover((n) => { hoverId = n ? n.id : null; el.style.cursor = n ? 'pointer' : 'default'; onFocusChange(); })
      .onNodeClick(openPanel)
      .onBackgroundClick(onBackground)
      .d3VelocityDecay(0.28);
    if (dag) g.dagMode(dag).dagLevelDistance(48).onDagError(() => true);
    applyForces(g);
    return g;
  }

  function build3d(dag) {
    const g = ForceGraph3D({ controlType: 'orbit' })(el)
      .graphData(view)
      .backgroundColor('#0f1117')
      .showNavInfo(false)
      .nodeRelSize(NODE_REL_SIZE_3D)
      .nodeVal(nodeVal3d)
      .nodeColor(nodeColor3d)          // rgba alpha drives per-node opacity
      .nodeLabel((n) => n.title)       // hover tooltip (no always-on labels in 3D)
      .linkColor(linkColor3d)
      .linkWidth((l) => (focusTouches(l) ? 0.8 : 0.3))
      .linkOpacity(0.45)
      .linkDirectionalParticles(linkParticles)
      .linkDirectionalParticleSpeed(0.008)
      .linkDirectionalParticleWidth(1.8)
      .linkDirectionalParticleColor(particleColor)
      .onNodeHover((n) => { hoverId = n ? n.id : null; el.style.cursor = n ? 'pointer' : 'default'; onFocusChange(); })
      .onNodeClick(openPanel)
      .onBackgroundClick(onBackground)
      .d3VelocityDecay(0.28);
    if (dag) g.dagMode(dag).dagLevelDistance(70).onDagError(() => true);
    applyForces(g);
    enableIdleOrbit(g);
    return g;
  }

  // A curation night is mostly unlinked nodes, and unlinked nodes are pure
  // repulsion: at the full-graph charge they fly apart until the fit frames a
  // near-empty volume and the highlight reads as three specks. Isolating a
  // night pulls the charge in so the set stays a readable cluster.
  function applyForces(g) {
    g.d3Force('charge').strength(pulseIds ? -70 : -230);
    g.d3Force('link').distance(pulseIds ? 40 : 64);
  }

  // Agent nodes are painted with their project's dashboard color; show a
  // swatch key so those colors are decodable. Each swatch is a toggle button:
  // clicking one highlights only that agent's nodes. Falls back to nothing when
  // no agent nodes are present.
  function renderProjectLegend(projects) {
    const host = document.getElementById('mm-proj-legend');
    if (!host) return;
    if (!projects || !projects.length) { host.innerHTML = ''; return; }
    const counts = {};
    (graphData ? graphData.nodes : []).forEach((n) => {
      if (n.project) counts[n.project] = (counts[n.project] || 0) + 1;
    });
    host.innerHTML =
      '<span class="mm-leg-div"></span>' +
      '<span class="mm-leg-label">agents</span>' +
      projects.map((p) => {
        const c = counts[p.name] || 0;
        return '<button type="button" class="mm-leg-proj" data-project="' +
          escapeHtml(p.name) + '" aria-pressed="false" title="' +
          escapeHtml(p.name) + ' — ' + c + ' node' + (c === 1 ? '' : 's') +
          '. Click to highlight; click again to clear."><span class="mm-dot" ' +
          'style="background:' + p.color + '"></span>' + escapeHtml(p.name) +
          (c ? '<span class="mm-leg-count">' + c + '</span>' : '') + '</button>';
      }).join('');
    Array.prototype.slice.call(host.querySelectorAll('.mm-leg-proj'))
      .forEach((btn) => btn.addEventListener('click', () => {
        selectProject(btn.dataset.project === activeProject
          ? null : btn.dataset.project);
      }));
  }

  // Highlight one agent's nodes (or clear with null). Clearing also drops any
  // node selection made while the agent was highlighted, so the graph returns
  // to a genuinely neutral state rather than a half-focused one.
  function selectProject(name, deferRender) {
    // One isolation at a time: picking an agent drops a curation-day pulse,
    // or computeView() would keep showing the night instead of the agent.
    if (name && pulseIds) {
      pulseIds = null;
      if (curCell) curCell.classList.remove('is-selected');
      curCell = null;
      renderCurationDetail(null, []);
    }
    activeProject = name;
    const host = document.getElementById('mm-proj-legend');
    if (host) {
      Array.prototype.slice.call(host.querySelectorAll('.mm-leg-proj'))
        .forEach((b) => {
          const on = b.dataset.project === activeProject;
          b.classList.toggle('is-active', on);
          b.classList.toggle('is-dim', !!activeProject && !on);
          b.setAttribute('aria-pressed', String(on));
        });
    }
    if (!activeProject) { selectedId = null; closePanel(); }
    // A rebuild, not just a repaint: isolating an agent changes which nodes are
    // in the simulation, so the force engine re-lays out the subgraph and the
    // refit in render() zooms to it. A caller mid-way through its own state
    // change (the curation strip) renders once at the end instead.
    if (!deferRender) render();
    renderStats();
  }

  // True when a node belongs to the highlighted agent. Nodes with no project
  // (generic root knowledge) never match, which is the point: selecting an
  // agent should mute everything that isn't that agent's.
  function inProject(n) {
    return !activeProject || n.project === activeProject;
  }

  function wireControls() {
    modeBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        if (mode.layout === btn.dataset.layout) return;
        mode.layout = btn.dataset.layout;
        modeBtns.forEach((b) => b.classList.toggle('is-active', b === btn));
        render();
      });
    });
    if (threeDBtn) {
      threeDBtn.addEventListener('click', () => {
        document.getElementById('mm-view-note').textContent = '';
        mode.threeD = !mode.threeD;
        threeDBtn.classList.toggle('is-on', mode.threeD);
        threeDBtn.setAttribute('aria-pressed', String(mode.threeD));
        render();
      });
    }
    layerBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.classList.contains('is-empty')) return;
        const Lr = btn.dataset.layer;
        if (activeLayers.has(Lr)) activeLayers.delete(Lr); else activeLayers.add(Lr);
        const on = activeLayers.has(Lr);
        btn.classList.toggle('is-active', on);
        btn.setAttribute('aria-pressed', String(on));
        renderResults();
        if (mode.threeD) refresh3d();
      });
    });
  }

  // Layer is encoded in the leading id segment (<layer>:<source>:<orig>); the
  // backend also carries it as n.layer. Read it defensively so a server still
  // on pre-aggregator code (bare ids, no n.layer) degrades to L1 instead of
  // blanking every layer toggle.
  function layerOf(n) {
    if (n.layer) return n.layer;
    const id = n.id || '';
    const i = id.indexOf(':');
    return i > 0 ? id.slice(0, i) : 'L1';
  }
  function matches(n) {
    if (!activeLayers.has(layerOf(n))) return false;
    if (!query) return true;
    const hay = (n.title + ' ' + (n.summary || '') + ' ' + (n.tags || []).join(' ')).toLowerCase();
    return query.split(/\s+/).every((term) => term.startsWith('#')
      ? (n.tags || []).some((tag) => tag.toLowerCase() === term.slice(1)) : hay.includes(term));
  }
  function lit(n) {
    const focus = hoverId || selectedId;
    // Hover/selection is the narrower intent, so it wins over an agent
    // highlight rather than intersecting with it -- otherwise clicking a node
    // outside the highlighted agent would light nothing at all.
    if (focus) return n.id === focus || adj[focus].has(n.id);
    return inProject(n);
  }
  function focusTouches(l) {
    const focus = hoverId || selectedId;
    if (!focus) {
      // With an agent highlighted and nothing focused, treat a link as "lit"
      // only when it runs between two of that agent's nodes, so the highlight
      // reads as a subgraph instead of a scatter of dots.
      if (!activeProject) return false;
      const s = nodeById[l.source.id || l.source];
      const t = nodeById[l.target.id || l.target];
      return !!(s && t && inProject(s) && inProject(t));
    }
    const sid = l.source.id || l.source, tid = l.target.id || l.target;
    return sid === focus || tid === focus;
  }

  function drawNode(n, ctx, scale) {
    const active = matches(n);
    const isLit = lit(n);
    const r = Math.max(Math.sqrt(1 + n.deg) * NODE_R, 3 / scale);
    const base = n.color || COL[n.kind] || '#94a3b8';
    const pulsing = pulseIds && pulseIds.has(n.id);
    // With a curation day selected, everything else recedes hard: a handful of
    // ringed dots inside a normally-lit graph was too easy to miss.
    // Context neighbors stay faintly visible so the night's nodes read as
    // part of the graph rather than floating in a void.
    const alpha = pulsing ? 1
      : (pulseIds ? 0.22 : (active ? (isLit ? 1 : 0.16) : 0.05));
    const focus = hoverId || selectedId;
    if (active && isLit && (focus || n.deg >= 5)) {
      ctx.shadowColor = base;
      // Hubs (deg >= 5) gently breathe their glow; the phase is offset by
      // degree so they don't all pulse in unison. Everything else that
      // glows (focused neighbors) holds a steady halo.
      if (n.deg >= 5) {
        const breathe = 0.5 + 0.5 * Math.sin(performance.now() / 1000 * 1.2 + n.deg * 0.7);
        ctx.shadowBlur = 9 + 11 * breathe;
      } else {
        ctx.shadowBlur = 14;
      }
    } else { ctx.shadowBlur = 0; }
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = rgba(base, alpha);
    ctx.fill();
    ctx.shadowBlur = 0;
    // Layer cue: concentric rings encode nesting depth (L1 none, L2 one,
    // L3 two), so layer reads independently of the kind/project fill color.
    const rings = LAYERS.indexOf(layerOf(n));
    if (active && rings > 0) {
      ctx.strokeStyle = rgba('#94a3b8', isLit ? 0.6 : 0.12);
      ctx.lineWidth = 1 / scale;
      for (let i = 1; i <= rings; i++) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + i * NODE_RING_GAP, 0, 2 * Math.PI);
        ctx.stroke();
      }
    }
    if (n.id === selectedId) {
      ctx.shadowBlur = 0;
      ctx.lineWidth = 1.4 / scale;
      ctx.strokeStyle = '#e2e8f0';
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
    // Curation highlight: a clicked curation day pulses the nodes it added with
    // a breathing emerald ring, on top of (and independent of) hover/selection.
    if (pulsing) {
      const t = 0.5 + 0.5 * Math.sin(performance.now() / 1000 * 2.2);
      ctx.strokeStyle = 'rgba(52,211,153,' + (0.55 + 0.4 * t) + ')';
      ctx.lineWidth = 2 / scale;
      ctx.shadowColor = '#34d399';
      ctx.shadowBlur = 10 + 10 * t;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r + 3.5, 0, 2 * Math.PI);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    // Full, untruncated labels. Shown when zoomed in, for hubs, or focused.
    // A pulsed node always labels itself, at any zoom: the point of clicking a
    // curation day is to read which nodes that night produced.
    const showLabel = pulsing ||
      (!pulseIds && active && isLit && (scale > 1.6 || mainHubIds.has(n.id) || n.id === focus));
    if (showLabel) {
      ctx.font = (pulsing ? 12 : 11) / scale + 'px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      if (pulsing) {
        // Chip behind the label so it stays readable over links and dots.
        const w = ctx.measureText(n.title).width;
        ctx.fillStyle = 'rgba(6,20,16,0.72)';
        ctx.fillRect(n.x - w / 2 - 3 / scale, n.y + r + 4 / scale,
          w + 6 / scale, 14 / scale);
      }
      ctx.fillStyle = pulsing ? '#a7f3d0'
        : 'rgba(226,232,240,' + (isLit ? 0.92 : 0.3) + ')';
      const label = !pulsing && n.id !== focus && scale < 1.6 && n.title.length > 44 ? n.title.slice(0, 41) + '…' : n.title;
      const width = ctx.measureText(label).width;
      const box = { x: n.x - width / 2, y: n.y + r + 2, w: width, h: 14 / scale };
      if (!pulsing && n.id !== focus && labelRects.some((b) => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y)) return;
      labelRects.push(box);
      ctx.fillText(label, n.x, n.y + r + (pulsing ? 5 / scale : 2));
    }
  }

  function paintArea(n, color, ctx, scale) {
    // Pointer hit area must track the drawn radius, or the clickable target
    // drifts from the visible dot.
    const r = Math.max(Math.sqrt(1 + n.deg) * NODE_R, 3 / (scale || 1)) + 3;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    ctx.fill();
  }

  // True when a link runs between two nodes a selected curation day added --
  // the only links that stay visible while a day is highlighted.
  function pulseTouches(l) {
    if (!pulseIds) return false;
    return pulseIds.has(l.source.id || l.source) && pulseIds.has(l.target.id || l.target);
  }
  function linkColor(l) {
    if (pulseIds)
      return pulseTouches(l) ? 'rgba(52,211,153,.75)' : 'rgba(71,85,105,.3)';
    if (l.class === 'lineage')
      return focusTouches(l) ? 'rgba(251,191,36,.75)' : 'rgba(251,191,36,.32)';
    return focusTouches(l) ? 'rgba(129,140,248,.55)' : 'rgba(51,65,85,.4)';
  }
  function linkWidth(l) {
    if (pulseIds) return pulseTouches(l) ? 1.8 : 0.5;
    if (l.class === 'lineage') return focusTouches(l) ? 1.4 : 0.6;
    return focusTouches(l) ? 1.6 : 0.7;
  }

  // 3D node/link styling. force-graph parses the alpha channel of an
  // rgba() color into per-node opacity, so we can reuse the 2D dimming
  // logic (filtered-out and out-of-neighborhood nodes fade back).
  function nodeColor3d(n) {
    const pulsing = pulseIds && pulseIds.has(n.id);
    const active = matches(n);
    const isLit = lit(n);
    const base = pulsing ? '#34d399' : (n.color || COL[n.kind] || '#94a3b8');
    const alpha = pulsing ? 1
      : (pulseIds ? 0.22 : (active ? (isLit ? 1 : 0.18) : 0.05));
    return rgba(base, alpha);
  }
  function linkColor3d(l) {
    if (pulseIds)
      return pulseTouches(l) ? 'rgba(52,211,153,.8)' : 'rgba(120,134,170,.25)';
    if (l.class === 'lineage')
      return focusTouches(l) ? 'rgba(251,191,36,.8)' : 'rgba(251,191,36,.3)';
    return focusTouches(l) ? 'rgba(129,140,248,.6)' : 'rgba(120,134,170,.22)';
  }
  // Re-applying an accessor forces 3d-force-graph to re-render materials.
  // Cheap at this graph size; how we reflect hover/selection/filter in 3D.
  function refresh3d() {
    if (!mode.threeD || !Graph) return;
    // nodeVal too: 3D has no labels, so a curation node has to read as bigger
    // as well as brighter or the highlight is just a slightly greener speck.
    Graph.nodeColor(nodeColor3d).nodeVal(nodeVal3d).linkColor(linkColor3d);
  }

  function nodeVal3d(n) {
    const base = 1 + n.deg;
    return pulseIds && pulseIds.has(n.id) ? base * 2 + 3 : base;
  }

  // --- animations ---
  // Directional particles ride only the focused node's links, painted in that
  // node's color, so the graph stays still until you hover or select something.
  // Particles ride only a hovered/selected node's links. Deliberately not the
  // agent-highlight subgraph: every intra-agent link emitting particles reads
  // as noise rather than emphasis.
  function linkParticles(l) {
    return (hoverId || selectedId) && focusTouches(l) ? 4 : 0;
  }
  function particleColor() {
    const focus = hoverId || selectedId;
    const n = focus && nodeById[focus];
    return (n && (n.color || COL[n.kind])) || '#818cf8';
  }
  // force-graph only re-reads the particle count when the accessor is
  // (re)assigned, so nudge it whenever the focused node changes.
  function refreshParticles() {
    if (Graph && Graph.linkDirectionalParticles) Graph.linkDirectionalParticles(linkParticles);
  }
  // Anything that changes the focused node refreshes both the 3D highlight
  // colors (no-op in 2D) and the particle emission.
  function onFocusChange() {
    refresh3d(); refreshParticles();
    document.querySelectorAll('.mm-result').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.id === selectedId)));
  }

  // 3D only: slowly orbit the camera, but only after a long idle stretch
  // (~2 min) so the graph sits still while you're reading it and starts
  // drifting only once you've clearly stepped away. Any interaction cancels
  // and restarts the timer; grabbing the graph stops it instantly.
  // 3d-force-graph calls controls.update() each frame, so autoRotate just
  // needs enabling.
  function enableIdleOrbit(g) {
    const controls = g.controls && g.controls();
    if (!controls || !controls.addEventListener) return;
    const IDLE_MS = 120000; // ~2 minutes before auto-orbit kicks in
    controls.autoRotateSpeed = 0.6;
    controls.autoRotate = false;
    let idle = setTimeout(() => { controls.autoRotate = true; }, IDLE_MS);
    controls.addEventListener('start', () => {
      if (idle) { clearTimeout(idle); idle = null; }
      controls.autoRotate = false;
    });
    controls.addEventListener('end', () => {
      if (idle) clearTimeout(idle);
      idle = setTimeout(() => { controls.autoRotate = true; }, IDLE_MS);
    });
  }

  function openPanel(n) {
    selectedId = n.id;
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    const kindEl = document.getElementById('mm-panel-kind');
    kindEl.textContent = n.project
      ? ('AGENT · ' + n.project.toUpperCase())
      : (n.kind === 'map' ? 'MAP · WHAT EXISTS' : 'PRACTICE · HOW WE WORK');
    kindEl.style.color = n.color || COL[n.kind];
    document.getElementById('mm-panel-title').textContent = n.title;
    const tagsEl = document.getElementById('mm-panel-tags');
    tagsEl.innerHTML = (n.tags || [])
      .map((t) => '<span class="mm-tag">#' + escapeHtml(t) + '</span>').join('');
    document.getElementById('mm-panel-body').innerHTML = n.body_html || '';
    const rel = (n.relates_to || [])
      .map((id) => nodeById[id])
      .filter(Boolean)
      .sort((a, b) => a.title.localeCompare(b.title));
    const relEl = document.getElementById('mm-panel-rel');
    if (rel.length) {
      relEl.innerHTML = '<div class="mm-rel-head">Related</div>' +
        rel.map((r) =>
          '<button class="mm-rel-item" data-id="' + r.id + '">' +
          '<span class="mm-dot" style="background:' + (r.color || COL[r.kind] || '#94a3b8') + '"></span>' +
          escapeHtml(r.title) + '</button>').join('');
      relEl.querySelectorAll('.mm-rel-item').forEach((btn) => {
        btn.addEventListener('click', () => {
          const target = nodeById[btn.dataset.id];
          if (target) { openPanel(target); flyTo(target); }
        });
      });
    } else {
      relEl.innerHTML = '';
    }
    onFocusChange();
  }

  // Center the view on a node — 2D pans+zooms, 3D orbits the camera in.
  function flyTo(target) {
    if (target.x == null) return;
    if (!mode.threeD) {
      if (Graph.centerAt) { Graph.centerAt(target.x, target.y, 500); Graph.zoom(2, 500); }
      return;
    }
    if (Graph.cameraPosition) {
      const r = Math.hypot(target.x, target.y, target.z || 0) || 1;
      const k = (r + 120) / r;
      Graph.cameraPosition(
        { x: target.x * k, y: target.y * k, z: (target.z || 0) * k },
        target, 600);
    }
  }

  function closePanel() {
    selectedId = null;
    panel.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
    onFocusChange();
  }

  // Background click clears both the node panel and any curation-day highlight,
  // so a click on empty space always returns the graph to its neutral state.
  function onBackground() { closePanel(); clearCuration(); }

  // --- Curation activity strip (below the graph) ---
  // One cell per day the nightly kenkeep curation ran: green with a count when
  // it added nodes, gray when it ran but kept nothing — the "or not" signal a
  // node graph alone can't show, since a zero-yield night leaves no node to
  // draw. Clicking a green day pulses the nodes it added. Records arrive
  // newest-first from /api/memory-map.
  function renderCuration(records) {
    const section = document.getElementById('mm-curation');
    const strip = document.getElementById('mm-curation-strip');
    const summary = document.getElementById('mm-curation-summary');
    if (!section || !strip) return;
    if (!records || !records.length) { section.hidden = true; return; }
    section.hidden = false;

    const latest = records[0];
    if (latest.status === 'added') {
      summary.innerHTML = 'Last run <b>' + escapeHtml(latest.date) + '</b> — +' +
        latest.nodes_added + ' new node' + (latest.nodes_added === 1 ? '' : 's');
    } else {
      summary.innerHTML = 'Last run <b>' + escapeHtml(latest.date) + '</b> — 0 new nodes' +
        (latest.pending != null ? ' · ' + latest.pending + ' pending before that run' : '');
    }

    strip.innerHTML = '';
    records.forEach((r) => {
      const cell = document.createElement('div');
      cell.className = 'mm-cur-day ' + (r.status === 'added' ? 'is-added' : 'is-empty');
      if (r.conflicts) cell.classList.add('has-conflict');
      cell.setAttribute('role', 'listitem');
      cell.title = curationTip(r);
      const count = r.status === 'added' ? '+' + r.nodes_added : '·';
      cell.innerHTML = '<span class="mm-cur-count">' + count + '</span>' +
        '<span class="mm-cur-date">' + escapeHtml((r.date || '').slice(5)) + '</span>';
      const ids = (r.added_nodes || []).map((n) => n.id).filter((id) => id && nodeById[id]);
      if (r.status === 'added' && ids.length) {
        cell.addEventListener('click', () => selectCurationDay(cell, ids, r));
      } else if (r.status === 'added') {
        // The day added nodes but none of them are in the graph any more
        // (curated away, or renamed). Say so instead of being a dead cell.
        cell.classList.add('is-inert');
        cell.title = cell.title + '\n(none of these nodes are in the graph any more)';
      }
      strip.appendChild(cell);
    });
  }

  function curationTip(r) {
    const out = [r.date + (r.source === 'git' ? '  (from git history)' : '')];
    if (r.status === 'added') {
      out.push('+' + r.nodes_added + ' new node' + (r.nodes_added === 1 ? '' : 's'));
      (r.added_nodes || []).slice(0, 12).forEach((n) => out.push('  • ' + n.slug));
      if ((r.added_nodes || []).length > 12) out.push('  …');
    } else {
      out.push('curation ran, kept nothing');
      if (r.pending != null) out.push(r.pending + ' pending session signal');
    }
    if (r.conflicts) out.push('⚠ ' + r.conflicts + ' conflict file' + (r.conflicts === 1 ? '' : 's') + ' recorded at this run (historical)');
    return out.join('\n');
  }

  function selectCurationDay(cell, ids, rec) {
    if (curCell === cell) { clearCuration(); return; }
    if (curCell) curCell.classList.remove('is-selected');
    curCell = cell;
    cell.classList.add('is-selected');
    pulseIds = new Set(ids);
    closePanel();                 // a node panel + a pulse set would fight for focus
    // Anything that could hide a highlighted node has to go, or the click
    // "does nothing": a text filter, a layer toggle, or an isolated agent can
    // each drop the very nodes we are trying to point at.
    if (query) { query = ''; filterEl.value = ''; }
    ids.forEach((id) => {
      const L = layerOf(nodeById[id]);
      if (!activeLayers.has(L)) {
        activeLayers.add(L);
        const btn = layerBtns.filter((b) => b.dataset.layer === L)[0];
        if (btn) { btn.classList.add('is-active'); btn.setAttribute('aria-pressed', 'true'); }
      }
    });
    if (activeProject) selectProject(null, true);  // one isolation at a time
    // A rebuild, not a repaint: computeView() now mounts only this night's
    // nodes and their immediate context, so the force engine lays that
    // subgraph out on its own and render()'s refit frames it.
    render();
    renderCurationDetail(rec, ids);
    if (mode.threeD) refresh3d(); // 2D repaints every frame; 3D needs a nudge
  }

  function clearCuration() {
    if (curCell) curCell.classList.remove('is-selected');
    curCell = null;
    renderCurationDetail(null, []);
    if (!pulseIds) return;
    pulseIds = null;
    render();   // remount the full graph the isolation was filtering
  }

  // Names the highlighted nodes under the strip. The pulse tells you WHERE
  // they are; this tells you WHAT they are, and each chip jumps to its node.
  function renderCurationDetail(rec, ids) {
    const host = document.getElementById('mm-curation-detail');
    if (!host) return;
    if (!rec) { host.hidden = true; host.innerHTML = ''; return; }
    const missing = (rec.added_nodes || []).filter((n) => !n.id || !nodeById[n.id]).length;
    const bits = ['<span class="mm-cur-detail-lead">Highlighting <b>' + ids.length +
      '</b> node' + (ids.length === 1 ? '' : 's') + ' added <b>' +
      escapeHtml(rec.date) + '</b></span>'];
    ids.forEach((id) => {
      const n = nodeById[id];
      bits.push('<button type="button" class="mm-cur-chip" data-id="' +
        escapeHtml(id) + '">' + escapeHtml(n.title || id) + '</button>');
    });
    if (missing) {
      bits.push('<span class="mm-cur-detail-missing">' + missing +
        ' no longer in the graph</span>');
    }
    bits.push('<button type="button" class="mm-cur-clear" id="mm-cur-clear">Clear</button>');
    host.innerHTML = bits.join(' ');
    host.hidden = false;
    Array.prototype.slice.call(host.querySelectorAll('.mm-cur-chip')).forEach((b) => {
      b.addEventListener('click', () => {
        // Focus one node without losing the day's pulse set.
        selectedId = b.dataset.id;
        openPanel(nodeById[selectedId]);
        fitToIds([selectedId]);
        onFocusChange();
      });
    });
    const clear = document.getElementById('mm-cur-clear');
    if (clear) clear.addEventListener('click', clearCuration);
  }

  // Center/zoom the graph on the highlighted node set.
  function fitToIds(ids, ms) {
    if (!Graph || !ids.length) return;
    const dur = ms || 600;
    const pts = ids.map((id) => nodeById[id]).filter((n) => n && n.x != null);
    if (!pts.length) return;
    if (!mode.threeD && Graph.centerAt) {
      const xs = pts.map((n) => n.x), ys = pts.map((n) => n.y);
      const cx = (Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2;
      const cy = (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2;
      // Zoom to the set's own spread rather than a fixed 2.2x: one node should
      // fill the frame, while a 15-node night has to stay entirely on screen.
      const w = Math.max(Math.max.apply(null, xs) - Math.min.apply(null, xs), 40);
      const h = Math.max(Math.max.apply(null, ys) - Math.min.apply(null, ys), 40);
      const z = Math.min(3.2, Math.max(0.4,
        Math.min((el.clientWidth - 140) / w, (el.clientHeight - 140) / h)));
      Graph.centerAt(cx, cy, dur);
      Graph.zoom(z, dur);
    } else if (mode.threeD && Graph.zoomToFit) {
      const set = new Set(ids);
      // Generous padding: a 3D sphere is drawn well outside its node position,
      // so a tight fit clips the outermost dots of the set.
      try { Graph.zoomToFit(dur, 150, (n) => set.has(n.id)); } catch (e) { /* noop */ }
    }
  }

  document.getElementById('mm-panel-close').addEventListener('click', closePanel);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    closePanel();
    clearCuration();
    if (activeProject) selectProject(null);
  });
  filterEl.addEventListener('input', () => {
    query = filterEl.value.toLowerCase().trim();
    renderResults();
    refresh3d();
  });

  const layerNames = { L1: 'Shared knowledge', L2: 'Project workspace', L3: 'Codebase' };

  function renderResults() {
    if (!view) return;
    const host = document.getElementById('mm-results');
    const nodes = view.nodes.filter((n) => matches(n) && inProject(n) && (!pulseIds || pulseIds.has(n.id)))
      .sort((a, b) => query ? a.title.localeCompare(b.title) : b.deg - a.deg || a.title.localeCompare(b.title));
    document.getElementById('mm-results-count').textContent = nodes.length + (query ? (nodes.length === 1 ? ' match' : ' matches') : ' knowledge items') +
      (activeProject ? ' · ' + activeProject : pulseIds ? ' · selected curation day' : ' · enabled layers');
    host.replaceChildren();
    if (!nodes.length) {
      host.textContent = 'No matches. Try another search or enable more layers and projects.';
      return;
    }
    nodes.forEach((n) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'mm-result'; button.dataset.id = n.id;
      button.setAttribute('aria-pressed', String(n.id === selectedId));
      const title = document.createElement('strong'); title.textContent = n.title;
      const meta = document.createElement('small');
      meta.textContent = [n.project, layerNames[layerOf(n)], ...(n.tags || []).slice(0, 3).map((t) => '#' + t)].filter(Boolean).join(' · ');
      button.append(title, meta);
      if (n.summary) { const desc = document.createElement('p'); desc.textContent = n.summary; button.append(desc); }
      button.addEventListener('click', () => { openPanel(n); flyTo(n); });
      host.append(button);
    });
  }

  function renderReview(review, records) {
    const host = document.getElementById('mm-review-content');
    host.replaceChildren();
    const addText = (text) => { const p = document.createElement('p'); p.textContent = text; host.append(p); return p; };
    if (!review) { addText('Review sources are unavailable. Reload after the dashboard has updated.'); return; }
    const conflicts = review.conflicts || [];
    addText(conflicts.length + ' conflict' + (conflicts.length === 1 ? '' : 's') + ' marked pending in the available stores. Expand to compare the proposal with existing knowledge, then resolve it with /kk-curate in a Claude Code session.');
    if ((review.unavailable || []).length) addText('Some review sources could not be read; this count may be incomplete.');
    conflicts.forEach((c) => {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = c.title + ' · ' + (c.project || 'Shared knowledge') + ' · ' + c.detected_at.slice(0, 10);
      const body = document.createElement('div'); body.className = 'mm-review-body';
      // Generated by the same HTML-escaping renderer used for node details.
      if (c.body_html) body.innerHTML = c.body_html;
      else body.textContent = c.body;
      const source = document.createElement('p'); source.className = 'mm-review-source'; source.textContent = 'Review source: ' + c.source;
      details.append(summary, body, source);
      if (c.target_id && nodeById[c.target_id]) {
        const btn = document.createElement('button'); btn.type = 'button'; btn.textContent = 'Compare existing knowledge';
        btn.addEventListener('click', () => {
          const target = nodeById[c.target_id];
          query = ''; filterEl.value = ''; clearCuration(); selectProject(null, true);
          activeLayers.add(layerOf(target));
          layerBtns.forEach((b) => { const on = activeLayers.has(b.dataset.layer); b.classList.toggle('is-active', on); b.setAttribute('aria-pressed', String(on)); });
          render(); openPanel(target);
          panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          setTimeout(() => flyTo(target), 650);
        });
        details.append(btn);
      } else { const note = document.createElement('p'); note.textContent = 'Existing target is not available in this map: ' + c.target; details.append(note); }
      host.append(details);
    });
    const latest = (records || []).find((r) => r.source === 'capture');
    const p = addText(latest && latest.pending != null
      ? 'Shared-knowledge curation backlog: ' + latest.pending + ' queued items before the ' + latest.date + ' run. This is a historical snapshot, not a live queue.'
      : 'A current curation backlog count is not available.');
    const link = document.createElement('a'); link.href = '/retrospector'; link.textContent = ' Open curation reports'; p.append(link);
  }

  function rgba(hex, a) {
    const m = hex.replace('#', '');
    return 'rgba(' + parseInt(m.slice(0, 2), 16) + ',' +
      parseInt(m.slice(2, 4), 16) + ',' + parseInt(m.slice(4, 6), 16) + ',' + a + ')';
  }
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
})();
