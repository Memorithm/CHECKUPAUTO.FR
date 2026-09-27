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

const nodeMatrix=(node,translationOverride=null)=>{
  const t=translationOverride||node.translation||[0,0,0];
  const q=node.rotation||[0,0,0,1];
  const s=node.scale||[1,1,1];
  const [x,y,z,w]=q;
  const x2=x+x,y2=y+y,z2=z+z;
  const xx=x*x2,xy=x*y2,xz=x*z2;
  const yy=y*y2,yz=y*z2,zz=z*z2;
  const wx=w*x2,wy=w*y2,wz=w*z2;
  return new Float32Array([
    (1-(yy+zz))*s[0],(xy+wz)*s[0],(xz-wy)*s[0],0,
    (xy-wz)*s[1],(1-(xx+zz))*s[1],(yz+wx)*s[1],0,
    (xz+wy)*s[2],(yz-wx)*s[2],(1-(xx+yy))*s[2],0,
    t[0]||0,t[1]||0,t[2]||0,1
  ]);
};

const sampleAnimation=(times,values,timeSeconds)=>{
  if(!times||!values||times.length<2) return null;
  const duration=times[times.length-1];
  if(!(duration>0)) return null;
  const t=((timeSeconds%duration)+duration)%duration;
  let lo=0,hi=times.length-1;
  while(lo+1<hi){
    const mid=(lo+hi)>>1;
    if(times[mid]<=t) lo=mid; else hi=mid;
  }
  const t0=times[lo],t1=times[hi];
  const span=Math.max(0.000001,t1-t0);
  const mix=Math.max(0,Math.min(1,(t-t0)/span));
  const base0=lo*3,base1=hi*3;
  return [
    values[base0]+(values[base1]-values[base0])*mix,
    values[base0+1]+(values[base1+1]-values[base0+1])*mix,
    values[base0+2]+(values[base1+2]-values[base0+2])*mix
  ];
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
    return buffer;
  };
  const vehiclePositionBuffer=bind(loc.position,positions,3);
  const vehicleUVBuffer=bind(loc.uv,uvs,2);
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

  const diagnosticVertex=`
    attribute vec3 aPosition;
    uniform mat4 uProjection;
    uniform mat4 uView;
    uniform mat4 uModel;
    void main(){gl_Position=uProjection*uView*uModel*vec4(aPosition,1.0);}
  `;
  const diagnosticFragment=`
    precision mediump float;
    uniform vec4 uColor;
    void main(){gl_FragColor=uColor;}
  `;
  const diagnosticProgram=gl.createProgram();
  gl.attachShader(diagnosticProgram,compile(gl.VERTEX_SHADER,diagnosticVertex));
  gl.attachShader(diagnosticProgram,compile(gl.FRAGMENT_SHADER,diagnosticFragment));
  gl.linkProgram(diagnosticProgram);
  if(!gl.getProgramParameter(diagnosticProgram,gl.LINK_STATUS)) throw new Error("diagnostic_link");
  const diagnosticLoc={
    position:gl.getAttribLocation(diagnosticProgram,"aPosition"),
    projection:gl.getUniformLocation(diagnosticProgram,"uProjection"),
    view:gl.getUniformLocation(diagnosticProgram,"uView"),
    model:gl.getUniformLocation(diagnosticProgram,"uModel"),
    color:gl.getUniformLocation(diagnosticProgram,"uColor")
  };

  const diagnosticColor=name=>{
    if(name==="CyberCyan") return new Float32Array([0.08,0.73,0.76,0.24]);
    if(name==="CyberGold") return new Float32Array([0.88,0.62,0.24,0.22]);
    if(name==="ScanBlade") return new Float32Array([0.14,0.82,0.90,0.20]);
    return new Float32Array([0.32,0.42,0.38,0.10]);
  };
  const diagnosticNodeIndices=(lowPower?[0,3,4]:[0,1,2,3,4]).filter(index=>json.nodes?.[index]?.mesh!==undefined);
  const diagnostics=diagnosticNodeIndices.map(nodeIndex=>{
    const diagnosticNode=json.nodes[nodeIndex];
    const diagnosticMesh=json.meshes?.[diagnosticNode.mesh];
    const diagnosticPrimitive=diagnosticMesh?.primitives?.[0];
    if(!diagnosticPrimitive) throw new Error("glb_diagnostic_mesh");
    const diagnosticPositions=accessorView(json,binary,diagnosticPrimitive.attributes.POSITION);
    const diagnosticIndices=accessorView(json,binary,diagnosticPrimitive.indices);
    if(!(diagnosticPositions instanceof Float32Array)) throw new Error("glb_diagnostic_position");
    const positionBuffer=gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER,positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER,diagnosticPositions,gl.STATIC_DRAW);
    const elementBuffer=gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,elementBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,diagnosticIndices,gl.STATIC_DRAW);
    const materialName=json.materials?.[diagnosticPrimitive.material]?.name||"";
    return {nodeIndex,node:diagnosticNode,positionBuffer,elementBuffer,indices:diagnosticIndices,color:diagnosticColor(materialName)};
  });

  let scanAnimation=null;
  const animation=json.animations?.[0];
  if(animation?.channels?.length&&animation?.samplers?.length){
    const channel=animation.channels.find(item=>item.target?.path==="translation"&&item.target?.node===3);
    const sampler=channel?animation.samplers[channel.sampler]:null;
    if(sampler){
      const times=accessorView(json,binary,sampler.input);
      const values=accessorView(json,binary,sampler.output);
      if(times instanceof Float32Array&&values instanceof Float32Array) scanAnimation={times,values};
    }
  }

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
    const projection=perspective(Math.PI/4.4,w/h,.1,100);
    gl.useProgram(program);
    gl.uniformMatrix4fv(loc.projection,false,projection);
    gl.useProgram(diagnosticProgram);
    gl.uniformMatrix4fv(diagnosticLoc.projection,false,projection);
    gl.uniformMatrix4fv(diagnosticLoc.view,false,view);
    gl.useProgram(program);
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
      const root=modelMatrix(yaw);

      gl.useProgram(diagnosticProgram);
      for(const diagnostic of diagnostics){
        let translation=null;
        if(!reduced&&diagnostic.nodeIndex===3&&scanAnimation){
          translation=sampleAnimation(scanAnimation.times,scanAnimation.values,time/1000);
        }
        gl.bindBuffer(gl.ARRAY_BUFFER,diagnostic.positionBuffer);
        gl.enableVertexAttribArray(diagnosticLoc.position);
        gl.vertexAttribPointer(diagnosticLoc.position,3,gl.FLOAT,false,0,0);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,diagnostic.elementBuffer);
        gl.uniformMatrix4fv(diagnosticLoc.model,false,multiply(root,nodeMatrix(diagnostic.node,translation)));
        gl.uniform4fv(diagnosticLoc.color,diagnostic.color);
        gl.drawElements(gl.TRIANGLES,diagnostic.indices.length,diagnostic.indices instanceof Uint32Array?gl.UNSIGNED_INT:gl.UNSIGNED_SHORT,0);
      }

      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER,vehiclePositionBuffer);
      gl.enableVertexAttribArray(loc.position);
      gl.vertexAttribPointer(loc.position,3,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ARRAY_BUFFER,vehicleUVBuffer);
      gl.enableVertexAttribArray(loc.uv);
      gl.vertexAttribPointer(loc.uv,2,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,indexBuffer);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D,textureObject);
      gl.uniformMatrix4fv(loc.model,false,root);
      gl.drawElements(gl.TRIANGLES,indices.length,indices instanceof Uint32Array?gl.UNSIGNED_INT:gl.UNSIGNED_SHORT,0);
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

  stage.classList.add("webgl-ready");
  stage.dataset.quality=lowPower?"glb-adaptive":"glb-high";
  stage.dataset.modelSource="blender-glb";
  stage.dataset.diagnosticScene=diagnostics.length?"active":"vehicle-only";
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
