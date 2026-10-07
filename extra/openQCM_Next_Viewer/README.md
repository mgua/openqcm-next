# openQCM Next Viewer — Flask + SQLite

Applicazione web Python per importare, conservare e visualizzare misure CSV.

## Funzionalità

- Accesso autenticato con sessione.
- Ruoli `admin` e `user`.
- Ogni utente può cambiare autonomamente la propria password.
- Solo gli amministratori possono importare CSV.
- Solo gli amministratori possono eliminare dataset singolarmente.
- Gestione utenti da pannello amministratore.
- Ogni importazione diventa un dataset indipendente in SQLite.
- Visualizzazione di `Temperature`, `Resonance_Frequency` e `Dissipation`.
- Asse X basato su `Relative_time`, convertito da secondi a minuti.
- Confronto simultaneo di 1, 2 o 3 importazioni negli stessi tre grafici.
- Selezione massima di 3 dataset dalla dashboard.
- Validazione delle colonne e dei valori numerici del CSV.
- Token CSRF per i form che modificano dati.

## Avvio locale

Richiede Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Apri `https://127.0.0.1:5443`. Al primo avvio viene generato automaticamente un certificato autofirmato per `localhost` e `127.0.0.1`; il browser mostrerà un avviso di sicurezza, normale per un certificato non emesso da una CA pubblica.

### Credenziali iniziali

Al primo avvio viene creato automaticamente l'utente amministratore:

- Username: `admin`
- Password iniziale: `admin123!`

La password iniziale non viene mostrata nella pagina di login. Dopo il primo accesso, usa **Cambia password** dal menu dell'applicazione.

Per un ambiente reale, imposta una `SECRET_KEY` sicura e modifica subito la password iniziale.

## Struttura dati CSV

L'importatore richiede queste colonne:

`Date, Time, Relative_time, Temperature, Resonance_Frequency, Dissipation`

Supporta separatori CSV comuni (virgola, punto e virgola, tab) e UTF-8/UTF-8 BOM/CP1252.

`Relative_time` viene memorizzato in secondi come nel CSV e convertito in minuti esclusivamente per la visualizzazione dei grafici e dell'anteprima.

## Confronto importazioni

Dalla dashboard seleziona fino a tre dataset e premi **Confronta selezionate**. Ogni importazione mantiene la propria scala temporale relativa, quindi i tre tracciati possono avere durate e numero di campioni differenti.

## Produzione

Per un deployment pubblico si consiglia di usare un server WSGI (es. Waitress o Gunicorn), HTTPS, una `SECRET_KEY` generata casualmente e una strategia di backup del file `instance/app.db`.


## HTTPS

HTTPS è attivo per impostazione predefinita. Il certificato autofirmato viene creato nella cartella `certs/` al primo avvio.

Per usare un certificato reale, imposta:

```text
SSL_CERT_FILE=/percorso/server.crt
SSL_KEY_FILE=/percorso/server.key
```

Per disattivare temporaneamente HTTPS in locale:

```text
HTTPS_ENABLED=0
```

La chiave privata generata automaticamente non va condivisa o committata.
