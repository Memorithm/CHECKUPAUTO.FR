from pathlib import Path
import math
import bpy
from mathutils import Vector

ROOT = Path('/root/CyberCheck3D')
REF = ROOT / 'references' / 'vehicle_cutout.png'
BLEND = ROOT / 'blend' / 'CyberCheckVehicle_Photo3D.blend'
EXPORT = ROOT / 'exports' / 'CyberCheckVehicle_Photo3D.glb'
RENDER_DIR = ROOT / 'renders'
RENDER_DIR.mkdir(parents=True, exist_ok=True)

# Start from a deterministic empty scene.
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights, bpy.data.materials):
    pass

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 1280
scene.render.resolution_y = 778
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.fps = 30
scene.frame_start = 1
scene.frame_end = 180
scene.render.film_transparent = False
try:
    scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception:
    pass

world = bpy.data.worlds.get('World') or bpy.data.worlds.new('World')
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get('Background')
bg.inputs['Color'].default_value = (0.955, 0.965, 0.962, 1.0)
bg.inputs['Strength'].default_value = 0.8


def collection(name):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in scene.collection.children:
        scene.collection.children.link(c)
    return c

REF_COL = collection('CYBERCHECK_REFERENCE')
CAR_COL = collection('CYBERCHECK_PHOTO_3D')
STAGE_COL = collection('CYBERCHECK_STAGE')
CAM_COL = collection('CYBERCHECK_CAMERA')


def move_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def emission_mat(name, color, strength=1.0, alpha=1.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    trans = nodes.new('ShaderNodeBsdfTransparent')
    em = nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*color, 1.0)
    em.inputs['Strength'].default_value = strength
    mix = nodes.new('ShaderNodeMixShader')
    mix.inputs[0].default_value = alpha
    links.new(trans.outputs[0], mix.inputs[1])
    links.new(em.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs['Surface'])
    return mat

# Exact photo texture with its generated transparent background.
img = bpy.data.images.load(str(REF), check_existing=True)
mat = bpy.data.materials.new('VehiclePhotoMaterial')
mat.use_nodes = True
mat.blend_method = 'BLEND'
mat.show_transparent_back = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links
nodes.clear()
out = nodes.new('ShaderNodeOutputMaterial')
trans = nodes.new('ShaderNodeBsdfTransparent')
em = nodes.new('ShaderNodeEmission')
tex = nodes.new('ShaderNodeTexImage')
tex.image = img
tex.interpolation = 'Linear'
mix = nodes.new('ShaderNodeMixShader')
links.new(tex.outputs['Color'], em.inputs['Color'])
em.inputs['Strength'].default_value = 1.0
links.new(tex.outputs['Alpha'], mix.inputs[0])
links.new(trans.outputs[0], mix.inputs[1])
links.new(em.outputs[0], mix.inputs[2])
links.new(mix.outputs[0], out.inputs['Surface'])

# Curved UV card: enough real geometry for subtle perspective parallax while
# preserving the supplied photograph exactly at the reference angle.
cols, rows = 48, 28
width = 6.25
height = width * img.size[1] / img.size[0]
center_z = 1.42
verts, faces, uvs = [], [], []
for j in range(rows + 1):
    v = j / rows
    for i in range(cols + 1):
        u = i / cols
        x = (u - 0.5) * width
        z = (v - 0.5) * height + center_z
        nx = (u - 0.5) * 2.0
        nz = (v - 0.5) * 2.0
        depth = 0.10 * max(0.0, 1.0 - nx * nx) * max(0.15, 1.0 - 0.55 * nz * nz)
        verts.append((x, depth, z))
for j in range(rows):
    for i in range(cols):
        a = j * (cols + 1) + i
        b = a + 1
        d = (j + 1) * (cols + 1) + i
        c = d + 1
        faces.append((a, b, c, d))
mesh = bpy.data.meshes.new('VehiclePhotoDepthMesh')
mesh.from_pydata(verts, [], faces)
mesh.update()
uv_layer = mesh.uv_layers.new(name='UVMap')
for poly in mesh.polygons:
    for loop_idx in poly.loop_indices:
        vi = mesh.loops[loop_idx].vertex_index
        i = vi % (cols + 1)
        j = vi // (cols + 1)
        uv_layer.data[loop_idx].uv = (i / cols, j / rows)
car = bpy.data.objects.new('VehiclePhoto3D', mesh)
CAR_COL.objects.link(car)
car.data.materials.append(mat)

