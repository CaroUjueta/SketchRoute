from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from apps.plans.models import Plan


@login_required
def calculate_routes(request, plan_pk):
    plan = Plan.objects.get(pk=plan_pk, project__user=request.user)
    return JsonResponse({'status': 'ok', 'message': 'Rutas calculadas (placeholder)'})
