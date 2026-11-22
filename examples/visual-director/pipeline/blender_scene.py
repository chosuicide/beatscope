"""Blender 5.x headless 3-channel physical pass renderer driven by BeatScope directives.

Invoked via:
    blender --background --python pipeline/blender_scene.py -- \
        --schedule schedule.json --out-dir passes --width 1280 --height 720

Outputs three strictly aligned, non-EXR PNG passes per frame:
  - beauty_XXXXXX.png (8-bit RGB sunlit concrete/tiled courtyard)
  - depth_XXXXXX.png  (16-bit grayscale linear Mist depth mapped to [0, 1])
  - mask_XXXXXX.png   (8-bit hard binary intrusion mask with 3D foreground occlusion)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bmesh
import bpy
from mathutils import Euler, Vector


def _parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Render aligned beauty/depth16/mask passes in Blender.")
    parser.add_argument("--schedule", type=Path, required=True, help="JSON list of BeatScope FrameDirective dicts")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for PNG passes")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=16)
    return parser.parse_args(argv)


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _make_tiled_wall_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("SunlitTiles")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.42
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.55

    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.offset = 0.0
    brick.inputs["Color1"].default_value = (0.86, 0.81, 0.72, 1.0)
    brick.inputs["Color2"].default_value = (0.76, 0.71, 0.61, 1.0)
    brick.inputs["Mortar"].default_value = (0.14, 0.13, 0.12, 1.0)
    brick.inputs["Scale"].default_value = 6.0
    brick.inputs["Mortar Size"].default_value = 0.022
    brick.inputs["Mortar Smooth"].default_value = 0.04
    brick.inputs["Brick Width"].default_value = 0.5
    brick.inputs["Row Height"].default_value = 0.5

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 18.0
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.65

    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 0.14

    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.015

    nt.links.new(tex_coord.outputs["Object"], brick.inputs["Vector"])
    nt.links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(brick.outputs["Color"], mix.inputs["A"])
    nt.links.new(noise.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    nt.links.new(brick.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _make_concrete_material(name: str, base_rgb: tuple[float, float, float], rough: float = 0.78) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = rough

    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 9.0
    noise.inputs["Detail"].default_value = 10.0
    noise.inputs["Roughness"].default_value = 0.7

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.25
    ramp.color_ramp.elements[0].color = (base_rgb[0] * 0.72, base_rgb[1] * 0.72, base_rgb[2] * 0.70, 1.0)
    ramp.color_ramp.elements[1].position = 0.78
    ramp.color_ramp.elements[1].color = (min(1.0, base_rgb[0] * 1.12), min(1.0, base_rgb[1] * 1.10), min(1.0, base_rgb[2] * 1.06), 1.0)

    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.30
    bump.inputs["Distance"].default_value = 0.02

    nt.links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _make_metal_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("GalvanizedSteel")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.56, 0.58, 0.60, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.36
    return mat


def _make_emission_material(name: str, rgba: tuple[float, float, float, float]) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = rgba
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def _add_box(name: str, col: bpy.types.Collection, loc: tuple[float, float, float], scale: tuple[float, float, float], mat: bpy.types.Material, rot: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = loc
    obj.scale = scale
    obj.rotation_euler = Euler(rot, "XYZ")
    obj.data.materials.append(mat)
    col.objects.link(obj)
    return obj


def _add_jagged_crack_shard(name: str, col: bpy.types.Collection, mat: bpy.types.Material, variant: int) -> bpy.types.Object:
    """Build an irregular sharp-angled vertical/diagonal fracture shard along wall/floor joints."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()
    # Asymmetric razor-like fracture silhouettes in (x, z) wall plane
    profiles = [
        [(-0.08, 0.0), (0.38, 0.06), (0.14, 0.82), (0.56, 1.65), (0.08, 2.75), (-0.18, 1.38), (-0.34, 0.48)],
        [(-0.52, 0.0), (0.64, 0.12), (1.05, 0.58), (0.36, 1.18), (-0.12, 0.86), (-0.64, 0.28)],
        [(-0.16, 0.0), (0.24, 0.34), (0.06, 1.28), (0.42, 2.25), (-0.08, 2.60), (-0.28, 1.05)],
    ]
    pts = profiles[variant % len(profiles)]
    front = [bm.verts.new((x, 0.0, z)) for (x, z) in pts]
    back = [bm.verts.new((x * 0.85, 0.22, z * 0.96)) for (x, z) in pts]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([front[i], front[j], back[j], back[i]])
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    col.objects.link(obj)
    return obj


