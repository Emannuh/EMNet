from django.contrib import admin
from .models import RadiusNas, RadiusUserGroup


@admin.register(RadiusNas)
class RadiusNasAdmin(admin.ModelAdmin):
    list_display = ["nasname", "shortname", "type", "description"]
    search_fields = ["nasname", "shortname"]


@admin.register(RadiusUserGroup)
class RadiusUserGroupAdmin(admin.ModelAdmin):
    list_display = ["username", "groupname", "priority"]
    search_fields = ["username", "groupname"]
