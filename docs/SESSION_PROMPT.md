<!--
Kept in Italian on purpose, unlike the rest of the repo: this file is not prose
about the code, it is the literal text to paste as the first message of a new
session, and the working language in chat is Italian. Everything it points at --
HANDOFF, CHANGELOG, the commit history -- is in English.

ONE file, identical on both branches, cherry-picked like any other shared change.
The two previous copies drifted apart and started contradicting each other.

Keep it short and keep it true. It is a shortcut, not the source: HANDOFF.md and
the `## [Unreleased]` entries in CHANGELOG.md are.

Last aligned: 2026-09-07.
-->

# openQCM NEXT — prompt per iniziare una nuova sessione

Incolla tutto quello che segue come primo messaggio della chat nuova, aprendola
nella cartella `/Users/marco/claude_code/openqcm-next`.

---

Lavoriamo su **openQCM NEXT**.

## ⚠️ Come va letto questo documento

Questo prompt serve a darti **conoscenza dello stato attuale dello sviluppo**, non
è una lista di cose da fare. La sezione "Cose aperte" è un inventario, **non una
coda di lavoro**: alcune voci sono parcheggiate apposta e l'ordine non è il mio
ordine di priorità. Leggi, verifica pure un paio di affermazioni sul codice se
vuoi, riportami lo stato in breve — **e poi aspetta che ti dica io su cosa
lavoriamo**. Non propormi un programma di lavoro dedotto da qui.

Prima di toccare qualsiasi cosa leggi `HANDOFF.md` (§1 moduli condivisi, §2 rami,
§3 stato su `main`, §4 ramo impedenza, §6 convenzioni) e le voci sotto
`## [Unreleased]` in `CHANGELOG.md`. **Non fidarti della tua memoria del codice:
leggi il file prima di modificarlo.**

## Come lavoro

- **Parla italiano in chat, scrivi in inglese nel repo** — commit, documentazione,
  commenti.
- **Risposte concise.** Per modifiche non banali: prima il piano, poi esegui dopo
  il mio ok. Se ti chiedo più modifiche insieme, **una alla volta**.
- **Misura invece di dedurre.** Se un tuo risultato precedente si rivela
  sbagliato, dillo esplicitamente con i numeri. È successo più volte e va bene
  così: quello che non va bene è tenerselo.
- ⚠️ **Una funzione con un ripiego che produce lo stesso esito corretto va
  strumentata, o non è verificabile.** Il comando `'Q'` è rimasto codice morto per
  quattro sessioni di banco perché il drain rimediava da solo. Se aggiungi
  qualcosa che ha una via di riserva, aggiungi l'osservabile che distingue le due
  strade — e che sia un **numero**, non un "ha funzionato".
- ⚠️ **Un campione non è una misura.** In questa sessione una conclusione su cinque
  punti ("il group delay non è costante") è stata smentita da 100 001 punti sugli
  stessi standard. Prima di concludere, guarda quanti dati hai davvero.
- Gli artifact che produci durante il lavoro devono essere **file markdown con le
  figure incorporate**.
- Dopo ogni commit+push, **allinea `HANDOFF.md` e `CHANGELOG.md`**.

## I due rami, e la regola che non si viola

| worktree | ramo |
|---|---|
| `/Users/marco/claude_code/openqcm-next` | `main` |
| `/Users/marco/claude_code/openqcm-next-impedance` | `impedance-analysis` |

- ⚠️ **`main` NON deve contenere l'analisi di impedenza.** È già stato mergiato per
  errore due volte e revertito (`1b3fe81`). Il merge verso main avverrà in futuro
  ed è una **mia** decisione: non proporlo come "passo naturale".
- ⚠️ **Mai `git merge main` dentro il branch.** Il codice condiviso si modifica su
  `main` e poi `git cherry-pick <sha>`, **un commit alla volta**.
- ⚠️ **Un commit = un argomento.** `f1b82c9` mescolava codice, documentazione e
  quattro file hex, e il cherry-pick è finito in conflitto proprio per quello.
- Il push richiede l'helper di `gh` (il token vive solo lì):
  `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.https://github.com.helper GIT_CONFIG_VALUE_0='!gh auth git-credential' git push origin <branch>`

## Trappole del repo

- ⚠️ `PeakFrequencies.txt`, `PeakFrequenciesRT.txt` e `config.txt` sono **versionati
  di proposito**: l'app non parte senza.
- ⚠️ Togliere un file dal tracking **lo cancella** su ogni altro clone che fa pull;
  `.gitignore` non protegge i file già tracciati.