def _build_scene(width: int, height: int, samples: int) -> tuple[bpy.types.Scene, bpy.types.Object, list[bpy.types.Object], bpy.types.Collection, bpy.types.Collection]:
    _clear_scene()
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.use_motion_blur = False
    scene.eevee.taa_render_samples = samples

    # Crisp AgX / Standard daylight tone mapping
    try:
        scene.view_settings.view_transform = "AgX"
    except Exception:
        scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = -0.15

    # Low ambient fill so harsh noon SUN light carves deep, razor-sharp architectural shadows
    world = bpy.data.worlds.new("NoonSky")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.48, 0.58, 0.72, 1.0)
        bg.inputs["Strength"].default_value = 0.22
    world.mist_settings.use_mist = True
    world.mist_settings.start = 1.5
    world.mist_settings.depth = 13.0
    world.mist_settings.falloff = "LINEAR"

    scene_col = bpy.data.collections.new("Architecture")
    intrusion_col = bpy.data.collections.new("Intrusion")
    scene.collection.children.link(scene_col)
    scene.collection.children.link(intrusion_col)

    mat_tile = _make_tiled_wall_material()
    mat_concrete = _make_concrete_material("SunlitConcrete", (0.72, 0.70, 0.66), rough=0.84)
    mat_dark_concrete = _make_concrete_material("DrainConcrete", (0.34, 0.34, 0.33), rough=0.90)
    mat_steel = _make_metal_material()
    mat_void = _make_emission_material("VoidBlack", (0.005, 0.005, 0.005, 1.0))

    # Sun-baked tiled courtyard floor + back/side concrete walls + overhead shadow-casting beams
    _add_box("FloorSlab", scene_col, (0.0, 2.5, -0.1), (12.0, 14.0, 0.2), mat_concrete)
    _add_box("DrainChannel", scene_col, (0.0, 3.6, -0.005), (12.0, 0.32, 0.04), mat_dark_concrete)
    _add_box("BackTiledWall", scene_col, (0.0, 7.2, 2.4), (11.0, 0.35, 5.2), mat_tile)
    _add_box("LeftConcreteWall", scene_col, (-4.2, 2.5, 2.4), (0.4, 12.0, 5.2), mat_concrete)
    _add_box("RightPillar", scene_col, (3.1, 4.4, 2.3), (0.65, 0.65, 4.8), mat_concrete)
    _add_box("ConcreteBench", scene_col, (-1.85, 4.9, 0.28), (2.2, 0.58, 0.56), mat_concrete)

    # Overhead louvered beams casting razor-sharp high-angle noon stripes across tiles & floor
    for i in range(5):
        _add_box(f"SunBeam_{i}", scene_col, (-2.6 + i * 1.45, 4.4, 4.35), (0.28, 7.6, 0.38), mat_concrete)

    # Foreground metal handrail & vertical post (~2.4m from camera) so 3D depth sorting occludes cleanly
    _add_box("FgPostLeft", scene_col, (-1.15, 0.65, 0.75), (0.085, 0.085, 1.65), mat_steel)
    _add_box("FgPostRight", scene_col, (1.55, 1.15, 0.75), (0.085, 0.085, 1.65), mat_steel)
    _add_box("FgRailTop", scene_col, (0.20, 0.90, 1.46), (3.1, 0.065, 0.065), mat_steel, rot=(0.0, 0.0, 0.18))
    _add_box("FgRailMid", scene_col, (0.20, 0.90, 0.96), (3.1, 0.045, 0.045), mat_steel, rot=(0.0, 0.0, 0.18))

    # Harsh noon SUN light (slight warm-white daylight bias, crisp 0.015 rad shadow penumbra)
    sun_data = bpy.data.lights.new("NoonSun", type="SUN")
    sun_data.energy = 8.2
    sun_data.color = (1.0, 0.985, 0.95)
    sun_data.angle = 0.015
    sun_obj = bpy.data.objects.new("NoonSun", sun_data)
    sun_obj.rotation_euler = Euler((math.radians(34), math.radians(16), math.radians(-28)), "XYZ")
    scene_col.objects.link(sun_obj)

    # Camera: eye-level mundane perspective
    cam_data = bpy.data.cameras.new("MainCam")
    cam_data.lens = 35.0
    cam_data.clip_start = 0.1
    cam_data.clip_end = 50.0
    cam_obj = bpy.data.objects.new("MainCam", cam_data)
    cam_obj.location = Vector((-0.25, -2.25, 1.48))
    cam_obj.rotation_euler = Euler((math.radians(87.5), 0.0, math.radians(-4.0)), "XYZ")
    scene_col.objects.link(cam_obj)
    scene.camera = cam_obj

    # 3 irregular fracture intrusion shards anchored at wall/floor joints (behind foreground rail!)
    shards = [
        _add_jagged_crack_shard("CrackShard_0", intrusion_col, mat_void, 0),
        _add_jagged_crack_shard("CrackShard_1", intrusion_col, mat_void, 1),
        _add_jagged_crack_shard("CrackShard_2", intrusion_col, mat_void, 2),
    ]
    base_positions = [
        (0.35, 6.85, 0.02),
        (-1.40, 4.10, 0.02),
        (2.35, 5.40, 0.45),
    ]
    for shard, pos in zip(shards, base_positions):
        shard.location = Vector(pos)

    return scene, cam_obj, shards, scene_col, intrusion_col


