from django.urls import path
from . import views

urlpatterns = [
    path('auto-place/<int:plan_pk>/', views.auto_place_signals, name='auto_place_signals'),
]
