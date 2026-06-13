from django.urls import path
from . import views

urlpatterns = [
    path('create/<int:project_pk>/', views.plan_create, name='plan_create'),
    path('<int:pk>/editor/',         views.editor_view, name='plan_editor'),
    path('<int:pk>/save/',           views.save_canvas, name='plan_save'),
]
