import argparse
import json
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import UnityPy
from UnityPy.enums import ClassIDType
from UnityPy.files import ObjectReader

from unpack.unpack_utils import get_unity3d_files
from utils.data_utils import assets_root


@dataclass(frozen=True)
class Live2DVariant:
    name: str
    prefab_suffix: str
    moc_suffix: str
    motion_group: str
    motion_list_name: str


@dataclass
class Live2DMotion:
    name: str
    file: str
    duration: float
    fade_in: float
    fade_out: float
    parameter_count: int


@dataclass
class Live2DExportResult:
    skin_id: int
    variant: str
    output_dir: Path
    moc_name: str | None = None
    moc_file: str | None = None
    texture_files: list[str] = field(default_factory=list)
    motions: list[Live2DMotion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class Live2DModelCandidate:
    component_id: int
    game_object_id: int
    moc_name: str
    moc_bytes: bytes
    texture_objects: list[tuple[int, ObjectReader]]
    renderer_count: int


@dataclass(frozen=True)
class Live2DReadError:
    source_bundle: Path
    context: str
    path_id: int
    object_type: str
    container: str
    error_type: str
    message: str

    def format(self) -> str:
        container = f" {self.container}" if self.container else ""
        return (
            f"{self.source_bundle.name}: {self.context}: "
            f"{self.object_type} path_id={self.path_id}{container}: {self.error_type}: {self.message}"
        )


VARIANTS = {
    "base": Live2DVariant("base", "l", "L", "Base", "Live2D.fadeMotionList"),
    "full": Live2DVariant("full", "lf", "F", "Full", "Live2D_Full.fadeMotionList"),
    "talent": Live2DVariant("talent", "lt", "T", "Talent", "Live2D_Talent.fadeMotionList"),
}

DEFAULT_VARIANTS = set(VARIANTS)
TEXTURE_NAME_RE = re.compile(r"^(.*?)(\d+)$")


def _path_id(ref: dict[str, Any] | None) -> int | None:
    if not isinstance(ref, dict):
        return None
    return ref.get("m_PathID")


def _component_path_id(component: dict[str, Any]) -> int | None:
    return _path_id(component.get("component"))


def _object_type_name(obj: ObjectReader) -> str:
    return getattr(obj.type, "name", str(obj.type))


def _read_typetree(
    obj: ObjectReader,
    source_bundle: Path,
    read_errors: list[Live2DReadError],
    context: str,
) -> dict[str, Any] | None:
    try:
        return obj.read_typetree()
    except Exception as exc:
        read_errors.append(Live2DReadError(
            source_bundle=source_bundle,
            context=context,
            path_id=obj.path_id,
            object_type=_object_type_name(obj),
            container=obj.container or "",
            error_type=type(exc).__name__,
            message=str(exc),
        ))
        return None


def _script_names(
    objects: dict[int, ObjectReader],
    source_bundle: Path,
    read_errors: list[Live2DReadError],
) -> dict[int, str]:
    scripts: dict[int, str] = {}
    for path_id, obj in objects.items():
        if obj.type != ClassIDType.MonoScript:
            continue
        data = _read_typetree(obj, source_bundle, read_errors, "read MonoScript")
        if data is None:
            continue
        name = data.get("m_Name") or data.get("m_ClassName")
        if name:
            scripts[path_id] = name
    return scripts


def _script_name(data: dict[str, Any], scripts: dict[int, str]) -> str | None:
    return scripts.get(_path_id(data.get("m_Script")))


def _safe_json_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _unique_read_error_formats(read_errors: list[Live2DReadError]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for read_error in read_errors:
        formatted = read_error.format()
        if formatted in seen:
            continue
        seen.add(formatted)
        result.append(formatted)
    return result


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return
    path.write_bytes(data)
    print(f"Written to {path}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=4, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")
    print(f"Written to {path}")


def _export_texture(obj: ObjectReader, path: Path) -> None:
    data = obj.read()
    buffer = BytesIO()
    data.image.save(buffer, format="png")
    _write_bytes(path, buffer.getvalue())


def _bundle_by_skin_id() -> dict[int, Path]:
    result: dict[int, Path] = {}
    for file in get_unity3d_files():
        match = re.fullmatch(r"char_2d_(\d+)\.unity3d", file.name)
        if match:
            result[int(match.group(1))] = file
    return result


def _prefab_roots(objects: dict[int, ObjectReader], skin_id: int) -> dict[str, ObjectReader]:
    roots: dict[str, ObjectReader] = {}
    for obj in objects.values():
        if obj.type != ClassIDType.GameObject or not obj.container:
            continue
        container = obj.container.lower()
        for variant in VARIANTS.values():
            expected = f"/{skin_id}_{variant.prefab_suffix}.prefab"
            if container.endswith(expected):
                roots[variant.name] = obj
    return roots


def _descendant_game_objects(
    root: ObjectReader,
    objects: dict[int, ObjectReader],
    source_bundle: Path,
    read_errors: list[Live2DReadError],
) -> list[int]:
    root_data = _read_typetree(root, source_bundle, read_errors, "read prefab root")
    if root_data is None:
        return []
    components = root_data.get("m_Component") or []
    if not components:
        return []
    root_transform_id = _component_path_id(components[0])
    if root_transform_id is None:
        return []

    result: list[int] = []
    seen_transforms: set[int] = set()
    stack = [root_transform_id]
    while stack:
        transform_id = stack.pop()
        if transform_id in seen_transforms:
            continue
        seen_transforms.add(transform_id)
        transform_obj = objects.get(transform_id)
        if transform_obj is None:
            continue
        transform = _read_typetree(transform_obj, source_bundle, read_errors, "read transform hierarchy")
        if transform is None:
            continue
        game_object_id = _path_id(transform.get("m_GameObject"))
        if game_object_id is not None:
            result.append(game_object_id)
        for child in transform.get("m_Children") or []:
            child_id = _path_id(child)
            if child_id is not None:
                stack.append(child_id)
    return result


def _transform_for_game_object(
    game_object_id: int,
    objects: dict[int, ObjectReader],
    source_bundle: Path,
    read_errors: list[Live2DReadError],
    context: str,
) -> int | None:
    game_object = objects.get(game_object_id)
    if game_object is None:
        return None
    game_object_data = _read_typetree(game_object, source_bundle, read_errors, context)
    if game_object_data is None:
        return None
    for component in game_object_data.get("m_Component") or []:
        component_id = _component_path_id(component)
        component_obj = objects.get(component_id)
        if component_id is not None and component_obj is not None and component_obj.type == ClassIDType.Transform:
            return component_id
    return None


def _descendant_game_objects_from_id(
    root_game_object_id: int,
    objects: dict[int, ObjectReader],
    source_bundle: Path,
    read_errors: list[Live2DReadError],
) -> list[int]:
    root_transform_id = _transform_for_game_object(
        root_game_object_id,
        objects,
        source_bundle,
        read_errors,
        "read CubismModel GameObject transform",
    )
    if root_transform_id is None:
        return []

    result: list[int] = []
    seen_transforms: set[int] = set()
    stack = [root_transform_id]
    while stack:
        transform_id = stack.pop()
        if transform_id in seen_transforms:
            continue
        seen_transforms.add(transform_id)
        transform_obj = objects.get(transform_id)
        if transform_obj is None:
            continue
        transform = _read_typetree(transform_obj, source_bundle, read_errors, "read CubismModel transform hierarchy")
        if transform is None:
            continue
        game_object_id = _path_id(transform.get("m_GameObject"))
        if game_object_id is not None:
            result.append(game_object_id)
        for child in transform.get("m_Children") or []:
            child_id = _path_id(child)
            if child_id is not None:
                stack.append(child_id)
    return result


def _components_for_game_objects(
    game_object_ids: list[int],
    objects: dict[int, ObjectReader],
    scripts: dict[int, str],
    source_bundle: Path,
    read_errors: list[Live2DReadError],
) -> list[tuple[int, str | None, dict[str, Any]]]:
    components: list[tuple[int, str | None, dict[str, Any]]] = []
    for game_object_id in game_object_ids:
        game_object = objects.get(game_object_id)
        if game_object is None:
            continue
        game_object_data = _read_typetree(game_object, source_bundle, read_errors, "read GameObject components")
        if game_object_data is None:
            continue
        for component in game_object_data.get("m_Component") or []:
            component_id = _component_path_id(component)
            component_obj = objects.get(component_id)
            if component_id is None or component_obj is None or component_obj.type != ClassIDType.MonoBehaviour:
                continue
            data = _read_typetree(component_obj, source_bundle, read_errors, "read MonoBehaviour component")
            if data is None:
                continue
            components.append((component_id, _script_name(data, scripts), data))
    return components


def _components_by_game_object(
    components: list[tuple[int, str | None, dict[str, Any]]],
) -> dict[int, list[tuple[int, str | None, dict[str, Any]]]]:
    result: dict[int, list[tuple[int, str | None, dict[str, Any]]]] = {}
    for component in components:
        game_object_id = _path_id(component[2].get("m_GameObject"))
        if game_object_id is None:
            continue
        result.setdefault(game_object_id, []).append(component)
    return result


def _texture_sort_key(item: tuple[int, str]) -> tuple[str, int, str]:
    _, name = item
    match = TEXTURE_NAME_RE.match(name)
    if match:
        prefix, number = match.groups()
        return prefix, int(number), name
    return name, -1, name


def _collect_textures(
    components: list[tuple[int, str | None, dict[str, Any]]],
    objects: dict[int, ObjectReader],
) -> list[tuple[int, ObjectReader]]:
    texture_ids: dict[int, str] = {}
    for _, script, data in components:
        if script != "CubismRenderer":
            continue
        texture_id = _path_id(data.get("_mainTexture"))
        texture_obj = objects.get(texture_id)
        if texture_id is None or texture_obj is None or texture_obj.type != ClassIDType.Texture2D:
            continue
        texture_ids[texture_id] = texture_obj.read().m_Name
    return [(path_id, objects[path_id]) for path_id, _ in sorted(texture_ids.items(), key=_texture_sort_key)]


def _moc_base_name(skin_id: int, variant: Live2DVariant) -> str:
    return f"{skin_id}_{variant.moc_suffix}"


def _moc_split_suffix(moc_name: str, skin_id: int, variant: Live2DVariant) -> str | None:
    base_name = _moc_base_name(skin_id, variant)
    match = re.fullmatch(rf"{re.escape(base_name)}_([a-z])", moc_name)
    if match is None:
        return None
    return match.group(1)


def _candidate_components(
    game_object_ids: list[int],
    components_by_game_object: dict[int, list[tuple[int, str | None, dict[str, Any]]]],
) -> list[tuple[int, str | None, dict[str, Any]]]:
    result: list[tuple[int, str | None, dict[str, Any]]] = []
    for game_object_id in game_object_ids:
        result.extend(components_by_game_object.get(game_object_id) or [])
    return result


def _model_candidates(
    skin_id: int,
    variant: Live2DVariant,
    components: list[tuple[int, str | None, dict[str, Any]]],
    objects: dict[int, ObjectReader],
    source_bundle: Path,
    read_errors: list[Live2DReadError],
    result: Live2DExportResult,
) -> list[Live2DModelCandidate]:
    candidates: list[Live2DModelCandidate] = []
    components_by_game_object = _components_by_game_object(components)
    for component_id, script, data in components:
        if script != "CubismModel":
            continue
        game_object_id = _path_id(data.get("m_GameObject"))
        if game_object_id is None:
            result.warnings.append(f"CubismModel component {component_id} has no GameObject.")
            continue
        moc_id = _path_id(data.get("_moc"))
        moc_obj = objects.get(moc_id)
        if moc_id is None or moc_obj is None:
            result.warnings.append(f"CubismModel component {component_id} has no readable CubismMoc reference.")
            continue
        moc_data = _read_typetree(moc_obj, source_bundle, read_errors, "read CubismMoc")
        if moc_data is None:
            result.warnings.append(f"CubismMoc reference for component {component_id} could not be read.")
            continue
        moc_name = moc_data.get("m_Name") or _moc_base_name(skin_id, variant)
        moc_bytes = bytes(moc_data.get("_bytes") or [])
        if not moc_bytes.startswith(b"MOC3"):
            result.warnings.append(f"CubismMoc {moc_name} bytes do not start with MOC3.")
            continue
        descendant_ids = _descendant_game_objects_from_id(game_object_id, objects, source_bundle, read_errors)
        if not descendant_ids:
            result.warnings.append(f"CubismModel {moc_name} has no readable descendant hierarchy.")
            continue
        scoped_components = _candidate_components(descendant_ids, components_by_game_object)
        texture_objects = _collect_textures(scoped_components, objects)
        if not texture_objects:
            result.warnings.append(f"CubismModel {moc_name} has no readable textures.")
            continue
        renderer_count = sum(1 for _, scoped_script, _ in scoped_components if scoped_script == "CubismRenderer")
        candidates.append(Live2DModelCandidate(
            component_id=component_id,
            game_object_id=game_object_id,
            moc_name=moc_name,
            moc_bytes=moc_bytes,
            texture_objects=texture_objects,
            renderer_count=renderer_count,
        ))
    return candidates


def _select_model_candidate(
    skin_id: int,
    variant: Live2DVariant,
    candidates: list[Live2DModelCandidate],
) -> Live2DModelCandidate | None:
    if not candidates:
        return None
    split_a = [
        candidate
        for candidate in candidates
        if _moc_split_suffix(candidate.moc_name, skin_id, variant) == "a"
    ]
    if split_a:
        return max(split_a, key=lambda candidate: candidate.renderer_count)

    exact_name = _moc_base_name(skin_id, variant)
    exact = [candidate for candidate in candidates if candidate.moc_name == exact_name]
    if exact:
        return max(exact, key=lambda candidate: candidate.renderer_count)

    return max(candidates, key=lambda candidate: (candidate.renderer_count, candidate.moc_name))


def _motion_list_names(variant: Live2DVariant, moc_name: str, skin_id: int) -> list[str]:
    names: list[str] = []
    split_suffix = _moc_split_suffix(moc_name, skin_id, variant)
    if split_suffix is not None:
        names.append(f"{split_suffix}.fadeMotionList")
    names.append(variant.motion_list_name)
    return list(dict.fromkeys(names))


def _find_motion_list(
    objects: dict[int, ObjectReader],
    scripts: dict[int, str],
    motion_list_names: list[str],
    source_bundle: Path,
    read_errors: list[Live2DReadError],
) -> tuple[str, dict[str, Any]] | None:
    requested_names = set(motion_list_names)
    matches: dict[str, dict[str, Any]] = {}
    for obj in objects.values():
        if obj.type != ClassIDType.MonoBehaviour:
            continue
        data = _read_typetree(obj, source_bundle, read_errors, "read motion list candidate")
        if data is None:
            continue
        name = data.get("m_Name")
        if _script_name(data, scripts) == "CubismFadeMotionList" and name in requested_names:
            matches.setdefault(name, data)
    for name in motion_list_names:
        if name in matches:
            return name, matches[name]
    return None


def _convert_keyframes_to_segments(keyframes: list[dict[str, float]]) -> tuple[list[float | int], int]:
    if not keyframes:
        return [], 0
    segments: list[float | int] = [float(keyframes[0]["time"]), float(keyframes[0]["value"])]
    segment_count = 0
    for previous, current in zip(keyframes, keyframes[1:]):
        time0 = float(previous["time"])
        value0 = float(previous["value"])
        time1 = float(current["time"])
        value1 = float(current["value"])
        duration = time1 - time0
        if duration <= 0:
            continue
        out_slope = float(previous.get("outSlope") or 0)
        in_slope = float(current.get("inSlope") or 0)
        segments.extend([
            1,
            time0 + duration / 3,
            value0 + out_slope * duration / 3,
            time1 - duration / 3,
            value1 - in_slope * duration / 3,
            time1,
            value1,
        ])
        segment_count += 1
    return segments, segment_count


def _motion_json(data: dict[str, Any]) -> dict[str, Any]:
    parameter_ids = data.get("ParameterIds") or []
    parameter_curves = data.get("ParameterCurves") or []
    fade_in_times = data.get("ParameterFadeInTimes") or []
    fade_out_times = data.get("ParameterFadeOutTimes") or []
    curves: list[dict[str, Any]] = []
    total_segments = 0
    total_points = 0

    for index, parameter_id in enumerate(parameter_ids):
        if index >= len(parameter_curves):
            break
        keyframes = parameter_curves[index].get("m_Curve") or []
        segments, segment_count = _convert_keyframes_to_segments(keyframes)
        if not segments:
            continue
        curve: dict[str, Any] = {
            "Target": "Parameter",
            "Id": parameter_id,
            "Segments": segments,
        }
        if index < len(fade_in_times) and float(fade_in_times[index]) >= 0:
            curve["FadeInTime"] = float(fade_in_times[index])
        if index < len(fade_out_times) and float(fade_out_times[index]) >= 0:
            curve["FadeOutTime"] = float(fade_out_times[index])
        curves.append(curve)
        total_segments += segment_count
        total_points += 1 + 3 * segment_count

    return {
        "Version": 3,
        "Meta": {
            "Duration": float(data.get("MotionLength") or 0),
            "Fps": 30.0,
            "Loop": True,
            "AreBeziersRestricted": False,
            "CurveCount": len(curves),
            "TotalSegmentCount": total_segments,
            "TotalPointCount": total_points,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
            "FadeInTime": float(data.get("FadeInTime") or 0),
            "FadeOutTime": float(data.get("FadeOutTime") or 0),
        },
        "Curves": curves,
        "UserData": [],
    }


def _motion_file_name(data: dict[str, Any]) -> str:
    motion_name = Path(data.get("MotionName") or data.get("m_Name") or "motion.motion3.json").name
    if motion_name.endswith(".motion3.json"):
        motion_name = motion_name.removesuffix(".motion3.json")
    else:
        motion_name = motion_name.removesuffix(".fade")
    return f"{_safe_json_name(motion_name)}.motion3.json"


def _export_motion_data(
    motion_list: dict[str, Any],
    objects: dict[int, ObjectReader],
    out_dir: Path,
    source_bundle: Path,
    read_errors: list[Live2DReadError],
) -> list[Live2DMotion]:
    motions: list[Live2DMotion] = []
    for motion_ref in motion_list.get("CubismFadeMotionObjects") or []:
        motion_id = _path_id(motion_ref)
        motion_obj = objects.get(motion_id)
        if motion_id is None or motion_obj is None:
            continue
        data = _read_typetree(motion_obj, source_bundle, read_errors, "read fade motion data")
        if data is None:
            continue
        file_name = _motion_file_name(data)
        motion_json = _motion_json(data)
        _write_json(out_dir / "motions" / file_name, motion_json)
        name = file_name.removesuffix(".motion3.json")
        motions.append(Live2DMotion(
            name=name,
            file=f"motions/{file_name}",
            duration=float(data.get("MotionLength") or 0),
            fade_in=float(data.get("FadeInTime") or 0),
            fade_out=float(data.get("FadeOutTime") or 0),
            parameter_count=len(data.get("ParameterIds") or []),
        ))
    return motions


def _model_json(moc_file: str, texture_files: list[str], variant: Live2DVariant, motions: list[Live2DMotion]) -> dict[str, Any]:
    return {
        "Version": 3,
        "FileReferences": {
            "Moc": moc_file,
            "Textures": texture_files,
            "Motions": {
                variant.motion_group: [
                    {
                        "File": motion.file,
                        "FadeInTime": motion.fade_in,
                        "FadeOutTime": motion.fade_out,
                    }
                    for motion in motions
                ],
            },
        },
        "Groups": [],
        "HitAreas": [],
    }


def _model_file_name(skin_id: int, variant: Live2DVariant) -> str:
    return f"{skin_id}_{variant.name}.model3.json"


def _remove_stale_model_json(out_dir: Path, skin_id: int, variant: Live2DVariant) -> None:
    model_path = out_dir / _model_file_name(skin_id, variant)
    if model_path.exists():
        model_path.unlink()
        print(f"Removed stale skipped model {model_path}")


def _manifest(result: Live2DExportResult, source_bundle: Path, prefab_container: str) -> dict[str, Any]:
    return {
        "skin_id": result.skin_id,
        "variant": result.variant,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "source_bundle": str(source_bundle),
        "prefab": prefab_container,
        "moc": {
            "name": result.moc_name,
            "file": result.moc_file,
        },
        "textures": result.texture_files,
        "motions": [
            {
                "name": motion.name,
                "file": motion.file,
                "duration": motion.duration,
                "fade_in": motion.fade_in,
                "fade_out": motion.fade_out,
                "parameter_count": motion.parameter_count,
            }
            for motion in result.motions
        ],
        "warnings": result.warnings,
    }


def _skip_variant(
    result: Live2DExportResult,
    variant: Live2DVariant,
    source_bundle: Path,
    prefab_container: str,
    reason: str,
) -> Live2DExportResult:
    result.skipped = True
    result.skip_reason = reason
    result.warnings.append(reason)
    _remove_stale_model_json(result.output_dir, result.skin_id, variant)
    _write_json(result.output_dir / "stella_live2d_manifest.json", _manifest(result, source_bundle, prefab_container))
    return result


def _export_variant(
    skin_id: int,
    variant: Live2DVariant,
    source_bundle: Path,
    objects: dict[int, ObjectReader],
    scripts: dict[int, str],
    prefab_root: ObjectReader,
    output_root: Path,
    read_errors: list[Live2DReadError],
) -> Live2DExportResult:
    out_dir = output_root / str(skin_id) / "live2d" / variant.name
    result = Live2DExportResult(skin_id, variant.name, out_dir)
    error_count = len(read_errors)
    game_object_ids = _descendant_game_objects(prefab_root, objects, source_bundle, read_errors)
    components = _components_for_game_objects(game_object_ids, objects, scripts, source_bundle, read_errors)
    if len(read_errors) > error_count:
        result.warnings.append(f"Skipped {len(read_errors) - error_count} unreadable prefab objects.")
    candidates = _model_candidates(skin_id, variant, components, objects, source_bundle, read_errors, result)
    if not candidates:
        return _skip_variant(
            result,
            variant,
            source_bundle,
            prefab_root.container or "",
            "No valid CubismModel candidate found in prefab hierarchy.",
        )
    candidate = _select_model_candidate(skin_id, variant, candidates)
    if candidate is None:
        return _skip_variant(
            result,
            variant,
            source_bundle,
            prefab_root.container or "",
            "No CubismModel candidate could be selected.",
        )
    if len(candidates) > 1:
        candidate_names = ", ".join(candidate.moc_name for candidate in candidates)
        result.warnings.append(
            f"Found {len(candidates)} CubismModel candidates ({candidate_names}); selected {candidate.moc_name}."
        )

    result.moc_name = candidate.moc_name
    result.moc_file = f"{_safe_json_name(candidate.moc_name)}.moc3"
    _write_bytes(out_dir / result.moc_file, candidate.moc_bytes)

    for index, (_, texture_obj) in enumerate(candidate.texture_objects):
        texture_name = texture_obj.read().m_Name
        file_name = f"{_safe_json_name(texture_name)}.png"
        texture_file = f"textures/{file_name}"
        result.texture_files.append(texture_file)
        _export_texture(texture_obj, out_dir / texture_file)
        if index > 0 and result.texture_files[index] == result.texture_files[index - 1]:
            result.warnings.append(f"Duplicate texture filename generated for {texture_name}.")

    error_count = len(read_errors)
    requested_motion_lists = _motion_list_names(variant, candidate.moc_name, skin_id)
    motion_list = _find_motion_list(objects, scripts, requested_motion_lists, source_bundle, read_errors)
    if len(read_errors) > error_count:
        result.warnings.append(f"Skipped {len(read_errors) - error_count} unreadable motion list candidates.")
    if motion_list is None:
        result.warnings.append(f"No motion list found; tried {', '.join(requested_motion_lists)}.")
    else:
        motion_list_name, motion_list_data = motion_list
        if motion_list_name != variant.motion_list_name:
            result.warnings.append(f"Using {motion_list_name} for {candidate.moc_name}.")
        error_count = len(read_errors)
        result.motions = _export_motion_data(motion_list_data, objects, out_dir, source_bundle, read_errors)
        if len(read_errors) > error_count:
            result.warnings.append(f"Skipped {len(read_errors) - error_count} unreadable motion objects.")

    _write_json(out_dir / _model_file_name(skin_id, variant), _model_json(
        result.moc_file,
        result.texture_files,
        variant,
        result.motions,
    ))
    _write_json(out_dir / "stella_live2d_manifest.json", _manifest(result, source_bundle, prefab_root.container or ""))
    return result


def export_live2d(
    skin_ids: set[int] | None = None,
    variants: set[str] | None = None,
    output_root: Path | None = None,
) -> list[Live2DExportResult]:
    selected_variants = variants or DEFAULT_VARIANTS
    unknown_variants = selected_variants - set(VARIANTS)
    if unknown_variants:
        raise ValueError(f"Unknown Live2D variants: {sorted(unknown_variants)}")

    output_root = output_root or assets_root / "actor2d/character"
    bundles = _bundle_by_skin_id()
    if skin_ids is not None:
        missing = sorted(skin_ids - set(bundles))
        for skin_id in missing:
            print(f"WARNING: No char_2d bundle found for skin {skin_id}")
        bundles = {skin_id: bundles[skin_id] for skin_id in sorted(skin_ids & set(bundles))}

    results: list[Live2DExportResult] = []
    read_errors: list[Live2DReadError] = []
    for skin_id, source_bundle in sorted(bundles.items()):
        print(f"Processing {source_bundle.name}")
        env = UnityPy.load(str(source_bundle))
        objects = {obj.path_id: obj for obj in env.objects}
        scripts = _script_names(objects, source_bundle, read_errors)
        prefabs = _prefab_roots(objects, skin_id)
        for variant_name in sorted(selected_variants):
            prefab_root = prefabs.get(variant_name)
            if prefab_root is None:
                print(f"WARNING: No {variant_name} prefab found for skin {skin_id}")
                continue
            results.append(_export_variant(
                skin_id,
                VARIANTS[variant_name],
                source_bundle,
                objects,
                scripts,
                prefab_root,
                output_root,
                read_errors,
            ))
    if read_errors:
        formatted_errors = _unique_read_error_formats(read_errors)
        print(f"Skipped {len(formatted_errors)} unreadable Unity objects:")
        for formatted in formatted_errors:
            print(f"WARNING: {formatted}")
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Stella Sora Live2D assets from Unity bundles.")
    parser.add_argument("--skin-id", type=int, action="append", dest="skin_ids")
    parser.add_argument("--variant", choices=sorted(VARIANTS), action="append", dest="variants")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    skin_ids = set(args.skin_ids) if args.skin_ids else None
    variants = set(args.variants) if args.variants else None
    results = export_live2d(skin_ids=skin_ids, variants=variants, output_root=args.out)
    exported = sum(1 for result in results if result.moc_file)
    print(f"Exported {exported} Live2D variants.")


if __name__ == "__main__":
    main()
