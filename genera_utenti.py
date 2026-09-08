#!/usr/bin/env python3
"""
Genera utenti/schemi PostgreSQL per una classe a partire da un CSV con
intestazioni: Nome,Cognome,"Indirizzo email",Gruppi

Output prodotti:
  - init.sql            -> DDL da eseguire sul DB (CREATE ROLE/SCHEMA/GRANT)
  - pg_service.conf     -> una sezione [studente_username] per host/porta/db/utente
  - .pgpass             -> credenziali associate (permessi 0600 raccomandati)
  - credenziali.csv     -> riepilogo leggibile (username, nome, cognome, email, password)

Uso:
  python3 genera_utenti.py studenti.csv \
      --host localhost --port 5432 --dbname corso_gis \
      --outdir ./output

Le password sono generate con basso livello di robustezza (scopo didattico,
istanza effimera senza volumi persistenti) ma restano casuali e uniche per
evitare che uno studente indovini quella di un altro per errore.
"""

import argparse
import csv
import re
import secrets
import string
import sys
import unicodedata
from pathlib import Path


def strip_accents(text: str) -> str:
    """Rimuove diacritici (Ferraro -> Ferraro, Perego -> Perego, D'Amico -> D Amico)."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def slugify_part(text: str) -> str:
    """Minuscolo, solo [a-z], niente apostrofi/spazi/trattini."""
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z]", "", text)
    return text


def build_username(nome: str, cognome: str, taken: set) -> str:
    """iniziale + cognome, con suffisso numerico progressivo in caso di collisione."""
    iniziale = slugify_part(nome)[:1]
    cognome_slug = slugify_part(cognome)
    base = f"{iniziale}{cognome_slug}"
    if not base:
        base = "studente"

    username = base
    counter = 2
    while username in taken:
        username = f"{base}{counter}"
        counter += 1
    taken.add(username)
    return username


def genera_password(lunghezza: int = 10) -> str:
    """Password semplice ma casuale: lettere minuscole/maiuscole + cifre.
    Livello di sicurezza basso di proposito (uso didattico, istanza effimera),
    ma sufficientemente casuale da non essere indovinabile a colpo d'occhio."""
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(lunghezza))


