# JARVIS UI Design Specification
**Source:** `dashboard/static/dashboard.html`  
**Target:** `ui.py` (PyQt6)  
**Goal:** Pixel-perfect match between HTML dashboard and Qt UI

---

## 1. Color Palette (CSS Custom Properties)

```css
:root {
  --amber:        #ffaa00;      /* Primary accent */
  --amber-bright: #ffe0a0;      /* Bright text/glow */
  --amber-hot:    #fff2cf;      /* Hover/hot state */
  --amber-dim:    #6b4400;      /* Borders, dim elements */
  --amber-glass:  rgba(255,170,0,0.08);  /* Glass backgrounds */
  --bg:           #020202;      /* Page background */
  --panel-bg:     rgba(7,8,5,0.84);      /* Panel backgrounds */
  --red:          #ff3b30;      /* Danger/abort */
  --text-dim:     #8a6a2a;      /* Muted text */
}
```

**Body Background:**
```css
radial-gradient(ellipse at 50% 45%, #0b0906 0%, #050403 45%, #000000 100%)
```

---

## 2. Typography

| Element | Font | Weight | Size | Letter-Spacing | Color |
|---------|------|--------|------|----------------|-------|
| Body | 'Share Tech Mono' | 400 | 14px (base) | normal | #ffaa00 |
| Brand Title | 'Orbitron' | 900 | 22px | 6px | #ffe0a0 |
| Brand Subtitle | 'Share Tech Mono' | 400 | 10px | 3px | #8a6a2a |
| Clock Time | 'Orbitron' | 700 | 26px | 2px | #ffe0a0 |
| Clock Date | 'Share Tech Mono' | 400 | 11px | 2px | #8a6a2a |
| Status Strip | 'Share Tech Mono' | 400 | 10px | 2px | #8a6a2a |
| Telemetry Label | 'Share Tech Mono' | 400 | 10px | 1px | #8a6a2a |
| Telemetry Value | 'Orbitron' | 700 | 14px | normal | #ffe0a0 |
| Panel Header | 'Orbitron' | 700 | 11-12px | 1-2px | #ffe0a0 |
| Panel Row Label | 'Share Tech Mono' | 400 | 11px | normal | #8a6a2a |
| Panel Row Value | 'Orbitron' | 400 | 11px | normal | #ffaa00 |
| Dock Buttons | 'Orbitron' | 400 | 11-12px | 1px | #ffaa00 |
| Dock Input | 'Share Tech Mono' | 400 | 14px | normal | #ffaa00 |
| Detail Title | 'Orbitron' | 700 | 16px | normal | #ffe0a0 |

**Text Shadows:**
- Brand h1: `0 0 14px rgba(255,180,60,0.6)`
- Clock time: `0 0 12px rgba(255,180,60,0.55)`

---

## 3. Layout Structure (Z-Index Hierarchy)

```
z-index: 0   → #grid (animated CSS grid backdrop)
z-index: 1   → #vignette (radial gradient overlay)
z-index: 1   → #stage canvas (Three.js globe)  ← FIXED: was behind UI
z-index: 5   → .bracket (corner brackets)
z-index: 10  → .hud (all UI overlays)
z-index: 20  → .sidebar.open (side panels)
z-index: 30  → .detail-panel (modal detail view)
```

**Key Container:**
```html
<div id="hud" class="hud">          <!-- Full viewport, pointer-events:none -->
  <div class="bracket tl"></div>    <!-- 46×46px, 18px from edges -->
  <div class="bracket tr"></div>
  <div class="bracket bl"></div>
  <div class="bracket br"></div>
  <div class="topbar">...</div>     <!-- 26px top, 70px horizontal -->
  <div class="status-strip">...</div>  <!-- top:96px, left:70px -->
  <div class="telemetry">...</div>     <!-- top:130px, left:70px, right:70px -->
  <aside class="sidebar left">...</aside>   <!-- Full height, 320px width -->
  <aside class="sidebar right">...</aside>  <!-- Full height, 320px width -->
  <div class="dock">...</div>           <!-- Bottom, 14px/70px padding -->
  <div id="detailPanel">...</div>       <!-- z-index:30, right:-420px -->
  <div id="tooltip">...</div>
</div>
<div id="stage"></div>              <!-- Three.js canvas container -->
```

---

## 4. Component Specifications

### 4.1 Corner Brackets
- Size: 46×46px
- Border: 1.5px solid #ffaa00
- Opacity: 0.45
- Position: 18px from each corner
- Each shows only two edges (L-shape)

### 4.2 Top Bar
- Padding: 26px top, 70px horizontal
- Left: Brand (KD + "COGNITIVE AUTONOMOUS OS")
- Right: Clock (time + date)
- `pointer-events: auto`

### 4.3 Status Strip
- Position: top:96px, left:70px
- Items: Flex, gap:22px
- Each item: Dot (6px, animated pulse) + text
- Animation: `pulse 1.8s ease-in-out infinite` (opacity 1→0.25→1)

### 4.4 Telemetry Grid
- Position: top:130px, left:70px, right:70px
- Grid: `repeat(auto-fit, minmax(140px, 1fr))`, gap:10px
- Cards: `--panel-bg` background, 1px `--amber-dim` border
- Padding: 10px 14px
- Label: 10px, `--text-dim`, letter-spacing:1px
- Value: 14px, Orbitron 700, `--amber-bright`

