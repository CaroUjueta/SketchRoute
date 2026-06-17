from django.urls import path
from . import views

urlpatterns = [
    path('upload/<int:plan_pk>/', views.upload_image, name='upload_image'),
    path('reprocess/<int:plan_pk>/', views.reprocess, name='reprocess_plan'),
    path('status/<int:plan_pk>/', views.job_status, name='processing_status'),
]
