import json
import os
import smtplib
import unicodedata
from pathlib import Path
from urllib.parse import urljoin
from email.message import EmailMessage

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://online.pele-mele.be/"
STATE_FILE = Path("livres_deja_vus.json")

AUTHORS = [
    "Greg Girard",
    "Sebastiao Salgado",
    "Fred Herzog",
    "David Alan Harvey",
    "Ian Teh",
    "Ernst Haas",
    "James Nachtwey",
    "Saul Leiter",
    "Todd Hido",
    "Alex Webb",
    "Bruno Barbey",
    "Larry Burrows",
    "Werner Bischof",
    "Harry Gruyaert",
    "Fan Ho",
]

EMAIL_FROM = os.getenv("BOOKS_EMAIL_FROM", "")
EMAIL_TO = os.getenv("BOOKS_EMAIL_TO", "")
EMAIL_PASSWORD = os.getenv("BOOKS_EMAIL_PASSWORD", "")


def normaliser(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(
        c for c in texte if not unicodedata.combining(c)
    )
    return " ".join(texte.casefold().split())


def chercher_auteur(session, auteur):
    response = session.get(
        BASE_URL,
        params={
            "s": auteur,
            "post_type": "product",
            "orderby": "date",
            "order": "desc",
        },
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    livres = {}

    cartes = soup.select(
        "li.product, div.product, li.type-product"
    )

    for carte in cartes:
        lien = carte.select_one(
            "a.woocommerce-LoopProduct-link, "
            "a.woocommerce-loop-product__link, "
            "a[href*='/product/']"
        )

        if not lien or not lien.get("href"):
            continue

        titre_node = carte.select_one(
            ".woocommerce-loop-product__title, h2, h3"
        )
        titre = (
            titre_node.get_text(" ", strip=True)
            if titre_node
            else lien.get_text(" ", strip=True)
        )

        texte = carte.get_text(" ", strip=True)

        if normaliser(auteur) not in normaliser(texte):
            continue

        prix_node = carte.select_one(".price")
        prix = (
            prix_node.get_text(" ", strip=True)
            if prix_node
            else "Prix non indiqué"
        )

        url = urljoin(BASE_URL, lien["href"])

        livres[url] = {
            "auteur": auteur,
            "titre": titre,
            "prix": prix,
            "url": url,
        }

    return livres


def envoyer_email(nouveaux):
    if not EMAIL_FROM or not EMAIL_TO or not EMAIL_PASSWORD:
        raise RuntimeError(
            "Les identifiants e-mail ne sont pas configurés."
        )

    message = EmailMessage()
    message["Subject"] = (
        f"[Pêle-Mêle] {len(nouveaux)} nouveau(x) livre(s)"
    )
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO

    lignes = ["Nouveaux livres repérés sur Pêle-Mêle :", ""]

    for livre in nouveaux:
        lignes.extend([
            f"Auteur recherché : {livre['auteur']}",
            f"Titre : {livre['titre']}",
            f"Prix : {livre['prix']}",
            f"Lien : {livre['url']}",
            "",
        ])

    message.set_content("\n".join(lignes))

    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, timeout=30
    ) as serveur:
        serveur.login(EMAIL_FROM, EMAIL_PASSWORD)
        serveur.send_message(message)


def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "PersonalBookWatch/1.0"
    })

    historique_existe = STATE_FILE.exists()

    if historique_existe:
        historique = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    else:
        historique = {}

    resultats = {}
    erreurs = []

    print("Recherche des livres sur Pêle-Mêle...")

    for auteur in AUTHORS:
        try:
            livres = chercher_auteur(session, auteur)
            resultats.update(livres)
            print(f"{auteur} : {len(livres)} résultat(s)")
        except requests.RequestException as exc:
            erreurs.append(auteur)
            print(f"Erreur pour {auteur} : {exc}")

    if erreurs:
        print(
            "Certaines recherches ont échoué. "
            "Historique non modifié ; nouvel essai au prochain passage."
        )
        raise RuntimeError(
            "Recherche incomplète pour : " + ", ".join(erreurs)
        )

    if not historique_existe:
        STATE_FILE.write_text(
            json.dumps(resultats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            "Inventaire initial enregistré. "
            "Aucun e-mail envoyé pour les annonces existantes."
        )
        return

    nouveaux = [
        livre
        for url, livre in resultats.items()
        if url not in historique
    ]

    if nouveaux:
        envoyer_email(nouveaux)
        print(f"E-mail envoyé : {len(nouveaux)} nouveau(x) livre(s).")
    else:
        print("Aucune nouvelle annonce.")

    historique.update(resultats)
    STATE_FILE.write_text(
        json.dumps(historique, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
