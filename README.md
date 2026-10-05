# Tool-precompilazione
Tool per precompilare documenti tramite database anagrafico

## Avvio
```
pip install -r requirements.txt
python seed_db.py        # opzionale: DB SQLite di esempio
streamlit run app.py
```

### Avvio locale su Windows
1. Installa Python 3 e LibreOffice.
2. Estrai tutti i file del pacchetto in una cartella locale.
3. Fai doppio clic su `Avvia-Tool-Windows.bat`; al primo avvio installa automaticamente le dipendenze e apre il programma nel browser.
4. Nella scheda **Database**, seleziona il tuo file Excel `.xls`. Il database non è incluso nel pacchetto.

LibreOffice deve essere raggiungibile dal PATH; lo script aggiunge automaticamente il percorso di installazione predefinito `C:\Program Files\LibreOffice\program`.

## Uso
1. **Configura documento**: carica il .docx (segnaposto `{{campo}}` oppure testo esistente da sostituire); per ogni campo scegli l'origine: colonna del database (per persona fisica/giuridica), testo manuale breve/lungo (premessa, condizioni economiche...) o valore fisso. Salva il modello.
2. **Compila documento**: scegli modello e tipo cliente, quindi l'anagrafica. Se il documento contiene segnaposto con suffisso `_LR` o `_TE1`, `_TE2` e successivi, la persona giuridica viene selezionata automaticamente come tipo cliente (la scelta resta modificabile). Per le persone giuridiche, `RESIDENZA` è collegata alla sede legale; i segnaposto `NOME SOCIETA`, `NOME DELLA SOCIETÀ` e `RAGIONE SOCIALE` leggono il nome dell'impresa. `[FORMA GIURIDICA]` viene ricavato dalla forma sociale in coda alla ragione sociale: SRL/S.R.L. (anche S.R.L.S.) e GmbH producono `SOCIETA' A RESPONSABILITA' LIMITATA`; UG produce `SOCIETA' IMPRENDITORIALE A RESPONSABILITA' LIMITATA`; SPA/S.P.A. e AG producono `SOCIETA' PER AZIONI`; SNC/S.N.C. e OHG producono `SOCIETA' IN NOME COLLETTIVO`; KG e GmbH & Co. KG producono `SOCIETA' IN ACCOMANDITA`; KGaA produce `SOCIETA' IN ACCOMANDITA PER AZIONI`; GbR produce `SOCIETA' DI DIRITTO CIVILE`. `RUOLO LR` riporta la carica scelta per il legale rappresentante. Puoi anche selezionare dal database il legale rappresentante e il primo titolare effettivo; i titolari aggiuntivi sono disponibili quando il documento li richiede con segnaposto `_TE2`, `_TE3` e così via. I menu a tendina restano visibili, mentre i campi anagrafici sono raccolti in sezioni espandibili chiuse all'avvio. Premessa, commissioni e percentuali restano visibili. I campi si precompilano e sono modificabili; `[COMMISSIONE ANNUALE]` e `[COMMISSIONE APERTURA]` sono campi manuali, formattati come importi italiani con valore in lettere (per esempio `2000` diventa `2.000,00 (duemila/00)`). I campi vuoti sono evidenziati con un bordo rosso nello strumento e nell'anteprima; durante la generazione tutti i segnaposto rimasti senza valore vengono rimossi dal documento scaricato.
3. **Database**: URL SQLAlchemy, tabelle e colonne etichetta (per PostgreSQL/MySQL installare il driver).
