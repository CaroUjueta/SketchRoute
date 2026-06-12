from django.db import models


class ProcessingJob(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('processing', 'Procesando'),
        ('completed', 'Completado'),
        ('failed', 'Error'),
    ]

    plan = models.OneToOneField(
        'plans.Plan',
        on_delete=models.CASCADE,
        related_name='processing_job',
        verbose_name='Plano',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='pending', verbose_name='Estado',
    )
    processed_image = models.ImageField(
        upload_to='processed/',
        blank=True, null=True,
        verbose_name='Imagen procesada',
    )
    vector_data = models.JSONField(
        blank=True, null=True,
        verbose_name='Datos vectorizados',
    )
    error_message = models.TextField(blank=True, verbose_name='Mensaje de error')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Trabajo de procesamiento'
        verbose_name_plural = 'Trabajos de procesamiento'

    def __str__(self):
        return f'Processing #{self.pk} — {self.plan.name}'
