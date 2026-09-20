from __future__ import annotations

from typing import Any

from ..database import DatabaseBackend


REGIONS = {
    "all": "Toutes les régions",
    "europe": "Europe",
    "africa_middle_east": "Afrique & Moyen-Orient",
    "asia_pacific": "Asie-Pacifique",
    "americas": "Amériques",
    "local": "Distributeur local",
}

COMMON_STEPS = [
    {
        "number": 1,
        "title": "Définir le besoin technique",
        "detail": "Fixer la norme, le grade, la quantité, le conditionnement, la destination et la fenêtre de livraison.",
    },
    {
        "number": 2,
        "title": "Envoyer le même RFQ à au moins trois vendeurs",
        "detail": "Demander prix, devise, validité, volume minimum, origine, point de chargement, délai et Incoterm 2020.",
    },
    {
        "number": 3,
        "title": "Vérifier chaque contrepartie",
        "detail": "Contrôler registre du commerce, licence, bénéficiaire effectif, sanctions, références et compte bancaire par un second canal.",
    },
    {
        "number": 4,
        "title": "Comparer le coût rendu",
        "detail": "Additionner marchandise, fret, assurance, inspection, droits, taxes, change, stockage et frais de retard ou de chauffage.",
    },
    {
        "number": 5,
        "title": "Contracter qualité, paiement et réclamations",
        "detail": "Joindre la spécification, la tolérance de quantité, l'inspection, les documents, le calendrier, le droit applicable et la procédure de réclamation.",
    },
    {
        "number": 6,
        "title": "Payer et réceptionner avec contrôle",
        "detail": "Privilégier crédit documentaire ou crédit approuvé; rapprocher poids, certificat d'analyse et inspection avant paiement final.",
    },
]

PRODUCT_GUIDANCE = {
    "gasoil": {
        "title": "Acheter du gasoil / diesel en gros",
        "specification": "EN 590, soufre 10 ppm, cétane, densité, point éclair, point de trouble et teneur FAME selon le pays.",
        "logistics": "Pour camion-citerne: Ex-rack/FCA ou DAP. Pour cargaison: FOB, CFR ou CIF avec terminal de réception confirmé.",
        "rfq_fields": [
            "Produit et norme (ex. EN 590 10 ppm)", "Quantité et tolérance", "Port/dépôt de destination",
            "Date ou fenêtre de livraison", "Incoterm 2020 demandé", "Devise et formule de prix",
            "Certificat d'analyse, SDS et origine", "Modalité de paiement et validité de l'offre",
        ],
        "warning": (
            "Le relevé DDFUELNYH est un prix spot FOB New York Harbor en USD/gallon. "
            "C'est un benchmark de négociation, pas le prix rendu dans votre pays."
        ),
    },
    "bitume": {
        "title": "Acheter du bitume",
        "specification": "Choisir le grade (ex. 35/50, 50/70 ou 70/100), EN 12591/ASTM D946, bitume modifié ou émulsion et usage final.",
        "logistics": "Le vrac exige citerne et stockage chauffés. Pour petits volumes/import lointain, comparer fûts, big bags ou conteneurs avec le coût de fusion et les pertes.",
        "rfq_fields": [
            "Grade, norme et usage routier/industriel", "Quantité et conditionnement", "Origine et raffinerie",
            "Point de chargement et destination", "Température de chargement/livraison", "Incoterm 2020 demandé",
            "PDS, SDS, certificat d'analyse et méthode d'inspection", "Fret, surestaries, chauffage et validité de l'offre",
        ],
        "warning": (
            "Il n'existe pas de prix spot mondial gratuit et exécutable du bitume. WPU058 est un indice mensuel américain "
            "de tendance; le prix USD/tonne doit venir d'un devis fournisseur comparable par grade, lieu et Incoterm."
        ),
    },
}


def build_procurement_guide(
    database: DatabaseBackend, product: str = "gasoil", region: str = "all"
) -> dict[str, Any]:
    product = product.strip().lower()
    if product not in PRODUCT_GUIDANCE:
        raise ValueError("Produit inconnu. Utilisez gasoil ou bitume.")
    region = region.strip().lower() or "all"
    if region not in REGIONS:
        raise ValueError("Région inconnue.")

    latest_prices = [row for row in database.latest() if row.get("product") == product]
    latest_quote = latest_prices[0] if latest_prices else None
    benchmarks = database.latest_benchmarks(product=product)
    guidance = PRODUCT_GUIDANCE[product]
    return {
        "product": product,
        "region": region,
        "region_label": REGIONS[region],
        "title": guidance["title"],
        "market_context": {
            "latest_price": latest_quote,
            "benchmarks": benchmarks,
            "warning": guidance["warning"],
        },
        "suppliers": database.supplier_channels(product=product, region=region),
        "steps": COMMON_STEPS,
        "specification": guidance["specification"],
        "logistics": guidance["logistics"],
        "rfq_fields": guidance["rfq_fields"],
        "landed_cost_formula": (
            "coût rendu = marchandise + fret + assurance + inspection + droits/taxes "
            "+ stockage/chauffage + frais financiers ± change"
        ),
        "disclaimer": (
            "Les entreprises listées sont des voies de contact officielles, pas une recommandation ni une garantie de vente. "
            "Vérifiez disponibilité, licences, sanctions, qualité, fiscalité et conditions contractuelles dans votre juridiction."
        ),
    }
