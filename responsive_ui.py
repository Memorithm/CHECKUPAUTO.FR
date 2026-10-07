"""Shared responsive rules for server-rendered customer pages."""

FORM_RESPONSIVE_CSS = """
/* Shared responsive forms: controls and long account identifiers stay in their card. */
:where(main,.shell,.card,.hero,.grid,.panel,.profile,.feedback-card,.report,form,label,.actions,.top-actions) { min-width:0; }
body { overflow-wrap:anywhere; }
input:not([type=checkbox]):not([type=radio]), select, textarea { min-width:0; max-width:100%; width:100%; box-sizing:border-box; font-size:16px; }
button,.sso,.cta { min-height:44px; }
.top,.top-actions,.actions,.report-item { gap:12px; flex-wrap:wrap; }
:focus-visible { outline:3px solid #1f5443; outline-offset:3px; }
@media(max-width:520px) {
 .card,.hero,.panel,.profile,.feedback-card { padding:20px; }
 .card h1,.hero h1 { font-size:clamp(32px,10vw,46px); line-height:1.08; }
 .report { padding:12px; }
 .report-controls { align-items:stretch; }
 .report-controls>* { width:100%; }
 .review-star { min-width:44px; min-height:44px; }
 .consent { min-height:44px; }
 .consent input { flex:0 0 auto; width:20px; height:20px; }
}
"""
