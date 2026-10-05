# Tool-precompilazione

Tool web per precompilare documenti Word a partire da un database di anagrafiche.

## Avvio

    pip install -r requirements.txt
    python -m precompilazione          # http://127.0.0.1:5000

## Flusso

1. **Carica il file Word**. Nel documento scrivi i campi come `{{nome_campo}}`
   (es. `{{ragione_sociale}}`, `{{premessa}}`). Il tool li rileva anche nelle tabelle, intestazioni e piè di pagina.
2. **Configura** ogni campo:
   - *Dal database*: scegli la colonna dell'anagrafica da usare;
   - *Testo libero*: spazio personalizzabile (campo di testo breve);
   - *Testo lungo*: spazio personalizzabile multiriga (premessa, condizioni economiche, ...);
   - opzionalmente un valore predefinito (anche per i campi DB, usato se la colonna è vuota).
   Imposta il database esterno (file SQLite, tabella, colonna del tipo cliente e colonna di visualizzazione).
3. **Precompila**: scegli tipo cliente (Persona fisica / giuridica), seleziona l'anagrafica,
   compila gli spazi aggiuntivi e scarica il `.docx` generato.

Alla prima esecuzione viene creato un database di esempio in `data/anagrafiche.db`.
Variabile d'ambiente `PRECOMP_DATA` per cambiare la cartella dati.

## Test

    pytest
