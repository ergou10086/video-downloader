/**
 * 主题管理器 — Everforest 深色/浅色切换
 *
 * 将偏好保存到 localStorage，默认跟随系统主题设置。
 */

const THEME_KEY = 'video-dl-theme';
const PALETTE_KEY = 'video-dl-palette';

/** 获取系统级主题偏好。 */
function getSystemTheme() {
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** 获取 localStorage 中存储的主题设置。 */
function getStoredTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch(e) { return null; }
}

function getStoredPalette() {
  try { return localStorage.getItem(PALETTE_KEY); } catch(e) { return null; }
}

function applyPalette(palette) {
  const html = document.documentElement;
  html.classList.add('theme-transitioning');
  html.setAttribute('data-palette', palette);
  try { localStorage.setItem(PALETTE_KEY, palette); } catch(e) {}
  document.querySelectorAll('.palette-toggle').forEach(btn => {
    const normal = palette === 'normal';
    btn.classList.toggle('active', normal);
    btn.title = normal ? '切换为原始暖色配色' : '切换为正常中性配色';
    btn.setAttribute('aria-label', btn.title);
  });
  clearTimeout(html._paletteTimeout);
  html._paletteTimeout = setTimeout(() => html.classList.remove('theme-transitioning'), 400);
}

function togglePalette() {
  const current = document.documentElement.getAttribute('data-palette');
  applyPalette(current === 'normal' ? 'everforest' : 'normal');
}

/** 应用指定主题并持久化。 */
function applyTheme(theme) {
  const html = document.documentElement;
  html.classList.add('theme-transitioning');
  html.setAttribute('data-theme', theme);
  try { localStorage.setItem(THEME_KEY, theme); } catch(e) {}
  clearTimeout(html._themeTimeout);
  html._themeTimeout = setTimeout(() => {
    html.classList.remove('theme-transitioning');
  }, 400);
}

/** 切换深色/浅色主题并触发按钮旋转动画。 */
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'light' ? 'dark' : 'light';
  applyTheme(next);
  document.querySelectorAll('.theme-toggle:not(.palette-toggle)').forEach(btn => {
    btn.classList.add('spin');
    setTimeout(() => btn.classList.remove('spin'), 400);
  });
}

/** 初始化主题系统：应用存储/系统偏好，监听系统主题变更。 */
function initTheme() {
  const stored = getStoredTheme();
  applyTheme(stored || getSystemTheme());
  applyPalette(getStoredPalette() || 'normal');

  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
    if (!getStoredTheme()) {
      applyTheme(e.matches ? 'light' : 'dark');
    }
  });

  document.querySelectorAll('.theme-toggle:not(.palette-toggle)').forEach(btn => {
    btn.addEventListener('click', toggleTheme);
  });
  document.querySelectorAll('.palette-toggle').forEach(btn => {
    btn.addEventListener('click', togglePalette);
  });
}
