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
APP_PASSWORD = "scegli-una-password-lunga"
ARCHIVE_DATABASE_URL = "postgresql://..."
```

`ARCHIVE_DATABASE_URL` deve essere la stringa di connessione PostgreSQL del progetto Supabase (per Streamlit usa il transaction pooler indicato in **Connect**). La tabella dell'archivio viene creata automaticamente al primo avvio. La stessa password è richiesta a tutti gli utenti; il browser può proporre di salvarla per l'autocompilazione. Non inserire segreti nel repository. In locale, imposta le variabili d'ambiente `APP_PASSWORD` e `ARCHIVE_DATABASE_URL`, oppure aggiungile a `.streamlit/secrets.toml` (file escluso da Git).

Ogni utente deve caricare il proprio database Excel nella scheda **Database**. Il file viene letto in memoria nella sessione dell'utente, non salvato nella cartella condivisa del server, e va caricato di nuovo quando si apre una nuova sessione. Anche i file Word caricati e generati non sono archiviati come archivio permanente. Evita comunque di includere dati personali reali, documenti o credenziali nel repository: un link protetto da password non sostituisce le misure di sicurezza e gli obblighi privacy applicabili.

La scheda **Archivio** salva su Supabase una copia della persona giuridica, del legale rappresentante e di uno o più titolari effettivi con le rispettive percentuali. I dati archiviati sono condivisi tra tutti gli utenti che conoscono la password; seleziona la scheda dalla pagina **Documento** per riutilizzarla anche senza ricaricare l'Excel. Usa solo dati che sei autorizzato a conservare e limita l'accesso alla password.

## Uso
1. **Configura documento**: carica il .docx (segnaposto `{{campo}}` oppure testo esistente da sostituire); per ogni campo scegli l'origine: colonna del database (per persona fisica/giuridica), testo manuale breve/lungo (premessa, condizioni economiche...) o valore fisso. Salva il modello.
2. **Compila documento**: scegli modello e tipo cliente, quindi l'anagrafica. Se il documento contiene segnaposto con suffisso `_LR` o `_TE1`, `_TE2` e successivi, la persona giuridica viene selezionata automaticamente come tipo cliente (la scelta resta modificabile). Per le persone giuridiche, `RESIDENZA` è collegata alla sede legale; i segnaposto `NOME SOCIETA`, `NOME DELLA SOCIETÀ` e `RAGIONE SOCIALE` leggono il nome dell'impresa. `[FORMA GIURIDICA]` viene ricavato dalla forma sociale in coda alla ragione sociale: SRL/S.R.L. (anche S.R.L.S.) e GmbH producono `SOCIETA' A RESPONSABILITA' LIMITATA`; UG produce `SOCIETA' IMPRENDITORIALE A RESPONSABILITA' LIMITATA`; SPA/S.P.A. e AG producono `SOCIETA' PER AZIONI`; SNC/S.N.C. e OHG producono `SOCIETA' IN NOME COLLETTIVO`; KG e GmbH & Co. KG producono `SOCIETA' IN ACCOMANDITA`; KGaA produce `SOCIETA' IN ACCOMANDITA PER AZIONI`; GbR produce `SOCIETA' DI DIRITTO CIVILE`. `RUOLO LR` riporta la carica scelta per il legale rappresentante. Puoi anche selezionare dal database il legale rappresentante e il primo titolare effettivo; i titolari aggiuntivi sono disponibili quando il documento li richiede con segnaposto `_TE2`, `_TE3` e così via. I menu a tendina restano visibili, mentre i campi anagrafici sono raccolti in sezioni espandibili chiuse all'avvio. Premessa, commissioni e percentuali restano visibili. I campi si precompilano e sono modificabili; `[COMMISSIONE ANNUALE]` e `[COMMISSIONE APERTURA]` sono campi manuali, formattati come importi italiani con valore in lettere (per esempio `2000` diventa `2.000,00 (duemila/00)`). I campi vuoti sono evidenziati con un bordo rosso nello strumento e nell'anteprima; durante la generazione tutti i segnaposto rimasti senza valore vengono rimossi dal documento scaricato.
3. **Database**: URL SQLAlchemy, tabelle e colonne etichetta (per PostgreSQL/MySQL installare il driver).
