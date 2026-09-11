# Conversational & Workflow Backtesting Report

**System:** Home IHC WhatsApp AI CRM Automation ([BentongLand.com.my](https://bentongland.com.my/))
**Execution Timestamp:** 2026-09-11T15:34:34.539124+00:00
**Status:** ✅ PASSED
**Pass Rate:** 100.0% (7/7 scenarios)
**Total Execution Latency:** 9.55 ms

## Scenario Summary Matrix

| Scenario ID | Name | Persona | Status | Latency | Assertions Passed |
|:---|:---|:---|:---:|:---:|:---:|
| `SCENARIO-01-BUYER` | Buyer Qualification & Durian Land Criteria Matching | Buyer | ✅ Pass | 0.0ms | 4/4 |
| `SCENARIO-02-SELLER` | Landowner Intake & Anti-Bypassing Verification | Seller / Landowner | ✅ Pass | 0.0ms | 3/3 |
| `SCENARIO-03-TENANT` | Off-Market Rental Inquiry & Tenant Profiling | Tenant | ✅ Pass | 0.0ms | 3/3 |
| `SCENARIO-04-VALUER` | Bank Valuer Intake & Automated Handover | Bank Valuer | ✅ Pass | 0.0ms | 3/3 |
| `SCENARIO-05-DOCS` | Customer Viewing Acknowledgement OpenXML & 22-Field Verification | Co-Broke Agent / Legal | ✅ Pass | 6.0ms | 4/4 |
| `SCENARIO-06-POLICY` | Meta 24-Hour Customer Care Policy Window Enforcement | Nurturing Daemon / Policy Guard | ✅ Pass | 1.2ms | 5/5 |
| `SCENARIO-07-PARITY` | OpenXML Archive & Excel Schema Parity Verification | System Architecture / QA | ✅ Pass | 2.1ms | 3/3 |

## Detailed Scenario Audit & Assertions

### `SCENARIO-01-BUYER`: Buyer Qualification & Durian Land Criteria Matching
- **Persona:** Buyer
- **Execution Time:** 0.01 ms
- **Verification Assertions:**
  - [✓] **Persona Intent Identification**: Identified as Buyer persona.
  - [✓] **Data Completeness Ratio**: Collected 5/5 required qualification fields (100%).
  - [✓] **Lead Temperature Calculation**: Qualified buyer with >= 80% completeness correctly classified as Hot lead.
  - [✓] **Interested Property Tracking**: Tracked property interest: '5 Acres Karak Musang King Farm'.

### `SCENARIO-02-SELLER`: Landowner Intake & Anti-Bypassing Verification
- **Persona:** Seller / Landowner
- **Execution Time:** 0.00 ms
- **Verification Assertions:**
  - [✓] **Ownership Verification**: Confirmed direct registered landowner status.
  - [✓] **Asking Price Extraction**: Extracted total asking price and per-acre metric.
  - [✓] **Anti-Bypassing Agency Representation**: AI maintains exclusive representation via Irene Leong (Home IHC Sdn Bhd). Anti-bypassing active.

### `SCENARIO-03-TENANT`: Off-Market Rental Inquiry & Tenant Profiling
- **Persona:** Tenant
- **Execution Time:** 0.00 ms
- **Verification Assertions:**
  - [✓] **Persona Intent**: Identified as Tenant persona.
  - [✓] **Rental Budget Captured**: Captured monthly rental budget.
  - [✓] **Off-Market Property Routing**: Flagged off-market inquiry for internal matching without system failure.

### `SCENARIO-04-VALUER`: Bank Valuer Intake & Automated Handover
- **Persona:** Bank Valuer
- **Execution Time:** 0.00 ms
- **Verification Assertions:**
  - [✓] **Valuer Intent**: Identified as Bank Valuer persona.
  - [✓] **Lot & Mukim Extraction**: Correctly parsed legal lot number and mukim.
  - [✓] **Senior Agent Handover Triggered**: Valuer request automatically prioritized and handed over to senior agent.

### `SCENARIO-05-DOCS`: Customer Viewing Acknowledgement OpenXML & 22-Field Verification
- **Persona:** Co-Broke Agent / Legal
- **Execution Time:** 6.04 ms
- **Verification Assertions:**
  - [✓] **Form Number Run Verification**: Found form number in header paragraph: 'CUSTOMER PROPERTY VIEWING ACKNOWLEDGEMENT 	                                  		      No: 0777'.
  - [✓] **Customer Name in Table 0**: Customer name correctly populated inside Table 0 Cell 0.
  - [✓] **Partner Agency Legal Override**: Partner agency accurately overridden in Paragraph 9.
  - [✓] **OpenXML tblBorders Stabilization**: Table 0 contains explicit <w:tblBorders> preventing headless border loss.

### `SCENARIO-06-POLICY`: Meta 24-Hour Customer Care Policy Window Enforcement
- **Persona:** Nurturing Daemon / Policy Guard
- **Execution Time:** 1.20 ms
- **Verification Assertions:**
  - [✓] **Customer A Eligibility Evaluation**: Customer A evaluated as eligible and within 24-hour window.
  - [✓] **Customer A Automated Follow-up Dispatch**: Automated follow-up message sent within 24h window.
  - [✓] **Customer B Eligibility Evaluation**: Customer B evaluated as eligible but outside 24-hour window.
  - [✓] **Customer B Meta Policy Block & Private Note**: Free-form message blocked past 24h. Internal private note posted in Chatwoot.
  - [✓] **Zero Policy Violations**: Confirmed zero illegal WhatsApp messages dispatched outside 24h window.

### `SCENARIO-07-PARITY`: OpenXML Archive & Excel Schema Parity Verification
- **Persona:** System Architecture / QA
- **Execution Time:** 2.12 ms
- **Verification Assertions:**
  - [✓] **Buyer Excel Generation**: Generated 1914 bytes of valid Excel OpenXML archive.
  - [✓] **Buyer OpenXML Archive Integrity**: Contains [Content_Types].xml, workbook.xml, and sheet1.xml.
  - [✓] **Owner Excel Generation**: Generated 1995 bytes of valid Owner Excel archive.