- ⚠️ Mai `git add -A`: i bit `skip-worktree` sono per-worktree e su un worktree
  possono non essere impostati. Usa sempre `git add -- <file>`.
- ⚠️ `processors/Calibration.py` (815 CRLF) e `common/fileStorage.py` (179 CRLF) sono file
  **CRLF**, 0 LF nudi. Vanno modificati in binario, altrimenti il diff diventa il file intero:
  è successo il 2026-09-17 con una scrittura in modo testo, su entrambi i rami, riscritta prima del push.
- ⚠️ Prima di analizzare dati grezzi, **copiali fuori dal repo**: `sweep_data/` è
  gitignorata e sovrascritta a ogni acquisizione. I dataset dietro le tabelle di
  validazione di luglio sono andati persi esattamente così.

## Ambiente

PyQt5 **5.9.2** / Qt 5.9.7 / Python 3.9.12 — namespace widget classico `QtGui`,
non "modernizzare". pyqtgraph 0.11.0 copia i membri di `QtWidgets` dentro `QtGui`,
quindi del codice funziona **per effetto collaterale** di un import di terze parti:
nel codice nuovo importa esplicitamente da `QtWidgets`.

Test headless con `QT_QPA_PLATFORM=offscreen`; tieni la `QApplication` in una
variabile. Segfault noti: `QMainWindow.show()`, un `QTabWidget` pieno di
`GraphicsLayoutWidget`, due alberi openQCM nello stesso processo Qt. I `QDialog` e
i `QWidget` semplici invece si mostrano e si catturano senza problemi.
⚠️ **Con `offscreen` non ci sono font veri** (~17 px/carattere): qualsiasi misura di
larghezza fatta lì è priva di valore. Per misurare la GUI serve la piattaforma
reale.

`arduino-cli` non è sul PATH ma è dentro `Arduino IDE.app` con il core Teensy:
gli sketch del firmware si compilano headless.

## I file di dati grezzi

Specifica completa: **`software/docs/DATA_FORMAT_sweep_data.md`** — leggila prima
di scrivere una riga di analisi. In sintesi, `sweep_data/` (dump di sviluppo,
attivo solo con `OPENQCM_SWEEP_DUMP=1`, **sovrascritto a ogni sweep**):

- `1.txt 3.txt 5.txt 7.txt 9.txt` — nome = **ordine armonico**, 3 colonne, 18001
  righe, passo 1 Hz. Colonna 2 = canale magnitudine, ⚠️ **attenuatore NON
  compensato**. Colonna 3 = ⚠️ **`90 − |Δφ|`, non la fase**.
- `g1.txt … g9.txt` (solo ramo impedenza) — `V_MAG` in volt **già compensato** e
  `V_PHS` in volt.
- ⚠️ **Compensare due volte l'attenuatore mette il quarzo a 10.4× la sua impedenza
  vera, sopra un circuito aperto.** È già successo su dati veri.

## Cose aperte

### Tre interruttori da rimettere prima di una build di produzione

- ⚠️ `Constants.environment = 3` → **10**, su **entrambi** i rami. Motivo ormai
  solo metrologico (la fragilità è stata risolta da `core/averaging.py`).
- ⚠️ `Constants.accept_test_firmware = True` → **False**, su entrambi i rami. Fa
  passare il firmware `-TEST` della scheda prototipo.
- ⚠️ `Constants.plot_reassert_yrange_freq_diss = False` → **True** quando l'asse
  verticale di frequenza e dissipazione sarà sistemato. **Esiste solo sul ramo
  `impedance-analysis`**, su `main` la costante non c'è.

### Aggiornamento firmware

- ✅ **Procedura verificata su macOS** il 2026-09-01: l'updater passa l'hex al
  Teensy Loader, rilascia l'handle, e la finestra va a Disconnected con un popup
  informativo. `firmware_update/` porta ora **entrambe** le immagini `0.1.5c`
  (produzione e `-TEST`) e `_firmware_image()` sceglie in base alla versione che la
  scheda dichiara.
- ⚠️ **Il ramo Windows non è mai stato eseguito.** Va provato in fase di produzione.
- ⚠️ `firmware_update/` contiene ancora l'immagine `0.1.5` (tre versioni indietro),
  lasciata lì di proposito: decideremo io e te cosa farne.
- ⚠️ In `firmware/` ci sono **tre coppie** di versioni. `0.1.5a` e `0.1.5b` vanno
  cancellate quando nessuna scheda le monta più; la variante `-TEST` senza TEC
  resta finché la scheda prototipo è in uso.

