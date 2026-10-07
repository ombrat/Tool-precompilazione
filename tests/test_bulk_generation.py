import io
import unittest
import zipfile

import core


class BulkGenerationTests(unittest.TestCase):
    def test_classifies_customer_from_first_fiscal_code_character(self):
        self.assertEqual(core.classify_customer_type("RSSMRA80A01H501U"), "fisica")
        self.assertEqual(core.classify_customer_type("12345678901"), "giuridica")
        self.assertIsNone(core.classify_customer_type(""))
        self.assertIsNone(core.classify_customer_type("-1234567890"))

    def test_splits_additional_legal_representative_and_owner_placeholders(self):
        self.assertEqual(core.split_role("COGNOME_LR2"), ("COGNOME", "LR2"))
        self.assertEqual(core.split_role("PERCENTUALE_TE3"), ("PERCENTUALE", "TE3"))
        self.assertEqual(core.role_label("LR2"), "Legale rappresentante 2")
        self.assertEqual(core.role_label("TE3"), "Titolare effettivo 3")

    def test_creates_zip_with_individual_documents(self):
        content = core.create_document_archive(
            [("Mandato Mario Rossi.docx", b"persona fisica"),
             ("Mandato Societa Uno.docx", b"persona giuridica")]
        )

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(
                archive.namelist(),
                ["Mandato Mario Rossi.docx", "Mandato Societa Uno.docx"],
            )
            self.assertEqual(
                archive.read("Mandato Mario Rossi.docx"), b"persona fisica"
            )
            self.assertEqual(
                archive.read("Mandato Societa Uno.docx"), b"persona giuridica"
            )


if __name__ == "__main__":
    unittest.main()
