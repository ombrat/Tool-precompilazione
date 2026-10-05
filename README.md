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
2. **Compila documento**: scegli modello, tipo cliente, anagrafica; i campi si precompilano e sono modificabili; `[COMMISSIONE ANNUALE]` e `[COMMISSIONE APERTURA]` sono campi manuali, formattati come importi italiani con valore in lettere (per esempio `2000` diventa `2.000,00 (duemila/00)`). I campi vuoti sono evidenziati con un bordo rosso nello strumento e nell'anteprima; scarica il .docx.
3. **Database**: URL SQLAlchemy, tabelle e colonne etichetta (per PostgreSQL/MySQL installare il driver).
