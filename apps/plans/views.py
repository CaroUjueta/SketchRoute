import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.projects.models import Project
from .models import Plan


@login_required
@require_POST
def plan_create(request, project_pk):
    """Crea un plano nuevo (oficio horizontal por defecto) y entra al editor."""
    project = get_object_or_404(Project, pk=project_pk, user=request.user)
    name = (request.POST.get('name') or '').strip() or 'Plano sin título'
    plan = Plan.objects.create(
        project=project,
        name=name,
        orientation='horizontal',  # oficio horizontal por defecto
    )
    return redirect('plan_editor', pk=plan.pk)


@login_required
def editor_view(request, pk):
    plan = get_object_or_404(Plan, pk=pk, project__user=request.user)
    return render(request, 'plans/editor.html', {'plan': plan})


@login_required
@require_POST
def save_canvas(request, pk):
    """Persiste el JSON del canvas (Fabric.js). Llamado por fetch desde el editor.

    Control optimista de conflictos: el cliente manda `last_saved` (el
    updated_at que conoce); si otro guardado ya avanzó ese timestamp,
    respondemos 409 para que el editor avise en vez de pisar el trabajo."""
    plan = get_object_or_404(Plan, pk=pk, project__user=request.user)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    canvas_data = body.get('canvas_data')
    if not isinstance(canvas_data, dict):
        return JsonResponse({'error': 'canvas_data inválido'}, status=400)

    last_saved = body.get('last_saved')
    if last_saved and last_saved != plan.updated_at.isoformat():
        return JsonResponse({'error': 'conflict'}, status=409)

    plan.canvas_data = canvas_data
    plan.save(update_fields=['canvas_data', 'updated_at'])
    return JsonResponse({
        'ok': True,
        'saved_at': plan.updated_at.strftime('%H:%M:%S'),
        'updated_at': plan.updated_at.isoformat(),
    })
