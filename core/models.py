from django.db import models


class Division(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=8, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

