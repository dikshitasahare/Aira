from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    AVATAR_COLORS = [
        '#6C63FF', '#FF6584', '#43B89C', '#F9A825',
        '#E91E63', '#2196F3', '#FF5722', '#9C27B0',
    ]

    user         = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar_color = models.CharField(max_length=7, default='#6C63FF')
    bio          = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def get_initials(self):
        name = self.user.get_full_name()
        if name:
            parts = name.split()
            return ''.join(p[0].upper() for p in parts[:2])
        return self.user.username[:2].upper()