def _configure_layers_and_compositor(
    scene: bpy.types.Scene,
    out_dir: Path,
    scene_col: bpy.types.Collection,
    intrusion_col: bpy.types.Collection,
) -> tuple[bpy.types.Material, bpy.types.Material]:
    beauty_vl = scene.view_layers[0]
    beauty_vl.name = "BeautyLayer"
    beauty_vl.use_pass_combined = True
    beauty_vl.use_pass_mist = True

    # Second ViewLayer for 3D-occluded binary intrusion mask
    mask_vl = scene.view_layers.new("MaskLayer")
    mask_vl.use_pass_combined = True
    mask_vl.layer_collection.children[scene_col.name].holdout = True
    mask_vl.layer_collection.children[intrusion_col.name].holdout = False

    mat_white = _make_emission_material("MaskWhite", (1.0, 1.0, 1.0, 1.0))
    mat_void = bpy.data.materials["VoidBlack"]
    mask_vl.material_override = mat_white

    # Transparent film on MaskLayer? World stays dark when transparent=True (RGBA black=0)
    scene.render.film_transparent = False

    # Blender 5.x compositing_node_group outputs all 3 aligned PNG passes in one render pass
    ng = bpy.data.node_groups.new("BeatScopeThreePass", "CompositorNodeTree")
    scene.compositing_node_group = ng

    rl_beauty = ng.nodes.new("CompositorNodeRLayers")
    rl_beauty.scene = scene
    rl_beauty.layer = beauty_vl.name

    rl_mask = ng.nodes.new("CompositorNodeRLayers")
    rl_mask.scene = scene
    rl_mask.layer = mask_vl.name

    # Output 1: 8-bit RGB beauty PNG
    fo_beauty = ng.nodes.new("CompositorNodeOutputFile")
    fo_beauty.directory = str(out_dir.resolve())
    fo_beauty.format.media_type = "IMAGE"
    fo_beauty.format.file_format = "PNG"
    fo_beauty.format.color_mode = "RGB"
    fo_beauty.format.color_depth = "8"
    fo_beauty.file_output_items.clear()
    item_b = fo_beauty.file_output_items.new("RGBA", "beauty_")
    item_b.save_as_render = True
    ng.links.new(rl_beauty.outputs["Image"], fo_beauty.inputs[0])

    # Output 2: 16-bit grayscale PNG depth (linear Mist [0,1] -> uint16)
    fo_depth = ng.nodes.new("CompositorNodeOutputFile")
    fo_depth.directory = str(out_dir.resolve())
    fo_depth.format.media_type = "IMAGE"
    fo_depth.format.file_format = "PNG"
    fo_depth.format.color_mode = "BW"
    fo_depth.format.color_depth = "16"
    fo_depth.file_output_items.clear()
    item_d = fo_depth.file_output_items.new("FLOAT", "depth_")
    item_d.save_as_render = False
    ng.links.new(rl_beauty.outputs["Mist"], fo_depth.inputs[0])

    # Output 3: 8-bit grayscale PNG hard binary mask (3D holdout occluded)
    fo_mask = ng.nodes.new("CompositorNodeOutputFile")
    fo_mask.directory = str(out_dir.resolve())
    fo_mask.format.media_type = "IMAGE"
    fo_mask.format.file_format = "PNG"
    fo_mask.format.color_mode = "BW"
    fo_mask.format.color_depth = "8"
    fo_mask.file_output_items.clear()
    item_m = fo_mask.file_output_items.new("RGBA", "mask_")
    item_m.save_as_render = False
    ng.links.new(rl_mask.outputs["Image"], fo_mask.inputs[0])

    return mat_void, mat_white


