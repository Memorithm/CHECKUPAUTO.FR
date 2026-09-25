"""Deterministic first-pass advisor for French contrôle technique findings.

The report's regulatory severity is authoritative. This module never upgrades or
downgrades a CT defect. It adds maintenance context and prevention advice only.
"""
from __future__ import annotations

import re
import unicodedata

ADVISOR_VERSION = "ct-advisor-rules-v1"


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


_RULES = (
    {
        "id": "tyre-irregular-wear",
        "patterns": ("pneumatique", "usure irreguliere"),
        "title": "Usure irrégulière des pneumatiques",
        "explanation": (
            "Une usure irrégulière traduit souvent un écart de pression, de géométrie "
            "ou un jeu/usure dans les liaisons au sol. Le pneu peut encore être classé "
            "mineur aujourd’hui tout en se dégradant rapidement."
        ),
        "prevention": (
            "Contrôler la pression à froid au moins une fois par mois et avant un long trajet; "
            "faire contrôler géométrie/parallélisme et suspension si l’usure revient; surveiller "
            "la profondeur et l’état des deux flancs."
        ),
    },
    {
        "id": "tyre-pressure",
        "patterns": ("pneumatique", "pression"),
        "title": "Pression des pneumatiques",
        "explanation": (
            "Une pression incorrecte augmente l’échauffement et l’usure, dégrade le freinage "
            "et peut transformer un défaut simple en détérioration du pneu."
        ),
        "prevention": (
            "Régler la pression à froid selon l’étiquette constructeur, contrôler les quatre pneus "
            "chaque mois et rechercher une fuite si une roue perd régulièrement de la pression."
        ),
    },
    {
        "id": "brake-wear",
        "patterns": ("frein", "plaquette", "disque"),
        "title": "Freinage et pièces d’usure",
        "explanation": (
            "Une usure prononcée de plaquettes ou de disques réduit la marge avant d’atteindre "
            "les limites de service et peut dégrader disque, étrier ou équilibre de freinage."
        ),
        "prevention": (
            "Faire mesurer l’épaisseur des plaquettes et disques lors de l’entretien, contrôler "
            "les deux côtés d’un même essieu et traiter rapidement bruit, vibration ou tirage au freinage."
        ),
    },
    {
        "id": "suspension-steering",
        "patterns": ("amortisseur", "rotule", "silentbloc", "suspension", "direction"),
        "title": "Liaisons au sol et direction",
        "explanation": (
            "Un jeu ou une usure de suspension/direction peut s’aggraver progressivement et accélérer "
            "l’usure des pneumatiques tout en diminuant la stabilité du véhicule."
        ),
        "prevention": (
            "Faire contrôler les jeux, soufflets, fixations et amortisseurs lors des révisions; "
            "faire vérifier la géométrie après remplacement d’un élément de liaison au sol."
        ),
    },
    {
        "id": "lighting",
        "patterns": ("feu", "eclairage", "projecteur", "clignotant"),
        "title": "Éclairage et signalisation",
        "explanation": (
            "Les défauts d’éclairage sont souvent simples à corriger mais peuvent devenir bloquants "
            "si plusieurs fonctions cessent de fonctionner ou si le réglage se dégrade."
        ),
        "prevention": (
            "Tester régulièrement feux de croisement, stop, clignotants et éclairage de plaque; "
            "faire régler les projecteurs après remplacement ou choc."
        ),
    },
    {
        "id": "emissions",
        "patterns": ("opacite", "emission", "pollution", "co ", "lambda"),
        "title": "Émissions et dépollution",
        "explanation": (
            "Une valeur proche des limites ou une anomalie de dépollution peut évoluer avec l’encrassement, "
            "l’allumage, l’injection ou une fuite et conduire à un résultat défavorable ultérieur."
        ),
        "prevention": (
            "Respecter l’entretien moteur, remplacer les consommables aux échéances constructeur et faire "
            "diagnostiquer voyant moteur, fumée anormale ou hausse de consommation avant le prochain contrôle."
        ),
    },
    {
        "id": "windscreen",
        "patterns": ("pare-brise", "pare brise", "visibilite"),
        "title": "Visibilité et vitrage",
        "explanation": (
            "Un impact ou une dégradation dans la zone de vision peut s’étendre et devenir plus pénalisant "
            "au prochain contrôle."
        ),
        "prevention": (
            "Faire réparer rapidement les impacts réparables, remplacer les balais usés et maintenir "
            "pare-brise, lave-glace et désembuage en bon état."
        ),
    },
)


def _matches(rule: dict, text: str) -> bool:
    folded = _fold(text)
    patterns = tuple(rule["patterns"])
    if rule["id"] in {"tyre-irregular-wear", "tyre-pressure"}:
        return all(p in folded for p in patterns)
    return any(p in folded for p in patterns)


def _severity_context(severity: str) -> str:
    value = _fold(severity)
    if value == "critique":
        return (
            "Le rapport classe ce point critique. La priorité est de respecter les restrictions "
            "et délais réglementaires du procès-verbal et de faire contrôler le véhicule sans attendre."
        )
    if value == "majeure":
        return (
            "Le rapport classe ce point majeur. Une contre-visite est normalement associée à ce niveau; "
            "la réparation doit suivre le délai indiqué sur le procès-verbal."
        )
    if value == "mineure":
        return (
            "Le rapport classe ce point mineur aujourd’hui. Cela ne garantit pas qu’il restera mineur "
            "au prochain contrôle si l’usure ou le défaut progresse."
        )
    return (
        "La gravité réglementaire doit être lue sur le procès-verbal; l’agent ne la déduit pas "
        "et ne la modifie pas."
    )


def advise(defects: list[dict]) -> list[dict]:
    result = []
    for defect in defects:
        description = str(defect.get("description") or "")
        severity = str(defect.get("severity") or "non classée")
        matched = [rule for rule in _RULES if _matches(rule, description)]
        if not matched:
            result.append({
                "code": str(defect.get("code") or ""),
                "severity": severity,
                "title": "Point à surveiller",
                "explanation": (
                    "Ce défaut est repris tel qu’indiqué sur le rapport. Une inspection ciblée permet "
                    "d’établir son origine et son évolution avant le prochain contrôle."
                ),
                "severityContext": _severity_context(severity),
                "prevention": (
                    "Faire contrôler le point lors du prochain entretien et conserver les mesures ou "
                    "factures permettant de suivre son évolution."
                ),
                "ruleId": "generic",
            })
            continue
        # A defect can mention several systems; keep all distinct recommendations.
        for rule in matched:
            result.append({
                "code": str(defect.get("code") or ""),
                "severity": severity,
                "title": rule["title"],
                "explanation": rule["explanation"],
                "severityContext": _severity_context(severity),
                "prevention": rule["prevention"],
                "ruleId": rule["id"],
            })
    return result


def summary(defects: list[dict]) -> str:
    counts = {"critique": 0, "majeure": 0, "mineure": 0, "non classée": 0}
    for defect in defects:
        severity = _fold(str(defect.get("severity") or ""))
        key = severity if severity in {"critique", "majeure", "mineure"} else "non classée"
        counts[key] += 1
    total = len(defects)
    if total == 0:
        return "Aucune défaillance structurée n’a été détectée dans le texte extrait."
    return (
        f"{total} défaillance(s) structurée(s) : "
        f"{counts['critique']} critique(s), {counts['majeure']} majeure(s), "
        f"{counts['mineure']} mineure(s), {counts['non classée']} non classée(s)."
    )
