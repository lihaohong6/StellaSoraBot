"""Export Stella Sora character models and their Mecanim clips to glTF.

Each character becomes one `.glb` holding meshes, skeleton and toon materials,
plus one `.glb` per animation clip. Standard glTF PBR fields are filled in so the
files open anywhere, while the full Game/Actor/Toon material state is carried in
material `extras` for `tools/model_viewer.html`.

    uv run -m unpack.unpack_model                 # everything
    uv run -m unpack.unpack_model --char-id 13301 # one character
"""
import argparse
import io
import json
import os
import re
import struct
import zlib
from concurrent.futures import ProcessPoolExecutor
from functools import cache, partial
from pathlib import Path
from typing import Any, Optional

import numpy as np
import UnityPy
from UnityPy.classes import (AnimationClip, Material, Mesh, SkinnedMeshRenderer,
                             Transform)
from UnityPy.helpers.MeshHelper import MeshHandler

from unpack.unpack_paths import unity_asset_dir_1, unity_asset_dir_2
from unpack.unpack_utils import get_unity3d_files
from utils.data_utils import assets_root, autoload

model_root = assets_root / "actor3d"
CAB_INDEX_PATH = assets_root / "cab_index.json"

# Unity is left handed (+X right, +Z forward); glTF is right handed (-X right,
# +Z forward). Mirroring X converts between them while preserving model facing.
FLIP = np.diag([-1.0, 1.0, 1.0, 1.0]).astype(np.float32)

TOON_FLOATS = [
    "_RampThreshold", "_RampSmoothing", "_AttenAdjustCorrection",
    "_Specular_Mode", "_SpecularIntensity", "_SpecularSmoothness",
    "_StylizedSpecularThreshold", "_StylizedSpecularSmoothing",
    "_Rim_Lighting_Mode", "_RimLightingThreshold", "_RimLightingSmooth",
    "_RimLightingWidth", "_Enable_MatCap", "_MatCap_Mode", "_MatCapMapSmoothness",
    "_Enable_EmissionMap", "_OutlineWidth", "_Outline_Normal_Source",
    "_CharSurface", "_LightingMode", "_Surface", "_Cull", "_FlipBackFaceNormal",
    "_Enable_Alpha_Test", "_AlphaCutoff", "_DstBlend",
]
TOON_COLORS = [
    "_BaseColor", "_HighlightColor", "_ShadowColor",
    "_SpecularHighlightColor", "_SpecularShadowColor",
    "_RimLightingHighlightColor", "_RimLightingShadowColor",
    "_MatCapColor", "_EmissionColor", "_OutlineColor",
    "_BackFaceTintColor", "_MainLightDirScale", "_DepthBasedRimLightingParams",
]
TOON_TEXTURES = ["_BaseMap", "_MaskMap", "_SpecularMap", "_MatCapMap", "_EmissionMap"]
SRGB_TEXTURES = {"_BaseMap", "_EmissionMap", "_MatCapMap"}

COMPONENT_FLOAT, COMPONENT_USHORT, COMPONENT_UINT, COMPONENT_UBYTE = 5126, 5123, 5125, 5121
COMPONENT_SHORT = 5122
TARGET_ARRAY, TARGET_ELEMENT = 34962, 34963

MODEL_PARTS = ("models", "materials", "textures")


def character_is_known(char_id: str) -> bool:
    """Whether the data files describe this id well enough to name it.

    Bundles can ship before the data files describing them do, leaving a
    character nothing but its id to be exported under. Those are skipped
    rather than guessed at.
    """
    skin = autoload("CharacterSkin").get(char_id)
    return skin is not None and str(skin["CharId"]) in autoload("Character")


def character_base_name(char_id: str) -> str:
    """The character's own name, regardless of skin.

    Every one of a character's skins is exported into one subdirectory, named
    after this rather than any particular skin, so that an alt outfit sits
    next to the default it is a variant of.
    """
    skin = autoload("CharacterSkin")[char_id]
    return autoload("Character")[str(skin["CharId"])]["Name"]


def character_display_name(char_id: str) -> str:
    """The name a character's model should be shown and saved under.

    `char_id` is `CharacterSkin`'s own id: a 3-digit character id plus a
    2-digit skin suffix. The default skin (`Type == 1`) takes the character's
    bare name; any other skin appends its own title, in the same
    `Character: Skin` style `CharacterSkin.Name` already uses for the default.
    """
    skin = autoload("CharacterSkin")[char_id]
    name = character_base_name(char_id)
    return name if skin["Type"] == 1 else f"{name}: {skin['Name']}"


def slug(name: str) -> str:
    """A display or clip name, made safe for a filename and URL path segment."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def _bundle_cabs(path: str) -> tuple[str, list[str]]:
    try:
        cabs = []
        for outer in UnityPy.load(path).files.values():
            cabs.extend(name.lower() for name in getattr(outer, "files", {}))
        return path, cabs
    except Exception:
        return path, []


@cache
def get_cab_index() -> dict[str, str]:
    """Map internal CAB name -> owning bundle, so cross-bundle PPtrs resolve.

    Materials reference shared textures (matcap, face masks) that live outside the
    per-character bundles; without this they silently fail to read.
    """
    if CAB_INDEX_PATH.exists():
        return json.loads(CAB_INDEX_PATH.read_text())
    CAB_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Not get_unity3d_files(): that dedupes by name, dropping patched bundles in
    # Persistent_Store whose CABs differ from their InstallResource counterparts.
    files = [str(f) for root in (unity_asset_dir_1, unity_asset_dir_2)
             for f in root.rglob("*.unity3d")]
    print(f"building CAB index over {len(files)} bundles (one time, ~1 min)...")
    index: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=16) as pool:
        for path, cabs in pool.map(_bundle_cabs, files, chunksize=16):
            for cab in cabs:
                index.setdefault(cab, path)
    CAB_INDEX_PATH.write_text(json.dumps(index))
    print(f"indexed {len(index)} CABs")
    return index


def convert_matrix(m) -> np.ndarray:
    raw = np.array([[m.e00, m.e01, m.e02, m.e03],
                    [m.e10, m.e11, m.e12, m.e13],
                    [m.e20, m.e21, m.e22, m.e23],
                    [m.e30, m.e31, m.e32, m.e33]], dtype=np.float32)
    return FLIP @ raw @ FLIP


class GltfBuilder:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.root: dict[str, Any] = {
            "asset": {"version": "2.0", "generator": "StellaSoraBot model_viewer"},
            "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
            "materials": [], "textures": [], "images": [], "skins": [],
            "samplers": [{"magFilter": 9729, "minFilter": 9987,
                          "wrapS": 10497, "wrapT": 10497}],
            "accessors": [], "bufferViews": [], "buffers": [],
        }

    def _align(self) -> None:
        while len(self.buffer) % 4:
            self.buffer.append(0)

    def add_view(self, data: bytes, target: Optional[int] = None) -> int:
        self._align()
        view = {"buffer": 0, "byteOffset": len(self.buffer), "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.buffer.extend(data)
        self.root["bufferViews"].append(view)
        return len(self.root["bufferViews"]) - 1

    def add_accessor(self, array: np.ndarray, type_: str, component: int,
                     target: Optional[int] = None, minmax: bool = False,
                     normalized: bool = False) -> int:
        accessor = {"bufferView": self.add_view(array.tobytes(), target),
                    "componentType": component, "count": len(array), "type": type_}
        if normalized:
            accessor["normalized"] = True
        if minmax:
            accessor["min"] = array.min(axis=0).tolist()
            accessor["max"] = array.max(axis=0).tolist()
        self.root["accessors"].append(accessor)
        return len(self.root["accessors"]) - 1

    def add_image(self, png: bytes, name: str) -> int:
        self.root["images"].append({"bufferView": self.add_view(png),
                                    "mimeType": "image/png", "name": name})
        self.root["textures"].append({"sampler": 0, "source": len(self.root["images"]) - 1})
        return len(self.root["textures"]) - 1

    def save(self, path: Path) -> None:
        self._align()
        self.root["buffers"] = [{"byteLength": len(self.buffer)}]
        for key in ("meshes", "skins", "materials", "textures", "images"):
            if not self.root[key]:
                del self.root[key]
        js = json.dumps(self.root, separators=(",", ":")).encode()
        js += b" " * ((4 - len(js) % 4) % 4)
        out = struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(self.buffer))
        out += struct.pack("<II", len(js), 0x4E4F534A) + js
        out += struct.pack("<II", len(self.buffer), 0x004E4942) + bytes(self.buffer)
        path.write_bytes(out)


def load_externals(env: UnityPy.Environment, loaded: set[str]) -> None:
    index = get_cab_index()
    for _ in range(4):
        missing = set()
        for obj in env.objects:
            for external in obj.assets_file.externals:
                cab = external.path.rsplit("/", 1)[-1].lower()
                if cab not in env.files and cab in index:
                    missing.add(index[cab])
        missing -= loaded
        if not missing:
            return
        for path in missing:
            env.load_file(path)
            loaded.add(path)


def load_character_env(char_id: str,
                       parts: tuple[str, ...] = MODEL_PARTS) -> UnityPy.Environment:
    available = {f.name: f for f in get_unity3d_files()}
    wanted = [f"char_{char_id}.unity3d"] + [
        f"char_{char_id}_{part}.unity3d" for part in parts]
    paths = [str(available[n]) for n in wanted if n in available]
    if not paths:
        raise FileNotFoundError(f"no bundles found for char_{char_id}")
    env = UnityPy.Environment(*paths)
    load_externals(env, set(paths))
    return env


def blend_shape_channels(mesh: Mesh) -> list[Any]:
    """The mesh's blend shape channels, in the order glTF morph targets take."""
    return list(getattr(getattr(mesh, "m_Shapes", None), "channels", None) or [])


