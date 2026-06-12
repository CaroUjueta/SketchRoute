from django.urls import path
from . import views

urlpatterns = [
    path('calculate/<int:plan_pk>/', views.calculate_routes, name='calculate_routes'),
]
