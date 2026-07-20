from django.urls import path
from . import views

urlpatterns = [
    path('',              views.plan_list,   name='plan_list'),
    path('create/',       views.plan_create, name='plan_create'),
    path('<int:pk>/editor/', views.editor_view, name='plan_editor'),
    path('<int:pk>/save/',   views.save_canvas, name='plan_save'),
    path('<int:pk>/delete/', views.plan_delete, name='plan_delete'),
]
