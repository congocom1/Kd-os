# JARVIS 3D Asset Resources

## Local assets (downloaded, ready to import)

Kenney kits, CC0 (public domain — no attribution required), direct zips from
kenney.nl, extracted here:

- `assets/models/space-kit/` — **Space Kit 2.0**, 153 OBJ models (rockets,
  corridors, satellites, machines, computers). On-theme picks:
  `machine_generator.obj`, `machine_wireless.obj`, `desk_computer.obj`
- `assets/models/blaster-kit/` — **Blaster Kit 2.1**, 40 OBJ models (sci-fi
  blasters, turrets, targets)

Import any of them with:

```
studio import assets/models/space-kit/Models/OBJ format/machine_generator.obj generator
```

Verified loading: `generator` (208v/406f), `wireless` (89v/174f),
`computer` (46v/88f), `blaster-a` (298v/880f) all import through
`studio_modeler_visual` and render in the HUD 3D workshop.

License texts: `assets/models/space-kit/License.txt`,
`assets/models/blaster-kit/License.txt` (both CC0 1.0, by Kenney — kenney.nl).

## Sketchfab "JARVIS" collection (reference links, login required to download)

Source collection: <https://sketchfab.com/StarLordMe/collections/jarvis-915b481a69a84c538bd4a9ac49980df5>
Curated by: StarLordMe — 6 models, all animated.

> Downloading any of these requires a Sketchfab account login (the site's
> download button opens a login dialog even for CC-licensed models). To pull
> the actual geometry, log in on sketchfab.com and use each model page's
> "Download 3D Model" button, then import the glTF/GLB/OBJ through
> `studio_modeler import <path> <name>`.

## Models

### 1. Ironman : Arc Reactor (with sound)
- URL: <https://sketchfab.com/3d-models/ironman-arc-reactor-with-sound-d87547f21f904cfa954f4cf77a1409ac>
- Author: Jongmin (@kingjongmin)
- 25.1k triangles / 12.8k vertices — Staff Pick — animated
- 53.9k views, 977 likes — published Jun 17 2019
- Notes: the Arc Reactor powering Tony's electromagnet; matches the project's
  existing `arc_reactor_model/ArcReactor.blend` theme.

### 2. Teleportation Sculpture /// HOLOGRAM
- URL: <https://sketchfab.com/3d-models/teleportation-sculpture-hologram-1ff540323c6d4019a83de82b5ac68e59>
- Author: indierocktopus
- Animated — 5.7k views, 112 likes
- Notes: hologram-style sculpture; visual reference for the holographic
  viewport work in `core/visual_display.py`.

### 3. UI ◉ PLANET ◉ WIDE VER
- URL: <https://sketchfab.com/3d-models/ui-planet-wide-ver-33ad844466584fa28db155e9d2c6dabc>
- Author: Graphic[MOD]
- Animated — 3k views, 65 likes
- Notes: wide-screen FUI planet; good reference for God's-Eye-View styling.

### 4. Interstellar : Endurance (with sound)
- URL: <https://sketchfab.com/3d-models/interstellar-endurance-with-sound-6e391e1c7789448dbcc832fb41f557da>
- Author: Jongmin (@kingjongmin)
- 27.2k triangles / 15.3k vertices — animated
- 12.3k views, 304 likes — published Jul 30 2019

### 5. Evangelion - Entry Plug (with sound)
- URL: <https://sketchfab.com/3d-models/evangelion-entry-plugwith-sound-3e4245a5f40b45eca02dab55e6b47a93>
- Author: Jongmin (@kingjongmin)
- Staff Pick — animated
- 33k views, 742 likes

### 6. Attack helicopter concept
- URL: <https://sketchfab.com/3d-models/attack-helicopter-concept-8980af7152db43f6ba49e93f3950a74e>
- Author: Conor O'Kane (@conorokane)
- 2.7k triangles / 793 vertices — Staff Pick — animated
- License: **CC Attribution** (free download, login required) — 3.8k downloads
- 22.5k views, 602 likes — published Nov 24 2016
- Notes: Tron Legacy styling; lightest mesh in the set, best fit for the
  real-time holographic viewport.
