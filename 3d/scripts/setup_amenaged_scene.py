import math, bpy
from pathlib import Path
ROOT=Path('/root/CyberCheck3D')
REF=ROOT/'references/vehicules_amenages_clean.jpg'
BLEND=ROOT/'blend/CyberCheckAmenaged_Photo3D.blend'
WEB=Path('/root/CyberCheckLive/assets/vehicle-amenaged.mp4')
scene=bpy.context.scene
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
scene.render.engine='BLENDER_EEVEE'; scene.render.resolution_x=1280; scene.render.resolution_y=778; scene.render.resolution_percentage=100
scene.render.fps=30; scene.frame_start=1; scene.frame_end=180
world=bpy.data.worlds.get('World') or bpy.data.worlds.new('World'); scene.world=world; world.use_nodes=True; bg=world.node_tree.nodes.get('Background'); bg.inputs['Color'].default_value=(0.955,0.965,0.962,1.0); bg.inputs['Strength'].default_value=0.8
img=bpy.data.images.load(str(REF),check_existing=False)
mat=bpy.data.materials.new('AmenagedPhoto'); mat.use_nodes=True
nodes=mat.node_tree.nodes; links=mat.node_tree.links; nodes.clear()
out=nodes.new('ShaderNodeOutputMaterial'); em=nodes.new('ShaderNodeEmission'); tex=nodes.new('ShaderNodeTexImage'); tex.image=img
links.new(tex.outputs['Color'],em.inputs['Color']); em.inputs['Strength'].default_value=1.0; links.new(em.outputs[0],out.inputs['Surface'])
cols,rows=48,28; width=6.25; height=width*img.size[1]/img.size[0]; center_z=1.55
verts=[]; faces=[]
for j in range(rows+1):
 v=j/rows
 for i in range(cols+1):
  u=i/cols; x=(u-.5)*width; z=(v-.5)*height+center_z; nx=(u-.5)*2; nz=(v-.5)*2
  depth=.10*max(0,1-nx*nx)*max(.15,1-.55*nz*nz); verts.append((x,depth,z))
for j in range(rows):
 for i in range(cols):
  a=j*(cols+1)+i; b=a+1; d=(j+1)*(cols+1)+i; c=d+1; faces.append((a,b,c,d))
mesh=bpy.data.meshes.new('AmenagedDepthMesh'); mesh.from_pydata(verts,[],faces); mesh.update()
uv=mesh.uv_layers.new(name='UVMap')
for p in mesh.polygons:
 for li in p.loop_indices:
  vi=mesh.loops[li].vertex_index; i=vi%(cols+1); j=vi//(cols+1); uv.data[li].uv=(i/cols,j/rows)
obj=bpy.data.objects.new('AmenagedPhoto3D',mesh); bpy.context.collection.objects.link(obj); obj.data.materials.append(mat)
# floor
fm=bpy.data.materials.new('Floor'); fm.use_nodes=True; bs=fm.node_tree.nodes.get('Principled BSDF'); bs.inputs['Base Color'].default_value=(.92,.94,.93,1); bs.inputs['Roughness'].default_value=.72
bpy.ops.mesh.primitive_plane_add(size=9.0,location=(0,.55,-.34)); floor=bpy.context.object; floor.data.materials.append(fm); floor.hide_render=True
# camera motion identical in spirit to the 208 scene
bpy.ops.object.empty_add(type='PLAIN_AXES',location=(0,.02,1.25)); target=bpy.context.object
bpy.ops.object.camera_add(location=(-.18,-8.45,1.46)); cam=bpy.context.object; cam.data.lens=54
track=cam.constraints.new(type='DAMPED_TRACK'); track.target=target; track.track_axis='TRACK_NEGATIVE_Z'; scene.camera=cam
for f,loc in ((1,(-.18,-8.45,1.46)),(90,(.20,-8.15,1.52)),(180,(-.18,-8.45,1.46))): cam.location=loc; cam.keyframe_insert('location',frame=f)
for f,loc in ((1,(-.06,.02,1.24)),(90,(.10,.04,1.30)),(180,(-.06,.02,1.24))): target.location=loc; target.keyframe_insert('location',frame=f)
scene['cybercheck_method']='single-image 2.5D depth-card animation'; scene['cybercheck_reference']=str(REF)
bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
scene.frame_set(1)
scene.render.filepath='/root/CyberCheckLive/assets/vehicle-amenaged.png'
scene.render.image_settings.file_format='PNG'
bpy.ops.render.render(write_still=True)
scene.render.filepath=str(WEB); scene.render.image_settings.file_format='FFMPEG'; scene.render.ffmpeg.format='MPEG4'; scene.render.ffmpeg.codec='H264'; scene.render.ffmpeg.constant_rate_factor='MEDIUM'; scene.render.ffmpeg.ffmpeg_preset='GOOD'
bpy.ops.render.render(animation=True)
print('DONE',BLEND,WEB,img.size[:])
