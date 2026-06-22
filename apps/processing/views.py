import json
import logging
from pathlib import Path

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse
from django.conf import settings

from apps.plans.models import Plan
from .models import ProcessingJob
from .services.pipeline import ProcessingPipeline
from .services.preprocessing import drawing_legend

logger = logging.getLogger(__name__)


@login_required
def upload_image(request, plan_pk):
    """Sube una imagen de croquis e inicia el pipeline de procesamiento."""
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)

    if request.method == 'POST' and request.FILES.get('image'):
        plan.original_image = request.FILES['image']
        plan.save()

        job, _ = ProcessingJob.objects.get_or_create(plan=plan)
        job.status = 'pending'
        job.save()

        # procesar la imagen
        result = _run_pipeline(plan, job)

        if result['success']:
            messages.success(
                request,
                f'Vectorización completada: {result["walls"]} paredes, '
                f'{result["rooms"]} recintos detectados.',
            )
        else:
            messages.warning(
                request,
                f'Imagen subida pero la vectorización falló: {result["error"]}',
            )

        return redirect('plan_editor', pk=plan.pk)

    return render(request, 'processing/upload.html', {
        'plan': plan,
        'legend': drawing_legend(),
    })


@login_required
def reprocess(request, plan_pk):
    """Re-ejecuta el pipeline sobre un plano ya existente."""
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)

    if not plan.original_image:
        messages.error(request, 'El plano no tiene una imagen de croquis.')
        return redirect('plan_editor', pk=plan.pk)

    job, _ = ProcessingJob.objects.get_or_create(plan=plan)
    result = _run_pipeline(plan, job)

    if result['success']:
        messages.success(
            request,
            f'Re-vectorización completada: {result["walls"]} paredes, '
            f'{result["rooms"]} recintos.',
        )
    else:
        messages.error(request, f'Vectorización falló: {result["error"]}')

    return redirect('plan_editor', pk=plan.pk)


def _run_pipeline(plan, job):
    """Ejecuta el pipeline y actualiza el modelo ProcessingJob."""
    job.status = 'processing'
    job.error_message = ''
    job.save(update_fields=['status', 'error_message'])

    pipeline = ProcessingPipeline()
    image_path = Path(plan.original_image.path)

    result = pipeline.process(image_path)

    if result['success']:
        plan.canvas_data = result['canvas_data']
        plan.is_vectorized = True
        plan.save(update_fields=['canvas_data', 'is_vectorized'])

        job.status = 'completed'
        job.vector_data = result['canvas_data']
        job.save(update_fields=['status', 'vector_data'])
    else:
        job.status = 'failed'
        job.error_message = result['error']
        job.save(update_fields=['status', 'error_message'])

    return result


@login_required
def job_status(request, plan_pk):
    """Endpoint AJAX para consultar estado del procesamiento."""
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)
    try:
        job = plan.processing_job
        return JsonResponse({
            'status': job.status,
            'error': job.error_message,
            'vectorized': plan.is_vectorized,
        })
    except ProcessingJob.DoesNotExist:
        return JsonResponse({'status': 'none', 'vectorized': plan.is_vectorized})
