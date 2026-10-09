"""Garde-fou des reponses de l'assistant.

Trois controles :
  1. provenance : chaque nombre de la reponse doit figurer dans la fiche (ou la question) ;
  2. unite     : un nombre doit garder l'unite qu'il a dans la fiche (67 heures ne deviennent pas 67 agents) ;
  3. calcul    : l'assistant n'a pas le droit de calculer (pas de « 586 - 653 = ... »).
Le contrôle 1 dit d'ou vient un chiffre ; les controles 2 et 3 attrapent les mauvais usages d'un chiffre exact.
"""
import re

NUMBER = re.compile(r"(?<![\w,.])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?(?![\d])|(?<![\w])\d+(?:[.,]\d+)?")
SMALL_INTEGERS = set(range(0, 11))         # "deux agents", "1 alerte"... sans valeur informative
UNITS = {"agent": "agents", "agents": "agents", "heure": "heures", "heures": "heures", "h": "heures",
         "appel": "appels", "appels": "appels", "etp": "ETP", "€": "euros", "eur": "euros", "euros": "euros",
         "%": "pourcents"}
ARITHMETIC = re.compile(r"\d\s*[-+×x*/]\s*\d[\d\s,.]*=|=\s*-?\d")


def _to_float(raw: str) -> float | None:
    try:
        return float(re.sub(r"[ \u00a0\u202f]", "", raw).replace(",", "."))
    except ValueError:
        return None


def numbers(text: str) -> list[float]:
    return [x for x in (_to_float(r) for r in NUMBER.findall(text)) if x is not None]


def numbers_with_units(text: str) -> list[tuple[float, str | None]]:
    """Chaque nombre et l'unite qui le suit immediatement (si elle est reconnue)."""
    out = []
    for m in NUMBER.finditer(text):
        value = _to_float(m.group())
        if value is None:
            continue
        following = re.match(r"\s*(€|%|[A-Za-zÀ-ÿ]+)", text[m.end():m.end() + 12])
        unit = UNITS.get(following.group(1).lower()) if following else None
        out.append((value, unit))
    return out


def _close(x: float, a: float) -> bool:
    return abs(x - a) <= max(0.5, 0.005 * abs(a))


def verify(answer: str, sheet: str, question: str = "") -> dict:
    allowed = set(numbers(sheet)) | set(numbers(question))
    used = numbers(answer)
    unknown = sorted({x for x in used if x not in SMALL_INTEGERS and not any(_close(x, a) for a in allowed)})

    issues = []
    sheet_units = numbers_with_units(sheet)
    for value, unit in numbers_with_units(answer):
        if unit is None or value in SMALL_INTEGERS:
            continue
        known = {u for v, u in sheet_units if u and _close(value, v)}
        if known and unit not in known:
            issues.append(f"{fmt(value)} {unit} (dans les données : {fmt(value)} {' ou '.join(sorted(known))})")
    if ARITHMETIC.search(answer):
        issues.append("calcul effectué par le modèle")
    issues = list(dict.fromkeys(issues))
    return {"verified": not unknown and not issues, "numbers": len(used),
            "unknown": [fmt(x) for x in unknown], "issues": issues}


def fmt(x: float) -> str:
    return f"{x:,.10g}".replace(",", " ").replace(".", ",")
