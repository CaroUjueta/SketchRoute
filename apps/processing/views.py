import json
import logging
import threading
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse

from apps.plans.models import Plan
from .models import ProcessingJob
from .services.pipeline import ProcessingPipeline
from .services.preprocessing import drawing_legend
from .services.overlay import render_canvas_preview_png

logger = logging.getLogger(__name__)

SENSITIVITY_CHOICES = ('alta', 'media', 'baja')
SENSITIVITY_LABELS = [
    ('alta', 'Alta (detecta más, tolera trazos tenues)'),
    ('media', 'Media (recomendada)'),
    ('baja', 'Baja (más estricta, menos ruido)'),
]


def _clean_sensitivity(value):
    return value if value in SENSITIVITY_CHOICES else 'media'


@login_required
def upload_image(request, plan_pk):
    """Sube una imagen de croquis e inicia el pipeline en segundo plano."""
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)

    if request.method == 'POST' and request.FILES.get('image'):
        plan.original_image = request.FILES['image']
        plan.save()

        sensitivity = _clean_sensitivity(request.POST.get('sensitivity'))

        job, _ = ProcessingJob.objects.get_or_create(plan=plan)
        job.status = 'pending'
        job.error_message = ''
        job.vector_data = {'sensitivity': sensitivity}
        job.save()

        thread = threading.Thread(
            target=_run_pipeline_threaded,
            args=(plan.pk, job.pk, sensitivity),
            daemon=True,
        )
        thread.start()

        return redirect('processing_progress', plan_pk=plan.pk)

    return render(request, 'processing/upload.html', {
        'plan': plan,
        'legend': drawing_legend(),
        'sensitivity_labels': SENSITIVITY_LABELS,
    })


@login_required
def reprocess(request, plan_pk):
    """Re-ejecuta el pipeline sobre un plano ya existente, en segundo plano."""
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)

    if not plan.original_image:
        messages.error(request, 'El plano no tiene una imagen de croquis.')
        return redirect('plan_editor', pk=plan.pk)

    job, _ = ProcessingJob.objects.get_or_create(plan=plan)
    # reutiliza la última sensibilidad elegida; se puede forzar con ?sensitivity=
    prev = (job.vector_data or {}).get('sensitivity', 'media')
    sensitivity = _clean_sensitivity(request.GET.get('sensitivity', prev))

    job.status = 'pending'
    job.error_message = ''
    job.vector_data = {'sensitivity': sensitivity}
    job.save()

    thread = threading.Thread(
        target=_run_pipeline_threaded,
        args=(plan.pk, job.pk, sensitivity),
        daemon=True,
    )
    thread.start()

    return redirect('processing_progress', plan_pk=plan.pk)


@login_required
def progress_view(request, plan_pk):
    """Pantalla de progreso: hace polling a job_status hasta terminar."""
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)
    return render(request, 'processing/progress.html', {'plan': plan})


def _run_pipeline_threaded(plan_id, job_id, sensitivity):
    """Wrapper para correr en un hilo aparte: cierra conexiones heredadas del
    proceso padre al empezar (Django no comparte conexiones de DB entre
    hilos con seguridad) y de nuevo al terminar, para no dejarlas colgadas."""
    close_old_connections()
    try:
        plan = Plan.objects.get(pk=plan_id)
        job = ProcessingJob.objects.get(pk=job_id)
        _run_pipeline(plan, job, sensitivity)
    except Exception:
        logger.exception('Error en el hilo de procesamiento (plan_id=%s)', plan_id)
    finally:
        close_old_connections()


def _run_pipeline(plan, job, sensitivity='media'):
    """Ejecuta el pipeline y actualiza el modelo ProcessingJob."""
    job.status = 'processing'
    job.error_message = ''
    job.save(update_fields=['status', 'error_message'])

    pipeline = ProcessingPipeline(config={'sensitivity': sensitivity})
    image_path = Path(plan.original_image.path)

    result = pipeline.process(image_path)

    if result['success']:
        plan.canvas_data = result['canvas_data']
        plan.is_vectorized = True
        plan.save(update_fields=['canvas_data', 'is_vectorized'])

        counts = {
            'paredes': result['walls'],
            'puertas': result['doors'],
            'muebles': result['furniture'],
            'recintos': result['rooms'],
        }
        job.status = 'completed'
        job.vector_data = {
            'sensitivity': sensitivity,
            'counts': counts,
            'debug': _json_safe(result.get('debug', {})),
        }
        try:
            png_bytes = render_canvas_preview_png(result['canvas_data'])
            job.processed_image.save(
                f'overlay_{plan.pk}.png', ContentFile(png_bytes), save=False,
            )
        except Exception:
            logger.exception('No se pudo generar el overlay de verificación')
        job.save()
    else:
        job.status = 'failed'
        job.error_message = result['error']
        job.vector_data = {'sensitivity': sensitivity}
        job.save()

    return result


def _json_safe(obj):
    """El dict `debug` del pipeline puede traer tipos no serializables
    (tuplas de numpy, etc.) — lo pasamos por json dumps/loads con un
    conversor best-effort para poder guardarlo en el JSONField."""
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {}


@login_required
def job_status(request, plan_pk):
    """Endpoint AJAX para la pantalla de progreso: estado + conteos/overlay
    cuando termina."""
    plan = get_object_or_404(Plan, pk=plan_pk, project__user=request.user)
    try:
        job = plan.processing_job
    except ProcessingJob.DoesNotExist:
        return JsonResponse({'status': 'none', 'vectorized': plan.is_vectorized})

    data = {
        'status': job.status,
        'error': job.error_message,
        'vectorized': plan.is_vectorized,
    }
    vd = job.vector_data or {}
    if job.status == 'completed':
        data['counts'] = vd.get('counts', {})
        if job.processed_image:
            data['overlay_url'] = job.processed_image.url
    return JsonResponse(data)
