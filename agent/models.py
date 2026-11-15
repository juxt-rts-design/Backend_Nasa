from django.db import models
from django.conf import settings


class ConversationAgent(models.Model):
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="conversations",
    )
    titre = models.CharField(max_length=200, default="Nouvelle conversation")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_mise_a_jour = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversation_agent"
        verbose_name = "Conversation IA"
        verbose_name_plural = "Conversations IA"
        ordering = ["-date_mise_a_jour"]

    def __str__(self):
        return f"{self.titre} ({self.date_creation:%d/%m/%Y})"


class MessageAgent(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Utilisateur"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(ConversationAgent, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    contenu = models.TextField()
    date_envoi = models.DateTimeField(auto_now_add=True, verbose_name="date d'envoi")

    class Meta:
        db_table = "message_agent"
        verbose_name = "Message IA"
        verbose_name_plural = "Messages IA"
        ordering = ["date_envoi"]

    def __str__(self):
        return f"[{self.role}] {self.contenu[:50]}"