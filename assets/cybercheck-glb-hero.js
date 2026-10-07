const canvas=document.getElementById("vehicle3DCanvas");
const stage=document.getElementById("vehicle3DStage");
const GLB_URL="/assets/3d/CyberCheckVehicle_Photo3D.glb?v=1";
const FALLBACK_URL="/assets/cybercheck-hero-3d.js?v=photo-depth-1";
const MAX_GLB_BYTES=4*1024*1024;

const fallback=async reason=>{
  if(stage) stage.dataset.modelSource="photo-depth";
  try{await import(FALLBACK_URL);}catch(_error){
    if(canvas) canvas.hidden=true;
    if(stage) stage.dataset.quality="fallback";
  }
  if(stage&&reason) stage.dataset.glbFallback=reason;
};

const parseGLB=buffer=>{
  if(buffer.byteLength<20||buffer.byteLength>MAX_GLB_BYTES) throw new Error("glb_size");
  const view=new DataView(buffer);
  if(view.getUint32(0,true)!==0x46546c67) throw new Error("glb_magic");
  if(view.getUint32(4,true)!==2) throw new Error("glb_version");
  if(view.getUint32(8,true)!==buffer.byteLength) throw new Error("glb_length");
  let offset=12,json=null,binary=null;
  while(offset+8<=buffer.byteLength){
    const length=view.getUint32(offset,true);
    const type=view.getUint32(offset+4,true);
    offset+=8;
    if(offset+length>buffer.byteLength) throw new Error("glb_chunk");
    const chunk=buffer.slice(offset,offset+length);
    offset+=length;
    if(type===0x4e4f534a){
      json=JSON.parse(new TextDecoder().decode(chunk).replace(/[\0\s]+$/,""));
    }else if(type===0x004e4942){
      binary=chunk;
    }
  }
  if(!json||!binary||json.asset?.version!=="2.0") throw new Error("glb_payload");
  return {json,binary};
};

const accessorView=(json,binary,index)=>{
  const accessor=json.accessors?.[index];
  const bufferView=json.bufferViews?.[accessor?.bufferView];
  if(!accessor||!bufferView) throw new Error("glb_accessor");
  if(bufferView.byteStride) throw new Error("glb_stride");
  const components={SCALAR:1,VEC2:2,VEC3:3,VEC4:4}[accessor.type];
  if(!components) throw new Error("glb_components");
  const byteOffset=(bufferView.byteOffset||0)+(accessor.byteOffset||0);
  const count=accessor.count*components;
  if(accessor.componentType===5126) return new Float32Array(binary,byteOffset,count);
  if(accessor.componentType===5123) return new Uint16Array(binary,byteOffset,count);
  if(accessor.componentType===5125) return new Uint32Array(binary,byteOffset,count);
  throw new Error("glb_component_type");
};

const loadImage=async blob=>{
  const url=URL.createObjectURL(blob);
  try{
    return await new Promise((resolve,reject)=>{
      const image=new Image();
      image.decoding="async";
      image.onload=()=>resolve(image);
      image.onerror=()=>reject(new Error("glb_texture_decode"));
      image.src=url;
    });
  }finally{
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
};

const ident=()=>new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
const multiply=(a,b)=>{
  const out=new Float32Array(16);
  for(let c=0;c<4;c++) for(let r=0;r<4;r++){
    out[c*4+r]=a[r]*b[c*4]+a[4+r]*b[c*4+1]+a[8+r]*b[c*4+2]+a[12+r]*b[c*4+3];
  }
  return out;
};
const perspective=(fov,aspect,near,far)=>{
  const f=1/Math.tan(fov/2),nf=1/(near-far);
  return new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0]);
};
const modelMatrix=(yaw)=>{
  const cy=Math.cos(yaw),sy=Math.sin(yaw);
  return new Float32Array([
    cy,0,-sy,0,
    0,1,0,0,
    sy,0,cy,0,
    0,-1.42,0,1
  ]);
};

