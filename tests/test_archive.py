import tempfile
import unittest
from pathlib import Path

import core


class ArchiveProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_url = f"sqlite:///{Path(self.temp_dir.name) / 'archive.db'}"
        self.payload = {
            "company": {"Codice Fiscale": "12345678901", "Ragione Sociale": "Società Uno"},
            "legal_representative": {"Codice Fiscale": "RSSMRA80A01H501U", "Cognome": "Rossi"},
            "representative_role": "Amministratore unico",
            "owners": [
                {
                    "person": {
                        "Codice Fiscale": "BNCLGU75A01H501T",
                        "Cognome": "Bianchi",
                    },
                    "percentage": "55.50",
                },
                {
                    "person": {
                        "Codice Fiscale": "VRDLRA90A01H501Y",
                        "Cognome": "Verdi",
                    },
                    "percentage": "44.50",
                },
            ],
        }

    def tearDown(self):
        core._archive_engine.cache_clear()
        self.temp_dir.cleanup()

    def test_create_update_and_delete_profile(self):
        profile_id = core.save_archive_profile(
            self.database_url, "Società Uno", self.payload
        )
        profiles = core.list_archive_profiles(self.database_url)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["id"], profile_id)
        self.assertEqual(profiles[0]["payload"]["owners"][1]["percentage"], "44.50")

        updated_payload = {**self.payload, "representative_role": "Presidente"}
        core.save_archive_profile(
            self.database_url, "Società Uno aggiornata", updated_payload, profile_id
        )
        updated = core.list_archive_profiles(self.database_url)[0]
        self.assertEqual(updated["name"], "Società Uno aggiornata")
        self.assertEqual(updated["payload"]["representative_role"], "Presidente")

        core.delete_archive_profile(self.database_url, profile_id)
        self.assertEqual(core.list_archive_profiles(self.database_url), [])

    def test_create_and_update_shared_database(self):
        original = b"original xls content"
        digest = core.save_default_database(
            self.database_url, "anagrafica.xls", original
        )
        info = core.get_default_database_info(self.database_url)
        self.assertEqual(info["filename"], "anagrafica.xls")
        self.assertEqual(info["sha256"], digest)
        self.assertEqual(
            core.get_default_database_content(self.database_url), original
        )

        replacement = b"updated xls content"
        replacement_digest = core.save_default_database(
            self.database_url, "anagrafica-aggiornata.xls", replacement
        )
        self.assertEqual(
            core.get_default_database_info(self.database_url)["sha256"],
            replacement_digest,
        )
        self.assertEqual(
            core.get_default_database_content(self.database_url), replacement
        )

    def test_rejects_empty_shared_database(self):
        with self.assertRaisesRegex(ValueError, "file Excel valido"):
            core.save_default_database(self.database_url, "vuoto.xls", b"")

    def test_rejects_duplicate_owners_and_out_of_range_percentages(self):
        duplicate_payload = {
            **self.payload,
            "owners": [self.payload["owners"][0], self.payload["owners"][0]],
        }
        with self.assertRaisesRegex(ValueError, "più di una volta"):
            core.save_archive_profile(
                self.database_url, "Società Uno", duplicate_payload
            )

        invalid_payload = {
            **self.payload,
            "owners": [{**self.payload["owners"][0], "percentage": "101"}],
        }
        with self.assertRaisesRegex(ValueError, "comprese tra 0 e 100"):
            core.save_archive_profile(
                self.database_url, "Società Uno", invalid_payload
            )

    def test_normalizes_supabase_postgres_urls_for_psycopg(self):
        engine = core._archive_engine(
            "postgresql://user.project:password@pooler.example:6543/postgres"
        )
        self.assertEqual(engine.url.drivername, "postgresql+psycopg")


if __name__ == "__main__":
    unittest.main()
