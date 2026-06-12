from django.db import models
from django.conf import settings


class Plan(models.Model):
    ORIENTATION_CHOICES = [
        ('horizontal', 'Horizontal (carta)'),
        ('vertical', 'Vertical'),
    ]

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='plans',
        verbose_name='Proyecto',
    )
    name = models.CharField(max_length=255, verbose_name='Nombre del plano')
    original_image = models.ImageField(
        upload_to='uploads/',
        blank=True, null=True,
        verbose_name='Croquis original',
    )
    scale = models.FloatField(default=1.0, verbose_name='Escala (px/cm)')
    orientation = models.CharField(
        max_length=20, choices=ORIENTATION_CHOICES,
        default='horizontal', verbose_name='Orientación',
    )
    canvas_data = models.JSONField(
        blank=True, null=True,
        verbose_name='Datos del canvas (Fabric.js)',
    )
    is_vectorized = models.BooleanField(default=False, verbose_name='Vectorizado')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Creado el')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Actualizado el')

    class Meta:
        verbose_name = 'Plano'
        verbose_name_plural = 'Planos'
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.name} — {self.project.name}'
