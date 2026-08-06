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
import re
import struct
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import UnityPy
from UnityPy.classes import (AnimationClip, Material, Mesh, SkinnedMeshRenderer,
                             Transform)
from UnityPy.helpers.MeshHelper import MeshHandler

from unpack.unpack_paths import unity_asset_dir_1, unity_asset_dir_2
from unpack.unpack_utils import get_unity3d_files
from utils.data_utils import assets_root

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


def find_prefab_root(env: UnityPy.Environment, char_id: str) -> Transform:
    transforms = [o.read() for o in env.objects if o.type.name == "Transform"]
    roots = {t.m_GameObject.read().m_Name: t for t in transforms
             if not (t.m_Father and t.m_Father.m_PathID)}
    for name in (f"{char_id}_model", char_id):
        if name in roots:
            return roots[name]
    raise LookupError(f"no model prefab among {sorted(roots)}")


class CharacterExporter:
    def __init__(self, char_id: str, include_lod: bool = False) -> None:
        self.char_id = char_id
        self.include_lod = include_lod
        self.gltf = GltfBuilder()
        self.node_of_transform: dict[int, int] = {}
        self.texture_cache: dict[int, Optional[int]] = {}
        self.material_cache: dict[int, Optional[int]] = {}
        self.env = load_character_env(char_id)

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
        if floats.get("_Enable_Alpha_Test", 0.0) or floats.get("_DstBlend", 0.0):
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

        primitives = []
        for i, triangles in enumerate(handler.get_triangles()):
            indices = np.asarray(triangles, dtype=np.uint32).reshape(-1, 3)[:, ::-1]
            primitive = {"attributes": attributes,
                         "indices": self.gltf.add_accessor(
                             indices.ravel().copy(), "SCALAR",
                             COMPONENT_UINT, TARGET_ELEMENT)}
            if i < len(renderer.m_Materials) and renderer.m_Materials[i].m_PathID:
                material_index = self._add_material(renderer.m_Materials[i])
                if material_index is not None:
                    primitive["material"] = material_index
            primitives.append(primitive)

        self.gltf.root["meshes"].append({"name": mesh.m_Name, "primitives": primitives})
        transform_id = next(c.component.m_PathID for c in game_object.m_Component
                            if c.component.m_PathID in self.node_of_transform)
        node = self.gltf.root["nodes"][self.node_of_transform[transform_id]]
        node["mesh"] = len(self.gltf.root["meshes"]) - 1
        if skin_index is not None:
            node["skin"] = skin_index
            node["translation"], node["scale"] = [0, 0, 0], [1, 1, 1]
            node["rotation"] = [0, 0, 0, 1]

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
    entries = [{"id": p.stem[len("char_"):], "file": p.name,
                "label": f"char_{p.stem[len('char_'):]}"}
               for p in sorted(out_dir.glob("char_*.glb"))]
    (out_dir / "index.json").write_text(json.dumps(entries, indent=1))


CLASS_TRANSFORM = 4
# Mecanim's kBindTransform* attributes, and how many curves each one spans.
ATTRIBUTE_WIDTH = {1: 3, 2: 4, 3: 3, 4: 3}    # position, rotation, scale, euler
ATTRIBUTE_PROPERTY = {1: "translation", 2: "rotation", 3: "scale", 4: "rotation"}

# How far a reconstructed track may stray, both when refining the sample grid and
# when decimating it again. Positions are in metres on a ~1.6 m character, and
# 4e-3 on a quaternion component is under half a degree.
TOLERANCE = {"translation": 5e-4, "rotation": 4e-3, "scale": 2e-3}


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
    """Drop keys that a straight line between their neighbours already reproduces."""
    count = len(times)
    if count < 3:
        return times, values
    keep, anchor = [0], 0
    while anchor < count - 1:
        # Longest run from the anchor whose interior stays within tolerance.
        end = anchor + 1
        while end < count - 1:
            candidate = end + 1
            span = times[candidate] - times[anchor]
            if span <= 0:
                break
            weight = ((times[anchor + 1:candidate] - times[anchor])
                      / span)[:, None]
            approximated = (values[anchor] * (1.0 - weight)
                            + values[candidate] * weight)
            if np.abs(approximated - values[anchor + 1:candidate]).max() > tolerance:
                break
            end = candidate
        keep.append(end)
        anchor = end
    index = np.array(keep)
    return times[index], values[index]


