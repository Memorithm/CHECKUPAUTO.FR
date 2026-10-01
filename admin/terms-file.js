(function(root){
 'use strict';
 function decode(name,bytes){
  if(!/\.(txt|md)$/i.test(name))throw new Error('Choisissez un fichier .txt ou .md en UTF-8.');
  if(bytes.byteLength>200000)throw new Error('Le fichier dépasse 200 Ko.');
  let text;
  try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes)}catch(_){throw new Error('Le fichier doit être encodé en UTF-8.')}
  text=text.replace(/\r\n?/g,'\n').trim();
  if(text.length<80||text.length>50000)throw new Error('Le texte doit contenir entre 80 et 50 000 caractères.');
  if(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text))throw new Error('Le fichier contient des caractères non textuels.');
  return text;
 }
 const api={decode};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 else root.CheckupAutoTermsFile=api;
})(typeof window==='undefined'?globalThis:window);
