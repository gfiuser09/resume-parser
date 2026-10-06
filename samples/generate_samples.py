"""Generate sample resumes (PDF, DOCX, PNG, JPG) for local testing.

Run from the project root::

    python samples/generate_samples.py

The files are written next to this script and are safe to delete at any time.
"""

import os

SAMPLE_DIR = os.path.dirname(os.path.abspath(__file__))

RESUME_TEXT = """JOHN A. DOE
john.doe@example.com | +91 98765 43210 | linkedin.com/in/johndoe
Bangalore, India

SUMMARY
Backend engineer with 6 years of experience designing high-throughput APIs.

TECHNICAL SKILLS
Languages: Python, JavaScript, Go, SQL
Frameworks: Flask, Django, React.js
Tools: Docker, Kubernetes, PostgreSQL, Redis, Git

WORK EXPERIENCE
Senior Backend Engineer | Acme Technologies Pvt Ltd | Jan 2020 - Present
- Designed REST APIs serving 2M requests/day using Flask and PostgreSQL.
- Led a team of 4 engineers and reduced p95 latency by 40%.

Software Engineer, Globex Solutions, Bangalore, Jun 2017 - Dec 2019
- Built internal tooling in Python and automated deployments with Docker.

EDUCATION
B.Tech in Computer Science, XYZ University, 2013 - 2017
CGPA: 8.7/10

Higher Secondary, ABC Public School, 2013
Percentage: 92%
"""


def path_for(name):
    return os.path.join(SAMPLE_DIR, name)


def write_text():
    target = path_for("resume.txt")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(RESUME_TEXT)
    return target


def write_pdf():
    import pymupdf

    target = path_for("resume.pdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((60, 60), RESUME_TEXT, fontsize=9, fontname="helv")
    document.save(target)
    document.close()
    return target


def write_docx():
    import docx

    target = path_for("resume.docx")
    document = docx.Document()
    for line in RESUME_TEXT.split("\n"):
        document.add_paragraph(line)
    document.save(target)
    return target


#: Tesseract reads a real typeface far better than Pillow's default bitmap
#: font, so the sample image is only a fair OCR test with one of these.
FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _load_font(size=22):
    """Return a TrueType font if one is available, else Pillow's default."""
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size), candidate
            except OSError:
                continue
    return ImageFont.load_default(), "pillow-default"


def write_images():
    from PIL import Image, ImageDraw

    font, source = _load_font()
    if source == "pillow-default":
        print("note: no TrueType font found; OCR of the sample image will be poor")

    image = Image.new("RGB", (1240, 1754), "white")   # ~A4 at 150 DPI
    draw = ImageDraw.Draw(image)
    draw.multiline_text((60, 50), RESUME_TEXT, fill="black", font=font, spacing=10)

    png, jpg = path_for("resume.png"), path_for("resume.jpg")
    image.save(png, dpi=(150, 150))
    image.save(jpg, quality=95, dpi=(150, 150))
    return png, jpg


def generate_all():
    """Write every sample file and return the list of paths."""
    created = [write_text(), write_pdf(), write_docx()]
    created.extend(write_images())
    return created


if __name__ == "__main__":
    for created in generate_all():
        print("wrote", os.path.relpath(created))
