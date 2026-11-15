"""Utilitaires partagés du projet FireWatch."""

from rest_framework.pagination import PageNumberPagination


def parse_int_param(request, name, default, max_value=None):
    """Parse un paramètre GET entier avec valeur par défaut et plafond."""
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default
    if max_value is not None:
        value = min(value, max_value)
    return value


def parse_float_param(request, name, default):
    """Parse un paramètre GET flottant avec valeur par défaut."""
    try:
        return float(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default


class StandardPagination(PageNumberPagination):
    """Pagination standard pour les endpoints liste."""
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


def paginer(queryset, request, serializer_class):
    """Pagine un queryset et retourne une réponse DRF paginée."""
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True)
    return paginator.get_paginated_response(serializer.data)