from rest_framework import serializers

from .models import ConversationAgent, MessageAgent


class MessageAgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageAgent
        fields = ["id", "role", "contenu", "date_envoi"]


class ConversationAgentSerializer(serializers.ModelSerializer):
    dernier_message = serializers.SerializerMethodField()

    class Meta:
        model = ConversationAgent
        fields = ["id", "titre", "date_creation", "date_mise_a_jour", "dernier_message"]

    def get_dernier_message(self, obj):
        # list() utilise le cache prefetch — .last() refaisait une requête SQL
        messages = list(obj.messages.all())
        return messages[-1].contenu[:100] if messages else None