### Elettronica e clock

- ⚠️ **Il DDS è specificato a 125 MHz di system clock a 3.3 V** (100 a 2.7 V, 180 a
  5.0 V), e il moltiplicatore 6× non aggira il limite: a 3.3 V il REFCLK massimo è
  20.83 MHz, cioè gli stessi 125 MHz. **Controlla il clock prima di archiviare uno
  sweep come prova**: sopra quel limite la parte è fuori specifica e il suo canale
  di fase non è riferimento per niente.
- La scheda nuova (filtri diversi, clock 125 MHz) è **dentro** specifica ed è quella
  su cui è tarato il criterio di fold.

### Ramo `impedance-analysis`

- ⚠️ **Il ramo del fold per carico smorzato non è validato.** Manca un dump in
  isopropanolo o in acqua sulle armoniche alte: in aria tutti e cinque gli overtone
  danno "fold", quindi il ramo "no fold" non è mai esercitato.
  `Constants.PHASE_FOLD_BY_PEAK_DEPTH = False` rimette la soglia vecchia.
- ⚠️ **La calibrazione OSL è parcheggiata, e non è la soluzione alla rotondità.**
  Dimostrato, non stimato: il modello d'errore lineare è bilineare, quindi Möbius,
  quindi manda cerchi in cerchi — il residuo del fit circolare è **invariante**
  (9.67 % prima, 9.74 % dopo). Per decidere quale Γ sia giusta serve un **quarto
  standard dentro il range operativo** (qualche pF, o 1–10 kΩ). Dettagli in
  `HANDOFF.md` §4.
- ⚠️ **Provenienza dei dataset aria/isopropanolo di luglio**: le tabelle nel
  CHANGELOG del ramo riportano risultati senza i dati grezzi dietro. Parcheggiato
  fino alla messa in produzione.
- `plot_color_multi_g`: palette esadecimale dei grafici di conduttanza, copia di una
  lista blu più vecchia, mai allineata alle due rampe.
- Copia benigna di `savitzky_golay` in `sweep_data/plot_conductance.py`.

### GUI

- **Larghezza dei pill delle armoniche**: tentata **due volte** e revertita due
  volte, la seconda per motivi estetici. Quello che si è imparato sta in
  `HANDOFF.md` §3, "The overtone chips, and why they still stretch", inclusa la
  variante mai provata: chip impaccati a sinistra con **un solo spaziatore in
  coda**, come i bottoni della temperatura.
- ⚠️ **"Sidebar tagliata a 435 px" era falso e va tolto dalla testa.** Misurato sulla
  piattaforma reale il 2026-09-01: il contenuto chiede **298 px**, 306 con il QSS,
  contro un pannello che concede 260 al minimo e 400 al massimo. I 435 px venivano
  da una misura fatta in `offscreen`, dove i font non esistono. Il nome del datalog
  che si vedeva tagliato era un bug diverso e separato — l'elisione a 140 px dentro
  un pannello da 244 — ed è **risolto** da `ui/widgets.ElidedLabel`.
- `polyfit` in tre copie: `Multiscan.baseline_correction`,
  `Serial.baseline_correction`, `Calibration.baseline_estimation`.
- Zeri spinti ai grafici durante il warm-up del Multiscan.

### File non tracciati (stato al 2026-09-07)

- `CODE_ANALYSIS.md` su `main`: audit non tracciato, **fuori perimetro** finché non
  dico il contrario. Non partire da lì.
- `software/openQCM_Next_py_0.1.5c_TEST_teensy.ino.hex` e i due hex accanto: lasciati
  lì di proposito, decideremo dopo.

⚠️ **Non tutti i dati acquisiti vanno nel repo.** Le corse fatte fuori specifica —
per esempio la scheda a 150 MHz alimentata a 3.3 V — sono diagnostica, non prove, e
per decisione di Marco **non vanno documentate né tracciate**. Prima di proporre di
versionare un dataset, chiedi in quali condizioni è stato preso.

## Una differenza fra i rami che è voluta

**N-SCALE** divide per l'ordine armonico. Su `main` solo la frequenza; su
`impedance-analysis` anche la dissipazione, e con una regola precisa: frequenza
sempre ÷n, **Γ ÷n, D mai** (`D_n = 2Γ_n/(n f₀)` è già normalizzata per armonica).
È specificato, non è deriva, e **non va riconciliato** con un cherry-pick in
nessuna delle due direzioni. La suite di verifica legge dall'ambiente quale
contratto sta controllando.
