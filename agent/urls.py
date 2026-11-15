from django.urls import path
from . import views

app_name = "agent"

urlpatterns = [
    path("agent/chat/", views.chat, name="chat"),
    path("agent/voix/", views.voix, name="voix"),
    path("agent/conversations/", views.conversations_liste, name="conversations-liste"),
    path("agent/conversations/<int:pk>/", views.conversation_detail, name="conversation-detail"),
]