def _apply_directive_to_scene(
    cam_obj: bpy.types.Object,
    shards: list[bpy.types.Object],
    directive: dict[str, Any],
) -> None:
    base_cam_loc = Vector((-0.25, -2.25, 1.48))
    base_cam_rot = Vector((math.radians(87.5), 0.0, math.radians(-4.0)))
    jx = float(directive.get("cam_jitter_x", 0.0))
    jy = float(directive.get("cam_jitter_y", 0.0))
    cam_obj.location = Vector((base_cam_loc.x + jx, base_cam_loc.y, base_cam_loc.z + jy))
    cam_obj.rotation_euler = Euler((base_cam_rot.x + jy * 0.25, 0.0, base_cam_rot.z + jx * 0.25), "XYZ")

    visible = bool(directive.get("intrusion_visible", False))
    seed = int(directive.get("intrusion_seed", 0))
    scale = float(directive.get("intrusion_scale", 1.0))

    anchor_table = [
        (0.35, 6.85, 0.02),
        (-1.40, 4.10, 0.02),
        (2.35, 5.40, 0.45),
    ]
    for idx, shard in enumerate(shards):
        shard.hide_render = not visible
        shard.hide_viewport = not visible
        if visible:
            ax, ay, az = anchor_table[idx]
            offset_x = math.sin((seed + 1) * (idx + 1) * 1.73) * 0.55
            offset_z = abs(math.cos((seed + 1) * (idx + 2) * 1.19)) * 0.25
            shard.location = Vector((ax + offset_x, ay, az + offset_z))
            s = scale * (0.85 + 0.35 * ((seed + idx) % 3) / 2.0)
            shard.scale = Vector((s, 1.0, s))
            shard.rotation_euler = Euler((0.0, math.radians(((seed * 17 + idx * 31) % 24) - 12), 0.0), "XYZ")


def _normalize_output_filename(out_dir: Path, prefix: str, frame_idx: int) -> Path:
    """Rename Blender's output filename to exact 6-digit prefixXXXXXX.png."""
    target = out_dir / f"{prefix}{frame_idx:06d}.png"
    candidates = [
        out_dir / f"Unsaved{prefix}.png",
        out_dir / f"{prefix}.png",
        out_dir / f"Unsaved{prefix}{frame_idx:04d}.png",
        out_dir / f"{prefix}{frame_idx:04d}.png",
        out_dir / f"{prefix}{frame_idx:06d}.png",
        out_dir / f"{prefix}{frame_idx}.png",
    ]
    for cand in candidates:
        if cand.exists():
            if cand != target:
                if target.exists():
                    target.unlink()
                cand.rename(target)
            return target
    raise FileNotFoundError(f"Expected Blender output for {prefix} frame {frame_idx} in {out_dir}")


def main() -> None:
    args = _parse_args()
    schedule: list[dict[str, Any]] = json.loads(args.schedule.read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    scene, cam_obj, shards, scene_col, intrusion_col = _build_scene(args.width, args.height, args.samples)
    _configure_layers_and_compositor(scene, args.out_dir, scene_col, intrusion_col)

    # film_transparent=True keeps MaskLayer background pure black (0) while BeautyLayer
    # composites cleanly over a crisp noon sky via Blender 5.x named AlphaOver sockets.
    scene.render.film_transparent = True
    ng = scene.compositing_node_group
    rl_beauty = next(n for n in ng.nodes if n.type == "R_LAYERS" and n.layer == "BeautyLayer")
    fo_beauty = next(n for n in ng.nodes if n.type == "OUTPUT_FILE" and n.format.color_mode == "RGB")
    alpha_over = ng.nodes.new("CompositorNodeAlphaOver")
    alpha_over.inputs["Background"].default_value = (0.86, 0.90, 0.94, 1.0)
    alpha_over.inputs["Factor"].default_value = 1.0
    for link in list(fo_beauty.inputs[0].links):
        ng.links.remove(link)
    ng.links.new(rl_beauty.outputs["Image"], alpha_over.inputs["Foreground"])
    ng.links.new(alpha_over.outputs["Image"], fo_beauty.inputs[0])

    # Avoid writing stray default render output to /tmp
    scene.render.filepath = str((args.out_dir / "_discard_").resolve())

    for entry in schedule:
        frame_idx = int(entry["frame"])
        scene.frame_set(frame_idx)
        _apply_directive_to_scene(cam_obj, shards, entry)
        bpy.ops.render.render(write_still=False)
        for prefix in ("beauty_", "depth_", "mask_"):
            _normalize_output_filename(args.out_dir, prefix, frame_idx)


if __name__ == "__main__":
    main()
