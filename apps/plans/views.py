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
    """Persiste el JSON del canvas (Fabric.js). Llamado por fetch desde el editor."""
    plan = get_object_or_404(Plan, pk=pk, project__user=request.user)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    plan.canvas_data = body.get('canvas_data')
    plan.save(update_fields=['canvas_data', 'updated_at'])
    return JsonResponse({'ok': True, 'saved_at': plan.updated_at.strftime('%H:%M:%S')})
