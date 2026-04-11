from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/',         admin.site.urls),
    path('accounts/',      include('accounts.urls')),
    path('chat/',          include('chat.urls')),
    path('manifest.json',  TemplateView.as_view(
                               template_name='manifest.json',
                               content_type='application/manifest+json'
                           ), name='manifest'),
    path('sw.js',          TemplateView.as_view(
                               template_name='sw.js',
                               content_type='application/javascript'
                           ), name='sw'),
    path('',               include('chat.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)