# Tool-precompilazione
Tool per precompilare documenti tramite database anagrafico

## Avvio
```
pip install -r requirements.txt
python seed_db.py        # opzionale: DB SQLite di esempio
streamlit run app.py
```

## Uso
1. **Configura documento**: carica il .docx (segnaposto `{{campo}}` oppure testo esistente da sostituire); per ogni campo scegli l'origine: colonna del database (per persona fisica/giuridica), testo manuale breve/lungo (premessa, condizioni economiche...) o valore fisso. Salva il modello.
2. **Compila documento**: scegli modello e tipo cliente, quindi l'anagrafica. Per le persone giuridiche, `RESIDENZA` è collegata alla sede legale; i segnaposto `NOME SOCIETA`, `NOME DELLA SOCIETÀ` e `RAGIONE SOCIALE` leggono il nome dell'impresa. `RUOLO LR` riporta la carica scelta per il legale rappresentante. Puoi anche selezionare dal database il legale rappresentante e il primo titolare effettivo; i titolari aggiuntivi sono disponibili quando il documento li richiede con segnaposto `_TE2`, `_TE3` e così via. I menu a tendina restano visibili, mentre i campi anagrafici sono raccolti in sezioni espandibili chiuse all'avvio. Premessa, commissioni e percentuali restano visibili. I campi si precompilano e sono modificabili; `[COMMISSIONE ANNUALE]` e `[COMMISSIONE APERTURA]` sono campi manuali, formattati come importi italiani con valore in lettere (per esempio `2000` diventa `2.000,00 (duemila/00)`). I campi vuoti sono evidenziati con un bordo rosso nello strumento e nell'anteprima; durante la generazione tutti i segnaposto rimasti senza valore vengono rimossi dal documento scaricato.
3. **Database**: URL SQLAlchemy, tabelle e colonne etichetta (per PostgreSQL/MySQL installare il driver).
