# Responsive rendering validation

The first CSS-only pass was insufficient. Live Chromium mobile rendering reproduced
`clientWidth=375` and `scrollWidth=393` on both staging origins. The hero's negative
horizontal insets widened the mobile layout viewport. Mobile navigation was hidden
without a replacement. A fractional IntersectionObserver threshold also made a tall
reservation section dependent on a visibility ratio it might never reach.

The corrective change bounds the 3D stage to its column, adds a native details/menu
with customer access, keeps reservation controls visible by default, normalizes touch
controls and fluid forms, fixes narrow admin grids, and bounds the cookie dialog's
height in landscape. The GLB poster remains until the first frame is drawn. Only the
exact existing GLB JavaScript module is added to the static allowlist.

## Reproducible checks

Use an isolated Python environment with the project's dependencies. RemoteOps
provisions browser system libraries; the pull-request job never receives generic sudo.

```bash
python3 -m venv .browser-venv
.browser-venv/bin/pip install -r requirements.txt playwright==1.55.0
.browser-venv/bin/python -m playwright install chromium webkit
.browser-venv/bin/python scripts/check-responsive-browser.py --browser chromium
.browser-venv/bin/python scripts/check-responsive-browser.py --browser webkit
```

The browser suite tests 320, 360, 375, 390, 430, 768, 844, 1024, 1440 and 1920 CSS-pixel
widths, including a 844x390 landscape viewport. It loads the real HTML/CSS/JavaScript
and server-rendered templates with synthetic identities and a tall six-day booking
fixture. All network requests are intercepted. No real account, appointment, contact
message, payment or production cookie is created.

Checks cover the document width, mobile layout viewport, overflowing elements,
3D stage bounds, menu access and Escape, JavaScript-disabled navigation, carousel
selection, reservation CTA, long names/e-mails, customer forms, administrator pages,
and the scrollable cookie dialog. Normal-motion mode must not hide the booking form.

The dedicated workflow publishes JSON measurements and screenshots from both engines.
WebKit emulation is not a physical iPhone/Safari validation. After deployment, verify
the live HTML references `responsive-3`, the CSS and scripts return HTTP 200, and repeat
viewport measurements without source overrides. Do not treat a successful local runtime
deploy as proof that the canonical public domain has switched to CyberCheck.

This harness can be invoked from the RemoteOps release checkout without duplicating
its fixtures in the control-plane repository.
