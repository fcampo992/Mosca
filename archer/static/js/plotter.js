/**
 * plotter.js — Diana interactiva con zoom, lupa y cálculo geométrico de puntaje.
 *
 * Uso:
 *   const plotter = new TargetPlotter({
 *     svgId:        'the-svg',         // id del SVG de la diana
 *     zoneId:       'diana-zone',      // contenedor externo (para posicionar lupa)
 *     containerId:  'diana-container', // el elemento que recibe el zoom
 *     loupeId:      'loupe-wrap',      // el div circular de lupa
 *     loupeSvgId:   'loupe-svg',
 *     pillId:       'score-pill',
 *     cursorId:     'drag-cursor',
 *     targetType:   'wa10',            // 'wa10' | 'wa6field'
 *     maxArrows:    6,
 *     onArrowAdded: (arrow) => {},     // callback: {val, x, y}
 *     onArrowRemoved: () => {},        // callback cuando se borra la última
 *   });
 *
 *   plotter.getArrows()          → [{val, x, y}, ...]
 *   plotter.clearArrows()        → vacía la tanda
 *   plotter.loadPreviousPlots(arr) → carga pins de tandas anteriores (solo lectura)
 *   plotter.renderPins(arrows)   → fuerza re-render de pins
 *   plotter.setMaxArrows(n)
 *   plotter.destroy()            → elimina event listeners
 */

