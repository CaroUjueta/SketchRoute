from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from apps.plans.models import Plan


@login_required
def auto_place_signals(request, plan_pk):
    """La señalización automática NTC (extintores por cobertura y señales de
    evacuación) se ejecuta en el editor del lado del cliente —ver
    SR.autoSignal() en static/js/canvas.js—, donde ya viven la grilla de
    ruteo y el sistema de iconos. Este endpoint queda como punto de
    integración futuro (p. ej. persistir las señales en el modelo Signal)."""
    plan = Plan.objects.get(pk=plan_pk, user=request.user)
    return JsonResponse({
        'status': 'ok',
        'plan': plan.pk,
        'message': 'La señalización automática se realiza en el editor (SR.autoSignal()).',
    })
