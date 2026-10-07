# Tool-precompilazione
Tool per precompilare documenti tramite database anagrafico

## Avvio
```
pip install -r requirements.txt
python seed_db.py        # opzionale: DB SQLite di esempio
streamlit run app.py
```

### Avvio locale su Windows
1. Installa Python 3 e Microsoft Word (desktop, installato e attivato).
2. Estrai tutti i file del pacchetto in una cartella locale.
3. Fai doppio clic su `Avvia-Tool-Windows.bat`; al primo avvio installa automaticamente le dipendenze e apre il programma nel browser.
4. Nella scheda **Database**, seleziona il tuo file Excel `.xls`. Il database non è incluso nel pacchetto.

Su Windows, l'anteprima e le conversioni `.doc`/`.docx`/PDF vengono eseguite da Microsoft Word tramite automazione COM; non è necessario installare LibreOffice. Lascia Word chiuso mentre lo strumento converte i documenti. Sugli altri sistemi operativi resta utilizzato LibreOffice.

## Pubblicazione gratuita

L'app può essere pubblicata su [Streamlit Community Cloud](https://share.streamlit.io/) collegando il repository GitHub e scegliendo `app.py` come file principale. Le dipendenze di sistema per LibreOffice sono elencate in `packages.txt`.

Prima di avviarla, configura i segreti nelle impostazioni dell'app su Streamlit Community Cloud:

```toml
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_..."
APP_PASSWORD = "solo-se-non-usi-l-autenticazione-a-due-fattori"
ARCHIVE_DATABASE_URL = "postgresql://..."
SUPABASE_URL = "https://<project-ref>.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "..."
SUPABASE_TEMPLATES_BUCKET = "document-templates"
```

`ARCHIVE_DATABASE_URL` deve essere la stringa di connessione PostgreSQL del progetto Supabase (per Streamlit usa il transaction pooler indicato in **Connect**). Le tabelle dell'archivio vengono create automaticamente al primo avvio. La stessa password è richiesta a tutti gli utenti; il browser può proporre di salvarla per l'autocompilazione. Non inserire segreti nel repository. In locale, imposta le variabili d'ambiente qui sopra oppure aggiungile a `.streamlit/secrets.toml` (file escluso da Git).

### Autenticazione a due fattori (TOTP)

Se sono configurati `SUPABASE_URL` e `SUPABASE_PUBLISHABLE_KEY` (chiave pubblicabile `sb_publishable_...`, non la secret), l'accesso richiede email e password dell'account personale più un codice TOTP; `APP_PASSWORD` non viene più usata. Per attivarla in Supabase:

1. **Authentication → Sign In / Providers**: lascia attivo il provider Email e **disattiva le registrazioni autonome** (Allow new users to sign up).
2. **Authentication → Users → Add user**: crea un account per ciascun utente autorizzato (con *Auto Confirm User*).
3. Al primo accesso l'utente scansiona il QR con Google/Microsoft Authenticator o simili e conferma il codice; dagli accessi successivi basta il codice a 6 cifre. Il TOTP è incluso nel piano gratuito.

Per recuperare l'accesso di un utente che perde il telefono, elimina il suo fattore in **Authentication → Users**: al prossimo accesso potrà registrarne uno nuovo.

`SUPABASE_URL` è l'URL del progetto. `SUPABASE_SERVICE_ROLE_KEY` è la chiave privata di servizio del progetto: configurala solo nei Secrets/variabili d'ambiente, mai nel repository o nel browser. `SUPABASE_TEMPLATES_BUCKET` è facoltativo e, se omesso, usa `document-templates`.

Crea in Supabase Storage un bucket **privato** chiamato `document-templates` e carica direttamente nella radice un modello per ciascun tipo, in formato `.doc` oppure `.docx`:

- `persona-fisica.doc` oppure `persona-fisica.docx` per le persone fisiche
- `persona-giuridica.doc` oppure `persona-giuridica.docx` per le persone giuridiche

Nella scheda **Documento**, selezionando il tipo cliente viene caricato il relativo modello dal bucket; l'app cerca prima `.docx` e, se non presente, usa `.doc`. I file `.doc` vengono convertiti automaticamente in `.docx` per la compilazione. Puoi sostituire i file direttamente in Supabase per aggiornare i modelli; la nuova versione viene rilevata al successivo aggiornamento dopo al massimo un minuto. Per una singola sessione puoi anche caricare un documento locale come override. I modelli devono contenere i segnaposto che vuoi compilare. La chiave di servizio dà accesso privilegiato al progetto: limita l'accesso ai Secrets dell'app e non rendere pubblico il bucket.

La scheda **Database** usa l'anagrafica condivisa salvata su Supabase come fonte predefinita. Per crearla o sostituirla, carica un file `.xls` e premi **Salva o aggiorna l'anagrafica condivisa**; sarà poi disponibile nelle sessioni successive senza ricaricarlo. In assenza di `ARCHIVE_DATABASE_URL`, resta possibile caricare un file per la sola sessione corrente. Chiunque conosca la password comune dell'app può aggiornare l'anagrafica condivisa. I documenti caricati localmente e quelli generati non sono archiviati in modo permanente dall'app; i due modelli caricati manualmente su Supabase sono invece conservati nel bucket. Evita comunque di includere dati personali reali, documenti o credenziali nel repository: un link protetto da password non sostituisce le misure di sicurezza e gli obblighi privacy applicabili.

