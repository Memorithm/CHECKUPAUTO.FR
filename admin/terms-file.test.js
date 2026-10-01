const {test}=require('node:test');
const assert=require('node:assert/strict');
const {decode}=require('./terms-file.js');
const bytes=s=>new TextEncoder().encode(s);
test('French text, BOM and line endings survive import',()=>{
 const value='Conditions de test : réservation, rétractation et paiement simulé. '.repeat(3);
 assert.equal(decode('CGV.TXT',bytes('\ufeff '+value+'\r\nFin. ')),value+'\nFin.');
});
test('Markdown remains inert text',()=>{
 const value='# TEST\n'+('<script>alert(1)</script> texte ').repeat(4);
 assert.equal(decode('cgv.md',bytes(value)),value.trim());
});
test('Invalid UTF-8 and binary content are refused',()=>{
 assert.throws(()=>decode('cgv.txt',new Uint8Array([0xff,0xfe])));
 assert.throws(()=>decode('cgv.txt',bytes('texte '.repeat(20)+'\0')));
 assert.throws(()=>decode('cgv.pdf',bytes('texte '.repeat(20))));
});
test('Length limits prevent empty or oversized imports',()=>{
 assert.throws(()=>decode('cgv.txt',bytes('court')));
 assert.throws(()=>decode('cgv.txt',bytes('x'.repeat(50001))));
 assert.throws(()=>decode('cgv.txt',new Uint8Array(200001)));
 assert.equal(decode('cgv.txt',bytes('x'.repeat(50000))).length,50000);
});
