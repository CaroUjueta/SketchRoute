from django.urls import path
from . import views

urlpatterns = [
    path('<int:pk>/editor/', views.editor_view, name='plan_editor'),
]
