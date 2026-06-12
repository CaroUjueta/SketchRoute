from django.urls import path
from . import views

urlpatterns = [
    path('<int:plan_pk>/', views.export_options, name='export_options'),
]
