/* CheckupAuto customer editorial carousel — CSP-safe, accessible and progressive. */
(() => {
  'use strict';
  const host = document.getElementById('customerAnnouncements');
  if (!host || host.dataset.carouselReady) return;
  host.dataset.carouselReady = 'true';

  const track = host.querySelector('.announcement-track');
  const counter = host.querySelector('.announcement-counter');
  const progress = host.querySelector('.announcement-progress');
  const previous = host.querySelector('.announcement-previous');
  const next = host.querySelector('.announcement-next');
  if (!track || !counter || !progress || !previous || !next) return;

  const DURATION = 9300;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let messages = [...track.querySelectorAll('.announcement-copy')].map(node => node.textContent.trim()).filter(Boolean);
  let active = 0;
  let lastChange = Date.now();
  let timer = null;
  let paused = false;

  const readableCount = () => String(active + 1).padStart(2, '0') + ' / ' + String(messages.length).padStart(2, '0');

  function resetProgress() {
    progress.classList.remove('is-running');
    progress.style.animationDuration = DURATION + 'ms';
    if (!reduceMotion.matches && messages.length > 1 && !paused) {
      void progress.offsetWidth;
      progress.classList.add('is-running');
    }
  }

  function moveTo(index, direction = 1) {
    if (messages.length < 2 || index === active) return;
    const items = [...track.querySelectorAll('.announcement-copy')];
    const old = items[active];
    const incoming = items[index];
    host.dataset.direction = direction < 0 ? 'back' : 'forward';
    old.classList.remove('is-active');
    old.classList.add('is-leaving');
    old.setAttribute('aria-hidden', 'true');
    incoming.classList.remove('is-leaving');
    // Force initial translate for the new copy before activating the transition.
    void incoming.offsetWidth;
    incoming.classList.add('is-active');
    incoming.removeAttribute('aria-hidden');
    active = index;
    counter.textContent = readableCount();
    lastChange = Date.now();
    resetProgress();
  }

  function advance(direction = 1) {
    if (!messages.length) return;
    moveTo((active + direction + messages.length) % messages.length, direction);
  }

  function render(nextMessages) {
    const cleaned = nextMessages.filter(message => typeof message === 'string' && message.trim()).map(message => message.trim());
    if (cleaned.length === messages.length && cleaned.every((x, i) => x === messages[i])) return;
    const existing = messages[active];
    messages = cleaned;
    active = Math.max(0, messages.indexOf(existing));
    if (active >= messages.length) active = 0;
    host.hidden = messages.length === 0;
    track.replaceChildren();
    messages.forEach((message, index) => {
      const slide = document.createElement('span');
      slide.className = 'announcement-copy' + (index === active ? ' is-active' : '');
      slide.textContent = message; // Never treat admin editorial text as HTML.
      if (index !== active) slide.setAttribute('aria-hidden', 'true');
      track.appendChild(slide);
    });
    counter.textContent = messages.length ? readableCount() : '00 / 00';
    const single = messages.length < 2;
    previous.hidden = single;
    next.hidden = single;
    progress.hidden = single;
    lastChange = Date.now();
    resetProgress();
  }

  function stopTimer() {
    if (timer) window.clearInterval(timer);
    timer = null;
    progress.classList.remove('is-running');
  }

  function startTimer() {
    stopTimer();
    if (paused || document.hidden || reduceMotion.matches || messages.length < 2) return;
    const remaining = Math.max(500, DURATION - (Date.now() - lastChange));
    timer = window.setTimeout(() => {
      if (!paused && !document.hidden) advance();
      startTimer();
    }, remaining);
    resetProgress();
  }

  host.addEventListener('mouseenter', () => { paused = true; stopTimer(); });
  host.addEventListener('mouseleave', () => { paused = false; lastChange = Date.now(); startTimer(); });
  host.addEventListener('focusin', () => { paused = true; stopTimer(); });
  host.addEventListener('focusout', event => {
    if (host.contains(event.relatedTarget)) return;
    paused = false;
    lastChange = Date.now();
    startTimer();
  });
  previous.addEventListener('click', () => { advance(-1); startTimer(); });
  next.addEventListener('click', () => { advance(1); startTimer(); });
  document.addEventListener('visibilitychange', () => { lastChange = Date.now(); if (document.hidden) stopTimer(); else startTimer(); });
  reduceMotion.addEventListener?.('change', () => { lastChange = Date.now(); startTimer(); });
  host.addEventListener('checkupauto:announcements', event => {
    if (!Array.isArray(event.detail?.messages)) return;
    render(event.detail.messages);
    startTimer();
  });
  render(messages);
  startTimer();
})();
