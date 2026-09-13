import docx

doc_c = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")
p7 = doc_c.paragraphs[7]
print("P7 text:", repr(p7.text))
for r_i, r in enumerate(p7.runs):
    color = r.font.color.rgb if r.font.color else None
    print(f"  Run {r_i}: text={r.text!r}, color={color}, bold={r.bold}, size={r.font.size.pt if r.font.size else None}")
