from django.db import models


class Signal(models.Model):
    SIGNAL_TYPES = [
        ('extinguisher', 'Extintor'),
        ('exit', 'Salida EXIT'),
        ('first_aid', 'Botiquín'),
        ('alarm', 'Alarma'),
        ('meeting_point', 'Punto de encuentro'),
        ('fire_hose', 'Manguera contra incendios'),
    ]

    plan = models.ForeignKey(
        'plans.Plan',
        on_delete=models.CASCADE,
        related_name='signals',
        verbose_name='Plano',
    )
    signal_type = models.CharField(
        max_length=30, choices=SIGNAL_TYPES,
        verbose_name='Tipo de señal',
    )
    position_x = models.FloatField(verbose_name='Posición X')
    position_y = models.FloatField(verbose_name='Posición Y')
    rotation = models.FloatField(default=0, verbose_name='Rotación (°)')
    auto_placed = models.BooleanField(default=False, verbose_name='Colocada automáticamente')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Señal'
        verbose_name_plural = 'Señales'

    def __str__(self):
        return f'{self.get_signal_type_display()} en ({self.position_x}, {self.position_y})'