class AnimationExporter:
    def __init__(self, char_id: str) -> None:
        self.char_id = char_id
        self.rest = _skeleton_rest_pose(char_id)
        self.env = self._load_environment()
        self.tos = self._read_tos()

    def _load_environment(self) -> UnityPy.Environment:
        available = {f.name: f for f in get_unity3d_files()}
        # Alternate outfits ship a model but no clips of their own; the last digit
        # is the outfit, and they animate off the default one's bundle.
        for char_id in (self.char_id, f"{self.char_id[:-1]}1"):
            name = f"char_{char_id}_animations.unity3d"
            if name in available:
                return UnityPy.Environment(str(available[name]))
        raise FileNotFoundError(f"no animation bundle for char_{self.char_id}")

    def _read_tos(self) -> dict[int, str]:
        """CRC path hash -> bone path, merged over every avatar in the bundle."""
        tos: dict[int, str] = {}
        for obj in self.env.objects:
            if obj.type.name == "Avatar":
                for path_hash, path in obj.read().m_TOS:
                    tos.setdefault(path_hash, path)
        return tos

    def clips(self) -> list[AnimationClip]:
        clips = [o.read() for o in self.env.objects if o.type.name == "AnimationClip"]
        return sorted(clips, key=lambda c: c.m_Name)

    def build(self, clip: AnimationClip) -> Optional[GltfBuilder]:
        curves = read_curves(clip)
        start = float(clip.m_MuscleClip.m_StartTime)
        duration = float(clip.m_MuscleClip.m_StopTime) - start
        if duration <= 0:
            return None
        rate = float(clip.m_SampleRate) or 30.0

        gltf = GltfBuilder()
        gltf.root["animations"] = [{"name": clip.m_Name, "channels": [], "samplers": []}]
        animation = gltf.root["animations"][0]
        nodes: dict[str, int] = {}
        inputs: dict[bytes, int] = {}

        for binding, first, width in clip_bindings(clip):
            if binding.typeID != CLASS_TRANSFORM or binding.attribute not in ATTRIBUTE_WIDTH:
                continue
            path = self.tos.get(binding.path)
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

        if not animation["channels"]:
            return None
        gltf.root["scenes"][0]["nodes"] = list(range(len(gltf.root["nodes"])))
        return gltf

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


def _output_accessor(gltf: GltfBuilder, prop: str, values: np.ndarray) -> int:
    if prop == "rotation":
        # Quaternion components are bounded, so normalised shorts halve the file
        # at ~1/32767 of a unit — far below what decimation already discards.
        quantised = np.rint(np.clip(values, -1.0, 1.0) * 32767.0).astype(np.int16)
        return gltf.add_accessor(quantised, "VEC4", COMPONENT_SHORT, normalized=True)
    return gltf.add_accessor(values.astype(np.float32), "VEC3", COMPONENT_FLOAT)


def _skeleton_rest_pose(char_id: str) -> dict[str, dict[str, Any]]:
    """Bone path -> node name and rest TRS, as the model .glb exports them."""
    env = load_character_env(char_id, parts=("models",))
    rest: dict[str, dict[str, Any]] = {}

    def walk(transform: Transform, prefix: str) -> None:
        name = transform.m_GameObject.read().m_Name
        path = f"{prefix}/{name}" if prefix else name
        p, q, s = (transform.m_LocalPosition, transform.m_LocalRotation,
                   transform.m_LocalScale)
        rest[path] = {"name": name,
                      "translation": [-p.x, p.y, p.z],
                      "rotation": [q.x, -q.y, -q.z, q.w],
                      "scale": [s.x, s.y, s.z]}
        for child in transform.m_Children:
            walk(child.read(), path)

    # Paths in m_TOS are relative to the prefab root, which is not itself in them.
    for child in find_prefab_root(env, char_id).m_Children:
        walk(child.read(), "")
    return rest


def export_animations(char_id: str, out_dir: Path) -> list[dict[str, Any]]:
    exporter = AnimationExporter(char_id)
    clip_dir = out_dir / "anim" / f"char_{char_id}"
    clip_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for clip in exporter.clips():
        gltf = exporter.build(clip)
        if gltf is None:
            continue
        # The name comes from the bundle and ends up in a URL, so keep it to
        # characters that need no escaping and cannot walk out of the directory.
        path = clip_dir / (re.sub(r"[^A-Za-z0-9._-]", "_", clip.m_Name) + ".glb")
        gltf.save(path)
        manifest.append({
            "name": clip.m_Name,
            "file": f"anim/char_{char_id}/{path.name}",
            "duration": round(float(clip.m_MuscleClip.m_StopTime
                                    - clip.m_MuscleClip.m_StartTime), 4),
            "loop": bool(clip.m_MuscleClip.m_LoopTime),
            "bytes": path.stat().st_size,
        })
    (out_dir / f"char_{char_id}.anims.json").write_text(
        json.dumps({"id": char_id, "clips": manifest}, indent=1))
    return manifest


def export_3d_models(char_ids: set[str] | None = None,
                     output_root: Path | None = None,
                     animations: bool = True,
                     overwrite: bool = False) -> None:
    output_root = output_root or model_root
    output_root.mkdir(parents=True, exist_ok=True)
    available = set(available_character_ids())
    if char_ids is None:
        char_ids = available
    else:
        for char_id in sorted(char_ids - available):
            print(f"WARNING: No char_{char_id}_models bundle found")
        char_ids &= available

    for char_id in sorted(char_ids):
        model_path = output_root / f"char_{char_id}.glb"
        if overwrite or not model_path.exists():
            try:
                CharacterExporter(char_id).export(model_path)
                print(f"{model_path.name}  {model_path.stat().st_size / 1e6:.2f} MB")
            except Exception as exc:
                print(f"char_{char_id}: {type(exc).__name__}: {exc}")
                continue
        if not animations:
            continue
        if not overwrite and (output_root / f"char_{char_id}.anims.json").exists():
            continue
        try:
            manifest = export_animations(char_id, output_root)
        except Exception as exc:
            print(f"char_{char_id} animations: {type(exc).__name__}: {exc}")
            continue
        total = sum(clip["bytes"] for clip in manifest)
        print(f"char_{char_id}: {len(manifest)} clips, {total / 1e6:.2f} MB")
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
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    export_3d_models(char_ids=set(args.char_ids) if args.char_ids else None,
                     output_root=args.out,
                     animations=not args.no_animations,
                     overwrite=args.overwrite)


if __name__ == "__main__":
    main()