(function (global) {
  'use strict';

  /* ── Constantes de geometría ──────────────────────────────────────────────
   * La diana SVG usa viewBox="-110 -110 220 220".
   * Las zonas están definidas por radio en esas unidades.
   */
  var GEOMETRY = {
    wa10: [
      { r:   5, val: 'X'  },
      { r:  10, val: '10' },
      { r:  20, val: '9'  },
      { r:  30, val: '8'  },
      { r:  40, val: '7'  },
      { r:  50, val: '6'  },
      { r:  60, val: '5'  },
      { r:  70, val: '4'  },
      { r:  80, val: '3'  },
      { r:  90, val: '2'  },
      { r: 100, val: '1'  },
      { r: Infinity, val: 'M' }
    ],
    wa6field: [
      { r:   5, val: 'X' },
      { r:  20, val: '6' },
      { r:  40, val: '5' },
      { r:  60, val: '4' },
      { r:  80, val: '3' },
      { r: 100, val: '2' },
      { r: Infinity, val: 'M' }
    ]
  };

  /* ── Paleta de colores ────────────────────────────────────────────────── */
  var PIN_FILL = {
    'X':'#fbbf24','10':'#f59e0b',
    '9':'#ef4444','8':'#dc2626','7':'#b91c1c',
    '6':'#3b82f6','5':'#2563eb',
    '4':'#4b5563','3':'#374151',
    '2':'#1f2937','1':'#111827','M':'#111827'
  };

  /* ── Puntos por valor ─────────────────────────────────────────────────── */
  var POINTS_WA10     = {X:10,'10':10,'9':9,'8':8,'7':7,'6':6,'5':5,'4':4,'3':3,'2':2,'1':1,'M':0};
  var POINTS_WA6FIELD = {X:6,'6':6,'5':5,'4':4,'3':3,'2':2,'1':1,'M':0};

  /* ── SVG de diana por tipo ────────────────────────────────────────────── */
  var DIANA_SVG_INNER = {
    wa10: [
      '<circle cx="0" cy="0" r="100" fill="#ffffff"/>',
      '<circle cx="0" cy="0" r="90"  fill="#f0f0f0"/>',
      '<circle cx="0" cy="0" r="80"  fill="#e8e8e8"/>',
      '<circle cx="0" cy="0" r="70"  fill="#1d4ed8"/>',
      '<circle cx="0" cy="0" r="60"  fill="#2563eb"/>',
      '<circle cx="0" cy="0" r="50"  fill="#ef4444"/>',
      '<circle cx="0" cy="0" r="40"  fill="#dc2626"/>',
      '<circle cx="0" cy="0" r="30"  fill="#b91c1c"/>',
      '<circle cx="0" cy="0" r="20"  fill="#fbbf24"/>',
      '<circle cx="0" cy="0" r="10"  fill="#f59e0b"/>',
      '<circle cx="0" cy="0" r="100" fill="none" stroke="#bbb" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="90"  fill="none" stroke="#bbb" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="80"  fill="none" stroke="#bbb" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="70"  fill="none" stroke="#aaa" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="60"  fill="none" stroke="#aaa" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="50"  fill="none" stroke="#999" stroke-width="0.6"/>',
      '<circle cx="0" cy="0" r="40"  fill="none" stroke="#999" stroke-width="0.6"/>',
      '<circle cx="0" cy="0" r="30"  fill="none" stroke="#888" stroke-width="0.6"/>',
      '<circle cx="0" cy="0" r="20"  fill="none" stroke="#cc8800" stroke-width="0.6"/>',
      '<line x1="-2.5" y1="0"   x2="2.5" y2="0"   stroke="#888" stroke-width="0.5"/>',
      '<line x1="0"    y1="-2.5" x2="0"   y2="2.5" stroke="#888" stroke-width="0.5"/>'
    ].join(''),
    wa6field: [
      '<circle cx="0" cy="0" r="100" fill="#1f2937"/>',
      '<circle cx="0" cy="0" r="80"  fill="#374151"/>',
      '<circle cx="0" cy="0" r="60"  fill="#4b5563"/>',
      '<circle cx="0" cy="0" r="40"  fill="#6b7280"/>',
      '<circle cx="0" cy="0" r="20"  fill="#fbbf24"/>',
      '<circle cx="0" cy="0" r="5"   fill="#fde68a"/>',
      '<circle cx="0" cy="0" r="100" fill="none" stroke="#555" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="80"  fill="none" stroke="#555" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="60"  fill="none" stroke="#555" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="40"  fill="none" stroke="#555" stroke-width="0.5"/>',
      '<circle cx="0" cy="0" r="20"  fill="none" stroke="#cc8800" stroke-width="0.6"/>',
      '<line x1="-2.5" y1="0"   x2="2.5" y2="0"   stroke="#888" stroke-width="0.5"/>',
      '<line x1="0"    y1="-2.5" x2="0"   y2="2.5" stroke="#888" stroke-width="0.5"/>'
    ].join('')
  };

  /* ── Helpers ─────────────────────────────────────────────────────────── */
  function scoreAt(x, y, targetType) {
    var r = Math.sqrt(x * x + y * y);
    var zones = GEOMETRY[targetType] || GEOMETRY.wa10;
    for (var i = 0; i < zones.length; i++) {
      if (r <= zones[i].r) return zones[i].val;
    }
    return 'M';
  }

  function svgCoords(svg, clientX, clientY) {
    var rect = svg.getBoundingClientRect();
    // viewBox: -110 -110 220 220
    return {
      x: ((clientX - rect.left)  / rect.width)  * 220 - 110,
      y: ((clientY - rect.top)   / rect.height) * 220 - 110
    };
  }

  function mkEl(ns, tag, attrs) {
    var el = document.createElementNS(ns, tag);
    Object.keys(attrs).forEach(function(k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  var NS = 'http://www.w3.org/2000/svg';

  /* ── Constructor ─────────────────────────────────────────────────────── */
  function TargetPlotter(opts) {
    this.svgEl       = document.getElementById(opts.svgId);
    this.zoneEl      = document.getElementById(opts.zoneId);
    this.containerEl = document.getElementById(opts.containerId);
    this.loupeEl     = document.getElementById(opts.loupeId);
    this.loupeSvgEl  = document.getElementById(opts.loupeSvgId);
    this.pillEl      = document.getElementById(opts.pillId);
    this.cursorEl    = document.getElementById(opts.cursorId);

    this.targetType    = opts.targetType || 'wa10';
    this.maxArrows     = opts.maxArrows  || 6;
    this.onArrowAdded  = opts.onArrowAdded  || function() {};
    this.onArrowRemoved= opts.onArrowRemoved|| function() {};

    this._arrows        = [];   // tanda actual: [{val,x,y}]
    this._prevPlots     = [];   // pins de tandas anteriores (read-only)
    this._pressing      = false;

    this._pinsG         = this.svgEl.getElementById
                          ? this.svgEl.querySelector('#pins-g')
                          : null;
    if (!this._pinsG) {
      this._pinsG = mkEl(NS, 'g', { id: 'pins-g' });
      this.svgEl.appendChild(this._pinsG);
    }

    // Inyectar SVG de diana si aún no tiene el fondo
    if (!this.svgEl.dataset.plotterReady) {
      var inner = DIANA_SVG_INNER[this.targetType] || DIANA_SVG_INNER.wa10;
      this.svgEl.insertAdjacentHTML('afterbegin', inner);
      this.svgEl.dataset.plotterReady = '1';
    }

    this._bindEvents();
  }

  TargetPlotter.prototype._bindEvents = function() {
    var self = this;
    var svg  = this.svgEl;

    function onStart(cx, cy) {
      if (self._arrows.length >= self.maxArrows) return;
      self._pressing = true;
      self.containerEl.classList.add('zoomed');
      var c = svgCoords(svg, cx, cy);
      if (self.cursorEl) {
        self.cursorEl.style.display = '';
        self.cursorEl.setAttribute('transform', 'translate(' + c.x + ',' + c.y + ')');
      }
      self._updateLoupe(c.x, c.y, cx, cy);
    }

    function onMove(cx, cy) {
      if (!self._pressing) return;
      var c = svgCoords(svg, cx, cy);
      if (self.cursorEl) {
        self.cursorEl.setAttribute('transform', 'translate(' + c.x + ',' + c.y + ')');
      }
      self._updateLoupe(c.x, c.y, cx, cy);
    }

    function onEnd(cx, cy) {
      if (!self._pressing) return;
      self._pressing = false;
      self.containerEl.classList.remove('zoomed');
      var c = svgCoords(svg, cx, cy);
      var r = Math.sqrt(c.x * c.x + c.y * c.y);
      if (r <= 107) {
        var val = scoreAt(c.x, c.y, self.targetType);
        self._arrows.push({ val: val, x: c.x, y: c.y });
        if (navigator.vibrate) navigator.vibrate(15);
        self._renderPins();
        self.onArrowAdded({ val: val, x: c.x, y: c.y });
      }
      self._hideLoupe();
    }

    // Touch
    this._onTouchStart = function(e) { e.preventDefault(); var t=e.touches[0]; onStart(t.clientX,t.clientY); };
    this._onTouchMove  = function(e) { e.preventDefault(); var t=e.touches[0]; onMove(t.clientX,t.clientY);  };
    this._onTouchEnd   = function(e) { e.preventDefault(); var t=e.changedTouches[0]; onEnd(t.clientX,t.clientY); };
    this._onTouchCancel= function()  { self._pressing=false; self.containerEl.classList.remove('zoomed'); self._hideLoupe(); };

    svg.addEventListener('touchstart',  this._onTouchStart,  { passive: false });
    svg.addEventListener('touchmove',   this._onTouchMove,   { passive: false });
    svg.addEventListener('touchend',    this._onTouchEnd,    { passive: false });
    svg.addEventListener('touchcancel', this._onTouchCancel);

    // Mouse (desktop)
    this._onMouseDown  = function(e) { onStart(e.clientX,e.clientY); };
    this._onMouseMove  = function(e) { if(self._pressing) onMove(e.clientX,e.clientY); };
    this._onMouseUp    = function(e) { onEnd(e.clientX,e.clientY); };
    this._onMouseLeave = function(e) { if(self._pressing) onEnd(e.clientX,e.clientY); };

    svg.addEventListener('mousedown',  this._onMouseDown);
    svg.addEventListener('mousemove',  this._onMouseMove);
    svg.addEventListener('mouseup',    this._onMouseUp);
    svg.addEventListener('mouseleave', this._onMouseLeave);
  };

  TargetPlotter.prototype._updateLoupe = function(x, y, clientX, clientY) {
    if (!this.loupeEl || !this.loupeSvgEl) return;
    var zRect = this.zoneEl.getBoundingClientRect();
    var half  = 22; // ventana 3x zoom

    // Reconstruir el SVG de la lupa
    this.loupeSvgEl.setAttribute('viewBox', (x-half)+' '+(y-half)+' '+(half*2)+' '+(half*2));
    this.loupeSvgEl.innerHTML = (DIANA_SVG_INNER[this.targetType] || DIANA_SVG_INNER.wa10) +
      this._pinsG.outerHTML;

    // Crosshair
    var ch = mkEl(NS,'g',{});
    ch.appendChild(mkEl(NS,'circle',{cx:x,cy:y,r:'1.8',fill:'rgba(255,255,255,0.95)'}));
    ch.appendChild(mkEl(NS,'line',{x1:x-6,y1:y,x2:x+6,y2:y,stroke:'rgba(255,255,255,0.9)','stroke-width':'0.9'}));
    ch.appendChild(mkEl(NS,'line',{x1:x,y1:y-6,x2:x,y2:y+6,stroke:'rgba(255,255,255,0.9)','stroke-width':'0.9'}));
    this.loupeSvgEl.appendChild(ch);

    // Posición lupa
    var lw = 100, lh = 100;
    var lx = clientX - zRect.left - lw / 2;
    var ly = clientY - zRect.top  - lh - 45;
    if (ly < 4) ly = clientY - zRect.top + 20;
    lx = Math.max(4, Math.min(lx, zRect.width  - lw - 4));
    this.loupeEl.style.left    = lx + 'px';
    this.loupeEl.style.top     = ly + 'px';
    this.loupeEl.style.display = 'block';

    // Pill de puntaje
    if (this.pillEl) {
      var val = scoreAt(x, y, this.targetType);
      this.pillEl.textContent    = val === 'X' ? '✕  10 (X)' : val + ' pts';
      this.pillEl.style.left     = (clientX - zRect.left) + 'px';
      this.pillEl.style.top      = Math.max(4, ly - 30) + 'px';
      this.pillEl.style.display  = 'block';
    }
  };

  TargetPlotter.prototype._hideLoupe = function() {
    if (this.loupeEl)  this.loupeEl.style.display  = 'none';
    if (this.pillEl)   this.pillEl.style.display   = 'none';
    if (this.cursorEl) this.cursorEl.style.display = 'none';
  };

  TargetPlotter.prototype._renderPins = function() {
    var g    = this._pinsG;
    g.innerHTML = '';

    // Pins de tandas anteriores — transparentes y más pequeños
    this._prevPlots.forEach(function(p) {
      var c = mkEl(NS,'circle',{cx:p.x,cy:p.y,r:'3',
        fill: PIN_FILL[p.val] || '#fff',
        stroke:'rgba(255,255,255,0.4)','stroke-width':'1',
        opacity:'0.45'
      });
      g.appendChild(c);
    });

    // Pins de la tanda actual — sólidos y numerados
    this._arrows.forEach(function(a, i) {
      var c = mkEl(NS,'circle',{cx:a.x,cy:a.y,r:'5',
        fill: PIN_FILL[a.val] || '#fff',
        stroke:'white','stroke-width':'1.5'
      });
      g.appendChild(c);
      var t = mkEl(NS,'text',{x:a.x,y:a.y-8,
        'text-anchor':'middle','font-size':'6','font-weight':'bold',
        fill:'white','paint-order':'stroke',
        stroke:'rgba(0,0,0,0.7)','stroke-width':'2.5'
      });
      t.textContent = a.val;
      g.appendChild(t);
      // número de flecha
      var n = mkEl(NS,'text',{x:a.x+7,y:a.y+3,
        'text-anchor':'start','font-size':'5',
        fill:'rgba(255,255,255,0.7)'
      });
      n.textContent = i + 1;
      g.appendChild(n);
    });
  };

  /* ── API pública ─────────────────────────────────────────────────────── */

  /** Retorna una copia del array de flechas actuales */
  TargetPlotter.prototype.getArrows = function() {
    return this._arrows.slice();
  };

  /** Retorna los puntos por valor según tipo de diana */
  TargetPlotter.prototype.getPoints = function() {
    return this.targetType === 'wa6field' ? POINTS_WA6FIELD : POINTS_WA10;
  };

  /** Borra la última flecha */
  TargetPlotter.prototype.deleteLast = function() {
    if (this._arrows.length) {
      this._arrows.pop();
      this._renderPins();
      this.onArrowRemoved();
    }
  };

  /** Vacía la tanda completa */
  TargetPlotter.prototype.clearArrows = function() {
    this._arrows = [];
    this._renderPins();
  };

  /** Carga pins de tandas anteriores (solo lectura, fondo transparente) */
  TargetPlotter.prototype.loadPreviousPlots = function(plots) {
    this._prevPlots = plots || [];
    this._renderPins();
  };

  /** Cambia el límite de flechas */
  TargetPlotter.prototype.setMaxArrows = function(n) {
    this.maxArrows = n;
  };

  /** Subtotal de la tanda actual */
  TargetPlotter.prototype.subtotal = function() {
    var pts = this.getPoints();
    return this._arrows.reduce(function(s, a) { return s + (pts[a.val] || 0); }, 0);
  };

  /** Renderiza los pins externamente (tras cargar prevPlots) */
  TargetPlotter.prototype.renderPins = function() {
    this._renderPins();
  };

  /** Elimina todos los event listeners */
  TargetPlotter.prototype.destroy = function() {
    var svg = this.svgEl;
    svg.removeEventListener('touchstart',  this._onTouchStart);
    svg.removeEventListener('touchmove',   this._onTouchMove);
    svg.removeEventListener('touchend',    this._onTouchEnd);
    svg.removeEventListener('touchcancel', this._onTouchCancel);
    svg.removeEventListener('mousedown',   this._onMouseDown);
    svg.removeEventListener('mousemove',   this._onMouseMove);
    svg.removeEventListener('mouseup',     this._onMouseUp);
    svg.removeEventListener('mouseleave',  this._onMouseLeave);
  };

  /* ── Función de heatmap (para resumen de sesión) ─────────────────────── */
  /**
   * renderHeatmap(svgId, plots, targetType)
   * Dibuja todos los plots sobre la diana del resumen.
   * plots: [{val, x, y, end}, ...]
   */
  function renderHeatmap(svgId, plots, targetType) {
    var svg = document.getElementById(svgId);
    if (!svg) return;

    // Inyectar fondo si no existe
    if (!svg.dataset.plotterReady) {
      var inner = DIANA_SVG_INNER[targetType] || DIANA_SVG_INNER.wa10;
      svg.insertAdjacentHTML('afterbegin', inner);
      svg.dataset.plotterReady = '1';
    }

    var g = svg.querySelector('#heatmap-g');
    if (!g) {
      g = mkEl(NS, 'g', { id: 'heatmap-g' });
      svg.appendChild(g);
    }
    g.innerHTML = '';

    plots.forEach(function(p) {
      var c = mkEl(NS,'circle',{cx:p.x,cy:p.y,r:'4.5',
        fill: PIN_FILL[p.val] || '#fff',
        stroke:'rgba(255,255,255,0.6)','stroke-width':'1.2',
        opacity:'0.85'
      });
      g.appendChild(c);
    });
  }

  /* ── Exports ─────────────────────────────────────────────────────────── */
  global.TargetPlotter   = TargetPlotter;
  global.renderHeatmap   = renderHeatmap;
  global.PLOTTER_POINTS  = { wa10: POINTS_WA10, wa6field: POINTS_WA6FIELD };

}(window));
