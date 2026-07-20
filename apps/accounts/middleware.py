from django.contrib.auth import get_user_model, login

TECHNICAL_USERNAME = 'systefarma'


class AutoLoginMiddleware:
    """Sin login real: cada request queda autenticada como un único
    usuario técnico compartido. Los proyectos/planos quedan bajo esa
    cuenta — evita tocar LoginRequiredMixin/login_required en el resto
    de la app, que sigue funcionando igual."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            User = get_user_model()
            user, _ = User.objects.get_or_create(
                username=TECHNICAL_USERNAME,
                defaults={'is_staff': True},
            )
            login(request, user)
        return self.get_response(request)
