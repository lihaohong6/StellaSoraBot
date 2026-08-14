# 3D model viewer (POC)

Exports Stella Sora character models to glTF and renders them in three.js with a
reimplementation of the game's `Game/Actor/Toon` shader.

## Use

```bash
uv run -m unpack.unpack_model                             # every character and clip
uv run -m unpack.unpack_model --char-id 13301             # one character
uv run -m unpack.unpack_model --char-id 13301 --no-animations
uv run -m unpack.unpack_model --jobs 4                    # fewer characters at once

python3 -m http.server 8777          # then open :8777/tools/model_viewer.html
```

Output goes to `assets/assetbundles/actor3d/`; the page loads it from there, so
serve the repo root rather than `tools/`; with nothing exported there the page
says so and names the exporter. A server is required — the page is an
ES module and fetches `.glb` over HTTP. three.js comes from jsDelivr, pinned to
r185 in the page's import map, so the viewer also needs a network connection.

Characters already exported are skipped; pass `--overwrite` to redo them. The
first run builds `assets/assetbundles/cab_index.json` (~1 min, 9,640 bundles);
it is cached. The viewer hides its animation controls for a character that has
no clips exported.

Characters export in parallel, one process each. All 50 with their clips takes
about 70 seconds on 20 cores. A character peaks near 2 GB and UnityPy hands
little of it back, so `--jobs` is worth lowering on a machine with less memory
than cores would suggest; it defaults to cores minus four.

The viewer opens on *Base colour only*. The toon shader is a reimplementation
working off the material properties alone, and its specular and matcap read
brighter than the game's; the flat view is the more trustworthy default. *Toon
(shader)* under View switches to it, and unfolds the Light and Toon sections,
which start folded because nothing in them reaches the flat view.

Two more defaults are tuned for that view rather than for the material: the
outline sits at 25%, since 100% is what `_OutlineWidth` says and the game
thickens the hull with distance while the viewer sits closer than it ever does,
and *Brows over hair* is off, so the fringe occludes the eyebrows as geometry
normally would.

## How it works

`unpack/unpack_model.py` reads the `char_<id>{,_models,_materials,_textures}` bundles and
writes one `.glb` per character:

- meshes with normals, UVs, vertex colours, skin weights and bind poses
- the `Root/Bip001` skeleton as a glTF skin
- `_SMOOTHNORMAL`, the outline-extrusion normal that Toony Colors Pro bakes into
  the mesh tangent (its `w` is 0, which is how you tell it from a real tangent)
- all five toon maps, and every toon float/colour, in material `extras`

Standard PBR fields are filled in too, so the files open in any glTF viewer —
they just look flat there. LOD meshes are skipped unless `include_lod=True`.

`CustomModelLODGroup` on the prefab root lists the renderers the game shows when
a model spawns. Everything outside that list — cutscene props, alternate
weapons, emote quads — waits for a script to enable it, so the exporter marks
those meshes `extras.optional` and the viewer starts them hidden. Some of them
ship with the GameObject already inactive and some do not, which is why the
group is the signal rather than `m_IsActive`.

Cross-bundle references are resolved through `cab_index.json`. Without it the
face lightmap and the shared matcap silently fail to load, because they live
outside the per-character bundles.

## Animations

It also reads `char_<id>_animations.unity3d` and writes one `.glb` per clip
under `anim/char_<id>/`, plus a `char_<id>.anims.json` manifest. Each
file holds only named nodes and the animation, so the viewer fetches clips on
demand and retargets them onto the model by bone name. Alternate outfits have no
clips of their own and fall back to the default outfit's bundle.

The clips are generic (non-humanoid) Mecanim, so there is no muscle rig to
decode — just float curves. `m_MuscleClip.m_Clip` splits them across three
storage classes sharing one index space: `m_StreamedClip` (sparse, cubic),
`m_DenseClip` (uniform samples) and `m_ConstantClip`. `m_ClipBindingConstant`
carves that index space back into per-transform position (3 curves), rotation
(4) and scale (3), and `Avatar.m_TOS` turns each binding's CRC path hash into a
bone path.

A streamed key stores the coefficients of the cubic running to the next key, so
sampling it is exact. The exporter evaluates every curve onto the union of its
keys and the authoring frame grid, bisects any interval where a straight line
still misses the curve by more than half a degree, then drops every key the
line does reproduce — most of them, since bones are keyed on every frame. Worst
case over a clip lands near 1°; without the bisection a fast weapon spin was 19°
out mid-frame. With normalised-int16 quaternions the median clip is 100 KB.