def sql_ident(identifier: str) -> str:
    """Quoting sicuro per identificatori SQL (anche se qui sono già puliti)."""
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    """Quoting sicuro per literal SQL."""
    return "'" + value.replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(description="Genera utenti/schemi PostgreSQL da CSV classe.")
    parser.add_argument("csv_path", help="Percorso del CSV con colonne Nome,Cognome,Indirizzo email,Gruppi")
    parser.add_argument("--host", default="localhost", help="Host del servizio PostgreSQL (default: localhost)")
    parser.add_argument("--port", default="5432", help="Porta PostgreSQL (default: 5432)")
    parser.add_argument("--dbname", default="corso_gis", help="Nome del database condiviso (default: corso_gis)")
    parser.add_argument("--outdir", default="./output", help="Cartella di output (default: ./output)")
    parser.add_argument("--password-length", type=int, default=10, help="Lunghezza password generate (default: 10)")
    parser.add_argument("--connection-limit", type=int, default=10,
                         help="CONNECTION LIMIT per ruolo (default: 10). Client GUI come DBeaver/QGIS "
                              "aprono più connessioni per sessione (editor SQL, metadata browser, ecc.), "
                              "quindi un valore troppo basso causa 'too many connections' anche con un solo utente collegato.")
    parser.add_argument("--force", action="store_true",
                         help="Sovrascrive un output preesistente senza chiedere conferma. "
                              "ATTENZIONE: rigenera password diverse da quelle di un run precedente; "
                              "se il database è già stato avviato con le vecchie credenziali, "
                              "andranno disallineate finché non rilanci init.sql sul DB.")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        sys.exit(f"Errore: file CSV non trovato: {csv_path}")

    outdir = Path(args.outdir)
    file_output_esistenti = [
        outdir / nome for nome in ("init.sql", "pg_service.conf", ".pgpass", "credenziali.csv")
        if (outdir / nome).exists()
    ]
    if file_output_esistenti and not args.force:
        nomi = ", ".join(f.name for f in file_output_esistenti)
        sys.exit(
            f"Errore: trovati output di un run precedente in '{outdir}' ({nomi}).\n"
            "Rigenerare produce PASSWORD DIVERSE per gli stessi utenti: se il database è già "
            "avviato con le credenziali attuali, distribuire le nuove renderebbe l'accesso "
            "disallineato finché non riesegui init.sql sul DB (es. 'docker compose down && up -d' "
            "su un'istanza senza volumi persistenti).\n\n"
            "Se vuoi comunque procedere, rilancia con --force, oppure svuota/rinomina la cartella di output."
        )

    outdir.mkdir(parents=True, exist_ok=True)

    righe_valide = []
    taken_usernames = set()

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        colonne_attese = {"Nome", "Cognome", "Indirizzo email"}
        if not colonne_attese.issubset(set(reader.fieldnames or [])):
            sys.exit(
                f"Errore: intestazioni CSV inattese. Trovate: {reader.fieldnames}. "
                f"Attese almeno: {sorted(colonne_attese)}"
            )

        for numero_riga, row in enumerate(reader, start=2):  # 2 = prima riga dati (1 è header)
            nome = (row.get("Nome") or "").strip()
            cognome = (row.get("Cognome") or "").strip()
            email = (row.get("Indirizzo email") or "").strip()

            if not nome or not cognome:
                print(f"[skip] riga {numero_riga}: Nome o Cognome mancante ({row})", file=sys.stderr)
                continue

            username = build_username(nome, cognome, taken_usernames)
            password = genera_password(args.password_length)

            righe_valide.append({
                "username": username,
                "nome": nome,
                "cognome": cognome,
                "email": email,
                "password": password,
            })

    if not righe_valide:
        sys.exit("Errore: nessuna riga valida trovata nel CSV.")

    # ---------- init.sql ----------
    sql_lines = [
        "-- Generato automaticamente da genera_utenti.py",
        "-- Crea un ruolo LOGIN e uno schema omonimo per ciascuno studente,",
        "-- con search_path preimpostato e connection limit per contenere errori.",
        "",
        "BEGIN;",
        "",
    ]

    for s in righe_valide:
        u = sql_ident(s["username"])
        pwd = sql_literal(s["password"])
        sql_lines.extend([
            f"-- {s['nome']} {s['cognome']} <{s['email']}>",
            f"DROP ROLE IF EXISTS {u};",
            f"CREATE ROLE {u} LOGIN PASSWORD {pwd} CONNECTION LIMIT {args.connection_limit};",
            f"DROP SCHEMA IF EXISTS {u} CASCADE;",
            f"CREATE SCHEMA {u} AUTHORIZATION {u};",
            f"ALTER ROLE {u} IN DATABASE {sql_ident(args.dbname)} SET search_path TO {u}, public;",
            f"GRANT ALL PRIVILEGES ON SCHEMA {u} TO {u};",
            "",
        ])

    sql_lines.append("COMMIT;")
    (outdir / "init.sql").write_text("\n".join(sql_lines), encoding="utf-8")

    # ---------- pg_service.conf ----------
    service_lines = []
    for s in righe_valide:
        service_lines.extend([
            f"[{s['username']}]",
            f"host={args.host}",
            f"port={args.port}",
            f"dbname={args.dbname}",
            f"user={s['username']}",
            "",
        ])
    (outdir / "pg_service.conf").write_text("\n".join(service_lines), encoding="utf-8")

    # ---------- .pgpass ----------
    # formato: hostname:port:database:username:password
    pgpass_lines = [
        f"{args.host}:{args.port}:{args.dbname}:{s['username']}:{s['password']}"
        for s in righe_valide
    ]
    pgpass_path = outdir / ".pgpass"
    pgpass_path.write_text("\n".join(pgpass_lines) + "\n", encoding="utf-8")
    try:
        pgpass_path.chmod(0o600)
    except OSError:
        pass  # su alcuni filesystem (es. mount Windows) il chmod può fallire silenziosamente

    # ---------- credenziali.csv (riepilogo leggibile per la distribuzione) ----------
    with (outdir / "credenziali.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["username", "nome", "cognome", "email", "password", "pg_service_name"])
        for s in righe_valide:
            writer.writerow([s["username"], s["nome"], s["cognome"], s["email"], s["password"], s["username"]])

    print(f"Generati {len(righe_valide)} utenti.")
    print(f"Output in: {outdir.resolve()}")
    print("  - init.sql            (esegui su PostgreSQL per creare ruoli/schemi)")
    print("  - pg_service.conf     (da copiare/unire in ~/.pg_service.conf lato client, o distribuire per studente)")
    print("  - .pgpass             (da copiare in ~/.pgpass lato client, permessi 600)")
    print("  - credenziali.csv     (riepilogo per distribuzione manuale/email)")


if __name__ == "__main__":
    main()