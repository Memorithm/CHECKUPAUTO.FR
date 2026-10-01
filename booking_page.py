"""Script-free public pages for unavailable checkout, never API downloads."""
import html
import re


def unavailable_html(*, terms_missing=False, phone=""):
    message = (
        "La réservation en ligne n’est pas encore disponible : les conditions "
        "générales de vente doivent être publiées avant de poursuivre."
        if terms_missing else
        "La réservation en ligne est temporairement indisponible. "
        "Aucun rendez-vous n’a été confirmé à cette étape."
    )
    number = re.sub(r"[^+0-9]", "", str(phone or ""))
    contact = (
        '<p><a href="tel:' + html.escape(number, quote=True) + '">'
        'Appeler le centre · ' + html.escape(str(phone)) + '</a></p>'
        if re.fullmatch(r"\+?[0-9]{6,15}", number) else ""
    )
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<title>Réservation indisponible | Checkup Auto</title>'
        '<style>body{font-family:system-ui;margin:0;background:#f5f6f1;color:#17372b}'
        'main{max-width:640px;margin:48px auto;padding:28px;background:#fff;'
        'border:1px solid #dbe1d8;border-radius:24px}p{line-height:1.6}'
        'a{color:#1f5845}h1{font-size:32px}</style></head><body><main>'
        '<h1>Réservation en ligne indisponible</h1><p>' + message + '</p>'
        + contact + '<p><a href="/#reservation">Retour aux créneaux</a></p>'
        '</main></body></html>'
    ).encode("utf-8")