from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('',                            views.index,                name='index'),
    path('<int:conv_id>/',              views.conversation_view,    name='conversation'),
    path('new/',                        views.new_conversation,     name='new_conversation'),
    path('send/',                       views.send_message,         name='send_message'),
    path('api/<int:conv_id>/delete/',   views.delete_conversation,  name='delete_conversation'),
    path('api/<int:conv_id>/rename/',   views.rename_conversation,  name='rename_conversation'),
    path('api/<int:conv_id>/pin/',      views.pin_conversation,     name='pin_conversation'),
    path('api/<int:conv_id>/clear/',    views.clear_conversation,   name='clear_conversation'),
]