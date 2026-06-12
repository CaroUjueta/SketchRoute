from django.db import models


class EvacuationRoute(models.Model):
    plan = models.ForeignKey(
        'plans.Plan',
        on_delete=models.CASCADE,
        related_name='evacuation_routes',
        verbose_name='Plano',
    )
    name = models.CharField(max_length=255, verbose_name='Nombre de la ruta')
    route_data = models.JSONField(verbose_name='Datos de la ruta (nodos/aristas)')
    total_length = models.FloatField(verbose_name='Longitud total (m)')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Creado el')

    class Meta:
        verbose_name = 'Ruta de evacuación'
        verbose_name_plural = 'Rutas de evacuación'
        ordering = ['total_length']

    def __str__(self):
        return f'{self.name} — {self.total_length:.1f}m'
