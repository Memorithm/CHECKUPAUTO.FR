const canvas=document.getElementById("vehicle3DCanvas");
const stage=document.getElementById("vehicle3DStage");

if(canvas&&stage){
  const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches;
  const cores=navigator.hardwareConcurrency||4;
  const memory=navigator.deviceMemory||4;
  const lowPower=cores<=4||memory<=4;
  const gl=canvas.getContext("webgl",{
    alpha:true,
    antialias:!lowPower,
    premultipliedAlpha:false,
    powerPreference:lowPower?"low-power":"high-performance"
  });

  if(gl){
    const vertexSource=`
      attribute vec3 aPosition;
      attribute vec2 aUV;
      uniform mat4 uProjection;
      uniform mat4 uView;
      uniform mat4 uModel;
      varying vec2 vUV;
      varying float vDepth;
      void main(){
        vec4 world=uModel*vec4(aPosition,1.0);
        vUV=aUV;
        vDepth=aPosition.z;
        gl_Position=uProjection*uView*world;
      }`;

    const fragmentSource=`
      precision mediump float;
      uniform sampler2D uTexture;
      uniform vec3 uBackground;
      uniform float uUseKey;
      uniform float uLight;
      varying vec2 vUV;
      varying float vDepth;

      void main(){
        vec4 tex=texture2D(uTexture,vUV);
        float backgroundDistance=max(
          max(abs(tex.r-uBackground.r),abs(tex.g-uBackground.g)),
          abs(tex.b-uBackground.b)
        );
        float keyed=smoothstep(0.035,0.145,backgroundDistance);
        float alpha=tex.a*mix(1.0,keyed,uUseKey);
        if(alpha<0.015) discard;

        float centre=1.0-abs(vUV.x-0.5)*0.16;
        float depthLight=0.96+clamp(vDepth,0.0,0.18)*0.45;
        vec3 color=tex.rgb*centre*depthLight*uLight;
        gl_FragColor=vec4(color,alpha);
      }`;

    const shader=(type,source)=>{
      const item=gl.createShader(type);
      gl.shaderSource(item,source);
      gl.compileShader(item);
      if(!gl.getShaderParameter(item,gl.COMPILE_STATUS)){
        throw new Error(gl.getShaderInfoLog(item)||"shader_compile_failed");
      }
      return item;
    };

    const ident=()=>new Float32Array([
      1,0,0,0,
      0,1,0,0,
      0,0,1,0,
      0,0,0,1
    ]);

    const multiply=(a,b)=>{
      const out=new Float32Array(16);
      for(let c=0;c<4;c++) for(let r=0;r<4;r++){
        out[c*4+r]=
          a[r]*b[c*4]+
          a[4+r]*b[c*4+1]+
          a[8+r]*b[c*4+2]+
          a[12+r]*b[c*4+3];
      }
      return out;
    };

    const perspective=(fov,aspect,near,far)=>{
      const f=1/Math.tan(fov/2);
      const nf=1/(near-far);
      return new Float32Array([
        f/aspect,0,0,0,
        0,f,0,0,
        0,0,(far+near)*nf,-1,
        0,0,2*far*near*nf,0
      ]);
    };

    const modelMatrix=(yaw,pitch=0)=>{
      const cy=Math.cos(yaw),sy=Math.sin(yaw);
      const cx=Math.cos(pitch),sx=Math.sin(pitch);
      const ry=new Float32Array([
        cy,0,-sy,0,
        0,1,0,0,
        sy,0,cy,0,
        0,0,0,1
      ]);
      const rx=new Float32Array([
        1,0,0,0,
        0,cx,sx,0,
        0,-sx,cx,0,
        0,0,0,1
      ]);
      return multiply(ry,rx);
    };

    const sampleCorners=image=>{
      const probe=document.createElement("canvas");
      probe.width=4;
      probe.height=4;
      const ctx=probe.getContext("2d",{willReadFrequently:true});
      if(!ctx) return {background:[0.96,0.97,0.95],useKey:0};
      ctx.drawImage(image,0,0,4,4);
      const pixels=ctx.getImageData(0,0,4,4).data;
      const indices=[0,3,12,15];
      const rgb=[0,0,0];
      let alpha=0;
      for(const index of indices){
        const offset=index*4;
        rgb[0]+=pixels[offset]/255;
        rgb[1]+=pixels[offset+1]/255;
        rgb[2]+=pixels[offset+2]/255;
        alpha+=pixels[offset+3]/255;
      }
      return {
        background:rgb.map(v=>v/indices.length),
        useKey:alpha/indices.length>0.95?1:0
      };
    };

    const createGrid=(aspect)=>{
      const cols=lowPower?28:44;
      const rows=lowPower?16:26;
      const width=6.3;
      const height=width/Math.max(0.5,aspect);
      const positions=[];
      const uvs=[];
      const indices=[];

      for(let y=0;y<=rows;y++){
        const v=y/rows;
        const ny=(v-0.5)*2;
        for(let x=0;x<=cols;x++){
          const u=x/cols;
          const nx=(u-0.5)*2;
          const edge=Math.max(0,1-nx*nx);
          const vertical=Math.max(0.2,1-0.52*ny*ny);
          const depth=0.16*edge*vertical;
          positions.push(
            (u-0.5)*width,
            (v-0.5)*height+0.14,
            depth
          );
          uvs.push(u,1-v);
        }
      }

      for(let y=0;y<rows;y++){
        for(let x=0;x<cols;x++){
          const a=y*(cols+1)+x;
          const b=a+1;
          const d=(y+1)*(cols+1)+x;
          const c=d+1;
          indices.push(a,b,c,a,c,d);
        }
      }

      return {
        positions:new Float32Array(positions),
        uvs:new Float32Array(uvs),
        indices:new Uint16Array(indices)
      };
    };

    try{
      const program=gl.createProgram();
      gl.attachShader(program,shader(gl.VERTEX_SHADER,vertexSource));
      gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragmentSource));
      gl.linkProgram(program);
      if(!gl.getProgramParameter(program,gl.LINK_STATUS)){
        throw new Error(gl.getProgramInfoLog(program)||"shader_link_failed");
      }
      gl.useProgram(program);

      const loc={
        position:gl.getAttribLocation(program,"aPosition"),
        uv:gl.getAttribLocation(program,"aUV"),
        projection:gl.getUniformLocation(program,"uProjection"),
        view:gl.getUniformLocation(program,"uView"),
        model:gl.getUniformLocation(program,"uModel"),
        texture:gl.getUniformLocation(program,"uTexture"),
        background:gl.getUniformLocation(program,"uBackground"),
        useKey:gl.getUniformLocation(program,"uUseKey"),
        light:gl.getUniformLocation(program,"uLight")
      };

      const texture=gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D,texture);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.uniform1i(loc.texture,0);

      const view=ident();
      view[14]=-7.7;
      view[13]=-0.02;
      gl.uniformMatrix4fv(loc.view,false,view);
      gl.uniform1f(loc.light,1.0);

      let geometry=null;
      let indexCount=0;

      const bindGeometry=mesh=>{
        geometry={
          position:gl.createBuffer(),
          uv:gl.createBuffer(),
          index:gl.createBuffer()
        };

        gl.bindBuffer(gl.ARRAY_BUFFER,geometry.position);
        gl.bufferData(gl.ARRAY_BUFFER,mesh.positions,gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc.position);
        gl.vertexAttribPointer(loc.position,3,gl.FLOAT,false,0,0);

        gl.bindBuffer(gl.ARRAY_BUFFER,geometry.uv);
        gl.bufferData(gl.ARRAY_BUFFER,mesh.uvs,gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc.uv);
        gl.vertexAttribPointer(loc.uv,2,gl.FLOAT,false,0,0);

        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,geometry.index);
        gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,mesh.indices,gl.STATIC_DRAW);
        indexCount=mesh.indices.length;
      };

      let yaw=-0.055;
      let targetYaw=yaw;
      let pointerStart=0;
      let yawStart=0;
      let dragging=false;
      let frameId=0;
      let lastFrame=0;
      let visible=false;
      let contextLost=false;
      let ready=false;

      const resize=()=>{
        const ratio=Math.min(devicePixelRatio||1,lowPower?1.25:1.7);
        const rect=canvas.getBoundingClientRect();
        const w=Math.max(1,Math.round(rect.width*ratio));
        const h=Math.max(1,Math.round(rect.height*ratio));
        if(canvas.width!==w||canvas.height!==h){
          canvas.width=w;
          canvas.height=h;
        }
        gl.viewport(0,0,w,h);
        gl.uniformMatrix4fv(
          loc.projection,
          false,
          perspective(Math.PI/4.4,w/h,0.1,100)
        );
        schedule();
      };

      const schedule=()=>{
        if(ready&&!frameId&&visible&&!document.hidden&&!contextLost){
          frameId=requestAnimationFrame(draw);
        }
      };

      const draw=time=>{
        frameId=0;
        if(!ready||!visible||document.hidden||contextLost) return;

        if(reduced||time-lastFrame>(lowPower?34:16)){
          lastFrame=time;
          if(!dragging&&!reduced){
            targetYaw+=(-0.055-targetYaw)*0.025;
          }
          yaw+=(targetYaw-yaw)*(dragging?0.28:0.08);

          gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
          gl.uniformMatrix4fv(loc.model,false,modelMatrix(yaw,-0.012));
          gl.drawElements(gl.TRIANGLES,indexCount,gl.UNSIGNED_SHORT,0);
        }

        if(!reduced||dragging||Math.abs(targetYaw-yaw)>0.001){
          frameId=requestAnimationFrame(draw);
        }
      };

      const image=new Image();
      image.decoding="async";
      image.onload=()=>{
        try{
          const aspect=image.naturalWidth/image.naturalHeight;
          bindGeometry(createGrid(aspect));
          const sampled=sampleCorners(image);

          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D,texture);
          gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
          gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
          gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.RGBA,
            gl.RGBA,
            gl.UNSIGNED_BYTE,
            image
          );

          gl.uniform3fv(loc.background,new Float32Array(sampled.background));
          gl.uniform1f(loc.useKey,sampled.useKey);

          gl.enable(gl.BLEND);
          gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
          gl.disable(gl.CULL_FACE);
          gl.enable(gl.DEPTH_TEST);
          gl.clearColor(0,0,0,0);

          ready=true;
          stage.classList.add("webgl-ready");
          stage.dataset.quality=lowPower?"adaptive":"high";
          resize();
          schedule();
        }catch(_error){
          canvas.hidden=true;
          stage.dataset.quality="fallback";
        }
      };
      image.onerror=()=>{
        canvas.hidden=true;
        stage.dataset.quality="fallback";
      };
      image.src="/assets/vehicle.png?v=photo-depth-1";

      new ResizeObserver(resize).observe(stage);

      canvas.addEventListener("pointerdown",event=>{
        canvas.setPointerCapture(event.pointerId);
        pointerStart=event.clientX;
        yawStart=targetYaw;
        dragging=true;
        schedule();
      });

      canvas.addEventListener("pointermove",event=>{
        if(!dragging) return;
        const delta=(event.clientX-pointerStart)*0.0019;
        targetYaw=Math.max(-0.18,Math.min(0.11,yawStart+delta));
        schedule();
      });

      const release=()=>{
        dragging=false;
        schedule();
      };
      canvas.addEventListener("pointerup",release);
      canvas.addEventListener("pointercancel",release);

      canvas.addEventListener("webglcontextlost",event=>{
        event.preventDefault();
        contextLost=true;
        if(frameId) cancelAnimationFrame(frameId);
        frameId=0;
        stage.classList.remove("webgl-ready");
        stage.dataset.quality="fallback";
      });

      canvas.addEventListener("webglcontextrestored",()=>{
        window.location.reload();
      });

      document.addEventListener("visibilitychange",schedule);

      if("IntersectionObserver" in window){
        new IntersectionObserver(entries=>{
          visible=entries.some(entry=>entry.isIntersecting);
          if(!visible&&frameId){
            cancelAnimationFrame(frameId);
            frameId=0;
          }
          schedule();
        },{rootMargin:"80px"}).observe(stage);
      }else{
        visible=true;
      }
    }catch(_error){
      canvas.hidden=true;
      stage.dataset.quality="fallback";
    }
  }else{
    canvas.hidden=true;
    stage.dataset.quality="fallback";
  }
}