def find_prefab_root(env: UnityPy.Environment, char_id: str) -> Transform:
    transforms = [o.read() for o in env.objects if o.type.name == "Transform"]
    roots = {t.m_GameObject.read().m_Name: t for t in transforms
             if not (t.m_Father and t.m_Father.m_PathID)}
    for name in (f"{char_id}_model", char_id):
        if name in roots:
            return roots[name]
    raise LookupError(f"no model prefab among {sorted(roots)}")


def renderers_shown_by_default(root: Transform) -> set[int]:
    """Path ids of the renderers the game shows when the model spawns.

    `CustomModelLODGroup` on the prefab root sorts the renderers into a high-
    and a low-detail set, plus a `modelGroup` of parts the runtime swaps in on
    its own: cutscene props (a phone, a cat, glasses), alternate weapons, and
    the emote quads. Only the high-detail set is on to begin with. Some of the
    swap-ins ship with the GameObject already inactive and some do not, so the
    group is the reliable signal, not `m_IsActive`.
    """
    for component in root.m_GameObject.read().m_Component:
        if component.component.type.name != "MonoBehaviour":
            continue
        tree = component.component.read().object_reader.read_typetree()
        if "highLevelGroup" in tree:
            return {p["m_PathID"] for p in tree["highLevelGroup"]}
    return set()


