import tempfile
import urllib.error
import unittest
from unittest.mock import patch
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


class SupabaseDocumentTemplateTests(unittest.TestCase):
    @patch("core.urllib.request.urlopen")
    def test_loads_customer_type_template_from_private_storage(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b"docx content"

        content = core.load_supabase_document_template(
            "https://project.supabase.co/",
            "service-role-secret",
            "document-templates",
            "giuridica",
        )

        self.assertEqual(content, (b"docx content", "persona-giuridica.docx"))
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://project.supabase.co/storage/v1/object/authenticated/"
            "document-templates/persona-giuridica.docx",
        )
        self.assertEqual(request.get_header("Apikey"), "service-role-secret")
        self.assertEqual(
            request.get_header("Authorization"), "Bearer service-role-secret"
        )

    @patch("core.urllib.request.urlopen")
    def test_reports_missing_template(self, urlopen):
        urlopen.side_effect = [
            urllib.error.HTTPError(
                "https://project.supabase.co/storage/v1/object/authenticated/"
                "document-templates/persona-fisica.docx",
                404,
                "Not Found",
                {},
                None,
            ),
            urllib.error.HTTPError(
                "https://project.supabase.co/storage/v1/object/authenticated/"
                "document-templates/persona-fisica.doc",
                404,
                "Not Found",
                {},
                None,
            ),
        ]
        with self.assertRaisesRegex(FileNotFoundError, "persona-fisica.docx.*persona-fisica.doc"):
            core.load_supabase_document_template(
                "https://project.supabase.co",
                "service-role-secret",
                "document-templates",
                "fisica",
            )

    @patch("core.urllib.request.urlopen")
    def test_falls_back_to_doc_template(self, urlopen):
        docx_not_found = urllib.error.HTTPError(
            "https://project.supabase.co/storage/v1/object/authenticated/"
            "document-templates/persona-fisica.docx",
            404,
            "Not Found",
            {},
            None,
        )
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b"legacy doc content"
        urlopen.side_effect = [
            docx_not_found,
            urlopen.return_value,
        ]

        content = core.load_supabase_document_template(
            "https://project.supabase.co",
            "service-role-secret",
            "document-templates",
            "fisica",
        )

        self.assertEqual(content, (b"legacy doc content", "persona-fisica.doc"))
        self.assertEqual(urlopen.call_count, 2)

    def test_rejects_unknown_customer_type(self):
        with self.assertRaisesRegex(ValueError, "Tipo cliente non valido"):
            core.load_supabase_document_template(
                "https://project.supabase.co",
                "service-role-secret",
                "document-templates",
                "unknown",
            )


if __name__ == "__main__":
    unittest.main()
