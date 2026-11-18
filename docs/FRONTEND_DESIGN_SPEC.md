"""
JARVIS Visual Display Frontend Design Specification
=====================================================

Aesthetic Direction: Cinematic Tron Futurism
---------------------------------------------
Tone: Retro-futuristic brutalism meets cyberpunk cinematography
Concept: The visual display isn't just a viewer—it's a holographic workshop
where 3D models materialize like blueprints in a JARVIS workshop.

Differentiation: Unlike generic CAD viewers, this treats 3D models as
living artifacts with cinematic presentation, dramatic lighting, and
holographic interface elements that feel like they belong in a sci-fi
film.

---

COLOR PALETTE & THEMING
========================

CSS Variables for Dynamic Theming:

:root {
  /* Base Cinematic Palette - Tron Cyan (Default) */
  --tron-bg: #00070a;
  --tron-panel: rgba(0, 10, 16, 235);
  --tron-accent: #00e5ff;
  --tron-accent-dim: #0088aa;
  --tron-ghost: #001a2e;
  --tron-text: #e0f7ff;
  --tron-text-dim: #7a9aa6;
  --tron-border: #003340;
  --tron-border-bright: #00e5ff;
  
  /* Dynamic Theme Overrides */
  --amber-accent: #ffb000;
  --alert-accent: #ff3355;
  --stealth-accent: #00ff9d;
}

Theme Application:
- Tron: Neural-blue cyan for 3D studio work
- Amber: Warm terminal for Kronos financial data
- Alert: Crimson red for security/status
- Stealth: Toxic green for covert ops

---

TYPOGRAPHY
===========

Display Font (Headings):
font-family: 'JetBrains Mono', monospace;
Variable weights 400-700
Kerning: -0.02em
Letter-spacing: 1px for all-caps

Body Font:
font-family: 'Inter', system-ui, sans-serif;
Weight: 300-400 for UI text
Line-height: 1.5

Monospace (Coordinates/Data):
font-family: 'JetBrains Mono', monospace;
Size: 11px
Color: var(--tron-text-dim)

---

SPATIAL COMPOSITION
====================

Layout Philosophy: Asymmetrical Workshop
- Left 180px: Model tree (vertical stack)
- Center: Massive 3D viewport (70% width)
- Right 320px: Properties & history (vertical)
- Bottom: Timeline/infinite canvas strip

Break the grid:
- 3D viewport has diagonal cut corner (clipped-path)
- Model cards overlap with 8px blur shadows
- Properties panel slides in from right with 24px parallax

---

VISUAL DISPLAY PANEL DESIGN
==============================

Component: VisualDisplayWorkshop
Location: HUD main workspace

Structure:
┌─────────────────────────────────────────────────────────┐
│ [TRON CYAN ACCENT BAR]                                  │
│ JARVIS 3D WORKSHOP  ●  SCENE: workshop_beta  ●  3.2MB  │
├─────────────────┬───────────────────────────────────────┤
│                 │                                       │
│   MODEL TREE    │          3D VIEWPORT                  │
│   (left)        │     [Perspective View]                │
│                 │                                       │
│  □ cube1        │       ╱ ╲                             │
│  ○ sphere1      │      ╱   ╲    [HOLOGRAM MESH]         │
│  ▭ cyl1         │     ╱     ╲                           │
│                 │    ╱       ╲                          │
│  + New...       │   ╱         ╲                         │
│                 │                                       │
│  [TRANSFORMS]   │                                       │
│  Scale: 1.0     │      [ORBIT CONTROLS]                 │
│  Rotation:      │                                       │
│                 │                                       │
├─────────────────┼───────────────────────────────────────┤
│  Properties     │  History / Timeline                  │
│  • Verts: 1024  │  14:32 create cube1                   │
│  • Faces: 512   │  14:33 transform sphere1             │
│  • Bounds       │  14:34 boolean union                  │
└─────────────────┴───────────────────────────────────────┘

---

3D VIEWPORT DESIGN
==================

Holographic Grid:
- Floor grid: 50x50 units, cyan 15% opacity
- Grid lines glow with subtle animation (opacity pulse 0.8 → 0.3)
- Center crosshair: 2px cyan line, 1px white accent

Mesh Rendering Style:
- Wireframe overlay: 40% opacity cyan lines
- Solid fill: Semi-transparent with fresnel edge glow
- Selected mesh: Gold outline (3px), emissive glow
- Ambient occlusion: Soft shadows on ground plane

Camera Controls UI:
- Orbit ring: Circular hint around viewport (stroke-dasharray animation)
- Zoom indicator: Vertical scale bar on right edge
- Snap buttons: 3 icons (top/front/side) in top-right corner

---

MODEL TREE DESIGN
=================

Visual Style: Brutalist file explorer
- Dark background: var(--tron-panel)
- Border: 1px solid var(--tron-border)
- Hover: Border glows var(--tron-accent)
- Selected: Background var(--tron-accent-dim), text white

Icons:
- □ Polygon primitive
- ○ Sphere
- ▭ Cylinder
- ◈ Custom mesh
- ⋯ Group

Color coding by object type:
- Primitives: Cyan
- Transformed: Blue
- Boolean results: Magenta
- Imported: Yellow

---

PROPERTIES PANEL DESIGN
========================

Header: "PROPERTIES — cube1"
Tab bars: Transform | Material | Metadata

Transform Section:
[Scale X] [Scale Y] [Scale Z]  (numeric inputs)
[Rotation X] [Rotation Y] [Rotation Z]
[Position X] [Position Y] [Position Z]

Each input:
- Background: rgba(0,20,30,0.8)
- Border: 1px solid var(--tron-border)
- Focus: Border glows var(--tron-accent)
- Value changes animate with 200ms spring

Live preview: Numbers update as you drag in 3D viewport

---

ANIMATION & MOTION
==================

Micro-interactions:
- Model selection: 150ms scale 0.95 → 1.0 with ease-out
- Panel slide in: 300ms cubic-bezier(0.2, 0.8, 0.2, 1)
- Value changes: Counter numbers roll with 200ms duration
- Grid pulse: 3s loop, opacity 0.8 → 0.3 → 0.8

Page Load Sequence:
1. Accent bar slides in from left (0ms)
2. Model tree fades in staggered (100ms delay per item)
3. 3D viewport appears with grid fade-in (300ms)
4. Properties panel slides from right (400ms)
5. Ambient scanlines sweep across viewport (600ms)

---

BACKGROUNDS & TEXTURES
========================

Viewport Background:
- Radial gradient from center cyan to edge black
- Subtle noise texture (5% opacity)
- Scanline overlay (2px lines, 10% opacity, moving upward)
- Vignette: Darkens corners by 30%

Panel Backgrounds:
- Main panels: Glassmorphism (backdrop-filter: blur(12px))
- Inset shadows: 0 0 40px rgba(0, 229, 255, 0.1)
- Border glow: Inner 1px solid rgba(0,229,255,0.3)

---

INTERACTION PATTERNS
=====================

Click Model Tree Item:
1. Highlight in tree (cyan background)
2. Mesh in viewport pulses once (scale 1.0 → 1.05 → 1.0)
3. Properties panel updates
4. Camera optionally orbits to center on mesh

Drag in Viewport:
1. Cursor changes to orbit icon
2. Meshes leave ghost trail (opacity fade)
3. Real-time coordinate overlay shows delta

Right-Click Mesh:
- Context menu slides out with scale/rotate/duplicate/delete
- Menu has glass morphism with cyan borders

---

DARK MODE OPTIMIZATION
=======================

All text has:
- Primary: --tron-text (high contrast)
- Secondary: --tron-text-dim (medium contrast)
- Tertiary: --tron-text-dim with 60% opacity

Never use pure white (#fff)—always use off-white for reduced eye strain
Never use pure black (#000)—always use --tron-bg for depth

---

RESPONSIVE BEHAVIOR
====================

Desktop (1920x1080+):
- Full 3-column layout
- Model tree 180px, Viewport flexible, Properties 320px

Tablet (1024x768):
- Model tree collapses to icons
- Properties becomes bottom drawer

Mobile:
- Single column stack
- Viewport on top, tree below, properties modal on demand

---

ACCESSIBILITY
=============

- All interactive elements: min 44px touch target
- Color contrast: 4.5:1 minimum for text
- Focus indicators: 2px cyan outline
- Keyboard navigation: Tab through tree → viewport → properties
- Screen reader: Model names announced, vertex counts as stats

---

IMPLEMENTATION NOTES
====================

Qt PyQt6 Implementation:
- Use QOpenGLWidget for viewport (not QPainter)
- Model tree: QTreeView with custom delegate
- Properties: QFormLayout with custom QDoubleSpinBox
- Animations: QPropertyAnimation for smooth transitions
- Themes: Dynamic stylesheet reloading from cinematic_theme.py

Performance:
- 60 FPS viewport target
- Mesh decimation for >100k vertices
- Level-of-detail based on camera distance
- Async loading for large scenes

---

UNIQUE DESIGN DECISIONS
========================

1. Holographic Workshop Metaphor: Treating 3D models as physical artifacts
   in a workshop, not abstract data

2. Diagonal Composition: Viewport corner is clipped at 45deg, breaking
   conventional rectangular UI

3. Living Grid: Floor grid pulses subtly, breathing life into the space

4. Asymmetrical Balance: Deliberately uneven panel sizes create tension
   and visual interest

5. Cinematic Lighting: Models cast soft shadows, have emissive edges,
   respond to "lighting" changes

6. Workshop Timeline: History panel shows operations as craftsman marks,
   not sterile logs

This frontend design transforms a standard 3D viewer into a distinctive,
cinematic workspace that feels worthy of JARVIS's futuristic aesthetic.
"""
