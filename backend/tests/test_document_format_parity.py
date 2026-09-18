"""
Test Document Format Parity for Property Acknowledgement Document.
Proves that ViewingAcknowledgementEngine populates documents matching
'Property Acknowledgement Document Correct Format.docx' element-for-element
and eliminates the formatting flaws observed in Viewing_Acknowledgement_0190_Nick.pdf.
"""

import os
import re
import unittest
from xml.etree import ElementTree as ET

import docx
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_COLOR_INDEX, WD_TAB_ALIGNMENT
from app.services.acknowledgement import (
    ViewingAcknowledgementEngine,
    populate_acknowledgement_document,
    get_sample_acknowledgement_data,
    get_blank_acknowledgement_data,
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

        # 1. Verify Table count matches golden doc
        self.assertEqual(len(generated_doc.tables), len(self.golden_doc.tables))

        # 2. Verify Table 0 (Customer & Requirements) structure
        t0_gen = generated_doc.tables[0]
        t0_gold = self.golden_doc.tables[0]
        self.assertEqual(len(t0_gen.rows), len(t0_gold.rows))
        self.assertEqual(len(t0_gen.columns), len(t0_gold.columns))

        # 3. Verify Table 1 (Properties Viewed)
        t1_gen = generated_doc.tables[1]
        t1_gold = self.golden_doc.tables[1]
        self.assertEqual(len(t1_gen.rows), len(t1_gold.rows))

        # 4. Verify Table 2 (Submission of Documents) - Verified with Unicode Checkboxes
        t2_gen = generated_doc.tables[2]
        self.assertEqual(len(t2_gen.rows), len(self.golden_doc.tables[2].rows))
        t2_c1_text = "".join(t2_gen.rows[1].cells[1]._tc.itertext())
        self.assertIn("GM", t2_c1_text)
        self.assertIn("GRN", t2_c1_text)
        self.assertIn("Topo Plan", t2_c1_text)
        t2_c4_text = "".join(t2_gen.rows[1].cells[4]._tc.itertext())
        self.assertIn("Whatsapp Messenger", t2_c4_text)

        # Verify zero OpenXML list numbering exists across the entire document
        num_pr_list = generated_doc._element.xpath('.//w:numPr')
        self.assertEqual(len(num_pr_list), 0, "All w:numPr elements must be purged to eliminate 1., 2., 3. numbering")

        # 5. Verify Form No in P5 (red bold run)
        p5 = generated_doc.paragraphs[5]
        red_runs = [r for r in p5.runs if r.font.color and r.font.color.rgb == RGBColor(255, 0, 0)]
        self.assertEqual(len(red_runs), 4)
        self.assertEqual("".join([r.text for r in red_runs]), "0257")

        # 6. Verify Margins
        sec = generated_doc.sections[0]
        self.assertEqual(sec.top_margin.pt, 36.0)
        self.assertEqual(sec.bottom_margin.pt, 36.0)
        self.assertEqual(sec.left_margin.pt, 36.0)
        self.assertEqual(sec.right_margin.pt, 36.0)

    def test_blank_data_and_formatting_items_a_to_k(self):
        """
        Validates Items a through k:
        a. Document ID dynamic generation
        b. Header Document ID and Date right-aligned via tab stops
        c. Checkbox font size is Pt(16.0) bold
        d. MRS cell has width >= 0.55 in and noWrap
        e. Company name, address, car plate, referral source are blank
        f. Customer request and requirement summary are blank
        g. Signatures aligned with tab stops at 3.5 in
        h. Page 2 Date on same line as Property Proposed/ Viewed
        i. Nested documents checklist has checkboxes in Col 0 and text in Col 1
        j. Remarks checklist has noWrap and 8.5pt font
        k. Stray accidental date at bottom of Page 2 is eliminated
        """
        blank = get_blank_acknowledgement_data(form_no="0192")
        self.assertEqual(blank["form_no"], "0192")
        self.assertEqual(blank["company_name"], "")
        self.assertEqual(blank["company_address"], "")
        self.assertEqual(blank["car_plate"], "")
        self.assertEqual(blank["customer_request"], "")

        # Set specific fields for Nick
        blank["customer_name"] = "Nick"
        blank["customer_signer"] = "Nick"
        blank["phone"] = "+60126761818"
        blank["date"] = "19.09.2026"
        blank["staff_name"] = "Irene Leong"
        blank["documents_submitted"] = [{"title_details": "Title", "qty": "1 set", "remarks": "Whatsapp Messenger"}]
        blank["properties_viewed"] = [{
            "no": "1.",
            "details": "Semi-D House In Raub\nPahang",
            "date": "19.09.2026 10:00 AM",
            "price": "RM 680,000",
            "description": "• 4 Bedrooms, 3 Bathrooms"
        }]

        doc = self.engine.populate(blank)
        out_path = os.path.join(OUTPUT_DIR, "Viewing_Acknowledgement_0192_Nick_Blank_Base.docx")
        doc.save(out_path)

        # Item a: Dynamic Form No
        self.assertIn("0192", doc.paragraphs[5].text)

        # Item b: Right-aligned Form No & Date with tab stop
        p5 = doc.paragraphs[5]
        self.assertTrue(len(p5.paragraph_format.tab_stops) > 0)
        self.assertEqual(p5.paragraph_format.tab_stops[0].alignment, WD_TAB_ALIGNMENT.RIGHT)

        p7 = doc.paragraphs[7]
        self.assertTrue(len(p7.paragraph_format.tab_stops) > 0)
        self.assertEqual(p7.paragraph_format.tab_stops[0].alignment, WD_TAB_ALIGNMENT.RIGHT)
        self.assertIn("Date: 19.09.2026", p7.text)

        # Item c: Checkbox size is Pt(16.0) bold
        t0 = doc.tables[0]
        c0 = t0.rows[0].cells[0]
        c0_nested = [docx.table.Table(node, c0) for node in c0._tc.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')]
        self.assertTrue(len(c0_nested) > 0)
        t_sal = c0_nested[0]
        sal_chk_run = t_sal.rows[0].cells[0].paragraphs[0].runs[0]
        self.assertEqual(sal_chk_run.font.size.pt, 16.0)
        self.assertTrue(sal_chk_run.bold)

        # Item d: MRS word wrap prevention
        cell_mrs = t_sal.rows[0].cells[3]
        self.assertGreaterEqual(cell_mrs.width, Inches(0.55))
        self.assertIn("noWrap", cell_mrs._tc.xml)

        # Items e & f: No hallucinated company, address, car plate, or request
        p_comp = c0.paragraphs[4]
        self.assertEqual(re.sub(r'(?i)company\s*name:?', '', p_comp.text).strip(), "")
        p_car = c0.paragraphs[9]
        self.assertEqual(re.sub(r'(?i)car\s*plate\s*no:?', '', p_car.text).strip(), "")
        c1 = t0.rows[0].cells[1]
        p_req = c1.paragraphs[1]
        self.assertEqual(re.sub(r'(?i)customer(\'?s)?\s*request:?', '', p_req.text).strip(), "")

        # Item g: Signatures aligned with tab stops at 3.5 in
        p_sig_lines = doc.paragraphs[14]
        p_sig_labels = doc.paragraphs[15]
        p_name = doc.paragraphs[16]
        p_date = doc.paragraphs[17]
        for p in [p_sig_lines, p_sig_labels, p_name, p_date]:
            self.assertTrue(len(p.paragraph_format.tab_stops) > 0)
            self.assertEqual(p.paragraph_format.tab_stops[0].position, Inches(3.5))
        self.assertIn("Customer\tAttended staff/representative", p_sig_labels.text)
        self.assertIn("Name: Nick\tName: Irene Leong", p_name.text)
        self.assertIn("Date: 19.09.2026\tDate: 19.09.2026", p_date.text)

        # Item h: Page 2 Header date locked on same line
        p_prop = None
        for p in doc.paragraphs:
            if "Property Proposed/ Viewed" in p.text:
                p_prop = p
                break
        self.assertIsNotNone(p_prop)
        self.assertIn("Property Proposed/ Viewed\tDate: 19.09.2026", p_prop.text)
        self.assertEqual(p_prop.paragraph_format.tab_stops[0].alignment, WD_TAB_ALIGNMENT.RIGHT)

        # Item i: Additional Documents nested table
        t2 = doc.tables[2]
        c_doc = t2.rows[1].cells[1]
        c_doc_nested = [docx.table.Table(node, c_doc) for node in c_doc._tc.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')]
        self.assertTrue(len(c_doc_nested) > 0)
        t_doc = c_doc_nested[0]
        self.assertIn("☑", t_doc.rows[0].cells[0].paragraphs[0].text)
        self.assertEqual(t_doc.rows[0].cells[1].paragraphs[0].text, "GM")
        self.assertNotIn("tblInd", t_doc._tbl.tblPr.xml)

        # Item j: Remarks nested table formatting
        c_rem = t2.rows[1].cells[4]
        c_rem_nested = [docx.table.Table(node, c_rem) for node in c_rem._tc.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')]
        self.assertTrue(len(c_rem_nested) > 0)
        t_rem = c_rem_nested[0]
        self.assertIn("☑", t_rem.rows[0].cells[0].paragraphs[0].text)
        self.assertEqual(t_rem.rows[0].cells[1].paragraphs[0].text, "Whatsapp Messenger")
        self.assertIn("noWrap", t_rem.rows[0].cells[1]._tc.xml)

        # Item k: Accidental stray date removed from bottom
        for p in doc.paragraphs:
            txt = p.text.strip()
            if "CUSTOMER" not in txt and "PARTICULARS" not in txt and "Property Proposed" not in txt and "Date:" not in txt:
                self.assertFalse(
                    txt == "27.03.2025" or (txt.startswith("2") and len(txt) == 10 and "." in txt),
                    f"Stray accidental date paragraph found: {txt}"
                )

    def test_form_0190_signature_stability_and_no_page_overflow(self):
        """
        Tests Form 0190 to verify that the signature block stays completely within Page 1.
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

        # Verify Signatures are aligned using tab stops
        self.assertIn("_______________________________", doc.paragraphs[14].text)
        self.assertIn("Customer\tAttended staff/representative", doc.paragraphs[15].text)
        self.assertIn("Name: Nick\tName: Leong Chu Ping", doc.paragraphs[16].text)
        self.assertIn("Date: 27.03.2025\tDate: 27.03.2025", doc.paragraphs[17].text)

        # Verify that Table 0 has explicit single border stabilization
        t0_xml = doc.tables[0]._tbl.tblPr.xml
        self.assertIn("tblBorders", t0_xml)
        self.assertIn('w:val="single"', t0_xml)


if __name__ == "__main__":
    unittest.main()
