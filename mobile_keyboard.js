// All input stays on the authenticated VNC channel. No storage or input logging.
export function attachKeyboard({screen,getViewer,isReady,status}) {
 const dock=document.querySelector('#input-tools'),input=document.querySelector('#phone-input');
 const panel=document.querySelector('#clipboard-panel'),copyText=document.querySelector('#copy-text');
 const mobile=matchMedia('(pointer:coarse)').matches;
 let composing=false,copyRequested=false,copyTimer=null;
 const sentinel='\u200b';
 const reset=()=>{input.value=sentinel;input.setSelectionRange(1,1)};
 const ready=()=>isReady()&&getViewer();
 const key=(sym,code)=>{if(ready())getViewer().sendKey(sym,code)};
 const text=value=>{
  if(!ready()){status.textContent='Reconnect before typing';return}
  if(value.length>4096){status.textContent='Paste up to 4096 characters at a time';return}
  for(const c of value.replace(/\r\n/g,'\n')){
   const n=c.codePointAt(0);
   if(c==='\n'||c==='\r')key(0xff0d,'Enter');
   else if(c==='\t')key(0xff09,'Tab');
   else if(n>=32)key(n<=255?n:0x01000000|n,null);
  }
 };
 const focus=()=>{if(!ready())return;dock.hidden=false;reset();input.focus({preventScroll:true})};
 document.querySelector('#keyboard').onclick=()=>{input.inputMode='text';focus()};
 document.querySelector('#numbers').onclick=()=>{input.inputMode='numeric';input.blur();focus()};
 document.querySelector('#hide-keyboard').onclick=()=>{input.blur();dock.hidden=true};
 // Focusing during a user touch opens iOS/Android keyboards. Do not steal scroll gestures.
 let touch=null;
 screen.addEventListener('pointerdown',e=>{if(e.pointerType==='touch')touch={x:e.clientX,y:e.clientY}});
 screen.addEventListener('pointerup',e=>{
  if(touch&&e.pointerType==='touch'&&Math.hypot(e.clientX-touch.x,e.clientY-touch.y)<10){input.inputMode=input.inputMode||'text';focus()}
  touch=null;
 });
 input.addEventListener('compositionstart',()=>{composing=true});
 input.addEventListener('compositionend',()=>{composing=false;text(input.value.split(sentinel).join(''));reset()});
 input.addEventListener('input',e=>{
  if(composing||e.isComposing)return;
  if(e.inputType?.startsWith('delete'))key(e.inputType.includes('Forward')?0xffff:0xff08,e.inputType.includes('Forward')?'Delete':'Backspace');
  else text(input.value.split(sentinel).join(''));
  reset();
 });
 input.addEventListener('keydown',e=>{
  if(composing||e.isComposing)return;
  const special={Enter:[0xff0d,'Enter'],Tab:[0xff09,'Tab'],ArrowLeft:[0xff51,'ArrowLeft'],ArrowRight:[0xff53,'ArrowRight']};
  if(special[e.key]){e.preventDefault();key(...special[e.key])}
 });
 input.addEventListener('paste',e=>{e.preventDefault();text(e.clipboardData.getData('text/plain'));reset()});
 for(const [id,sym,code]of [['backspace',0xff08,'Backspace'],['next-field',0xff09,'Tab'],['enter-key',0xff0d,'Enter']]){
  document.querySelector('#'+id).addEventListener('pointerdown',e=>e.preventDefault());
  document.querySelector('#'+id).onclick=()=>key(sym,code);
 }
 document.querySelector('#paste').onclick=async()=>{
  if(!ready())return;
  try{text(await navigator.clipboard.readText())}
  catch{focus();status.textContent='Long-press the typing box and choose Paste'}
 };
 document.querySelector('#copy').onclick=()=>{
  if(!ready())return;
  copyRequested=true;
  getViewer().sendKey(0xffe3,'ControlLeft',true);
  getViewer().sendKey(0x63,'KeyC');
  getViewer().sendKey(0xffe3,'ControlLeft',false);
  clearTimeout(copyTimer);copyTimer=setTimeout(()=>{copyRequested=false;status.textContent='Select text in the remote page, then tap Copy'},2500);
 };
 document.querySelector('#copy-confirm').onclick=async()=>{
  try{await navigator.clipboard.writeText(copyText.value);copyText.value='';panel.hidden=true;status.textContent='Copied'}
  catch{copyText.focus();copyText.select();status.textContent='Long-press the selected text and choose Copy'}
 };
 document.querySelector('#copy-close').onclick=()=>{copyText.value='';panel.hidden=true};
 const cleanup=()=>{composing=false;copyRequested=false;clearTimeout(copyTimer);input.blur();reset();copyText.value='';panel.hidden=true;dock.hidden=true};
 window.addEventListener('pagehide',cleanup);
 // Shrink the visible viewer around the mobile keyboard, without changing remote geometry.
 const resize=()=>{document.querySelector('main').style.height=(window.visualViewport?.height||window.innerHeight)+'px'};
 window.visualViewport?.addEventListener('resize',resize);resize();
 reset();
 return { bind(viewer){
  viewer.focusOnClick=!mobile;
  viewer.addEventListener('clipboard',e=>{
   if(!copyRequested||getViewer()!==viewer)return;
   copyRequested=false;clearTimeout(copyTimer);copyText.value=e.detail.text;panel.hidden=false;
  });
  viewer.addEventListener('disconnect',()=>{if(getViewer()===viewer)cleanup()});
 },cleanup};
}
