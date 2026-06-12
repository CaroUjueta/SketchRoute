from django.db import models


class ExportedFile(models.Model):
    FILE_TYPES = [
        ('pdf', 'PDF'),
        ('png', 'PNG'),
        ('svg', 'SVG'),
    ]

    plan = models.ForeignKey(
        'plans.Plan',
        on_delete=models.CASCADE,
        related_name='exported_files',
        verbose_name='Plano',
    )
    file_type = models.CharField(
        max_length=10, choices=FILE_TYPES,
        verbose_name='Tipo de archivo',
    )
    file = models.FileField(
        upload_to='exports/',
        verbose_name='Archivo exportado',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Creado el')

    class Meta:
        verbose_name = 'Archivo exportado'
        verbose_name_plural = 'Archivos exportados'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.plan.name}.{self.file_type}'
