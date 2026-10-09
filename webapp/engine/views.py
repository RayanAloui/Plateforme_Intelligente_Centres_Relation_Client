"""Administration des parametres de la plateforme (ref.cost_parameters)."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Role
from accounts.roles import role_required
from engine.catalog import CATALOG, CATEGORIES, cross_errors, is_percent
from engine.models import Parameter, ParameterChange


def parameter_rows() -> dict[str, list[dict]]:
    current = {p.param_name: p for p in Parameter.objects.all()}
    last = {}
    for change in ParameterChange.objects.select_related("changed_by"):
        last.setdefault(change.param_name, change)
    groups = {c: [] for c in CATEGORIES}
    for name, spec in CATALOG.items():
        value = float(current[name].value) if name in current else spec.default
        pct = is_percent(name)
        groups[spec.category].append({
            "name": name, "spec": spec, "percent": pct, "value": round(100 * value, 2) if pct else value,
            "minimum": 100 * spec.minimum if pct else spec.minimum,
            "maximum": 100 * spec.maximum if pct else spec.maximum,
            "unit": "%" if pct else spec.unit, "last": last.get(name),
            "modified": abs(value - spec.default) > 1e-9,
        })
    return groups


@role_required(Role.ADMINISTRATEUR)
def parameters_page(request, errors=None):
    return render(request, "administration/parameters.html", {
        "page_title": "Paramètres", "groups": parameter_rows(), "errors": errors or [],
        "history": ParameterChange.objects.select_related("changed_by")[:15]})


@require_POST
@role_required(Role.ADMINISTRATEUR)
def parameters_save(request):
    """Valide toutes les valeurs (bornes, regles croisees), puis enregistre les changements et leur historique."""
    current = {p.param_name: p for p in Parameter.objects.all()}
    values, errors = {}, []
    for name, spec in CATALOG.items():
        raw = request.POST.get(name, "").replace(",", ".").strip()
        try:
            value = float(Decimal(raw))
        except (InvalidOperation, ValueError):
            errors.append(f"{spec.label} : valeur invalide.")
            continue
        value = value / 100 if is_percent(name) else value
        if not spec.minimum <= value <= spec.maximum:
            errors.append(f"{spec.label} : doit être compris entre {spec.minimum:g} et {spec.maximum:g}"
                          f"{' (en proportion)' if is_percent(name) else ''}.")
        values[name] = value
    if not errors:
        errors = cross_errors(values)
    if errors:
        return parameters_page(request, errors=errors)

    comment = request.POST.get("comment", "").strip()[:200]
    changed = []
    with transaction.atomic():
        for name, value in values.items():
            old = float(current[name].value) if name in current else None
            if old is not None and abs(old - value) < 1e-9:
                continue
            Parameter.objects.update_or_create(param_name=name, defaults={
                "value": Decimal(str(round(value, 4))), "unit": CATALOG[name].unit,
                "source": f"Modifié par {request.user.display_name}"})
            ParameterChange.objects.create(param_name=name, old_value=old, new_value=Decimal(str(round(value, 4))),
                                           changed_by=request.user, comment=comment)
            changed.append(CATALOG[name].label)
    if changed:
        messages.success(request, f"{len(changed)} paramètre(s) mis à jour : {', '.join(changed)}. "
                                  "Ils s'appliquent au prochain calcul ; replanifiez demain pour les appliquer tout de suite.")
    else:
        messages.info(request, "Aucune valeur modifiée.")
    return redirect("settings")
