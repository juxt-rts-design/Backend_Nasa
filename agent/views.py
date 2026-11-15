import json
import logging
import re

import anthropic
from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.decorators import (
    api_view, permission_classes, throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from firewatch.utils import paginer
from .gemini import CLIPS, TECH, Indisponible, analyser_local, comprendre
from .models import ConversationAgent, MessageAgent
from .parole import repondre
from .serializers import ConversationAgentSerializer, MessageAgentSerializer
from .voix import piper_pret, synth_voix

logger = logging.getLogger(__name__)


# ── Throttle ─────────────────────────────────────────────────────

class ChatThrottle(SimpleRateThrottle):
    """Limite le débit du chat — lit le taux depuis DEFAULT_THROTTLE_RATES."""
    scope = "chat"


class VoixThrottle(SimpleRateThrottle):
    scope = "voix"

    def get_cache_key(self, request, view):
        ident = request.user.pk if request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


# ── Prompt système ───────────────────────────────────────────────

SYSTEM_PROMPT = (
    "Tu es l'assistant IA de FireWatch, calendrier d'activité de brûlage "
    "construit sur les points chauds NASA FIRMS (MODIS et VIIRS). "
    "Défi Space Apps 2026 : Harmonization of MODIS and VIIRS Hot Spots. "
    "Un point chaud est une anomalie thermique (brûlage de végétation, "
    "feu agricole, parfois volcan ou torchère), pas forcément un incendie "
    "de forêt. Tu es spécialisé dans :\n"
    "- L'explication des détections (brightness, FRP, confidence)\n"
    "- L'harmonisation des capteurs MODIS et VIIRS, pour que l'origine "
    "du capteur n'empêche plus de comparer les années\n"
    "- L'interprétation des anomalies thermiques et des z-scores "
    "par rapport à la médiane historique\n"
    "- Le calendrier d'activité de brûlage d'une zone choisie\n"
    "Réponds toujours en français, de manière concise et scientifiquement précise."
)

MAX_HISTORIQUE_MESSAGES = 21


# ── Vues ─────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def chat(request):
    """Envoie un message à l'agent IA et retourne la réponse."""
    contenu = request.data.get("message", "").strip()
    conversation_id = request.data.get("conversation_id")

    if not contenu:
        return Response(
            {"erreur": "Le message est vide."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not settings.ANTHROPIC_API_KEY:
        return Response(
            {"erreur": "Service IA non configuré."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Récupérer la conversation existante (si fournie)
    conversation = None
    if conversation_id:
        try:
            conversation = ConversationAgent.objects.get(
                id=conversation_id, utilisateur=request.user,
            )
        except ConversationAgent.DoesNotExist:
            return Response(
                {"erreur": "Conversation introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )

    # Construire l'historique
    historique = []
    if conversation:
        messages_qs = conversation.messages.order_by("date_envoi")
        total = messages_qs.count()
        if total > MAX_HISTORIQUE_MESSAGES - 1:
            messages_qs = messages_qs[total - (MAX_HISTORIQUE_MESSAGES - 1):]

        historique = [
            {"role": m.role, "content": m.contenu}
            for m in messages_qs
        ]

        # Garantir que le premier message est "user" (exigence API Anthropic)
        while historique and historique[0]["role"] != MessageAgent.Role.USER:
            historique.pop(0)

    # Ajouter le nouveau message
    historique.append({"role": "user", "content": contenu})

    # Appel à l'API Anthropic
    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=historique,
        )
        reponse_texte = "".join(
            block.text for block in response.content if block.type == "text"
        )
    except anthropic.AuthenticationError:
        logger.error("Clé API Anthropic invalide")
        return Response(
            {"erreur": "Service IA indisponible."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except anthropic.RateLimitError:
        logger.warning("Rate limit API Anthropic atteint")
        return Response(
            {"erreur": "Service IA surchargé. Réessayez plus tard."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except anthropic.APIConnectionError:
        logger.error("Connexion API Anthropic impossible")
        return Response(
            {"erreur": "Service IA injoignable."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except anthropic.APIError as e:
        logger.error("Erreur API Anthropic : %s", e.message)
        return Response(
            {"erreur": "Erreur du service IA."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Tout sauvegarder dans une transaction atomique, après succès API
    with transaction.atomic():
        if not conversation:
            conversation = ConversationAgent.objects.create(
                utilisateur=request.user,
                titre=contenu[:100],
            )

        MessageAgent.objects.create(
            conversation=conversation,
            role=MessageAgent.Role.USER,
            contenu=contenu,
        )
        MessageAgent.objects.create(
            conversation=conversation,
            role=MessageAgent.Role.ASSISTANT,
            contenu=reponse_texte,
        )

        # Force la mise à jour de date_mise_a_jour (auto_now)
        conversation.save(update_fields=["date_mise_a_jour"])

    return Response({
        "conversation_id": conversation.id,
        "reponse": reponse_texte,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def conversations_liste(request):
    """Liste les conversations de l'utilisateur connecté (paginée)."""
    queryset = (
        ConversationAgent.objects
        .filter(utilisateur=request.user)
        .prefetch_related("messages")
        .order_by("-date_mise_a_jour")
    )
    return paginer(queryset, request, ConversationAgentSerializer)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def conversation_detail(request, pk):
    """Détail d'une conversation avec tous ses messages."""
    try:
        conversation = (
            ConversationAgent.objects
            .prefetch_related("messages")
            .get(id=pk, utilisateur=request.user)
        )
    except ConversationAgent.DoesNotExist:
        return Response(
            {"erreur": "Conversation introuvable."},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ConversationAgentSerializer(conversation)
    # .all() utilise le cache prefetch — le tri est déjà dans Meta.ordering
    messages = MessageAgentSerializer(
        conversation.messages.all(), many=True,
    )

    data = serializer.data
    data["messages"] = messages.data
    return Response(data)


def _flux(entete, parole):
    yield json.dumps(entete, ensure_ascii=False) + "\n"
    if entete["clip"]:
        return
    # Piper parle phrase par phrase : le navigateur joue la première pendant que la suite se calcule.
    morceaux = [m for m in re.split(r"(?<=[.!?…])\s+", parole) if m.strip()] if piper_pret() else [parole]
    for rang, morceau in enumerate(morceaux or [parole]):
        try:
            audio = synth_voix(morceau)
        except Exception:
            logger.exception("Synthèse vocale")
            audio = None
        if not audio:
            if rang == 0:
                yield json.dumps({"clip": "tech"}) + "\n"
            return
        yield json.dumps({"audio": audio}) + "\n"


def _dire(parole, *, action=None, transcript="", technique=False, statut=status.HTTP_200_OK):
    """NDJSON : 1re ligne = phrase, action globe, clip éventuel ; puis une ligne audio WAV par phrase."""
    entete = {
        "parole": parole,
        "technique": technique,
        "action": action,
        "transcript": transcript,
        "clip": CLIPS.get(parole),
    }
    rep = StreamingHttpResponse(_flux(entete, parole), status=statut, content_type="application/x-ndjson")
    rep["Cache-Control"] = "no-cache"
    rep["X-Accel-Buffering"] = "no"
    return rep


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([VoixThrottle])
def voix(request):
    """Consigne orale ou écrite → chiffres FIRMS, action globe, note vocale."""
    payload = request.data or {}
    texte = str(payload.get("texte") or payload.get("message") or "").strip()
    audio_b64 = str(payload.get("audio") or "").strip()
    mime = str(payload.get("mime") or "audio/webm").split(";")[0].strip() or "audio/webm"
    contexte = payload.get("contexte") if isinstance(payload.get("contexte"), dict) else {}

    if not texte and not audio_b64:
        return Response({"erreur": "Parlez ou écrivez une consigne."}, status=status.HTTP_400_BAD_REQUEST)
    if audio_b64 and len(audio_b64) > 6_000_000:
        return Response({"erreur": "L’enregistrement est trop long. Parlez plus court."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    try:
        sens = analyser_local(texte) if texte else None
        if sens is None:
            sens = comprendre(texte, None if texte else audio_b64, mime)
        parole, action = repondre(sens, contexte)
    except Indisponible as err:
        logger.warning("Assistant vocal indisponible : %s", err)
        return _dire(TECH, transcript=texte, technique=True, statut=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception:
        logger.exception("Assistant vocal")
        return _dire(TECH, transcript=texte, technique=True, statut=status.HTTP_502_BAD_GATEWAY)

    return _dire(parole, action=action, transcript=sens.get("transcript") or texte)