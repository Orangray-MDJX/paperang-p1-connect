(() => {
  function setup() {
    if (!window.pywebview?.api) return;
    const controls = document.querySelector('.window-controls');
    if (!controls || !controls.hidden) return;
    document.body.classList.add('native-window');
    controls.hidden = false;
    controls.querySelector('[data-window=minimize]').onclick = () => window.pywebview.api.minimize();
    const maximize = controls.querySelector('[data-window=maximize]');
    maximize.onclick = async () => {
      const expanded = await window.pywebview.api.toggle_maximize();
      maximize.setAttribute('aria-label', expanded ? '还原窗口' : '最大化窗口');
      maximize.title = expanded ? '还原' : '最大化';
    };
    controls.querySelector('[data-window=close]').onclick = () => window.pywebview.api.close();
    document.querySelector('.titlebar-brand')?.addEventListener('dblclick', () => maximize.click());
  }
  window.addEventListener('pywebviewready', setup);
  if (window.pywebview?.api) setup();
})();
