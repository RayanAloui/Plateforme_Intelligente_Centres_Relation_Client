"""Garde-fou : chaque nombre de la reponse doit provenir de la fiche (ou de la question)."""
import re

NUMBER = re.compile(r"(?<![\w,.])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?(?![\d])|(?<![\w])\d+(?:[.,]\d+)?")
SMALL_INTEGERS = set(range(0, 11))         # "deux agents", "1 alerte"... sans valeur informative


def numbers(text: str) -> list[float]:
    out = []
    for raw in NUMBER.findall(text):
        clean = re.sub(r"[ \u00a0\u202f]", "", raw).replace(",", ".")
        try:
            out.append(float(clean))
        except ValueError:
            pass
    return out


def verify(answer: str, sheet: str, question: str = "") -> dict:
    """Renvoie les nombres de la reponse absents de la fiche (a l'arrondi pres)."""
    allowed = set(numbers(sheet)) | set(numbers(question))

    def known(x: float) -> bool:
        if x in SMALL_INTEGERS:
            return True
        return any(abs(x - a) <= max(0.5, 0.005 * abs(a)) for a in allowed)

    used = numbers(answer)
    unknown = [f"{x:,.10g}".replace(",", " ").replace(".", ",") for x in sorted({x for x in used if not known(x)})]
    return {"verified": not unknown, "numbers": len(used), "unknown": unknown}
