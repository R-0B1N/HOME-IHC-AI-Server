import zipfile

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    for f in ["docProps/core.xml", "docProps/app.xml"]:
        if f in z.namelist():
            print(f"=== {f} ===")
            print(z.read(f).decode('utf-8'))
