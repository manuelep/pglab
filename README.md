# Esercitazione PostGIS — setup rapido

## 1. Genera utenti/schemi dal CSV della classe

Il CSV deve avere intestazioni: `Nome,Cognome,"Indirizzo email",Gruppi`
(la colonna Gruppi viene letta ma al momento ignorata).

```bash
python3 genera_utenti.py studenti.csv --dbname corso_gis --outdir ./output
```

Produce in `./output/`:
- `init.sql` — DDL per creare ruolo + schema per ogni studente (username = iniziale+cognome, es. `mrossi`)
- `pg_service.conf` — una sezione per studente, da unire/distribuire
- `.pgpass` — credenziali abbinate, permessi già a 600
- `credenziali.csv` — riepilogo leggibile per distribuzione manuale/email

In caso di username duplicati (es. due "Mario Rossi") viene aggiunto un suffisso
numerico progressivo (`mrossi`, `mrossi2`, ...).

**Attenzione ai run ripetuti**: se rilanci lo script sulla stessa `--outdir` che
contiene già un output precedente, lo script si blocca e chiede `--force`.
Questo perché ogni run **genera password nuove e diverse** per gli stessi
utenti (username stabili, password no). Se il database è già stato avviato con
le credenziali del run precedente, sovrascriverle con `--force` produce un
disallineamento: i file di credenziali diranno una password, ma il DB in
esecuzione ne avrà un'altra, finché non rilanci `init.sql` sul database
(tipicamente `docker compose down && docker compose up -d`, dato che l'istanza
non ha volumi persistenti).

## 2. (Opzionale) Calibra le risorse sulla RAM del server

Il `docker-compose.yml` ha già default adatti a un server con **4GB di RAM**.
Per una macchina diversa, copia `.env.example` in `.env` (stessa cartella del
compose) e modifica i valori — il file `.env.example` include una tabella di
riferimento per 4/8/16/32GB di RAM. Se non crei il file `.env`, vengono usati
i default da 4GB.

```bash
cp .env.example .env
# poi modifica .env secondo la RAM disponibile
```

## 3. Avvia il servizio PostgreSQL/PostGIS

```bash
docker compose up -d
```

`init.sql` viene eseguito automaticamente al primo bootstrap del container
(nessun volume dati: ogni riavvio da zero rigenera tutto). Se cambi il CSV
e vuoi rigenerare gli utenti, fai `docker compose down` e poi di nuovo `up -d`
(down senza `-v` va bene comunque perché non ci sono volumi nominati).

## 4. Distribuisci le credenziali agli studenti

Opzioni, dalla più comoda alla più manuale:

- **pg_service.conf + .pgpass personali**: ogni studente riceve solo la propria
  sezione/riga (estraibile da `credenziali.csv`), da copiare in
  `~/.pg_service.conf` e `~/.pgpass` (Linux/Mac) o equivalenti Windows
  (`%APPDATA%\postgresql\.pg_service.conf`, `%APPDATA%\postgresql\pgpass.conf`).
  Poi si connettono con `service=mrossi` senza mai digitare la password.
- **credenziali.csv**: se preferisci comunicare utente/password singolarmente
  (es. via email o piattaforma didattica) e lasciare che si connettano da QGIS
  inserendo manualmente host/porta/utente/password.

## 5. Import shapefile efficiente (indicazioni per gli studenti)

```bash
ogr2ogr -f PostgreSQL PG:"service=mrossi" shapefile.shp \
  -nln nome_tabella \
  -lco SPATIAL_INDEX=NONE \
  --config PG_USE_COPY YES
```

Poi, se serve un indice spaziale, crearlo dopo l'import:

```sql
CREATE INDEX ON nome_tabella USING GIST (geom);
```

Grazie al `search_path` preimpostato per ogni ruolo, non serve qualificare lo
schema: `nome_tabella` finisce automaticamente nello schema personale dello
studente.