### 4.5 Side Panels (Left & Right)
- Width: 320px, full height
- Background: `linear-gradient(180deg, rgba(5,4,3,0.95), rgba(2,2,2,0.98))`
- Border: Right panel has left border, left panel has right border (1px `--amber-dim`)
- Header: 20px padding, Orbitron 12px, 2px letter-spacing, `--amber-bright`
- Cards: 14px margin, 14px padding, `--panel-bg`, 1px `--amber-dim` border
- Card Header: Orbitron 11px, 1px letter-spacing, `--amber-bright`
- Rows: Flex, justify-content:space-between, 6px margin, 11px font

### 4.6 Bottom Dock
- Position: absolute bottom, left:0, right:0
- Padding: 14px 70px
- Background: `linear-gradient(0deg, rgba(2,2,2,0.95), transparent)`
- Inner: max-width:1400px, centered
- Groups: Flex, gap:16px
- Buttons: 10px 16px padding, 1px `--amber-dim` border, `--amber` text
- Primary: `--amber` background, `#050402` text
- Danger: `--red` border/text
- Input: Flex-1, `#070603` bg, `--amber-dim` border, `--amber` text

### 4.7 Detail Panel (Modal)
- Position: fixed, top:0, bottom:0, right:-420px, width:400px
- Background: `linear-gradient(180deg, rgba(5,4,3,0.95), rgba(2,2,2,0.98))`
- Border-left: 1px `--amber-dim`
- Transition: `right .3s ease`
- z-index: 20
- Header: 20px padding, border-bottom
- Content: 20px padding, scrollable
- Actions: 20px padding, border-top, 2 buttons

### 4.8 Tooltip
- Fixed, z-index:30
- `--panel-bg`, 1px `--amber-dim` border
- 10px 14px padding, 11px font, `--text-dim`
- Pointer-events:none

---

## 5. Animations

| Animation | Duration | Easing | Properties |
|-----------|----------|--------|------------|
| `pulse` | 1.8s | ease-in-out | opacity 1→0.25→1 |
| `gridDrift` | 22s | linear | background-position |
| Globe rotation | Continuous | linear | Y: +0.0001/frame, Particles: +0.00015 |
| Detail panel slide | 0.3s | ease | right: -420px → 0 |
| Button hover | 0.15s | — | background, border-color |
| Button active | 0.1s | — | transform: scale(0.96) |

---

## 6. Three.js Globe (Stage)

**Container:** `#stage` - fixed, inset:0, cursor:grab
**Canvas:** `display:block; width:100%; height:100%; z-index:1;`

**Scene Contents:**
- Earth: SphereGeometry(1, 64, 64), MeshStandardMaterial(#0a1628, roughness:0.8, metalness:0.2)
- Atmosphere: SphereGeometry(1.08), MeshBasicMaterial(#00d9ff, transparent, opacity:0.08, BackSide)
- Particles: 2000 Points, radius 1-1.5, HSL(0.55-0.65, 1, 0.5-0.8), size 0.5-2.0
- Lights: Ambient(0x1a2a3a, 0.6), Directional(0xffe0a0, 1.2), Fill(0x00d9ff, 0.4)
- Grid: GridHelper(4, 40, 0x00d9ff, 0x003344), opacity:0.05

**Interaction:**
- Drag to rotate (pointerdown + pointermove)
- Wheel to zoom (z: 1.5-5)
- Auto-rotation: globe Y +0.0001, particles Y +0.00015

---

## 7. Responsive Breakpoints

```css
@media (max-width: 420px) {
  #scanFrame { width:300px; height:300px; }
  .panel { padding:14px 16px; }
}
```

---

## 8. Font Loading

```html
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
```

**Qt Equivalent:** Use `QFontDatabase.addApplicationFont()` to load bundled fonts from `dashboard/static/fonts/`

---

## 9. Implementation Notes for Qt

1. **Three.js Integration:** Use `QWebEngineView` for the globe, or port to Qt3D/OpenGL
2. **CSS Grid/Flex:** Use `QGridLayout`/`QHBoxLayout`/`QVBoxLayout` with stretch factors
3. **Animations:** Use `QPropertyAnimation` for slide/fade, `QTimer` for pulse/rotation
4. **Fonts:** Load Orbitron and Share Tech Mono from `dashboard/static/fonts/`
5. **Colors:** Define as `QColor` constants matching hex values exactly
6. **Z-Order:** Use `raise_()`/`lower()` or `QGraphicsView` layers
6. **Pointer Events:** Qt widgets handle this natively; use `setAttribute(Qt.WA_TransparentForMouseEvents)` for HUD overlay

---

## 10. Acceptance Criteria

- [ ] All colors match hex values exactly
- [ ] Fonts render identically (Orbitron/Share Tech Mono)
- [ ] Corner brackets at 18px, 46×46px, 1.5px border
- [ ] Top bar at 26px/70px padding
- [ ] Clock: 26px Orbitron 700 + 11px date
- [ ] Status strip at top:96px, left:70px, pulsing dots
- [ ] Telemetry grid: auto-fit minmax(140px), 70px margins
- [ ] Side panels: 320px, gradient bg, correct borders
- [ ] Dock: 14px/70px padding, max-width 1400px
- [ ] Detail panel: slides from right, 400px wide
- [ ] Three.js globe visible behind UI (z-index:1)
- [ ] All animations running (pulse, grid drift, globe rotation)
- [ ] Hover/active states on all buttons
- [ ] Responsive at ≤420px
