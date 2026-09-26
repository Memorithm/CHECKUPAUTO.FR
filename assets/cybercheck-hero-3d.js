const canvas=document.getElementById("vehicle3DCanvas");
const stage=document.getElementById("vehicle3DStage");

if(canvas&&stage){
  const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches;
  const cores=navigator.hardwareConcurrency||4;
  const memory=navigator.deviceMemory||4;
  const lowPower=cores<=4||memory<=4;
  const gl=canvas.getContext("webgl",{alpha:true,antialias:!lowPower,premultipliedAlpha:true,powerPreference:lowPower?"low-power":"high-performance"});

  if(gl){
    const vertexSource=`
      attribute vec3 aPosition;
      attribute vec3 aNormal;
      uniform mat4 uProjection;
      uniform mat4 uView;
      uniform mat4 uModel;
      varying vec3 vNormal;
      void main(){
        vNormal=normalize(mat3(uModel)*aNormal);
        gl_Position=uProjection*uView*uModel*vec4(aPosition,1.0);
      }`;
    const fragmentSource=`
      precision mediump float;
      varying vec3 vNormal;
      uniform vec3 uColor;
      uniform float uGloss;
      void main(){
        vec3 n=normalize(vNormal);
        vec3 light=normalize(vec3(-0.45,0.85,0.65));
        float diffuse=max(dot(n,light),0.0);
        float top=max(n.y,0.0);
        float rim=pow(1.0-max(n.z,0.0),2.0);
        vec3 base=uColor*(0.34+0.58*diffuse+0.16*top);
        vec3 highlight=vec3(1.0)*pow(max(dot(reflect(-light,n),vec3(0.0,0.18,0.98)),0.0),20.0)*uGloss;
        gl_FragColor=vec4(base+highlight+rim*0.035,1.0);
      }`;

    const shader=(type,source)=>{
      const item=gl.createShader(type);
      gl.shaderSource(item,source);gl.compileShader(item);
      if(!gl.getShaderParameter(item,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(item)||"shader");
      return item;
    };

    try{
      const program=gl.createProgram();
      gl.attachShader(program,shader(gl.VERTEX_SHADER,vertexSource));
      gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragmentSource));
      gl.linkProgram(program);
      if(!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program)||"link");
      gl.useProgram(program);

      const loc={
        position:gl.getAttribLocation(program,"aPosition"),
        normal:gl.getAttribLocation(program,"aNormal"),
        projection:gl.getUniformLocation(program,"uProjection"),
        view:gl.getUniformLocation(program,"uView"),
        model:gl.getUniformLocation(program,"uModel"),
        color:gl.getUniformLocation(program,"uColor"),
        gloss:gl.getUniformLocation(program,"uGloss")
      };

      const positions=[
        -1,-1,1, 1,-1,1, 1,1,1, -1,1,1,
        1,-1,-1, -1,-1,-1, -1,1,-1, 1,1,-1,
        -1,1,1, 1,1,1, 1,1,-1, -1,1,-1,
        -1,-1,-1, 1,-1,-1, 1,-1,1, -1,-1,1,
        1,-1,1, 1,-1,-1, 1,1,-1, 1,1,1,
        -1,-1,-1, -1,-1,1, -1,1,1, -1,1,-1
      ];
      const normals=[
        0,0,1,0,0,1,0,0,1,0,0,1,
        0,0,-1,0,0,-1,0,0,-1,0,0,-1,
        0,1,0,0,1,0,0,1,0,0,1,0,
        0,-1,0,0,-1,0,0,-1,0,0,-1,0,
        1,0,0,1,0,0,1,0,0,1,0,0,
        -1,0,0,-1,0,0,-1,0,0,-1,0,0
      ];
      const indices=[];
      for(let face=0;face<6;face++){const o=face*4;indices.push(o,o+1,o+2,o,o+2,o+3);}

      const positionBuffer=gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER,positionBuffer);
      gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(positions),gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc.position);
      gl.vertexAttribPointer(loc.position,3,gl.FLOAT,false,0,0);

      const normalBuffer=gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER,normalBuffer);
      gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(normals),gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc.normal);
      gl.vertexAttribPointer(loc.normal,3,gl.FLOAT,false,0,0);

      const indexBuffer=gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,indexBuffer);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,new Uint16Array(indices),gl.STATIC_DRAW);

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
      const transform=(tx,ty,tz,sx,sy,sz,ry=0,rz=0)=>{
        const cy=Math.cos(ry),syy=Math.sin(ry),cz=Math.cos(rz),szz=Math.sin(rz);
        const y=new Float32Array([cy,0,-syy,0,0,1,0,0,syy,0,cy,0,0,0,0,1]);
        const z=new Float32Array([cz,szz,0,0,-szz,cz,0,0,0,0,1,0,0,0,0,1]);
        const s=new Float32Array([sx,0,0,0,0,sy,0,0,0,0,sz,0,0,0,0,1]);
        const t=ident();t[12]=tx;t[13]=ty;t[14]=tz;
        return multiply(t,multiply(y,multiply(z,s)));
      };
      const view=ident();view[14]=-8.7;view[13]=-0.1;

      const pieces=[
        {p:[0,-0.25,0,2.85,0.48,1.08,0,0],c:[0.16,0.39,0.30],g:.52},
        {p:[-.15,.58,-.05,1.62,.58,.96,0,-.04],c:[0.19,0.46,0.36],g:.58},
        {p:[1.92,-.05,0,0.82,.26,1.02,0,-.08],c:[0.17,0.41,0.32],g:.52},
        {p:[-.35,.62,.94,1.18,.37,.045,0,-.04],c:[.22,.32,.29],g:.76},
        {p:[-.35,.62,-.94,1.18,.37,.045,0,-.04],c:[.22,.32,.29],g:.76},
        {p:[-1.65,.53,.0,.32,.48,1.10,0,.04],c:[.18,.43,.34],g:.56},
        {p:[-1.72,-.84,.88,.48,.48,.24,0,0],c:[.045,.052,.05],g:.12},
        {p:[1.72,-.84,.88,.48,.48,.24,0,0],c:[.045,.052,.05],g:.12},
        {p:[-1.72,-.84,-.88,.48,.48,.24,0,0],c:[.045,.052,.05],g:.12},
        {p:[1.72,-.84,-.88,.48,.48,.24,0,0],c:[.045,.052,.05],g:.12},
        {p:[2.78,-.22,.72,.08,.16,.28,0,0],c:[.92,.92,.78],g:.34},
        {p:[2.78,-.22,-.72,.08,.16,.28,0,0],c:[.92,.92,.78],g:.34}
      ];

      let yaw=-0.28,pointerStart=0,yawStart=0,dragging=false,lastFrame=0;
      let frameId=0,visible=false,contextLost=false;
      const resize=()=>{
        const ratio=Math.min(devicePixelRatio||1,lowPower?1.35:1.85);
        const rect=canvas.getBoundingClientRect();
        const w=Math.max(1,Math.round(rect.width*ratio)),h=Math.max(1,Math.round(rect.height*ratio));
        if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
        gl.viewport(0,0,w,h);
        gl.uniformMatrix4fv(loc.projection,false,perspective(Math.PI/4.2,w/h,.1,100));
      };
      new ResizeObserver(resize).observe(stage);resize();
      gl.enable(gl.DEPTH_TEST);gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);
      gl.clearColor(0,0,0,0);
      gl.uniformMatrix4fv(loc.view,false,view);

      const schedule=()=>{
        if(!frameId&&visible&&!document.hidden&&!contextLost) frameId=requestAnimationFrame(draw);
      };
      const draw=(time)=>{
        frameId=0;
        if(!visible||document.hidden||contextLost) return;
        if(time-lastFrame>(lowPower?32:16)){
          lastFrame=time;
          if(!dragging&&!reduced) yaw+=0.00022*(lowPower?1:1.2);
          gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
          const root=transform(0,0,0,1,1,1,yaw,0);
          for(const piece of pieces){
            gl.uniformMatrix4fv(loc.model,false,multiply(root,transform(...piece.p)));
            gl.uniform3fv(loc.color,new Float32Array(piece.c));
            gl.uniform1f(loc.gloss,piece.g);
            gl.drawElements(gl.TRIANGLES,indices.length,gl.UNSIGNED_SHORT,0);
          }
        }
        if(!reduced||dragging) frameId=requestAnimationFrame(draw);
      };
      const point=x=>{pointerStart=x;yawStart=yaw;dragging=true;schedule();};
      canvas.addEventListener("pointerdown",e=>{canvas.setPointerCapture(e.pointerId);point(e.clientX);});
      canvas.addEventListener("pointermove",e=>{if(dragging){yaw=yawStart+(e.clientX-pointerStart)*.008;schedule();}});
      canvas.addEventListener("pointerup",()=>{dragging=false;schedule();});
      canvas.addEventListener("pointercancel",()=>{dragging=false;schedule();});
      canvas.addEventListener("webglcontextlost",event=>{
        event.preventDefault();
        contextLost=true;
        if(frameId) cancelAnimationFrame(frameId);
        frameId=0;
        stage.classList.remove("webgl-ready");
        stage.dataset.quality="fallback";
      });
      canvas.addEventListener("webglcontextrestored",()=>window.location.reload());
      document.addEventListener("visibilitychange",schedule);
      if("IntersectionObserver" in window){
        new IntersectionObserver(entries=>{
          visible=entries.some(entry=>entry.isIntersecting);
          if(!visible&&frameId){cancelAnimationFrame(frameId);frameId=0;}
          schedule();
        },{rootMargin:"80px"}).observe(stage);
      }else{visible=true;schedule();}
      stage.classList.add("webgl-ready");
    }catch(_error){
      canvas.hidden=true;
      stage.dataset.quality="fallback";
    }
  }else{
    canvas.hidden=true;
    stage.dataset.quality="fallback";
  }
}