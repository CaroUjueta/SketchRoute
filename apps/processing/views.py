from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.plans.models import Plan
from .models import ProcessingJob


@login_required
def upload_image(request, plan_pk):
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)
    if request.method == 'POST' and request.FILES.get('image'):
        plan.original_image = request.FILES['image']
        plan.save()
        ProcessingJob.objects.get_or_create(plan=plan)
        messages.success(request, 'Imagen subida correctamente. Iniciando procesamiento...')
        return redirect('plan_editor', pk=plan.pk)
    return render(request, 'processing/upload.html', {'plan': plan})