Note the first and last streamed frames are sentinels holding pre- and post-wrap
state — and the first is stamped `-FLT_MAX`, not `-inf`, so it survives an
`isfinite` check.

Transform and blend shape bindings are taken. What that leaves out:

- **Cloth and skirt bones** are in the clips but not in the model prefab — the
  runtime spawns them — so those tracks are dropped.
- **Root motion** rides on the Animator binding (`kBindMotionT`/`Q`, seven
  curves) rather than a transform track, on the dashes and lunges. Skipping it is
  deliberate: clips then play in place instead of walking out of frame.

## Expressions

A face carries one blend shape per expression — 5 to 19 of them, named `face00`
onwards, in the mesh's `m_Shapes` — and the exporter writes them out as glTF
morph targets. The deltas are sparse in Unity, runs of (vertex index, offset)
shared by every shape in the mesh, and dense in glTF, one array per target.

A clip drives them through a `SkinnedMeshRenderer` binding whose attribute is the
CRC32 of the shape name — which is exactly the hash the mesh already stores
against the channel, so nothing has to be guessed. Weights are percentages there
and unit fractions in glTF.

Only a handful of clips animate a face — Ready, Victory, Timeline, Die — and the
manifest flags them, which is what `· face` in the viewer's clip list marks.
Everything else leaves the face neutral, including Idle, so a character only
changes expression on those clips.

Each clip that has one carries a stand-in mesh — a degenerate triangle — with
the right number of shapes: a weights channel may only target a node that has morph targets, and
three.js builds no track for one that has none. The node takes the name of the
mesh in the model, and the viewer retargets the track by that name — once per
material the face is split across, since each is its own object with its own
copy of the influences.

Characters exported before this went in carry no morph targets; re-export them
with `--overwrite` and their faces come to life. A viewer holding an old model
drops the weights track rather than misbinding it, so the mix is harmless.

The *Swap-in parts* checkbox is a different thing. It reveals the meshes the
game keeps off until a script turns them on: char_10301's phone, cat and
glasses, char_14401's quilt and cup, and the emote quads (`face11_sp01`,
`face_05sp`) that a few faces use in place of a blend shape. 29 of the 50
characters carry some, and the box is greyed out for the rest. They hang off
sockets no clip animates, so left visible they drift away from the body the
moment one plays — hence hidden by default.

## Shader notes

Channel semantics come from the shader's own property descriptions, recovered
from `shader.unity3d`:

| Property | Meaning |
|---|---|
| `_BaseMap` | Base Color (RGB) Alpha (A) |
| `_MaskMap` | Light Attenuation Adjust (R) MatCap Mask (G) Rim Mask (B) |
| `_SpecularMap` | Specular Color (RGB) |
| `_EmissionMap` | Emission Map (RGB) Animation Mask (A) |

Two things are worth knowing:

**`_MaskMap` R means different things per surface.** On the body it sits at a
neutral ~0.5 and drops to 0 in creases, so it biases the light ramp. On the face
(`_CharSurface == 3`) it is a face-shadow lightmap: each texel stores the
horizontal light angle at which it falls into shadow, and the map is mirrored in
U when the key light crosses the head's centre line. Texels outside the authored
island read 0 and fall back to half-lambert.

**Materials ship near-white `_ShadowColor`** (0.93–0.96). In game the contrast
comes from the scene light rig, which is not in the character bundles, so the
faithful result is almost flat. The *Shadow depth* slider scales the shadow tint;
100% is exactly what the material says, and it defaults to 35% to look right
standalone.

Unity serialises LDR material colours gamma-encoded and converts them on upload;
HDR colours (any component > 1) are already linear. The viewer follows that rule.
Getting it wrong makes outlines mid-grey instead of dark.

The face keeps an inverted hull, but a capped one. Without it the chin dissolves
into the neck — the head is its own mesh, ending at the jaw seam, and both sides
of that seam are the same shade of skin, so nothing marks the jawline. Past what
`_OutlineWidth` says the hull starts eating the mouth corners and the eyelids, so
the face stops there while the slider goes on thickening the rest. Everything
finer than the jaw — eyes, brows, lips — is texture linework, as in game.
Eyebrows (`_CharSurface == 1`) and the emote quads are decals lying flat on the
face and get no hull at all: on them it is pure artefact.

## Not implemented

- Weapons sit unposed in the prefab — they are socket-attached at runtime. Play
  any clip and they snap into place, because the clips animate their sockets.
- Size is unoptimised: textures are embedded as PNG. WebP or KTX2 plus Draco or
  meshopt should get a character from ~4 MB to under ~1 MB for wiki use.
