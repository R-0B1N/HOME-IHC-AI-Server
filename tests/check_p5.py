import docx

doc_c = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")
p5 = doc_c.paragraphs[5]
print("P5 text:", repr(p5.text))
for r_i, r in enumerate(p5.runs):
    color = r.font.color.rgb if r.font.color else None
    print(f"  Run {r_i}: text={r.text!r}, color={color}, bold={r.bold}, size={r.font.size.pt if r.font.size else None}")
