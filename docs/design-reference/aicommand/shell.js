// Shared tweaks + clock + fit-to-viewport for AiCommander pages
(function(){
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "accentHue": 45,
    "density": "comfortable",
    "ambientTelemetry": true,
    "animation": "normal"
  }/*EDITMODE-END*/;
  const state = { ...TWEAK_DEFAULTS };

  function setSeg(id, v) {
    document.querySelectorAll('#'+id+' button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  }
  function apply() {
    document.documentElement.style.setProperty('--accent-hue', state.accentHue);
    const hv = document.getElementById('hue-val'); if (hv) hv.textContent = state.accentHue + '°';
    const hr = document.getElementById('hue'); if (hr) hr.value = state.accentHue;
    document.body.dataset.density = state.density;
    document.body.dataset.telemetry = state.ambientTelemetry ? 'on' : 'off';
    document.body.dataset.animation = state.animation;
    setSeg('seg-density', state.density);
    setSeg('seg-telemetry', state.ambientTelemetry ? 'on' : 'off');
    setSeg('seg-animation', state.animation);
  }
  function persist() {
    try {
      window.parent.postMessage({ type: '__edit_mode_set_keys', edits: {
        accentHue: state.accentHue, density: state.density,
        ambientTelemetry: state.ambientTelemetry, animation: state.animation
      }}, '*');
    } catch(e) {}
  }

  document.querySelectorAll('.tk .seg').forEach(seg => {
    seg.addEventListener('click', e => {
      const btn = e.target.closest('button'); if (!btn) return;
      const id = seg.id.replace('seg-',''); const v = btn.dataset.v;
      if (id === 'density') state.density = v;
      else if (id === 'telemetry') state.ambientTelemetry = v === 'on';
      else if (id === 'animation') state.animation = v;
      apply(); persist();
    });
  });

  window.tweaks = {
    toggle() { document.getElementById('tweaks-panel').classList.toggle('open'); },
    setHue(v) { state.accentHue = +v; apply(); persist(); }
  };

  window.addEventListener('message', (e) => {
    const d = e.data || {};
    if (d.type === '__activate_edit_mode') document.getElementById('tweaks-panel').classList.add('open');
    if (d.type === '__deactivate_edit_mode') document.getElementById('tweaks-panel').classList.remove('open');
  });
  try { window.parent.postMessage({ type: '__edit_mode_available' }, '*'); } catch(e) {}
  apply();

  // clock
  function tickClock() {
    const d = new Date();
    const pad = n => String(n).padStart(2,'0');
    const h = document.getElementById('clk-h'); if (!h) return;
    h.textContent = pad(d.getHours());
    document.getElementById('clk-m').textContent = pad(d.getMinutes());
    document.getElementById('clk-s').textContent = pad(d.getSeconds());
    const weekdays = ['日','一','二','三','四','五','六'];
    document.getElementById('clk-d').textContent =
      d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' · 星期'+weekdays[d.getDay()]+' · 辖区滨州';
  }
  tickClock(); setInterval(tickClock, 1000);

  // fit-to-viewport scaling
  const stage = document.getElementById('stage');
  if (stage) {
    function fit(){
      const sx = window.innerWidth / 1920;
      const sy = window.innerHeight / 1080;
      const s = Math.min(sx, sy);
      const tx = (window.innerWidth  - 1920 * s) / 2;
      const ty = (window.innerHeight - 1080 * s) / 2;
      stage.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + s + ')';
    }
    fit();
    window.addEventListener('resize', fit);
  }
})();
