# 3D model viewer (POC)

Exports Stella Sora character models to glTF and renders them in three.js with a
reimplementation of the game's `Game/Actor/Toon` shader.

## Use

```bash
uv run -m unpack.unpack_model                             # every character and clip
uv run -m unpack.unpack_model --char-id 13301             # one character
uv run -m unpack.unpack_model --char-id 13301 --no-animations

python3 -m http.server 8777          # then open :8777/tools/model_viewer.html
```

Output goes to `assets/assetbundles/actor3d/`; the page loads it from there, so
serve the repo root rather than `tools/`. A server is required — the page is an
ES module and fetches `.glb` over HTTP. three.js comes from jsDelivr, pinned to
r185 in the page's import map, so the viewer also needs a network connection.

Characters already exported are skipped; pass `--overwrite` to redo them. The
first run builds `assets/assetbundles/cab_index.json` (~1 min, 9,640 bundles);
it is cached. The viewer hides its animation controls for a character that has
no clips exported.

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

Only transform bindings are taken. What that leaves out:

- **Cloth and skirt bones** are in the clips but not in the model prefab — the
  runtime spawns them — so those tracks are dropped.
- **Root motion** rides on the Animator binding (`kBindMotionT`/`Q`, seven
  curves) rather than a transform track, on the dashes and lunges. Skipping it is
  deliberate: clips then play in place instead of walking out of frame.
- **Blendshape weights** are bound by `SkinnedMeshRenderer` with the shape name
  hashed into the attribute; a handful of clips use them.

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

Faces get no inverted-hull outline — at head scale the shell swallows the nose
and mouth. Their linework comes from the diffuse texture, as in game.

## Not implemented

- **Blendshapes.** Faces carry 13 (`m_Shapes`); neither the shapes nor the clip
  curves that drive them are exported, so faces stay neutral.
- Weapons sit unposed in the prefab — they are socket-attached at runtime. Play
  any clip and they snap into place, because the clips animate their sockets.
- Size is unoptimised: textures are embedded as PNG. WebP or KTX2 plus Draco or
  meshopt should get a character from ~4 MB to under ~1 MB for wiki use.
