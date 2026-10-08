"""Build a standalone visual preview, never a production application.

Only the public home page, its stylesheet and an explicit media allowlist are
read. No application module, configuration, database or credential is loaded.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

MEDIA = {
    "assets/vehicle.mp4": "video/mp4",
    "assets/checkupauto-centre-map-osm.webp": "image/webp",
    **{
        "assets/premium/vehicle-" + name + "-premium.webp": "image/webp"
        for name in ("peugeot208", "suv4x4", "utility", "ambulance", "foodtruck")
    },
}
MAX_MEDIA_BYTES = 4 * 1024 * 1024
CSP = (
    "default-src 'none'; img-src data:; media-src data:; "
    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'"
)
PREVIEW_CSS = """
.preview-notice{padding:14px 5vw;background:#fff3c4;color:#463d1e;font:13px Arial;line-height:1.5;border-bottom:1px solid #d6c78d}
.preview-notice strong{display:block}.preview-notice code{font-size:11px}
#previewInformation{max-width:620px;width:calc(100% - 40px);padding:28px;border:1px solid #d9dfd3;background:#f6f7f2;color:#213b30}
#previewInformation::backdrop{background:#0007}#previewInformation h2{font:28px Georgia;margin-bottom:16px}
#previewInformation p{font:15px/1.7 Arial;margin-bottom:24px}#previewInformation button{padding:12px 24px;cursor:pointer}
.preview-app-card{padding:36px;border:1px solid #d9dfd3;background:#fff;font:16px/1.8 Arial}
#previewVehicleImage{width:100%;height:100%;object-fit:contain;position:relative;z-index:2;filter:drop-shadow(0 28px 20px #16231c2e)}
[hidden]{display:none!important}.slot-button{cursor:pointer}button:focus-visible,a:focus-visible{outline:3px solid #a57024;outline-offset:3px}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
"""
PREVIEW_JS = r"""
'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const buttons = [...document.querySelectorAll('.control-type-option')];
  const service = $('#service');
  const dateInput = $('#bookingStartDate');
  const dialog = $('#previewInformation');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function information(message) {
    $('#previewMessage').textContent = message;
    if (!dialog.open) dialog.showModal();
  }

  $('#previewClose').addEventListener('click', () => dialog.close());
  document.querySelectorAll('a[data-preview-disabled]').forEach(a => {
    a.addEventListener('click', event => {
      event.preventDefault();
      information('Cette fonction nécessite le serveur CheckupAuto. Dans cette démonstration, aucun appel, téléchargement d’application, paiement ou traitement de données n’est déclenché.');
    });
  });

  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Paris', year:'numeric', month:'2-digit', day:'2-digit'
  }).formatToParts(new Date()).filter(p => p.type !== 'literal').map(p => [p.type,p.value]));
  dateInput.value = `${parts.year}-${parts.month}-${parts.day}`;

  function amount() { return service.value === 'fitted' ? 90 : 80; }

  function resetSelection() {
    const box=$('#bookingSelection');
    box.classList.add('booking-awaiting');
    $('#bookingSelectionKicker').textContent='3 / RÉSERVER';
    $('#bookingSelectionLabel').textContent='Sélectionnez un créneau ci-dessus';
    $('#bookingSelectionPrice').textContent='Le bouton Réserver s’active automatiquement après votre choix.';
    const cta=$('#bookingContinue');
    cta.classList.add('disabled');
    cta.setAttribute('aria-disabled','true');
    cta.textContent='Choisissez un créneau pour réserver';
  }

  function render() {
    resetSelection();
    const root = $('#bookingDays');
    root.replaceChildren();
    const start = /^\d{4}-\d{2}-\d{2}$/.test(dateInput.value) ? dateInput.value : `${parts.year}-${parts.month}-${parts.day}`;
    const origin = new Date(start + 'T12:00:00Z');
    if (!Number.isFinite(origin.getTime())) return;
    for (let offset=0; offset<6; offset++) {
      const day = new Date(origin);
      day.setUTCDate(origin.getUTCDate()+offset);
      const label = new Intl.DateTimeFormat('fr-FR', {
        timeZone:'Europe/Paris',weekday:'long',day:'numeric',month:'short'
      }).format(day);
      const article = document.createElement('article');
      article.className='booking-day';
      const head = document.createElement('div');
      head.className='booking-day-head';
      const title = document.createElement('strong');
      title.textContent=label;
      head.append(title);
      article.append(head);
      const slots=document.createElement('div');
      slots.className='booking-slots';
      for (const time of ['09:00','10:30','14:00','16:30']) {
        const button=document.createElement('button');
        button.type='button';
        button.className='slot-button';
        const hour=document.createElement('span');
        hour.textContent=time;
        const price=document.createElement('small');
        price.textContent=amount()+' € TTC';
        const note=document.createElement('em');
        note.textContent='CRÉNEAU FICTIF';
        button.append(hour,price,note);
        button.addEventListener('click', () => {
          document.querySelectorAll('.slot-button.selected').forEach(b=>b.classList.remove('selected'));
          button.classList.add('selected');
          const box=$('#bookingSelection');
          box.classList.remove('booking-awaiting');
          $('#bookingSelectionKicker').textContent='3 / RÉSERVER';
          $('#bookingSelectionLabel').textContent=label+' · '+time;
          $('#bookingSelectionPrice').textContent=amount()+' € TTC · simulation uniquement';
          const cta=$('#bookingContinue');
          cta.classList.remove('disabled');
          cta.removeAttribute('aria-disabled');
          cta.textContent='Tester la réservation →';
          box.scrollIntoView({behavior:reduced?'auto':'smooth',block:'nearest'});
        });
        slots.append(button);
      }
      article.append(slots);
      root.append(article);
    }
    $('#bookingLiveStatus').textContent='DÉMONSTRATION · créneaux fictifs · aucune connexion à Mercure';
  }

  function choose(button) {
    buttons.forEach(b => {
      const active=b===button;
      b.classList.toggle('selected',active);
      b.setAttribute('aria-pressed',String(active));
    });
    service.value=button.dataset.service;
    $('#price').textContent=String(amount());
    render();
  }

  buttons.forEach(button=>button.addEventListener('click',()=>choose(button)));
  service.addEventListener('change',()=>{
    const selected=buttons.find(b=>b.dataset.service===service.value);
    if (selected) choose(selected);
  });
  dateInput.addEventListener('change',render);
  $('#bookingRefresh').addEventListener('click',render);
  $('#bookingContinue').addEventListener('click',event=>{
    event.preventDefault();
    if (event.currentTarget.classList.contains('disabled')) return;
    information('Parcours de démonstration terminé. Le créneau choisi est fictif : aucun rendez-vous n’a été créé, aucun paiement demandé et aucun message envoyé.');
  });

  choose(buttons[0]);
})();
"""


def public_bytes(root: Path, relative: str, limit: int) -> bytes:
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("Preview source missing or unsafe: " + relative)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Preview source escapes source tree")
    if candidate.stat().st_size > limit:
        raise ValueError("Preview source exceeds size limit")
    return candidate.read_bytes()


class PreviewHTML(HTMLParser):
    def __init__(self, root: Path, stylesheet: str, sha: str):
        super().__init__(convert_charrefs=False)
        self.root, self.stylesheet, self.sha = root, stylesheet, sha
        self.out: list[str] = []
        self.skipping_script = False
        self.media_cache: dict[str, str] = {}

    def media(self, value: str) -> str:
        parsed = urlsplit(value)
        relative = parsed.path.lstrip('/')
        if parsed.scheme or parsed.netloc or relative not in MEDIA:
            raise ValueError("Non-allowlisted preview media")
        if relative not in self.media_cache:
            raw = public_bytes(self.root, relative, MAX_MEDIA_BYTES)
            self.media_cache[relative] = 'data:' + MEDIA[relative] + ';base64,' + base64.b64encode(raw).decode('ascii')
        return self.media_cache[relative]

    def handle_decl(self, decl):
        self.out.append('<!' + decl + '>')

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.skipping_script = True
            return
        if self.skipping_script:
            return
        if tag in {'form', 'iframe', 'object', 'embed', 'base'}:
            raise ValueError("Active content is not permitted in the preview")
        values = dict(attrs)
        if tag == 'link':
            if values.get('rel') != 'stylesheet':
                return
            target = urlsplit(values.get('href', ''))
            if target.scheme or target.netloc or target.fragment:
                raise ValueError("Unknown stylesheet")
            if target.path == '/style.css':
                css = self.stylesheet
            elif target.path == '/assets/action-controls.css':
                css = public_bytes(self.root, 'assets/action-controls.css', 64 * 1024).decode('utf-8')
            else:
                raise ValueError("Unknown stylesheet")
            if re.search(r'url\s*\(|@import|</style', css, re.I):
                raise ValueError('External or active stylesheet dependency refused')
            self.out.append('<style>' + css + PREVIEW_CSS + '</style>')
            return
        if tag == 'head':
            self.out.append('<head><meta http-equiv="Content-Security-Policy" content="' + html.escape(CSP, quote=True) + '"><meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer">')
            return
        clean = []
        for name, value in attrs:
            if name.startswith('on') or name in {'srcset', 'ping', 'action', 'formaction', 'target'}:
                continue
            if name in {'src', 'poster'}:
                value = self.media(value or '')
            elif name == 'href' and not str(value or '').startswith('#'):
                value = '#previewInformation'
                clean.append(('data-preview-disabled', 'true'))
            clean.append((name, value))
        rendered = ''.join(' ' + name + ('' if value is None else '="' + html.escape(value, quote=True) + '"') for name, value in clean)
        self.out.append('<' + tag + rendered + '>')
        if tag == 'body':
            self.out.append('<aside class="preview-notice"><strong>DÉMONSTRATION DU SITE — SANS RÉSERVATION RÉELLE</strong>Design et médias du dépôt CheckupAuto. Créneaux fictifs ; aucun accès aux données clients. Version <code>' + self.sha[:12] + '</code>.</aside>')

    def handle_endtag(self, tag):
        if tag == 'script':
            self.skipping_script = False
            return
        if self.skipping_script:
            return
        if tag == 'body':
            self.out.append('<dialog id="previewInformation"><h2>Démonstration CheckupAuto</h2><p id="previewMessage"></p><button type="button" id="previewClose">Fermer</button></dialog><script>' + PREVIEW_JS + '</script>')
        self.out.append('</' + tag + '>')

    def handle_data(self, data):
        if not self.skipping_script:
            self.out.append(data)

    def handle_entityref(self, name):
        if not self.skipping_script:
            self.out.append('&' + name + ';')

    def handle_charref(self, name):
        if not self.skipping_script:
            self.out.append('&#' + name + ';')


def build(root: Path, sha: str) -> bytes:
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('An exact source commit SHA is required')
    source = public_bytes(root, 'index.html', 256 * 1024).decode('utf-8')
    # A real production QR must not be presented as a functioning demo download.
    source, count = re.subn(r'<a class="app-qr-card"\s.*?</a>', '<div class="preview-app-card"><strong>APPLICATION IPHONE</strong><br>Présentation visuelle uniquement.<br>Le téléchargement et les notifications nécessitent l’application publiée et le serveur.</div>', source, flags=re.S)
    if count != 1:
        raise ValueError('Expected application card was not found')
    source, count = re.subn(r'(<div class="booking-intro">.*?<p>).*?</p>', r'\1Parcours interactif simulé. Tous les créneaux ci-dessous sont fictifs ; aucune réservation ni réduction ne sera enregistrée dans Mercure.</p>', source, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Expected booking introduction was not found')
    css = public_bytes(root, 'style.css', 256 * 1024).decode('utf-8')
    if re.search(r'url\s*\(|@import|</style', css, re.I):
        raise ValueError('External or active stylesheet dependency refused')
    parser = PreviewHTML(root, css, sha)
    parser.feed(source)
    parser.close()
    page = ''.join(parser.out).replace('Connexion à Mercure…', 'Démonstration — créneaux fictifs')
    return page.encode('utf-8')


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    args.add_argument('--sha', required=True)
    args.add_argument('--output', type=Path, required=True)
    options = args.parse_args()
    if options.output.exists():
        raise SystemExit('Preview output must be a new directory')
    page = build(options.source, options.sha)
    options.output.mkdir(parents=True)
    (options.output / 'index.html').write_bytes(page)
    evidence = {'sourceSha': options.sha, 'mode': 'isolated-visual-preview', 'sha256': hashlib.sha256(page).hexdigest(), 'bytes': len(page), 'realBookings': False, 'backendIncluded': False, 'networkConnectionsAllowed': False}
    (options.output / 'preview.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