La scheda **Archivio** salva su Supabase una copia della persona giuridica, del legale rappresentante e di uno o più titolari effettivi con le rispettive percentuali. I dati archiviati sono condivisi tra tutti gli utenti che conoscono la password; dalla pagina **Documento**, seleziona una società presente nell'anagrafica condivisa e usa **Usa scheda salvata** per riutilizzarne i dati. Usa solo dati che sei autorizzato a conservare e limita l'accesso alla password.

## Uso
1. **Prepara i modelli**: carica i due documenti nella radice del bucket `document-templates`, usando i nomi indicati sopra e mantenendo l'estensione `.doc` o `.docx`; inserisci nei file i segnaposto `{{campo}}` oppure il testo esistente da sostituire.
2. **Documento singolo**: scegli persona fisica o giuridica; l'app carica il modello corrispondente, poi seleziona l'anagrafica. Per le persone giuridiche, `RESIDENZA` è collegata alla sede legale; i segnaposto `NOME SOCIETA`, `NOME DELLA SOCIETÀ` e `RAGIONE SOCIALE` leggono il nome dell'impresa. `[FORMA GIURIDICA]` viene ricavato dalla forma sociale in coda alla ragione sociale: SRL/S.R.L. (anche S.R.L.S.) e GmbH producono `SOCIETA' A RESPONSABILITA' LIMITATA`; UG produce `SOCIETA' IMPRENDITORIALE A RESPONSABILITA' LIMITATA`; SPA/S.P.A. e AG producono `SOCIETA' PER AZIONI`; SNC/S.N.C. e OHG producono `SOCIETA' IN NOME COLLETTIVO`; KG e GmbH & Co. KG producono `SOCIETA' IN ACCOMANDITA`; KGaA produce `SOCIETA' IN ACCOMANDITA PER AZIONI`; GbR produce `SOCIETA' DI DIRITTO CIVILE`. `RUOLO LR` riporta la carica scelta per il legale rappresentante. Puoi anche selezionare dal database il legale rappresentante e il primo titolare effettivo; i titolari aggiuntivi sono disponibili quando il documento li richiede con segnaposto `_TE2`, `_TE3` e così via. Se generi un mandato per una persona giuridica senza scheda archiviata, l'app salva automaticamente i dati del legale rappresentante e dei titolari effettivi compilati nel documento, se l'archivio è configurato. I menu a tendina restano visibili, mentre i campi anagrafici sono raccolti in sezioni espandibili chiuse all'avvio. Premessa, commissioni e percentuali restano visibili. I campi si precompilano e sono modificabili; `[COMMISSIONE ANNUALE]` e `[COMMISSIONE APERTURA]` sono campi manuali, formattati come importi italiani con valore in lettere (per esempio `2000` diventa `2.000,00 (duemila/00)`). I campi vuoti sono evidenziati con un bordo rosso nello strumento e nell'anteprima; durante la generazione tutti i segnaposto rimasti senza valore vengono rimossi dal documento scaricato.
3. **Generazione massiva**: nella scheda dedicata carica o usa i modelli per persone fisiche e giuridiche, seleziona più anagrafiche e, per ogni persona giuridica, indica almeno un legale rappresentante e un titolare effettivo. Le selezioni della fase 1 e le variabili della fase 2 vengono inviate in blocco con i pulsanti di conferma. Puoi tornare dalla compilazione dei dati specifici ai legali/titolari e da lì alla selezione delle anagrafiche; le modifiche già inserite vengono mantenute. Se la società ha una scheda nell'archivio, i dati dei legali rappresentanti e dei titolari effettivi vengono precompilati e restano modificabili. Se non esiste ancora una scheda, le informazioni societarie vengono salvate automaticamente nell'archivio quando confermi i legali rappresentanti e i titolari effettivi; la scheda sarà disponibile nelle sessioni successive. Puoi aggiungere altri legali rappresentanti (con la rispettiva carica) e titolari effettivi (con percentuale; il ruolo è socio). Le percentuali vengono visualizzate in formato italiano con due decimali e simbolo `%`. I dati dei titolari aggiuntivi richiedono i segnaposto `_TE2`, `_TE3` e così via; i legali rappresentanti aggiuntivi richiedono i segnaposto `_LR2`, `_LR3` e così via. La classificazione usa il primo carattere del codice fiscale: lettera per persona fisica, cifra per persona giuridica. Nella seconda fase inserisci premessa, commissioni e le altre variabili manuali per ciascun mandato. Il download è un archivio ZIP con un documento Word distinto per ogni anagrafica, nominato `Mandato <anagrafica>`.
4. **Database**: URL SQLAlchemy, tabelle e colonne etichetta (per PostgreSQL/MySQL installare il driver).
