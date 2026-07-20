from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='plan_list'), name='home'),
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('plans/', include('apps.plans.urls')),
    path('processing/', include('apps.processing.urls')),
    path('routing/', include('apps.routing.urls')),
    path('signaling/', include('apps.signaling.urls')),
    path('export/', include('apps.export.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