class CharacterExporter:
    def __init__(self, char_id: str, include_lod: bool = False) -> None:
        self.char_id = char_id
        self.include_lod = include_lod
        self.gltf = GltfBuilder()
        self.node_of_transform: dict[int, int] = {}
        self.texture_cache: dict[int, Optional[int]] = {}
        self.material_cache: dict[int, Optional[int]] = {}
        self.env = load_character_env(char_id)
        self.shown: set[int] = set()

    def _add_node(self, transform: Transform) -> int:
        game_object = transform.m_GameObject.read()
        p, q, s = (transform.m_LocalPosition, transform.m_LocalRotation,
                   transform.m_LocalScale)
        node: dict[str, Any] = {
            "name": game_object.m_Name,
            "translation": [-p.x, p.y, p.z],
            "rotation": [q.x, -q.y, -q.z, q.w],
            "scale": [s.x, s.y, s.z],
        }
        index = len(self.gltf.root["nodes"])
        self.gltf.root["nodes"].append(node)
        self.node_of_transform[transform.object_reader.path_id] = index
        children = [self._add_node(c.read()) for c in transform.m_Children]
        if children:
            node["children"] = children
        return index

    def _collect_renderers(self, transform: Transform) -> list[SkinnedMeshRenderer]:
        found: list[SkinnedMeshRenderer] = []
        game_object = transform.m_GameObject.read()
        for component in game_object.m_Component:
            if component.component.type.name == "SkinnedMeshRenderer":
                found.append(component.component.read())
        for child in transform.m_Children:
            found.extend(self._collect_renderers(child.read()))
        return found

    def _add_texture(self, pointer) -> Optional[int]:
        if not (pointer and pointer.m_PathID):
            return None
        key = pointer.m_PathID
        if key not in self.texture_cache:
            try:
                texture = pointer.read()
                stream = io.BytesIO()
                texture.image.save(stream, format="PNG", optimize=True)
                self.texture_cache[key] = self.gltf.add_image(stream.getvalue(),
                                                              texture.m_Name)
            except Exception:
                self.texture_cache[key] = None
        return self.texture_cache[key]

    def _add_material(self, pointer) -> Optional[int]:
        key = pointer.m_PathID
        if key in self.material_cache:
            return self.material_cache[key]
        try:
            material: Material = pointer.read()
        except Exception:
            self.material_cache[key] = None
            return None

        saved = material.m_SavedProperties
        tex_envs = dict(saved.m_TexEnvs)
        floats = dict(saved.m_Floats)
        colors = dict(saved.m_Colors)

        toon: dict[str, Any] = {
            "shader": "Game/Actor/Toon",
            "floats": {k: floats[k] for k in TOON_FLOATS if k in floats},
            "colors": {k: [colors[k].r, colors[k].g, colors[k].b, colors[k].a]
                       for k in TOON_COLORS if k in colors},
            "textures": {},
            "srgb": [],
        }
        for name in TOON_TEXTURES:
            if name not in tex_envs:
                continue
            index = self._add_texture(tex_envs[name].m_Texture)
            if index is None:
                continue
            toon["textures"][name] = index
            scale, offset = tex_envs[name].m_Scale, tex_envs[name].m_Offset
            if (scale.x, scale.y, offset.x, offset.y) != (1.0, 1.0, 0.0, 0.0):
                toon.setdefault("uvTransform", {})[name] = [scale.x, scale.y,
                                                            offset.x, offset.y]
            if name in SRGB_TEXTURES:
                toon["srgb"].append(index)

        gltf_material: dict[str, Any] = {
            "name": material.m_Name,
            "doubleSided": floats.get("_Cull", 2.0) == 0.0,
            "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9},
            "extras": toon,
        }
        if "_BaseMap" in toon["textures"]:
            gltf_material["pbrMetallicRoughness"]["baseColorTexture"] = {
                "index": toon["textures"]["_BaseMap"]}
        if "_BaseColor" in toon["colors"]:
            gltf_material["pbrMetallicRoughness"]["baseColorFactor"] = \
                toon["colors"]["_BaseColor"]
        if floats.get("_Enable_EmissionMap", 0.0) and "_EmissionMap" in toon["textures"]:
            gltf_material["emissiveTexture"] = {"index": toon["textures"]["_EmissionMap"]}
            gltf_material["emissiveFactor"] = [
                min(1.0, c) for c in toon["colors"].get("_EmissionColor", [1, 1, 1, 1])[:3]]
        # _Surface is URP's surface type: 1 is Transparent, which blends rather
        # than cuts out, so it has to be checked before _DstBlend implies a mask.
        if floats.get("_Surface", 0.0) > 0.5:
            gltf_material["alphaMode"] = "BLEND"
        elif floats.get("_Enable_Alpha_Test", 0.0) or floats.get("_DstBlend", 0.0):
            gltf_material["alphaMode"] = "MASK"
            gltf_material["alphaCutoff"] = floats.get("_AlphaCutoff", 0.5)

        self.gltf.root["materials"].append(gltf_material)
        self.material_cache[key] = len(self.gltf.root["materials"]) - 1
        return self.material_cache[key]

    def _add_renderer(self, renderer: SkinnedMeshRenderer) -> None:
        game_object = renderer.m_GameObject.read()
        if not self.include_lod and game_object.m_Name.endswith("_lod"):
            return
        mesh: Mesh = renderer.m_Mesh.read()
        handler = MeshHandler(mesh)
        handler.process()

        positions = np.asarray(handler.m_Vertices, dtype=np.float32)[:, :3].copy()
        positions[:, 0] *= -1
        vertex_count = len(positions)
        attributes = {"POSITION": self.gltf.add_accessor(
            positions, "VEC3", COMPONENT_FLOAT, TARGET_ARRAY, minmax=True)}

        if handler.m_Normals is not None:
            normals = np.asarray(handler.m_Normals, dtype=np.float32)[:, :3].copy()
            normals[:, 0] *= -1
            attributes["NORMAL"] = self.gltf.add_accessor(
                normals, "VEC3", COMPONENT_FLOAT, TARGET_ARRAY)
        if handler.m_UV0 is not None:
            uv = np.asarray(handler.m_UV0, dtype=np.float32)[:, :2].copy()
            uv[:, 1] = 1.0 - uv[:, 1]
            attributes["TEXCOORD_0"] = self.gltf.add_accessor(
                uv, "VEC2", COMPONENT_FLOAT, TARGET_ARRAY)
        if handler.m_Colors is not None:
            colors = np.asarray(handler.m_Colors, dtype=np.float32).reshape(vertex_count, -1)
            colors = np.clip(colors[:, :4] / 255.0, 0.0, 1.0).astype(np.float32)
            attributes["COLOR_0"] = self.gltf.add_accessor(
                colors, "VEC4", COMPONENT_FLOAT, TARGET_ARRAY)

        # Toony Colors Pro bakes the outline-extrusion normal into tangent.xyz.
        if handler.m_Tangents is not None:
            smooth = np.asarray(handler.m_Tangents, dtype=np.float32)[:, :3].copy()
            smooth[:, 0] *= -1
            attributes["_SMOOTHNORMAL"] = self.gltf.add_accessor(
                smooth, "VEC3", COMPONENT_FLOAT, TARGET_ARRAY)

        skin_index = self._add_skin(renderer, mesh, handler, vertex_count, attributes)
        targets, target_names = self._blend_shapes(mesh, vertex_count)

        primitives = []
        for i, triangles in enumerate(handler.get_triangles()):
            indices = np.asarray(triangles, dtype=np.uint32).reshape(-1, 3)[:, ::-1]
            primitive = {"attributes": attributes,
                         "indices": self.gltf.add_accessor(
                             indices.ravel().copy(), "SCALAR",
                             COMPONENT_UINT, TARGET_ELEMENT)}
            if targets:
                primitive["targets"] = targets
            if i < len(renderer.m_Materials) and renderer.m_Materials[i].m_PathID:
                material_index = self._add_material(renderer.m_Materials[i])
                if material_index is not None:
                    primitive["material"] = material_index
            primitives.append(primitive)

        gltf_mesh: dict[str, Any] = {"name": mesh.m_Name, "primitives": primitives}
        extras: dict[str, Any] = {}
        if targets:
            gltf_mesh["weights"] = [0.0] * len(targets)
            extras["targetNames"] = target_names
        if self.shown and renderer.object_reader.path_id not in self.shown:
            extras["optional"] = True
        if extras:
            gltf_mesh["extras"] = extras
        self.gltf.root["meshes"].append(gltf_mesh)
        transform_id = next(c.component.m_PathID for c in game_object.m_Component
                            if c.component.m_PathID in self.node_of_transform)
        node = self.gltf.root["nodes"][self.node_of_transform[transform_id]]
        node["mesh"] = len(self.gltf.root["meshes"]) - 1
        if skin_index is not None:
            node["skin"] = skin_index
            node["translation"], node["scale"] = [0, 0, 0], [1, 1, 1]
            node["rotation"] = [0, 0, 0, 1]

    def _blend_shapes(self, mesh: Mesh,
                      vertex_count: int) -> tuple[list[dict[str, int]], list[str]]:
        """glTF morph targets for the mesh's blend shapes — the face expressions.

        Unity keeps the deltas sparse, as runs of (vertex index, offset) shared
        by every shape in the mesh; glTF wants one dense array per target.
        """
        targets: list[dict[str, int]] = []
        names: list[str] = []
        for channel in blend_shape_channels(mesh):
            # A channel can hold several frames, in-betweens on the way to the
            # full shape; the last one is the shape as the clips address it.
            shape = mesh.m_Shapes.shapes[channel.frameIndex + channel.frameCount - 1]
            deltas = np.zeros((vertex_count, 3), np.float32)
            for i in range(shape.firstVertex, shape.firstVertex + shape.vertexCount):
                vertex = mesh.m_Shapes.vertices[i]
                if vertex.index < vertex_count:
                    deltas[vertex.index] = (-vertex.vertex.x, vertex.vertex.y,
                                            vertex.vertex.z)
            targets.append({"POSITION": self.gltf.add_accessor(
                deltas, "VEC3", COMPONENT_FLOAT, TARGET_ARRAY, minmax=True)})
            names.append(channel.name)
        return targets, names

    def _add_skin(self, renderer: SkinnedMeshRenderer, mesh: Mesh,
                  handler: MeshHandler, vertex_count: int,
                  attributes: dict[str, int]) -> Optional[int]:
        if handler.m_BoneIndices is None or not renderer.m_Bones:
            return None
        joints = np.asarray(handler.m_BoneIndices,
                            dtype=np.uint16).reshape(vertex_count, -1)
        joints = np.pad(joints, ((0, 0), (0, max(0, 4 - joints.shape[1]))))[:, :4].copy()
        if handler.m_BoneWeights is None:
            weights = np.zeros((vertex_count, 4), np.float32)
            weights[:, 0] = 1.0
        else:
            weights = np.asarray(handler.m_BoneWeights,
                                 dtype=np.float32).reshape(vertex_count, -1)
            weights = np.pad(weights,
                             ((0, 0), (0, max(0, 4 - weights.shape[1]))))[:, :4].copy()
        totals = weights.sum(axis=1, keepdims=True)
        weights = np.divide(weights, totals, out=np.zeros_like(weights), where=totals > 0)
        joints[weights == 0] = 0

        attributes["JOINTS_0"] = self.gltf.add_accessor(
            joints, "VEC4", COMPONENT_USHORT, TARGET_ARRAY)
        attributes["WEIGHTS_0"] = self.gltf.add_accessor(
            weights, "VEC4", COMPONENT_FLOAT, TARGET_ARRAY)

        bind = np.stack([convert_matrix(m).T for m in mesh.m_BindPose]).astype(np.float32)
        self.gltf.root["skins"].append({
            "joints": [self.node_of_transform[b.m_PathID] for b in renderer.m_Bones],
            "inverseBindMatrices": self.gltf.add_accessor(
                bind.reshape(len(bind), 16), "MAT4", COMPONENT_FLOAT)})
        return len(self.gltf.root["skins"]) - 1

    def export(self, out_path: Path) -> Path:
        root = find_prefab_root(self.env, self.char_id)
        self.gltf.root["scenes"][0]["nodes"] = [self._add_node(root)]
        self.shown = renderers_shown_by_default(root)
        for renderer in self._collect_renderers(root):
            self._add_renderer(renderer)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.gltf.save(out_path)
        return out_path


def available_character_ids() -> list[str]:
    ids = {f.name[len("char_"):-len("_models.unity3d")]
           for f in get_unity3d_files() if f.name.startswith("char_")
           and f.name.endswith("_models.unity3d")}
    return sorted(ids)


def write_index(out_dir: Path) -> None:
    """Every character with a model on disk, however it got there.

    Scanning `available_character_ids()` against the files already exported —
    rather than the ids this particular run touched — keeps a `--char-id`
    export from dropping every other character out of the index. `out_dir`
    itself stays a bare index plus one subdirectory per character; this is
    what points into them.
    """
    entries = []
    for char_id in filter(character_is_known, available_character_ids()):
        base_slug = slug(character_base_name(char_id))
        name = character_display_name(char_id)
        path = out_dir / base_slug / f"{slug(name)}.glb"
        if path.exists():
            entries.append({"id": char_id, "file": f"{base_slug}/{path.name}",
                            "label": name})
    entries.sort(key=lambda e: e["label"])
    (out_dir / "index.json").write_text(json.dumps(entries, indent=1))


