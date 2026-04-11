from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
import random
from .models import UserProfile

AVATAR_COLORS = [
    '#6C63FF', '#FF6584', '#43B89C', '#F9A825',
    '#E91E63', '#2196F3', '#FF5722', '#9C27B0',
]

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(
            user=instance,
            avatar_color=random.choice(AVATAR_COLORS)
        )