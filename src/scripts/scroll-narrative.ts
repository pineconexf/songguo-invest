// 滚动叙事控制器：每屏解决一个信任问题，动效只承担叙事功能
// 1. .reveal 元素进入视口 60% → 加 .in（渐显上移）
// 2. [data-count] 数字随进入视口递增（数据墙真实数字的"计算感"）
// 3. .steps-step 进入视口逐条点亮（审计步骤的"逐步解锁"叙事）
// 4. 叙事动画宁可慢，不让用户划过去没看懂

// 渐进增强：仅当 JS 可用时才隐藏初始状态（无 JS 时内容直接可见）
document.documentElement.classList.add('js');

const NARRATIVE_ANIM = 700; // ms，关键叙事动画
const COUNT_ANIM = 1200; // ms，数字递增

function inViewport(el: Element, ratio = 0.6): boolean {
  const r = el.getBoundingClientRect();
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const visible = Math.min(r.bottom, vh) - Math.max(r.top, 0);
  return visible > 0 && visible / Math.max(r.height, 1) >= ratio;
}

// 数字递增（只跑一次，慢速，表达"真实计算"而非炫技）
// HTML 里写最终值（无 JS 也显示真实数字），动画前先重置为 0 起点
function runCountUp(el: HTMLElement) {
  const target = parseFloat(el.dataset.count || '0');
  const suffix = el.dataset.suffix || '';
  const decimals = el.dataset.decimals ? parseInt(el.dataset.decimals, 10) : 0;
  const prefix = el.dataset.prefix || '';
  const start = performance.now();
  const dur = COUNT_ANIM;
  el.textContent = `${prefix}0${decimals > 0 ? '.' + '0'.repeat(decimals) : ''}${suffix}`;
  function tick(now: number) {
    const p = Math.min((now - start) / dur, 1);
    const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
    const v = target * eased;
    el.textContent = `${prefix}${v.toFixed(decimals)}${suffix}`;
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

const revealEls = Array.from(document.querySelectorAll<HTMLElement>('.reveal, .action-card'));
const countEls = Array.from(document.querySelectorAll<HTMLElement>('[data-count]'));
const stepEls = Array.from(document.querySelectorAll<HTMLElement>('.steps-step'));

const observed = new WeakSet<Element>();
let ticking = false;

function check() {
  ticking = false;
  revealEls.forEach((el) => {
    if (observed.has(el)) return;
    if (inViewport(el)) {
      el.classList.add('in');
      observed.add(el);
    }
  });
  countEls.forEach((el) => {
    if (observed.has(el)) return;
    if (inViewport(el, 0.4)) {
      runCountUp(el);
      observed.add(el);
    }
  });
  stepEls.forEach((el, i) => {
    if (observed.has(el)) return;
    if (inViewport(el, 0.5)) {
      // 点亮当前步，同时回溯点亮前面的（"逐步解锁"）
      for (let j = 0; j <= i; j++) {
        stepEls[j].classList.add('lit');
        observed.add(stepEls[j]);
      }
    }
  });
}

function onScroll() {
  if (!ticking) {
    ticking = true;
    requestAnimationFrame(check);
  }
}

// 首屏元素（hero）不依赖滚动直接检查一次
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    check();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
  });
} else {
  check();
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
}