CLASS_TRANSFORM = 4
CLASS_SKINNED_MESH_RENDERER = 137
# Mecanim's kBindTransform* attributes, and how many curves each one spans.
ATTRIBUTE_WIDTH = {1: 3, 2: 4, 3: 3, 4: 3}    # position, rotation, scale, euler
ATTRIBUTE_PROPERTY = {1: "translation", 2: "rotation", 3: "scale", 4: "rotation"}

# How far a reconstructed track may stray, both when refining the sample grid and
# when decimating it again. Positions are in metres on a ~1.6 m character, and
# 4e-3 on a quaternion component is under half a degree.
TOLERANCE = {"translation": 5e-4, "rotation": 4e-3, "scale": 2e-3, "weights": 5e-3}


class Curve:
    """One float channel as piecewise cubic segments, Unity's streamed form.

    A key at `times[i]` carries the coefficients of the polynomial running from
    it to the next key, so `value(t) = ((c0*dt + c1)*dt + c2)*dt + c3`. Dense and
    constant curves are re-expressed the same way, which lets everything
    downstream treat the three storage classes identically.
    """

    __slots__ = ("times", "coefficients")

    def __init__(self, times: np.ndarray, coefficients: np.ndarray) -> None:
        self.times = times
        self.coefficients = coefficients

    @classmethod
    def constant(cls, value: float) -> "Curve":
        return cls(np.zeros(1, np.float32),
                   np.array([[0.0, 0.0, 0.0, value]], np.float32))

    @classmethod
    def linear(cls, times: np.ndarray, values: np.ndarray) -> "Curve":
        slope = np.zeros_like(values)
        if len(values) > 1:
            step = np.diff(times)
            slope[:-1] = np.diff(values) / np.where(step > 0, step, 1.0)
        coefficients = np.zeros((len(values), 4), np.float32)
        coefficients[:, 2] = slope
        coefficients[:, 3] = values
        return cls(times, coefficients)

    def sample(self, times: np.ndarray) -> np.ndarray:
        index = np.clip(np.searchsorted(self.times, times, side="right") - 1,
                        0, len(self.times) - 1)
        delta = times - self.times[index]
        # The final key's coefficients describe extrapolation past the clip; hold.
        delta[index == len(self.times) - 1] = 0.0
        # Before the first key, hold it too, as Unity's clamped wrap does. A
        # negative delta would run the cubic backwards instead, and a blend shape
        # keyed only over the moment it fires — the streamed clip stores nothing
        # for the seconds it sits at zero — comes out tens of times its full
        # weight at t=0. Every transform curve is keyed from the start, so this
        # only ever bit the face.
        np.maximum(delta, 0.0, out=delta)
        c = self.coefficients[index]
        return ((c[:, 0] * delta + c[:, 1]) * delta + c[:, 2]) * delta + c[:, 3]


def _streamed_curves(streamed) -> dict[int, Curve]:
    """Unpack `StreamedClip.data`: frames of (time, [(curve index, 4 coeffs)])."""
    if not streamed.curveCount:
        return {}
    raw = np.asarray(streamed.data, dtype=np.uint32).tobytes()
    frames, offset = [], 0
    while offset < len(raw):
        time, count = struct.unpack_from("<fi", raw, offset)
        offset += 8
        block = np.frombuffer(raw, np.float32, count * 5, offset).reshape(count, 5)
        index = np.frombuffer(raw, np.int32, count * 5, offset).reshape(count, 5)
        offset += count * 20
        frames.append((time, index[:, 0].tolist(), block[:, 1:]))

    times: dict[int, list[float]] = {}
    coefficients: dict[int, list[np.ndarray]] = {}
    # The clip is bracketed by two sentinel frames, at -FLT_MAX and +inf, holding
    # the pre- and post-wrap state. Note -FLT_MAX passes an isfinite test.
    for time, index, block in frames[1:-1]:
        for curve, coeff in zip(index, block):
            times.setdefault(curve, []).append(time)
            coefficients.setdefault(curve, []).append(coeff)
    return {curve: Curve(np.array(times[curve], np.float32),
                         np.stack(coefficients[curve]).astype(np.float32))
            for curve in times}


def read_curves(clip: AnimationClip) -> dict[int, Curve]:
    """All of a clip's curves, keyed by the index its bindings address them with."""
    data = clip.m_MuscleClip.m_Clip.data
    streamed, dense, constant = (data.m_StreamedClip, data.m_DenseClip,
                                 data.m_ConstantClip)
    curves = _streamed_curves(streamed)

    width = int(dense.m_CurveCount)
    if width and dense.m_FrameCount:
        samples = np.asarray(dense.m_SampleArray, np.float32)
        samples = samples[:dense.m_FrameCount * width].reshape(-1, width)
        times = dense.m_BeginTime + np.arange(len(samples), dtype=np.float32) \
            / dense.m_SampleRate
        for i in range(width):
            curves[streamed.curveCount + i] = Curve.linear(times, samples[:, i])

    base = streamed.curveCount + width
    for i, value in enumerate(constant.data):
        curves[base + i] = Curve.constant(float(value))
    return curves


def clip_bindings(clip: AnimationClip) -> list[tuple[Any, int, int]]:
    """(binding, first curve index, width) for every generic binding, in order."""
    out, cursor = [], 0
    for binding in clip.m_ClipBindingConstant.genericBindings:
        width = (ATTRIBUTE_WIDTH.get(binding.attribute, 1)
                 if binding.typeID == CLASS_TRANSFORM else 1)
        out.append((binding, cursor, width))
        cursor += width
    return out


