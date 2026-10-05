"""Crea un database SQLite di esempio con due anagrafiche."""
import sqlite3
from pathlib import Path

con = sqlite3.connect(Path(__file__).parent / "anagrafica.db")
con.executescript("""
DROP TABLE IF EXISTS persone_fisiche;
DROP TABLE IF EXISTS persone_giuridiche;
CREATE TABLE persone_fisiche (
  id INTEGER PRIMARY KEY, nome TEXT, cognome TEXT, data_nascita TEXT,
  luogo_nascita TEXT, residenza TEXT, codice_fiscale TEXT);
CREATE TABLE persone_giuridiche (
  id INTEGER PRIMARY KEY, ragione_sociale TEXT, sede_legale TEXT,
  codice_fiscale TEXT, partita_iva TEXT, ruolo_societario TEXT);
""")
con.execute("INSERT INTO persone_fisiche (nome,cognome,data_nascita,luogo_nascita,residenza,codice_fiscale) VALUES ('Mario','Rossi','01/01/1980','Roma','Via Roma 1, Roma','RSSMRA80A01H501U')")
con.execute("INSERT INTO persone_giuridiche (ragione_sociale,sede_legale,codice_fiscale,partita_iva,ruolo_societario) VALUES ('Acme S.r.l.','Via Milano 10, Milano','01234567890','01234567890','Amministratore unico')")
con.commit()
