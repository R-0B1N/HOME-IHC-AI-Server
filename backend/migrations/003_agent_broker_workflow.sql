-- ===========================
-- AGENT/BROKER Workflow Steps
-- ===========================
-- Implements: docs/Work Flow - AI Customer Services (Agent or Broker) FINAL.txt
-- Mapped as persona_type = 'AGENT'
-- Step numbering starts at 10

-- Step 10: Greeting & Introduction (no data extraction)
-- Step 11: Verify Agent/Broker Info (collect agent_name, agency_name)
-- Step 12: Collect Buyer Requirements (buyer_property_type, buyer_location, buyer_budget)
-- Step 13: Confirm Purchase Entity (personal or company)
-- Step 14: Recommend Listings (auto-advance with property search)
-- Step 15: Follow-up & Viewing (final step, triggers handover)

INSERT INTO workflow_templates (persona_type, step_number, step_name, expected_data_keys, ai_action_instruction, message_template, next_step, created_at, updated_at)
VALUES
('AGENT', 10, 'Greeting & Intro', '{}',
 'Greet the Agent/Broker warmly. Identify that the enquiry is from an Agent or Broker. Request the buyers requirements.',
 E'Hi Agent/Broker! \U0001F44B\nThank you for contacting us.\n\nTo assist you more efficiently, could you please share your buyer''s requirements?\nProperty Type:\nPreferred Location:\nBudget:\nPurpose: (Own Use / Investment)\n\nYou may also browse our latest listings here:\n\U0001F517 https://bentongland.com.my/listings/\n\nI look forward to your reply. \U0001F60A',
 11, NOW(), NOW()),

('AGENT', 11, 'Verify Agent Info', '{agent_name,agency_name}',
 'Collect the Agent or Brokers basic information: their name and agency. Be flexible - if they provide a name card image, accept that as both name and agency confirmation.',
 E'To ensure a smooth co-broking process, may I kindly have the following information?\n\nAgent / Broker Information:\n1. Your name\n2. Your agency name card\n3. Your purpose of enquiry',
 12, NOW(), NOW()),

('AGENT', 12, 'Collect Buyer Requirements', '{buyer_property_type,buyer_location,buyer_budget}',
 'Collect the buyers specific requirements: property type, preferred location, and budget range. Also try to collect preferred land size and intended use if mentioned.',
 E'Your Buyer''s Requirements:\n1. Property Type\n2. Preferred Location\n3. Budget Range\n4. Preferred Land Size\n5. Intended Use: [Durian Farm / Residential / Investment / Resort / Other]\n\nYou may also browse all available listings here:\n\U0001F517 https://bentongland.com.my/listings/\n\nI look forward to your reply. \U0001F60A',
 13, NOW(), NOW()),

('AGENT', 13, 'Confirm Purchase Entity', '{purchase_entity}',
 'Confirm whether the buyers buyer will be purchasing under a personal name or company name. Accept values like personal, company, sdn bhd, individual.',
 E'Thank you for the information. \U0001F60A\nMay I also confirm whether your buyer will be purchasing the property under:\nPersonal Name\nor\nCompany Name?\n\nThis will help us prepare the relevant information and documentation accordingly.',
 14, NOW(), NOW()),

('AGENT', 14, 'Recommend Listings', '{}',
 'Match suitable listings based on the buyers requirements. Recommend the most relevant properties and suggest alternatives where applicable.',
 E'Based on your buyer''s requirements, I have shortlisted several suitable listings. \U0001F60A\n\nI can provide the available property information, including:\nProperty Description\nPhotos\nVideos\nTopo Plan\n\nWould you like me to send you the property details now?',
 15, NOW(), NOW()),

('AGENT', 15, 'Follow-up & Viewing', '{}',
 'Provide viewing arrangement info. This is the final step before handover to the main number. Do NOT create calendar events.',
 E'If your buyer is interested in arranging a site viewing, we will be happy to assist with the next step. \U0001F60A\n\nBefore the site visit can be arranged, the buyer is required to complete and sign our:\nCustomer Property Acknowledgement & Viewing Form\n\nOnce completed, our team will assist with the viewing arrangement.',
 NULL, NOW(), NOW())
ON CONFLICT DO NOTHING;