def decimate(times: np.ndarray, values: np.ndarray,
             tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Drop keys that a straight line between their neighbours already reproduces.

    Growing each run a key at a time and re-measuring the whole chord costs
    O(n^2), and bones are keyed on every frame. Reading it as a slope interval
    instead takes one pass: a chord from the anchor reproduces the key at `t`
    when its slope is within `tolerance / (t - anchor)` of that key's own, so
    intersecting those intervals as the run grows — a running max and min — says
    where it has to stop. Same keys out; a character's clips take 8s instead of
    19s.
    """
    count = len(times)
    if count < 3:
        return times, values
    keep, anchor = [0], 0
    while anchor < count - 1:
        span = (times[anchor + 1:] - times[anchor])[:, None]
        slope = (values[anchor + 1:] - values[anchor]) / span
        margin = tolerance / span
        # Every key up to but not including the candidate constrains the chord.
        low = np.maximum.accumulate(slope - margin, axis=0)[:-1]
        high = np.minimum.accumulate(slope + margin, axis=0)[:-1]
        outside = np.flatnonzero(((slope[1:] < low) | (slope[1:] > high)).any(axis=1))
        anchor += 1 + (outside[0] if len(outside) else len(slope) - 1)
        keep.append(anchor)
    index = np.array(keep)
    return times[index], values[index]


def _clip_display_name(clip_name: str, id_tokens: set[str]) -> str:
    """A clip's own name, with any character/skin id token dropped.

    Clips are exported one character at a time, so a token in the name that
    just repeats that id says nothing a filename already grouped under the
    character doesn't. Most clips are shared per-character and carry the
    3-digit character id (`133_Ready`, `Episode0Act_103_Run4-2`), but an alt
    outfit with its own timeline cutscene names those clips after its own
    5-digit skin id instead (`13303_Ready`), so both forms are stripped.
    """
    parts = [p for p in clip_name.split("_") if p not in id_tokens]
    return "_".join(parts) if parts else clip_name


def _norm_key(name: str) -> str:
    """A name reduced to what clip/rig matching compares: letters and digits."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _mesh_identity(pointer) -> Optional[tuple[str, int]]:
    """(assets file, path id): the mesh a renderer points at, bundle-agnostic."""
    if not (pointer and pointer.m_PathID):
        return None
    try:
        reader = pointer.read().object_reader
    except Exception:
        return None
    return reader.assets_file.name, reader.path_id


RIG_FURNITURE = {"fx", "base", "timeline"}


def _rig_clip_keys(rig_name: str, id_tokens: set[str]) -> list[str]:
    """The normalized clip names a context rig could be naming.

    `10301_Ready`, `fx_14401_base_Attack_3_Hide` and `fx_14401_timeline_Ultra`
    all name clips once the id and the `fx`/`base`/`timeline` furniture is
    dropped; a `timeline` rig also answers to `<name>_TL`, the take of the same
    animation played without its cutscene. Tokens only ever come off the front,
    and only while something would remain.
    """
    tokens = [t for t in re.split(r"[\s_]+", rig_name) if t]
    furniture = id_tokens | RIG_FURNITURE
    timeline = False
    while len(tokens) > 1 and tokens[0].lower() in furniture:
        timeline = timeline or tokens[0].lower() == "timeline"
        tokens.pop(0)
    key = _norm_key("".join(tokens))
    if not key:
        return []
    return [key, key + "tl"] if timeline else [key]


def _rig_mesh_states(transform: Transform,
                     parts: dict[tuple[str, int], Any]) -> dict[tuple[str, int], bool]:
    """The model's meshes under one rig, each mapped to its effective state.

    Active in Unity means the whole ancestry is active, not just the object
    itself; a mesh several times over — an Ultra rig carries three copies of
    the model — counts as active if any instance is.
    """
    states: dict[tuple[str, int], bool] = {}
    stack: list[tuple[Transform, bool]] = [(transform, True)]
    while stack:
        node, parent_active = stack.pop()
        try:
            game_object = node.m_GameObject.read()
            active = parent_active and bool(game_object.m_IsActive)
            for component in game_object.m_Component:
                if component.component.type.name != "SkinnedMeshRenderer":
                    continue
                key = _mesh_identity(component.component.read().m_Mesh)
                if key in parts:
                    states[key] = states.get(key, False) or active
            for child in node.m_Children:
                stack.append((child.read(), active))
        except Exception:
            continue
    return states


def _context_rig_states(char_id: str,
                        parts: dict[tuple[str, int], Any]
                        ) -> dict[str, dict[tuple[str, int], bool]]:
    """{rig name: {mesh: active}} for every whole-model copy in the rig bundles.

    A copy is recognized by mesh identity — its renderers point at the same
    mesh objects the model prefab uses — and only whole copies count, meaning
    at least half the model's meshes; an FX prefab that borrows a single face
    mesh is previewing an effect, not stating part visibility. The same copy
    ships in both bundles for some characters; the first read wins.
    """
    available = {f.name: f for f in get_unity3d_files()}
    threshold = max(2, len(parts) // 2)
    rigs: dict[str, dict[tuple[str, int], bool]] = {}
    for suffix in ("timeline", "fx"):
        bundle = available.get(f"char_{char_id}_{suffix}.unity3d")
        if bundle is None:
            continue
        path = str(bundle)
        env = UnityPy.Environment(path)
        load_externals(env, {path})
        transforms = [o.read() for o in env.objects if o.type.name == "Transform"]
        for transform in (t for t in transforms
                          if not (t.m_Father and t.m_Father.m_PathID)):
            rig = _rig_mesh_states(transform, parts)
            if len(rig) >= threshold:
                rigs.setdefault(transform.m_GameObject.read().m_Name, rig)
    return rigs


def rig_show_rules(char_id: str) -> dict[str, list[str]]:
    """Which optional parts to `show` per clip, read off the game's context rigs.

    The timeline and fx bundles carry whole copies of the model prefab, one per
    context the game plays clips in — cutscene actor, Ready, an Ultra take —
    with each copy's swap-in parts already active or inactive for that context.
    The copy named after a clip is the rig that clip plays on, so the optional
    parts it leaves on are what the clip should show; where no copy names a
    clip, the clip gets no rule and the viewer's `optional` baseline holds.

    Returns normalized clip name -> part names, for `show` in .anims.json. A
    character the rig bundles say nothing usable about simply maps to {}.
    """
    try:
        env = load_character_env(char_id, parts=("models",))
        root = find_prefab_root(env, char_id)
        shown = renderers_shown_by_default(root)
        parts: dict[tuple[str, int], tuple[str, bool]] = {}

        def collect(transform: Transform) -> None:
            game_object = transform.m_GameObject.read()
            for component in game_object.m_Component:
                if component.component.type.name != "SkinnedMeshRenderer":
                    continue
                key = _mesh_identity(component.component.read().m_Mesh)
                if key:
                    parts[key] = (game_object.m_Name,
                                  component.component.m_PathID not in shown)
            for child in transform.m_Children:
                collect(child.read())

        collect(root)
        if not parts:
            return {}
        id_tokens = {char_id, char_id[:-2]}
        rules: dict[str, list[str]] = {}
        for rig_name, rig in _context_rig_states(char_id, parts).items():
            show: set[str] = set()
            for key, active in rig.items():
                name, optional = parts[key]
                if active and optional and not name.endswith("_lod"):
                    show.add(name)
            if not show:
                continue
            for clip_key in _rig_clip_keys(rig_name, id_tokens):
                rules.setdefault(clip_key, sorted(show))
        return rules
    except Exception:
        return {}


class AnimationExporter:
    def __init__(self, char_id: str) -> None:
        self.char_id = char_id
        self.id_tokens = {char_id, char_id[:-2]}
        self.rest, self.shapes = _skeleton_rest_pose(char_id)
        self.sources = self._load_environments()

    def _load_environments(self) -> list[tuple[UnityPy.Environment, dict[int, str]]]:
        """The bundles holding this character's clips, each with its own TOS.

        The ultra cutscene lives in `_timeline` rather than `_animations`, and it
        is the clip that emotes most, so both are read. They cannot share an
        environment: the timeline bundle carries its own rig and avatars, and
        merging the two path tables would let one rig's hashes resolve against
        the other's bones.
        """
        available = {f.name: f for f in get_unity3d_files()}
        # Alternate outfits ship a model but no clips of their own; the last digit
        # is the outfit, and they animate off the default one's bundle.
        sources = []
        for part in ("animations", "timeline"):
            for char_id in (self.char_id, f"{self.char_id[:-1]}1"):
                name = f"char_{char_id}_{part}.unity3d"
                if name in available:
                    env = UnityPy.Environment(str(available[name]))
                    sources.append((env, self._read_tos(env)))
                    break
        if not sources:
            raise FileNotFoundError(f"no animation bundle for char_{self.char_id}")
        return sources

    @staticmethod
    def _read_tos(env: UnityPy.Environment) -> dict[int, str]:
        """CRC path hash -> bone path, merged over every avatar in the bundle."""
        tos: dict[int, str] = {}
        for obj in env.objects:
            if obj.type.name == "Avatar":
                for path_hash, path in obj.read().m_TOS:
                    tos.setdefault(path_hash, path)
        return tos

    def clips(self) -> list[tuple[AnimationClip, dict[int, str]]]:
        clips = [(o.read(), tos) for env, tos in self.sources
                 for o in env.objects if o.type.name == "AnimationClip"]
        return sorted(clips, key=lambda pair: pair[0].m_Name)

    def build(self, clip: AnimationClip, tos: dict[int, str]) -> Optional[GltfBuilder]:
        curves = read_curves(clip)
        start = float(clip.m_MuscleClip.m_StartTime)
        duration = float(clip.m_MuscleClip.m_StopTime) - start
        if duration <= 0:
            return None
        rate = float(clip.m_SampleRate) or 30.0

        gltf = GltfBuilder()
        name = _clip_display_name(clip.m_Name, self.id_tokens)
        gltf.root["animations"] = [{"name": name, "channels": [], "samplers": []}]
        animation = gltf.root["animations"][0]
        nodes: dict[str, int] = {}
        inputs: dict[bytes, int] = {}
        morphs: dict[str, dict[int, Curve]] = {}

        for binding, first, width in clip_bindings(clip):
            if binding.typeID == CLASS_SKINNED_MESH_RENDERER:
                self._collect_morph(binding, curves.get(first), morphs, tos)
                continue
            if binding.typeID != CLASS_TRANSFORM or binding.attribute not in ATTRIBUTE_WIDTH:
                continue
            path = tos.get(binding.path)
            rest = self.rest.get(path) if path else None
            # Cloth and skirt bones are spawned by the runtime, not in the prefab.
            if rest is None:
                continue
            components = [curves.get(first + i) for i in range(width)]
            if any(c is None for c in components):
                continue

            prop = ATTRIBUTE_PROPERTY[binding.attribute]
            times, values = self._sample(components, start, duration, rate,
                                         TOLERANCE[prop])
            if binding.attribute == 4:
                values = _euler_to_quaternion(values)
            values = _to_gltf(prop, values)
            times, values = decimate(times, values, TOLERANCE[prop])
            if len(times) <= 2 and np.abs(values - np.asarray(rest[prop])).max() \
                    <= TOLERANCE[prop]:
                continue                      # holds the rest pose; nothing to say

            if path not in nodes:
                nodes[path] = len(gltf.root["nodes"])
                gltf.root["nodes"].append({"name": rest["name"]})
            animation["samplers"].append({
                "input": _shared_input(gltf, inputs, times),
                "output": _output_accessor(gltf, prop, values),
                "interpolation": "LINEAR",
            })
            animation["channels"].append({
                "sampler": len(animation["samplers"]) - 1,
                "target": {"node": nodes[path], "path": prop},
            })

        for path, animated in morphs.items():
            names = self.shapes[path]
            columns = sorted(animated)
            # Unity keys blend shape weights as percentages; glTF wants unit
            # fractions, and every shape in one output rather than a curve each.
            times, values = self._sample([animated[c] for c in columns],
                                         start, duration, rate, 0.5)
            # Where a shape sits idle the bundle keys it only every ~0.8s, and the
            # cubic joining those keys wanders far outside the range a weight can
            # mean — 133_Ready holds face01 at 100 but swings to 578 in between,
            # against face02 at -483. Every channel in every model tops out at a
            # fullWeight of 100, so the runtime must clamp; do the same and the
            # curve reads as authored, a hold and then a crossfade. Excursions
            # inside a densely keyed stretch overshoot by 1-2% at most, so this
            # costs nothing where the artist actually keyed something.
            np.clip(values, 0.0, 100.0, out=values)
            weights = np.zeros((len(times), len(names)), np.float32)
            weights[:, columns] = values / 100.0
            times, weights = decimate(times, weights, TOLERANCE["weights"])
            animation["samplers"].append({
                "input": _shared_input(gltf, inputs, times),
                "output": gltf.add_accessor(weights.reshape(-1, 1).copy(), "SCALAR",
                                            COMPONENT_FLOAT),
                "interpolation": "LINEAR",
            })
            animation["channels"].append({
                "sampler": len(animation["samplers"]) - 1,
                "target": {"node": _morph_node(gltf, nodes, path, names),
                           "path": "weights"},
            })

        if not animation["channels"]:
            return None
        gltf.root["scenes"][0]["nodes"] = list(range(len(gltf.root["nodes"])))
        return gltf

    def _collect_morph(self, binding: Any, curve: Optional[Curve],
                       morphs: dict[str, dict[int, Curve]],
                       tos: dict[int, str]) -> None:
        """File a SkinnedMeshRenderer binding under the shape it drives.

        A generic binding names its attribute by CRC32, which for a blend shape
        is exactly the hash the mesh already stores against the channel. Matching
        on the hash rather than the channel index is what lets a timeline clip
        retarget: its rig often carries a reduced set of the same named shapes,
        and a shape it has no counterpart for simply finds no match and is left out.
        """
        path = tos.get(binding.path)
        names = self.shapes.get(path) if path else None
        if names is None or curve is None:
            return
        for index, name in enumerate(names):
            if zlib.crc32(name.encode()) & 0xFFFFFFFF == binding.attribute:
                morphs.setdefault(path, {})[index] = curve
                return

    @staticmethod
    def _sample(components: list[Curve], start: float, duration: float, rate: float,
                tolerance: float) -> tuple[np.ndarray, np.ndarray]:
        """Evaluate the curves onto a grid a straight line can follow.

        Start from the curves' own keys plus the authoring frame grid — the union
        of keys alone under-samples a curve that eases over a long segment — then
        bisect wherever the chord still misses the cubic. `decimate` afterwards
        takes back whatever either step added needlessly.
        """
        grid = np.arange(start, start + duration + 0.5 / rate, 1.0 / rate,
                         dtype=np.float32)
        ends = np.array([start, start + duration], np.float32)
        keys = np.concatenate([c.times for c in components] + [grid, ends])
        times = np.unique(np.clip(keys, start, start + duration))
        sample = lambda t: np.stack([c.sample(t) for c in components], axis=1)
        values = sample(times)

        # A fast bone can swing well off the chord inside a single frame.
        for _ in range(5):
            middle = (times[:-1] + times[1:]) / 2
            missed = np.abs(sample(middle) - (values[:-1] + values[1:]) / 2) \
                .max(axis=1) > tolerance
            if not missed.any():
                break
            times = np.sort(np.concatenate([times, middle[missed]]))
            values = sample(times)
        return times - start, values


def _to_gltf(prop: str, values: np.ndarray) -> np.ndarray:
    """Unity is left handed; the exporter mirrors X to reach glTF's right hand."""
    values = values.astype(np.float32, copy=True)
    if prop == "translation":
        values[:, 0] *= -1.0
    elif prop == "rotation":
        values[:, 1:3] *= -1.0
        values /= np.linalg.norm(values, axis=1, keepdims=True).clip(1e-8)
        # Keep successive keys on one hemisphere or linear blending takes the
        # long way round.
        flip = np.cumprod(np.where(
            np.concatenate([[1.0], (values[1:] * values[:-1]).sum(axis=1)]) < 0,
            -1.0, 1.0))
        values *= flip[:, None]
    return values


def _euler_to_quaternion(euler: np.ndarray) -> np.ndarray:
    """Unity euler curves are degrees applied in ZXY order."""
    x, y, z = np.radians(euler).T / 2.0
    cx, sx, cy, sy, cz, sz = (np.cos(x), np.sin(x), np.cos(y),
                              np.sin(y), np.cos(z), np.sin(z))
    return np.stack([
        sx * cy * cz + cx * sy * sz,
        cx * sy * cz - sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    ], axis=1)


def _shared_input(gltf: GltfBuilder, cache: dict[bytes, int],
                  times: np.ndarray) -> int:
    """Most tracks are keyed on the same frames, so hand out one accessor."""
    times = np.ascontiguousarray(times, np.float32)
    key = times.tobytes()
    if key not in cache:
        cache[key] = gltf.add_accessor(times.reshape(-1, 1), "SCALAR",
                                       COMPONENT_FLOAT, minmax=True)
    return cache[key]


def _morph_node(gltf: GltfBuilder, nodes: dict[str, int], name: str,
                shapes: list[str]) -> int:
    """A stand-in for the mesh whose blend shape weights the clip drives.

    A weights channel may only target a node that has morph targets, and
    three.js builds no track for one that has none, so the clip carries a
    degenerate triangle with the right shape count. The node takes the name of
    the mesh in the model, which is what the viewer retargets the track by — and
    so has to be the node the clip already moves, if it moves that one at all.
    """
    origin = gltf.add_accessor(np.zeros((3, 3), np.float32), "VEC3",
                               COMPONENT_FLOAT, TARGET_ARRAY, minmax=True)
    gltf.root["meshes"].append({
        "name": f"{name}_shapes",
        "primitives": [{"attributes": {"POSITION": origin},
                        "targets": [{"POSITION": origin}] * len(shapes)}],
        "weights": [0.0] * len(shapes),
        "extras": {"targetNames": shapes},
    })
    if name not in nodes:
        nodes[name] = len(gltf.root["nodes"])
        gltf.root["nodes"].append({"name": name.rsplit("/", 1)[-1]})
    gltf.root["nodes"][nodes[name]]["mesh"] = len(gltf.root["meshes"]) - 1
    return nodes[name]


def _output_accessor(gltf: GltfBuilder, prop: str, values: np.ndarray) -> int:
    if prop == "rotation":
        # Quaternion components are bounded, so normalised shorts halve the file
        # at ~1/32767 of a unit — far below what decimation already discards.
        quantised = np.rint(np.clip(values, -1.0, 1.0) * 32767.0).astype(np.int16)
        return gltf.add_accessor(quantised, "VEC4", COMPONENT_SHORT, normalized=True)
    return gltf.add_accessor(values.astype(np.float32), "VEC3", COMPONENT_FLOAT)


def _skeleton_rest_pose(
        char_id: str) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """What a clip has to be retargeted against, read off the model bundle.

    Bone path -> node name and rest TRS, as the model .glb exports them, and
    mesh path -> blend shape names, in morph target order.
    """
    env = load_character_env(char_id, parts=("models",))
    rest: dict[str, dict[str, Any]] = {}
    shapes: dict[str, list[str]] = {}

    def walk(transform: Transform, prefix: str) -> None:
        game_object = transform.m_GameObject.read()
        name = game_object.m_Name
        path = f"{prefix}/{name}" if prefix else name
        p, q, s = (transform.m_LocalPosition, transform.m_LocalRotation,
                   transform.m_LocalScale)
        rest[path] = {"name": name,
                      "translation": [-p.x, p.y, p.z],
                      "rotation": [q.x, -q.y, -q.z, q.w],
                      "scale": [s.x, s.y, s.z]}
        for component in game_object.m_Component:
            if component.component.type.name != "SkinnedMeshRenderer":
                continue
            renderer: SkinnedMeshRenderer = component.component.read()
            if renderer.m_Mesh and renderer.m_Mesh.m_PathID:
                names = [c.name for c in blend_shape_channels(renderer.m_Mesh.read())]
                if names:
                    shapes[path] = names
        for child in transform.m_Children:
            walk(child.read(), path)

    # Paths in m_TOS are relative to the prefab root, which is not itself in them.
    for child in find_prefab_root(env, char_id).m_Children:
        walk(child.read(), "")
    return rest, shapes


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    """The JSON and BIN chunks of a .glb, as `GltfBuilder.save` lays them out."""
    data = path.read_bytes()
    root: dict[str, Any] = {}
    binary = b""
    offset = 12
    while offset < len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + length]
        if kind == 0x4E4F534A:
            root = json.loads(chunk)
        else:
            binary = chunk
        offset += 8 + length
    return root, binary


def _read_accessor(root: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    accessor = root["accessors"][index]
    view = root["bufferViews"][accessor["bufferView"]]
    dtype = np.dtype({COMPONENT_FLOAT: "<f4", COMPONENT_USHORT: "<u2",
                      COMPONENT_UINT: "<u4", COMPONENT_UBYTE: "u1",
                      COMPONENT_SHORT: "<i2"}[accessor["componentType"]])
    columns = {"SCALAR": 1, "VEC2": 2, "VEC3": 3,
               "VEC4": 4, "MAT4": 16}[accessor["type"]]
    values = np.frombuffer(binary, dtype, accessor["count"] * columns,
                           view.get("byteOffset", 0) + accessor.get("byteOffset", 0))
    values = values.reshape(accessor["count"], columns).astype(np.float32)
    if accessor.get("normalized"):
        values = np.clip(values / np.iinfo(dtype).max, -1.0, 1.0)
    return values


def _compose(translation: np.ndarray, rotation: np.ndarray,
             scale: np.ndarray) -> np.ndarray:
    x, y, z, w = rotation
    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, :3] = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], np.float32) * scale[None, :]
    matrix[:3, 3] = translation
    return matrix


