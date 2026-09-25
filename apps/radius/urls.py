from django.urls import path
from . import views

app_name = "radius"

urlpatterns = [
    path("", views.NasListView.as_view(), name="index"),
    path("nas/add/", views.NasCreateView.as_view(), name="nas_add"),
    path("nas/<int:pk>/edit/", views.NasUpdateView.as_view(), name="nas_edit"),
    path("nas/<int:pk>/delete/", views.NasDeleteView.as_view(), name="nas_delete"),
]
