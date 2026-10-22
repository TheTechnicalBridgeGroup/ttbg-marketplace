const {JSDOM}=require('jsdom');
const fs=require('fs'), assert=require('assert');
(async()=>{
const dom=new JSDOM('<form><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="new-password"><label for="confirm">Confirm password</label><input id="confirm" type="password"></form><dialog><input id="reauth" type="password"></dialog>',{runScripts:'outside-only'});
const w=dom.window,d=w.document;let logs=[];w.console.log=(...a)=>logs.push(a);w.fetch=()=>{throw Error('No network permitted')};
w.eval(fs.readFileSync(require('path').join(__dirname,'../app/static/js/passwords.js'),'utf8'));
const p=d.querySelector('#password'), c=d.querySelector('#confirm');p.value='test-only-secret';c.value='independent';
assert.equal(d.querySelectorAll('.password-toggle').length,3);
const b=p.parentElement.querySelector('button');assert.equal(b.type,'button');assert.equal(b.getAttribute('aria-label'),'Show Password');assert.equal(b.getAttribute('aria-controls'),'password');
b.click();assert.equal(p.type,'text');assert.equal(p.value,'test-only-secret');assert.equal(c.type,'password');assert.equal(b.getAttribute('aria-pressed'),'true');assert.equal(p.autocomplete,'new-password');
b.click();assert.equal(p.type,'password');assert.equal(p.value,'test-only-secret');
b.click();d.querySelector('form').dispatchEvent(new w.Event('submit'));assert.equal(p.type,'password');
const reauth=d.querySelector('#reauth');reauth.parentElement.querySelector('button').click();assert.equal(reauth.type,'text');d.querySelector('dialog').dispatchEvent(new w.Event('close'));assert.equal(reauth.type,'password');
const next=d.createElement('input');next.type='password';d.body.append(next);await new Promise(r=>setTimeout(r,10));assert.equal(d.querySelectorAll('.password-toggle').length,4);
assert.equal(logs.length,0);assert(!d.body.innerHTML.includes('test-only-secret'));
dom.window.close();console.log('Password DOM checks passed: independent toggles, labels, preserved values/autofill, dynamic fields, submit/dialog reset, no logs/network.');
})();
