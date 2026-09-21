"""OpenAPI 3.0 description for the HTTP API."""

from __future__ import annotations


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Price Monitor API",
        "version": "0.1.0",
        "description": "API de suivi des prix du gasoil, du Brent et du bitume.",
    },
    "servers": [{"url": "/", "description": "Serveur courant"}],
    "tags": [
        {"name": "health", "description": "Sondes de vie et de disponibilité"},
        {"name": "market", "description": "Données et collectes de prix"},
    ],
    "components": {
        "securitySchemes": {
            "ApiKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            "BearerAuth": {"type": "http", "scheme": "bearer"},
        },
        "schemas": {
            "ObservationInput": {
                "type": "object",
                "required": ["product", "price", "source"],
                "properties": {
                    "product": {"type": "string", "enum": ["gasoil", "brent", "bitume"]},
                    "price": {"type": "number", "exclusiveMinimum": 0},
                    "unit": {"type": "string", "example": "USD/baril"},
                    "source": {"type": "string", "maxLength": 150},
                    "supplier": {"type": "string", "maxLength": 150},
                    "source_date": {"type": "string", "format": "date"},
                    "collected_at": {"type": "string", "format": "date-time"},
                    "notes": {"type": "string", "maxLength": 500},
                },
            },
            "ProcurementInput": {
                "type": "object",
                "required": ["product", "supplier", "quantity", "unit_price", "currency", "exchange_rate"],
                "properties": {
                    "product": {"type": "string", "enum": ["gasoil", "brent", "bitume"]},
                    "supplier": {"type": "string", "maxLength": 150},
                    "quantity": {"type": "number", "exclusiveMinimum": 0},
                    "unit": {"type": "string", "example": "tonne"},
                    "currency": {"type": "string", "pattern": "^[A-Z]{3}$", "example": "EUR"},
                    "unit_price": {"type": "number", "exclusiveMinimum": 0},
                    "exchange_rate": {"type": "number", "exclusiveMinimum": 0, "description": "USD pour 1 unité de la devise"},
                    "transport_cost": {"type": "number", "minimum": 0},
                    "budget_amount": {"type": "number", "minimum": 0},
                    "purchase_date": {"type": "string", "format": "date"},
                    "notes": {"type": "string", "maxLength": 500},
                },
            },
            "AlertRuleInput": {
                "type": "object",
                "required": ["product", "direction", "threshold", "channel"],
                "properties": {
                    "product": {"type": "string", "enum": ["gasoil", "brent", "bitume"]},
                    "direction": {"type": "string", "enum": ["above", "below"]},
                    "threshold": {"type": "number", "exclusiveMinimum": 0},
                    "channel": {"type": "string", "enum": ["webhook", "email", "both"]},
                    "muted": {"type": "boolean", "default": False},
                },
            },
            "Error": {"type": "object", "properties": {"error": {"type": "string"}}},
        },
    },
    "paths": {
        "/health": {
            "get": {"tags": ["health"], "summary": "Readiness probe", "responses": {"200": {"description": "Service prêt"}, "503": {"description": "Dépendance indisponible"}}}
        },
        "/health/live": {
            "get": {"tags": ["health"], "summary": "Liveness probe", "responses": {"200": {"description": "Processus actif"}}}
        },
        "/health/ready": {
            "get": {"tags": ["health"], "summary": "Readiness probe", "responses": {"200": {"description": "Dépendances disponibles"}, "503": {"description": "Dépendance indisponible"}}}
        },
        "/metrics": {
            "get": {"tags": ["health"], "summary": "Métriques Prometheus", "responses": {"200": {"description": "Métriques au format texte"}}}
        },
        "/api/dashboard": {
            "get": {"tags": ["market"], "summary": "Indicateurs, séries et qualité", "parameters": [{"$ref": "#/components/parameters/Days"}], "responses": {"200": {"description": "Tableau de bord"}}}
        },
        "/api/forecast": {
            "get": {"tags": ["market"], "summary": "Prévisions gasoil et Brent", "parameters": [{"$ref": "#/components/parameters/HistoryDays"}], "responses": {"200": {"description": "Prévisions à 7, 30 et 90 jours avec intervalles de confiance et métriques de backtest"}, "400": {"description": "Paramètre invalide"}}}
        },
        "/api/alerts": {
            "get": {"tags": ["market"], "summary": "Lister les règles et leur état", "responses": {"200": {"description": "Règles actives, rétablies ou en pause"}}},
            "post": {"tags": ["market"], "summary": "Créer une règle d'alerte", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AlertRuleInput"}}}}, "responses": {"201": {"description": "Règle créée"}, "400": {"description": "Règle invalide"}}},
        },
        "/api/alerts/{id}": {
            "put": {"tags": ["market"], "summary": "Modifier une règle d'alerte", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}], "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/AlertRuleInput"}}}}, "responses": {"200": {"description": "Règle modifiée"}, "400": {"description": "Règle invalide"}}},
            "delete": {"tags": ["market"], "summary": "Supprimer une règle d'alerte", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}], "responses": {"200": {"description": "Règle supprimée"}, "400": {"description": "Règle introuvable"}}},
        },
        "/api/observations": {
            "get": {"tags": ["market"], "summary": "Historique filtré", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "parameters": [{"$ref": "#/components/parameters/Product"}, {"$ref": "#/components/parameters/Days"}], "responses": {"200": {"description": "Observations"}, "401": {"description": "Authentification requise"}}},
            "post": {"tags": ["market"], "summary": "Ajouter une observation", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ObservationInput"}}}}, "responses": {"201": {"description": "Observation créée"}, "400": {"description": "Entrée invalide", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}}},
        },
        "/api/history": {
            "get": {"tags": ["market"], "summary": "Historique public paginé avec filtres", "parameters": [
                {"$ref": "#/components/parameters/Product"},
                {"$ref": "#/components/parameters/Page"},
                {"$ref": "#/components/parameters/PageSize"},
                {"name": "supplier", "in": "query", "schema": {"type": "string"}},
                {"name": "source", "in": "query", "schema": {"type": "string"}},
                {"name": "date_from", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "date_to", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "min_price", "in": "query", "schema": {"type": "number", "minimum": 0}},
                {"name": "max_price", "in": "query", "schema": {"type": "number", "minimum": 0}},
            ], "responses": {"200": {"description": "Historique filtré et paginé"}}}
        },
        "/api/history/compare": {
            "get": {"tags": ["market"], "summary": "Comparer publiquement deux périodes", "responses": {"200": {"description": "Comparaison par produit"}, "400": {"description": "Périodes invalides"}}}
        },
        "/api/collect": {
            "post": {"tags": ["market"], "summary": "Déclencher une collecte immédiate", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "responses": {"200": {"description": "Résultat de collecte"}, "401": {"description": "Authentification requise"}}}
        },
        "/api/logs": {"get": {"tags": ["market"], "summary": "Derniers journaux de collecte", "responses": {"200": {"description": "Journaux"}}}},
        "/api/benchmarks": {
            "get": {"tags": ["market"], "summary": "Derniers indicateurs de marché non exécutables", "parameters": [{"name": "product", "in": "query", "schema": {"type": "string", "enum": ["gasoil", "bitume"]}}], "responses": {"200": {"description": "Benchmarks séparés des devis fournisseurs"}}}
        },
        "/api/suppliers": {
            "get": {"tags": ["market"], "summary": "Canaux fournisseurs officiels", "parameters": [{"name": "product", "in": "query", "schema": {"type": "string", "enum": ["gasoil", "bitume"]}}, {"name": "region", "in": "query", "schema": {"type": "string"}}], "responses": {"200": {"description": "Répertoire SQL des voies de contact"}}}
        },
        "/api/procurement-guide": {
            "get": {"tags": ["market"], "summary": "Guide de sourcing et processus d'achat", "parameters": [{"name": "product", "in": "query", "schema": {"type": "string", "enum": ["gasoil", "bitume"], "default": "gasoil"}}, {"name": "region", "in": "query", "schema": {"type": "string", "default": "all"}}], "responses": {"200": {"description": "Contexte marché, fournisseurs, RFQ et étapes de contrôle"}, "400": {"description": "Filtre invalide"}}}
        },
        "/api/procurements": {
            "get": {"tags": ["market"], "summary": "Historique des achats", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "responses": {"200": {"description": "Achats et impacts calculés"}, "401": {"description": "Authentification requise"}}},
            "post": {"tags": ["market"], "summary": "Évaluer et enregistrer un achat", "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}], "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProcurementInput"}}}}, "responses": {"201": {"description": "Achat enregistré"}, "400": {"description": "Entrée invalide", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}}},
        },
        "/export.csv": {"get": {"tags": ["market"], "summary": "Exporter en CSV", "responses": {"200": {"description": "Fichier CSV"}}}},
        "/export.xlsx": {"get": {"tags": ["market"], "summary": "Exporter en Excel", "responses": {"200": {"description": "Fichier XLSX"}}}},
    },
}

OPENAPI_SPEC["components"]["parameters"] = {
    "Days": {"name": "days", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 1825, "default": 30}},
    "HistoryDays": {"name": "history_days", "in": "query", "schema": {"type": "integer", "minimum": 90, "maximum": 1825, "default": 1825}},
    "Product": {"name": "product", "in": "query", "schema": {"type": "string", "enum": ["gasoil", "brent", "bitume"]}},
    "Page": {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1}},
    "PageSize": {"name": "page_size", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}},
}
