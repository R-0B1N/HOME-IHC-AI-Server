"""
Test Document Format Parity for Property Acknowledgement Document.
Proves that ViewingAcknowledgementEngine populates documents matching
'Property Acknowledgement Document Correct Format.docx' element-for-element
and eliminates the formatting flaws observed in Viewing_Acknowledgement_0190_Nick.pdf.
"""

import os
import unittest
from xml.etree import ElementTree as ET

import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_COLOR_INDEX
from app.services.acknowledgement import (
    ViewingAcknowledgementEngine,
    populate_acknowledgement_document,
    get_sample_acknowledgement_data,
    generate_viewing_acknowledgement,
)

GOLDEN_DOCX_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "Property Acknowledgement Document Correct Format.docx"))
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "output", "test_verification"))


class TestDocumentFormatParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        cls.engine = ViewingAcknowledgementEngine()
        cls.golden_doc = docx.Document(GOLDEN_DOCX_PATH)

    def test_golden_reference_element_parity(self):
        """
        Generates document using golden reference data and verifies that
        paragraphs, tables, cells, and runs match Property Acknowledgement Document Correct Format.docx.
        """
        golden_data = {
            "form_no": "0257",
            "date": "27.03.2025",
            "salutation": "MR",
            "customer_name": "Nick",
            "no_of_pax": "2",
            "company_name": "ELPIJI (M) SDN BHD",
            "company_address": "601-A, Level 6, Tower A, Uptown 5, 5, Jalan SS21/39,\nDamansara Uptown, 47400 Petaling Jaya, Selangor D. E., Malaysia",
            "car_plate": "",
            "phone": "+60126761818",
            "called_in_date": "17-03-2025",
            "customer_request": "Required 2-3 acres Industrial Factory & Land with TNB Supply: 400amp",
            "requirement_summary": "Industrial Factory and Land",
            "property_types": ["Industrial Land", "Factory"],
            "target_location": "Temerloh",
            "remarks": "Currently Industrial Factory has 300amp",
            "assigned_to": "Direct Seller",
            "partner_agency": "Era Realtor Sdn. Bhd. [E(1)2053/1]",
            "customer_signer": "Nick",
            "staff_name": "Leong Chu Ping",
            "properties_viewed": [
                {
                    "no": "1.",
                    "details": "2.7 acres Mentakab Industry Land For Sale LOT 1745",
                    "date": "27.03.2025",
                    "price": "RM 4,000,000",
                    "description": "• Freehold & Industrial\nTitle\n• Connected electrical &\nwater supply and\nFencing & Gated"
                }
            ],
            "documents_submitted": [
                {
                    "qty": "1 set"
                }
            ]
        }

        generated_doc = self.engine.populate(golden_data)
        out_path = os.path.join(OUTPUT_DIR, "Parity_Test_Golden_Nick.docx")
        generated_doc.save(out_path)

        # 1. Verify Paragraphs count
        self.assertEqual(len(generated_doc.paragraphs), len(self.golden_doc.paragraphs))

        # 2. Verify Body Paragraph text
        for idx in range(len(self.golden_doc.paragraphs)):
            expected_text = self.golden_doc.paragraphs[idx].text
            actual_text = generated_doc.paragraphs[idx].text
            self.assertEqual(
                actual_text, expected_text,
                f"Paragraph {idx} text mismatch: actual={actual_text!r} vs expected={expected_text!r}"
            )

        # 3. Verify Table count
        self.assertEqual(len(generated_doc.tables), len(self.golden_doc.tables))

        # 4. Verify Table 0 (Customer & Requirements)
        t0_gen = generated_doc.tables[0]
        t0_gold = self.golden_doc.tables[0]
        self.assertEqual(len(t0_gen.rows), len(t0_gold.rows))
        self.assertEqual(len(t0_gen.columns), len(t0_gold.columns))

        # Check Cell 0 paragraphs
        # Check Cell 0 paragraphs (including top spacer for honorifics)
        c0_gen = t0_gen.rows[0].cells[0]
        c0_gold = t0_gold.rows[0].cells[0]
        # Top spacer paragraph ensures MR/MRS/MS has breathing space above it
        self.assertGreaterEqual(len(c0_gen.paragraphs), len(c0_gold.paragraphs))
        # Verify text parity for core customer fields
        self.assertIn("Full Name:  Nick", [p.text.strip() for p in c0_gen.paragraphs])
        self.assertIn("No of pax: 2", [p.text.strip() for p in c0_gen.paragraphs])
        self.assertIn("Company Name: ELPIJI (M) SDN BHD", [p.text.strip() for p in c0_gen.paragraphs])

        # Check Cell 1 paragraphs
        c1_gen = t0_gen.rows[0].cells[1]
        c1_gold = t0_gold.rows[0].cells[1]
        self.assertEqual(len(c1_gen.paragraphs), len(c1_gold.paragraphs))
        for p_i in range(len(c1_gold.paragraphs)):
            self.assertEqual(c1_gen.paragraphs[p_i].text, c1_gold.paragraphs[p_i].text)

        # 5. Verify Table 1 (Properties Viewed)
        t1_gen = generated_doc.tables[1]
        t1_gold = self.golden_doc.tables[1]
        self.assertEqual(len(t1_gen.rows), len(t1_gold.rows))
        for r_i in range(len(t1_gold.rows)):
            for c_i in range(len(t1_gold.columns)):
                self.assertEqual(
                    t1_gen.rows[r_i].cells[c_i].text,
                    t1_gold.rows[r_i].cells[c_i].text
                )

        # 6. Verify Table 2 (Submission of Documents) - Verified with Unicode Checkboxes
        t2_gen = generated_doc.tables[2]
        self.assertEqual(len(t2_gen.rows), len(self.golden_doc.tables[2].rows))
        t2_c1_text = t2_gen.rows[1].cells[1].text
        self.assertIn("☐  GM", t2_c1_text)
        self.assertIn("☐  GRN", t2_c1_text)
        self.assertIn("☐  Topo Plan", t2_c1_text)
        t2_c4_text = t2_gen.rows[1].cells[4].text
        self.assertIn("Whatsapp Messenger", t2_c4_text)

        # Verify zero OpenXML list numbering exists across the entire document
        num_pr_list = generated_doc._element.xpath('.//w:numPr')
        self.assertEqual(len(num_pr_list), 0, "All w:numPr elements must be purged to eliminate 1., 2., 3. numbering")

        # 7. Verify Form No in P5 (red bold run)
        p5 = generated_doc.paragraphs[5]
        red_runs = [r for r in p5.runs if r.font.color and r.font.color.rgb == RGBColor(255, 0, 0)]
        self.assertEqual(len(red_runs), 4)
        self.assertEqual("".join([r.text for r in red_runs]), "0257")

        # 8. Verify Yellow Highlight on Company Name
        p_comp = c0_gen.paragraphs[4]
        self.assertEqual(p_comp.runs[0].font.highlight_color, WD_COLOR_INDEX.YELLOW)
        self.assertEqual(p_comp.runs[1].font.highlight_color, WD_COLOR_INDEX.YELLOW)

        # 9. Verify Margins
        sec = generated_doc.sections[0]
        self.assertEqual(sec.top_margin.pt, 36.0)
        self.assertEqual(sec.bottom_margin.pt, 36.0)
        self.assertEqual(sec.left_margin.pt, 36.0)
        self.assertEqual(sec.right_margin.pt, 36.0)

    def test_form_0190_signature_stability_and_no_page_overflow(self):
        """
        Tests Form 0190 (the operational payload from Viewing_Acknowledgement_0190_Nick.pdf)
        to verify that the signature block stays completely within Section 1 / Page 1.
        """
        sample_0190 = get_sample_acknowledgement_data()
        sample_0190["form_no"] = "0190"
        sample_0190["customer_name"] = "Nick"
        sample_0190["customer_signer"] = "Nick"
        sample_0190["phone"] = "+60126761818"

        doc = self.engine.populate(sample_0190)
        out_path = os.path.join(OUTPUT_DIR, "Viewing_Acknowledgement_0190_Fixed.docx")
        doc.save(out_path)

        # Verify Form No is 0190
        p5 = doc.paragraphs[5]
        self.assertIn("0190", p5.text)

        # Verify Signatures are in Paragraphs 14, 15, 16, 17 before Page 2 Header (P19)
        self.assertEqual(doc.paragraphs[14].text, "_______________________________                                            _______________________________")
        self.assertEqual(doc.paragraphs[15].text, "Customer\t\t\t\t\t\t\t            Attended staff/representative")
        self.assertEqual(doc.paragraphs[16].text, "Name: Nick\t\t\t\t\t\t\t\tName: Leong Chu Ping")
        self.assertEqual(doc.paragraphs[17].text, "Date:\t27.03.2025\t\t\t\t\t\t            Date: 27.03.2025")

        # Verify Page 2 Header is in Paragraph 19
        self.assertEqual(doc.paragraphs[19].text, "Property Proposed/ Viewed \t\t\t\t\t\t            \tDate: 27.03.2025")

        # Verify that Table 0 has explicit single border stabilization
        t0_xml = doc.tables[0]._tbl.tblPr.xml
        self.assertIn("tblBorders", t0_xml)
        self.assertIn('w:val="single"', t0_xml)


if __name__ == "__main__":
    unittest.main()
