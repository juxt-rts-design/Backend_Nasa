from django.contrib import admin

from .models import ConversationAgent, MessageAgent


class MessageInline(admin.TabularInline):
    model = MessageAgent
    extra = 0
    readonly_fields = ("role", "contenu", "date_envoi")


@admin.register(ConversationAgent)
class ConversationAgentAdmin(admin.ModelAdmin):
    list_display = ("titre", "utilisateur", "date_creation", "date_mise_a_jour")
    list_filter = ("date_creation",)
    search_fields = ("titre",)
    inlines = [MessageInline]


@admin.register(MessageAgent)
class MessageAgentAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "date_envoi")
    list_filter = ("role", "date_envoi")
    search_fields = ("contenu",)