def _interpolate(track: Optional[tuple[np.ndarray, np.ndarray]], time: float,
                 rest: np.ndarray, quaternion: bool) -> np.ndarray:
    """One channel at one time; the clip's own LINEAR, ends held."""
    if track is None:
        return rest
    times, values = track
    if time <= times[0]:
        return values[0]
    if time >= times[-1]:
        return values[-1]
    key = int(np.searchsorted(times, time)) - 1
    ratio = (time - times[key]) / (times[key + 1] - times[key])
    before, after = values[key], values[key + 1]
    if quaternion:
        # Nearest arc, then renormalise: nlerp misplaces a fast turn's midpoint
        # by a degree or two, which no bounding box notices.
        if float(before @ after) < 0:
            after = -after
        blended = before + ratio * (after - before)
        return blended / np.linalg.norm(blended)
    return before + ratio * (after - before)


class PosedModel:
    """A model .glb, re-posed by a clip, to see where each of its meshes lands.

    The viewer's own skinning is the ground truth for what a reader sees, so
    this repeats it on the CPU: joint world matrices from the clip's tracks,
    times the inverse bind matrices, weighted per vertex. A few hundred
    vertices per mesh place a bounding box closely enough to tell a prop held
    in frame from one parked under the floor.
    """

    def __init__(self, path: Path, sample: int = 200) -> None:
        self.root, binary = _read_glb(path)
        nodes = self.root["nodes"]
        self.parents = [-1] * len(nodes)
        for index, node in enumerate(nodes):
            for child in node.get("children", ()):
                self.parents[child] = index
        self.names = [node.get("name", "") for node in nodes]
        self.rest = [(np.asarray(node.get("translation", (0, 0, 0)), np.float32),
                      np.asarray(node.get("rotation", (0, 0, 0, 1)), np.float32),
                      np.asarray(node.get("scale", (1, 1, 1)), np.float32))
                     for node in nodes]
        self.parts: list[dict[str, Any]] = []
        for index, node in enumerate(nodes):
            if "mesh" not in node:
                continue
            mesh = self.root["meshes"][node["mesh"]]
            attributes = mesh["primitives"][0]["attributes"]
            points = _read_accessor(self.root, binary, attributes["POSITION"])
            count = len(points)
            step = max(1, count // sample)
            points = points[::step]
            part = {
                "name": self.names[index],
                "node": index,
                "vertices": count,
                "optional": bool(mesh.get("extras", {}).get("optional")),
                "points": np.concatenate(
                    [points, np.ones((len(points), 1), np.float32)], axis=1),
                "joints": None,
            }
            if "skin" in node and "JOINTS_0" in attributes:
                skin = self.root["skins"][node["skin"]]
                part["joints"] = _read_accessor(
                    self.root, binary, attributes["JOINTS_0"])[::step].astype(np.intp)
                part["weights"] = _read_accessor(
                    self.root, binary, attributes["WEIGHTS_0"])[::step]
                part["bones"] = skin["joints"]
                part["bind"] = _read_accessor(
                    self.root, binary,
                    skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
            self.parts.append(part)

    def tracks(self, clip_path: Path) -> dict[str, dict[str, Any]]:
        """The clip's channels, keyed by the node name they retarget onto."""
        root, binary = _read_glb(clip_path)
        animation = root["animations"][0]
        found: dict[str, dict[str, Any]] = {}
        for channel in animation["channels"]:
            name = root["nodes"][channel["target"]["node"]].get("name")
            sampler = animation["samplers"][channel["sampler"]]
            found.setdefault(name, {})[channel["target"]["path"]] = (
                _read_accessor(root, binary, sampler["input"])[:, 0],
                _read_accessor(root, binary, sampler["output"]))
        return found

    def _world(self, tracks: dict[str, dict[str, Any]], time: float) -> np.ndarray:
        world = np.empty((len(self.rest), 4, 4), np.float32)
        for index, (translation, rotation, scale) in enumerate(self.rest):
            track = tracks.get(self.names[index], {})
            local = _compose(
                _interpolate(track.get("translation"), time, translation, False),
                _interpolate(track.get("rotation"), time, rotation, True),
                _interpolate(track.get("scale"), time, scale, False))
            parent = self.parents[index]
            world[index] = local if parent < 0 else world[parent] @ local
        return world

    def boxes(self, tracks: dict[str, dict[str, Any]],
              times: np.ndarray) -> dict[str, np.ndarray]:
        """Part name -> its skinned (min, max) at each of `times`, stacked."""
        found: dict[str, list[np.ndarray]] = {}
        for time in times:
            world = self._world(tracks, float(time))
            for part in self.parts:
                if part["joints"] is None:
                    points = (world[part["node"]] @ part["points"].T).T[:, :3]
                else:
                    skinning = world[part["bones"]] @ part["bind"]
                    points = np.zeros((len(part["points"]), 3), np.float32)
                    for column in range(part["joints"].shape[1]):
                        moved = np.einsum("nij,nj->ni",
                                          skinning[part["joints"][:, column]],
                                          part["points"])
                        points += moved[:, :3] * part["weights"][:, column, None]
                found.setdefault(part["name"], []).append(
                    np.stack([points.min(axis=0), points.max(axis=0)]))
        return {name: np.stack(boxes) for name, boxes in found.items()}

    def parked(self, clip_path: Path, duration: float,
               shown: list[str]) -> list[str]:
        """The parts this clip switches off, by node name.

        The context rigs state the pose a clip starts from, not what it goes
        on to do, so they keep naming a prop the clip has since put away. The
        game puts one away in two ways, and neither deactivates the node: it
        scales the rig the prop hangs from to nothing, or it drives that rig
        out of the scene — Ann's Ready drops her dog and her weapon seven
        metres under the floor. So a mesh with no size left is off, and so is
        one whose bounds never come near the body's: a body height away in any
        direction, or half that when it hangs entirely below the body, which
        is where a stowed prop nearly always goes. Held props clear the body
        by well under half a body height even at arm's length, and stay beside
        it rather than under it.

        Only what would otherwise be drawn is worth naming: an optional part
        no rig shows is already hidden by the viewer's baseline.
        """
        if not self.parts:
            return []
        tracks = self.tracks(clip_path)
        boxes = self.boxes(tracks, np.linspace(0.0, duration, 5))
        # The body is the mesh with the most vertices in every model here; ask
        # for it that way rather than by a name only some of them use.
        body = boxes[max(self.parts, key=lambda part: part["vertices"])["name"]]
        low, high = body[:, 0].min(axis=0), body[:, 1].max(axis=0)
        height = float(high[1] - low[1])
        parked = []
        for part in self.parts:
            if part["optional"] and part["name"] not in shown:
                continue
            box = boxes[part["name"]]
            # A prop scaled away collapses to a point, so every sample of it
            # measures nothing; one that only appears later in the clip does
            # not. The scale is never quite zero -- Minova's Walk leaves her
            # second weapon a millimetre across -- but nothing anyone is meant
            # to see is under a centimetre either, so the two are far apart.
            if float((box[:, 1] - box[:, 0]).max()) < 1e-2 * height:
                parked.append(part["name"])
                continue
            bottom, top = box[:, 0].min(axis=0), box[:, 1].max(axis=0)
            gap = float(np.maximum(low - top, bottom - high).max())
            if gap > height or (gap > height / 2 and top[1] < low[1]):
                parked.append(part["name"])
        return sorted(parked)


def export_animations(char_id: str, char_dir: Path, stem: str,
                      base_slug: str) -> list[dict[str, Any]]:
    """Writes `char_dir/<stem>_anims/*.glb` and `char_dir/<stem>.anims.json`.

    A clip's `file` in the manifest is fetched relative to the whole output
    root (`write_index`'s `out_dir`), not to `char_dir`, so it carries
    `base_slug` even though `char_dir` already is `<out_dir>/<base_slug>`.
    A clip the context rigs give parts to also carries a `show` list, and one
    that parks a part off screen a `hide` list.
    """
    exporter = AnimationExporter(char_id)
    show_rules = rig_show_rules(char_id)
    model_path = char_dir / f"{stem}.glb"
    model = PosedModel(model_path) if model_path.exists() else None
    clip_dir = char_dir / f"{stem}_anims"
    clip_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    taken: set[str] = set()
    for clip, tos in exporter.clips():
        gltf = exporter.build(clip, tos)
        if gltf is None:
            continue
        name = gltf.root["animations"][0]["name"]
        # The name comes from the bundle and ends up in a URL, so keep it to
        # characters that need no escaping and cannot walk out of the directory.
        clip_stem = slug(name)
        # Two bundles now feed this, and both name a clip `Recorded`.
        while clip_stem in taken:
            clip_stem += "_"
        taken.add(clip_stem)
        path = clip_dir / (clip_stem + ".glb")
        gltf.save(path)
        entry = {
            "name": name,
            "file": f"{base_slug}/{stem}_anims/{path.name}",
            "face": any(channel["target"]["path"] == "weights"
                        for channel in gltf.root["animations"][0]["channels"]),
            "duration": round(float(clip.m_MuscleClip.m_StopTime
                                    - clip.m_MuscleClip.m_StartTime), 4),
            "loop": bool(clip.m_MuscleClip.m_LoopTime),
            "bytes": path.stat().st_size,
        }
        show = show_rules.get(_norm_key(name), [])
        hide = model.parked(path, entry["duration"], show) if model else []
        # `hide` runs before `show` in the viewer, so a name left in both would
        # come back on screen.
        show = [part for part in show if part not in hide]
        if show:
            entry["show"] = show
        if hide:
            entry["hide"] = hide
        manifest.append(entry)
    (char_dir / f"{stem}.anims.json").write_text(
        json.dumps({"id": char_id, "clips": manifest}, indent=1))
    return manifest


def _export_character(char_id: str, output_root: Path, animations: bool,
                      overwrite: bool) -> list[str]:
    """One character's model and clips, in a worker process. Returns its output."""
    base_slug = slug(character_base_name(char_id))
    stem = slug(character_display_name(char_id))
    char_dir = output_root / base_slug
    model_path = char_dir / f"{stem}.glb"
    lines: list[str] = []
    if overwrite or not model_path.exists():
        try:
            CharacterExporter(char_id).export(model_path)
            lines.append(f"{base_slug}/{model_path.name}  "
                         f"{model_path.stat().st_size / 1e6:.2f} MB")
        except Exception as exc:
            return lines + [f"{stem}: {type(exc).__name__}: {exc}"]
    if not animations:
        return lines
    if not overwrite and (char_dir / f"{stem}.anims.json").exists():
        return lines
    try:
        manifest = export_animations(char_id, char_dir, stem, base_slug)
    except Exception as exc:
        return lines + [f"{stem} animations: {type(exc).__name__}: {exc}"]
    total = sum(clip["bytes"] for clip in manifest)
    return lines + [f"{stem}: {len(manifest)} clips, {total / 1e6:.2f} MB"]


def export_3d_models(char_ids: set[str] | None = None,
                     output_root: Path | None = None,
                     animations: bool = True,
                     overwrite: bool = False,
                     jobs: int | None = None) -> None:
    output_root = output_root or model_root
    output_root.mkdir(parents=True, exist_ok=True)
    available = set(available_character_ids())
    if char_ids is None:
        char_ids = available
    else:
        for char_id in sorted(char_ids - available):
            print(f"WARNING: No char_{char_id}_models bundle found")
        char_ids &= available
    unknown = {char_id for char_id in char_ids if not character_is_known(char_id)}
    for char_id in sorted(unknown):
        print(f"WARNING: No CharacterSkin entry for {char_id}")
    char_ids -= unknown
    if not char_ids:
        return

    # Build the CAB index here rather than letting every worker race to write it.
    get_cab_index()
    # Characters are independent, and one peaks near 2 GB that UnityPy does not
    # hand back, so give each a process of its own rather than let a worker
    # accumulate several. A fresh one costs half a second against half a minute.
    workers = min(jobs or max(os.cpu_count() - 4, 4), len(char_ids))
    work = partial(_export_character, output_root=output_root,
                   animations=animations, overwrite=overwrite)
    with ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=1) as pool:
        for lines in pool.map(work, sorted(char_ids)):
            for line in lines:
                print(line)
    write_index(output_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Stella Sora 3D character models and clips to glTF.")
    parser.add_argument("--char-id", action="append", dest="char_ids")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-animations", action="store_true",
                        help="Export models only, skipping their clips")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-export even if output already exists")
    parser.add_argument("--jobs", type=int, default=None,
                        help="Characters to export at once (default: cores - 4)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    export_3d_models(char_ids=set(args.char_ids) if args.char_ids else None,
                     output_root=args.out,
                     animations=not args.no_animations,
                     overwrite=args.overwrite,
                     jobs=args.jobs)


if __name__ == "__main__":
    main()