const renderGLB=async ({json,binary})=>{
  if(!canvas||!stage) throw new Error("glb_target");
  const vehicleNodeIndex=json.nodes?.findIndex(node=>node.name==="VehiclePhoto3D");
  if(vehicleNodeIndex<0) throw new Error("glb_vehicle_node");
  const node=json.nodes[vehicleNodeIndex];
  const mesh=json.meshes?.[node.mesh];
  const primitive=mesh?.primitives?.[0];
  if(!primitive) throw new Error("glb_vehicle_mesh");
  const material=json.materials?.[primitive.material];
  if(material?.name!=="VehiclePhotoMaterial"||material.alphaMode!=="BLEND") throw new Error("glb_vehicle_material");

  const textureIndex=material.pbrMetallicRoughness?.baseColorTexture?.index;
  const texture=json.textures?.[textureIndex];
  const imageDef=json.images?.[texture?.source];
  const imageView=json.bufferViews?.[imageDef?.bufferView];
  if(!imageDef||!imageView) throw new Error("glb_vehicle_texture");
  const imageStart=imageView.byteOffset||0;
  const imageBytes=binary.slice(imageStart,imageStart+imageView.byteLength);
  const image=await loadImage(new Blob([imageBytes],{type:imageDef.mimeType||"image/png"}));

  const positions=accessorView(json,binary,primitive.attributes.POSITION);
  const uvs=accessorView(json,binary,primitive.attributes.TEXCOORD_0);
  const indices=accessorView(json,binary,primitive.indices);
  if(!(positions instanceof Float32Array)||!(uvs instanceof Float32Array)) throw new Error("glb_vehicle_attributes");

  const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches;
  const cores=navigator.hardwareConcurrency||4;
  const memory=navigator.deviceMemory||4;
  const lowPower=cores<=4||memory<=4;
  const gl=canvas.getContext("webgl",{alpha:true,antialias:!lowPower,premultipliedAlpha:false,powerPreference:lowPower?"low-power":"high-performance"});
  if(!gl) throw new Error("webgl_unavailable");
  if(indices instanceof Uint32Array&&!gl.getExtension("OES_element_index_uint")) throw new Error("webgl_uint_indices");

  const vertex=`
    attribute vec3 aPosition;
    attribute vec2 aUV;
    uniform mat4 uProjection;
    uniform mat4 uView;
    uniform mat4 uModel;
    varying vec2 vUV;
    varying float vDepth;
    void main(){
      vUV=aUV;
      vDepth=aPosition.z;
      gl_Position=uProjection*uView*uModel*vec4(aPosition,1.0);
    }`;
  const fragment=`
    precision mediump float;
    uniform sampler2D uTexture;
    varying vec2 vUV;
    varying float vDepth;
    void main(){
      vec4 tex=texture2D(uTexture,vUV);
      if(tex.a<0.015) discard;
      float depthLight=0.96+clamp(-vDepth,0.0,0.12)*0.3;
      gl_FragColor=vec4(tex.rgb*depthLight,tex.a);
    }`;
  const compile=(type,source)=>{
    const shader=gl.createShader(type);
    gl.shaderSource(shader,source);gl.compileShader(shader);
    if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader)||"shader");
    return shader;
  };
  const program=gl.createProgram();
  gl.attachShader(program,compile(gl.VERTEX_SHADER,vertex));
  gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));
  gl.linkProgram(program);
  if(!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program)||"link");
  gl.useProgram(program);

  const loc={
    position:gl.getAttribLocation(program,"aPosition"),
    uv:gl.getAttribLocation(program,"aUV"),
    projection:gl.getUniformLocation(program,"uProjection"),
    view:gl.getUniformLocation(program,"uView"),
    model:gl.getUniformLocation(program,"uModel"),
    texture:gl.getUniformLocation(program,"uTexture")
  };
  const bind=(location,data,size)=>{
    const buffer=gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location,size,gl.FLOAT,false,0,0);
  };
  bind(loc.position,positions,3);
  bind(loc.uv,uvs,2);
  const indexBuffer=gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,indices,gl.STATIC_DRAW);

  const textureObject=gl.createTexture();
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D,textureObject);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);
  gl.uniform1i(loc.texture,0);

  const view=ident();view[14]=-7.7;
  gl.uniformMatrix4fv(loc.view,false,view);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  gl.disable(gl.CULL_FACE);
  gl.enable(gl.DEPTH_TEST);
  gl.clearColor(0,0,0,0);

  let targetYaw=-0.045,yaw=targetYaw,pointerStart=0,yawStart=0,dragging=false,frameId=0,visible=false,lastFrame=0,contextLost=false;
  const resize=()=>{
    const ratio=Math.min(devicePixelRatio||1,lowPower?1.25:1.7);
    const rect=canvas.getBoundingClientRect();
    const w=Math.max(1,Math.round(rect.width*ratio)),h=Math.max(1,Math.round(rect.height*ratio));
    if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
    gl.viewport(0,0,w,h);
    gl.uniformMatrix4fv(loc.projection,false,perspective(Math.PI/4.4,w/h,.1,100));
    schedule();
  };
  const schedule=()=>{if(!frameId&&visible&&!document.hidden&&!contextLost)frameId=requestAnimationFrame(draw);};
  const draw=time=>{
    frameId=0;
    if(!visible||document.hidden||contextLost)return;
    if(reduced||time-lastFrame>(lowPower?34:16)){
      lastFrame=time;
      if(!dragging&&!reduced)targetYaw+=(-0.045-targetYaw)*0.025;
      yaw+=(targetYaw-yaw)*(dragging?0.28:0.08);
      gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      gl.uniformMatrix4fv(loc.model,false,modelMatrix(yaw));
      gl.drawElements(gl.TRIANGLES,indices.length,indices instanceof Uint32Array?gl.UNSIGNED_INT:gl.UNSIGNED_SHORT,0);
      // Keep the poster visible until a frame has actually been drawn.
      stage.classList.add("webgl-ready");
    }
    if(!reduced||dragging||Math.abs(targetYaw-yaw)>0.001)frameId=requestAnimationFrame(draw);
  };

  new ResizeObserver(resize).observe(stage);resize();
  canvas.addEventListener("pointerdown",event=>{canvas.setPointerCapture(event.pointerId);pointerStart=event.clientX;yawStart=targetYaw;dragging=true;schedule();});
  canvas.addEventListener("pointermove",event=>{if(!dragging)return;targetYaw=Math.max(-0.18,Math.min(0.11,yawStart+(event.clientX-pointerStart)*0.0019));schedule();});
  const release=()=>{dragging=false;schedule();};
  canvas.addEventListener("pointerup",release);canvas.addEventListener("pointercancel",release);
  canvas.addEventListener("webglcontextlost",event=>{event.preventDefault();contextLost=true;if(frameId)cancelAnimationFrame(frameId);stage.classList.remove("webgl-ready");stage.dataset.quality="fallback";});
  canvas.addEventListener("webglcontextrestored",()=>location.reload());
  document.addEventListener("visibilitychange",schedule);
  if("IntersectionObserver" in window){
    new IntersectionObserver(entries=>{visible=entries.some(entry=>entry.isIntersecting);if(!visible&&frameId){cancelAnimationFrame(frameId);frameId=0;}schedule();},{rootMargin:"80px"}).observe(stage);
  }else{visible=true;schedule();}

  stage.dataset.quality=lowPower?"glb-adaptive":"glb-high";
  stage.dataset.modelSource="blender-glb";
  const badge=stage.querySelector(".vehicle-3d-badge span");
  const hint=stage.querySelector(".vehicle-3d-badge b");
  if(badge) badge.textContent="MODÈLE BLENDER · GLB";
  if(hint) hint.textContent="GLISSEZ POUR EXPLORER";
};

if(canvas&&stage){
  try{
    const response=await fetch(GLB_URL,{cache:"force-cache",credentials:"same-origin"});
    if(!response.ok) throw new Error("glb_http_"+response.status);
    const contentLength=Number(response.headers.get("content-length")||0);
    if(contentLength&&contentLength>MAX_GLB_BYTES) throw new Error("glb_http_size");
    const buffer=await response.arrayBuffer();
    await renderGLB(parseGLB(buffer));
  }catch(error){
    await fallback(String(error?.message||"glb_unavailable").slice(0,48));
  }
}
