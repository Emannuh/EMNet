"""
RADIUS domain models.
Mirrors FreeRADIUS SQL tables so Django can manage NAS entries
and RADIUS profiles from the admin UI (per-tenant schema).
"""
from django.db import models


class RadiusNas(models.Model):
    """
    Network Access Server (router/AP) registered with FreeRADIUS.
    Maps to the 'nas' table used by FreeRADIUS SQL module.
    """
    nasname = models.CharField(max_length=128, unique=True)   # IP or hostname
    shortname = models.CharField(max_length=32, blank=True)
    type = models.CharField(max_length=30, default="other")
    ports = models.IntegerField(null=True, blank=True)
    secret = models.CharField(max_length=60)
    server = models.CharField(max_length=64, blank=True)
    community = models.CharField(max_length=50, blank=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "nas"
        verbose_name = "NAS"
        verbose_name_plural = "NAS Devices"

    def __str__(self):
        return f"{self.nasname} ({self.shortname})"


class RadiusUserGroup(models.Model):
    """
    Maps a RADIUS username to a group.
    Mirrors FreeRADIUS radusergroup table.
    """
    username = models.CharField(max_length=64)
    groupname = models.CharField(max_length=64)
    priority = models.IntegerField(default=1)

    class Meta:
        db_table = "radusergroup"
        unique_together = [("username", "groupname")]

    def __str__(self):
        return f"{self.username} → {self.groupname}"