# Diagnostic stage rings.
cyan = emission_mat('CyberCyan', (0.05, 0.72, 0.78), 2.2, 0.72)
gold = emission_mat('CyberGold', (0.70, 0.48, 0.20), 1.4, 0.40)
for idx, (radius, material) in enumerate(((3.15, cyan), (3.42, gold), (3.65, cyan))):
    bpy.ops.mesh.primitive_torus_add(major_radius=radius, minor_radius=0.012 if idx != 1 else 0.008,
                                    major_segments=128, minor_segments=8,
                                    location=(0.0, 0.10 + idx * 0.015, -0.18))
    ring = bpy.context.object
    ring.name = f'DiagnosticRing_{idx+1}'
    ring.data.materials.append(material)
    move_to(ring, STAGE_COL)

# Floor and turntable.
floor_mat = bpy.data.materials.new('StudioFloor')
floor_mat.use_nodes = True
pbsdf = floor_mat.node_tree.nodes.get('Principled BSDF')
pbsdf.inputs['Base Color'].default_value = (0.91, 0.93, 0.92, 1.0)
pbsdf.inputs['Roughness'].default_value = 0.68
bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=3.32, depth=0.06, location=(0, 0.10, -0.22))
turntable = bpy.context.object
turntable.name = 'DiagnosticTurntable'
turntable.data.materials.append(floor_mat)
move_to(turntable, STAGE_COL)

# Animated scan blade in front of the photographed vehicle.
scan_mat = emission_mat('ScanBlade', (0.00, 0.92, 1.00), 3.0, 0.20)
bpy.ops.mesh.primitive_plane_add(size=2.0, location=(-3.3, -0.035, center_z))
scan = bpy.context.object
scan.name = 'DiagnosticScanBlade'
scan.scale = (0.035, 1.0, 2.1)
scan.rotation_euler = (math.radians(90), 0.0, 0.0)
scan.data.materials.append(scan_mat)
move_to(scan, STAGE_COL)
for frame, x in ((1, -3.3), (90, 3.3), (180, -3.3)):
    scan.location.x = x
    scan.keyframe_insert(data_path='location', index=0, frame=frame)
for fc in scan.animation_data.action.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = 'SINE'

# Camera rig: intentionally small excursion so the single-view photograph
# remains faithful while gaining depth/parallax.
bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.02, 1.25))
target = bpy.context.object
target.name = 'VehicleFocus'
move_to(target, CAM_COL)
bpy.ops.object.camera_add(location=(-0.18, -8.45, 1.46))
cam = bpy.context.object
cam.name = 'CyberCheckCamera'
cam.data.lens = 54
cam.data.sensor_width = 36
move_to(cam, CAM_COL)
track = cam.constraints.new(type='DAMPED_TRACK')
track.target = target
track.track_axis = 'TRACK_NEGATIVE_Z'
scene.camera = cam
for frame, loc in ((1, (-0.18, -8.45, 1.46)), (90, (0.20, -8.15, 1.52)), (180, (-0.18, -8.45, 1.46))):
    cam.location = loc
    cam.keyframe_insert(data_path='location', frame=frame)
for frame, loc in ((1, (-0.06, 0.02, 1.24)), (90, (0.10, 0.04, 1.30)), (180, (-0.06, 0.02, 1.24))):
    target.location = loc
    target.keyframe_insert(data_path='location', frame=frame)
for obj in (cam, target):
    if obj.animation_data and obj.animation_data.action:
        for fc in obj.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'BEZIER'

# Add a reference image object outside camera view for Blender editing only.
bpy.ops.object.empty_add(type='IMAGE', location=(0, 1.8, 4.7))
ref_obj = bpy.context.object
ref_obj.name = 'SOURCE_REFERENCE_EDITING_ONLY'
ref_obj.data = img
ref_obj.empty_display_size = 2.4
ref_obj.hide_render = True
move_to(ref_obj, REF_COL)

# Metadata makes the limitation explicit inside the .blend itself.
scene['cybercheck_source'] = str(REF)
scene['cybercheck_method'] = 'single-image 2.5D depth-card animation'
scene['cybercheck_limitation'] = 'Not a metric/CAD 360-degree reconstruction; hidden surfaces are unknown from one photograph.'

# Save and render checkpoints.
bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
for frame in (1, 90):
    scene.frame_set(frame)
    scene.render.filepath = str(RENDER_DIR / f'photo3d_preview_{frame:03d}.png')
    bpy.ops.render.render(write_still=True)

# Export a web-ready GLB containing the curved photo mesh, stage and animation.
for obj in bpy.context.scene.objects:
    obj.select_set(obj.name != 'SOURCE_REFERENCE_EDITING_ONLY')
bpy.context.view_layer.objects.active = car
try:
    bpy.ops.export_scene.gltf(filepath=str(EXPORT), export_format='GLB', use_selection=True,
                              export_animations=True, export_cameras=False, export_lights=False)
    print('GLB_EXPORTED', EXPORT)
except Exception as exc:
    print('GLB_EXPORT_FAILED', repr(exc))

print('BLEND_SAVED', BLEND)
print('REFERENCE', REF, tuple(img.size))
print('CARD', width, height, len(verts), len(faces))