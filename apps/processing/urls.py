from django.urls import path
from . import views

urlpatterns = [
    path('upload/<int:plan_pk>/', views.upload_image, name='upload_image'),
]
