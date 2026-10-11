/* Copyright 2026 itshover. Apache-2.0, see licenses/itshover-Apache-2.0.txt.
 * Modified adaptation 2026-10-11: original icon paths and motion ideas are
 * mapped from React/Motion to native Web Animations for this design preview.
 * Added focus/click, finite text-frame analogues and reduced-motion controls.
 * This does not implement terminal graphics or execute any ISyCode action.
 */
(() => {
  const cards = [...document.querySelectorAll('[data-motion]')];
  const toggle = document.getElementById('reduce-motion');
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  const status = document.getElementById('motion-status');
  const timers = new Map();
  const sequences = {
    copy:['▣','✓'], terminal:['›_','› ','›_'], refresh:['◷','◴','◵','◶','◷'],
    connection:['↔','→←','↔'], shield:['◇','◇✓'], check:['✓','·','✓'],
  };
  const reduced = () => media.matches || toggle.checked;
  function reset(card) {
    clearTimeout(timers.get(card));
    card.querySelectorAll('svg,svg *').forEach(el => el.getAnimations().forEach(a => a.cancel()));
    card.querySelector('.text-frame').textContent = sequences[card.dataset.motion][0];
    card.dataset.playing = 'false';
  }
  function play(card) {
    reset(card);
    if (reduced()) {
      status.textContent = 'Movimiento reducido · iconos estáticos; las acciones mantienen su texto.';
      return;
    }
    const kind = card.dataset.motion;
    card.dataset.playing = 'true';
    status.textContent = 'Muestra de movimiento: ' + card.querySelector('.motion-label').textContent + ' · sólo demostración visual.';
    function animate(selector, frames, duration, easing='ease-in-out') {
      card.querySelectorAll(selector).forEach(el => el.animate(frames, {duration,easing,iterations:1}));
    }
    if(kind==='copy') animate('.front-copy', {transform:['translate(0,0)','translate(2px,2px)','translate(0,0)']},300);
    if(kind==='terminal') {
      animate('.cursor-line',{opacity:[1,0,1,0,1]},800);
      animate('.terminal-chevron',{transform:['translateX(0)','translateX(2px)','translateX(0)']},300);
    }
    if(kind==='refresh') animate('svg',{transform:['rotate(0deg)','rotate(180deg)','rotate(0deg)']},800);
    if(kind==='connection') {
      animate('.plug-upper-part',{transform:['translate(0,0)','translate(-2px,2px)','translate(0,0)']},650);
      animate('.plug-lower-part',{transform:['translate(0,0)','translate(2px,-2px)','translate(0,0)']},650);
      animate('.plug-lower-leg',{opacity:[1,0,1]},650);
    }
    if(kind==='shield') {
      animate('.shield-body',{transform:['scale(1)','scale(1.05)','scale(1)']},350,'ease-out');
      animate('.shield-check',{strokeDashoffset:['1','0'],opacity:[0,1]},300);
    }
    if(kind==='check') animate('.check-path',{strokeDashoffset:['0','1','0']},500);
    const frames=sequences[kind];
    let i=0;
    const step=()=>{
      card.querySelector('.text-frame').textContent=frames[i++];
      timers.set(card,setTimeout(i<frames.length?step:()=>{reset(card);},i<frames.length?160:900-(frames.length-1)*160));
    };
    step();
  }
  cards.forEach(card => {
    card.querySelectorAll('.shield-check,.check-path').forEach(path=>{
      path.setAttribute('pathLength','1');
      path.style.strokeDasharray='1';
    });
    card.addEventListener('pointerenter',()=>play(card));
    card.addEventListener('pointerleave',()=>reset(card));
    card.addEventListener('focus',()=>play(card));
    card.addEventListener('blur',()=>reset(card));
    card.addEventListener('click',()=>play(card));
  });
  function updateReduced() {
    cards.forEach(reset);
    status.textContent=reduced()?'Movimiento reducido · iconos estáticos.':'Pasa el mouse, enfoca con Tab o pulsa un ejemplo.';
  }
  toggle.addEventListener('change',updateReduced);
  media.addEventListener('change',updateReduced);
  updateReduced();
})();
