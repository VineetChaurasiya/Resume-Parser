import io
import os
from typing import List, Optional

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from pydantic import BaseModel, Field

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-key")

_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
    return _client


MODEL = "gemini-2.5-flash"


SYSTEM_PROMPT = """You are an expert resume editor specializing in Applicant Tracking System (ATS) optimization.

Your job: rewrite a candidate's resume so it scores higher against a specific job description, WITHOUT fabricating anything and WITHOUT making the edits look like keyword stuffing.

# HARD CONSTRAINTS — NEVER VIOLATE

You MUST preserve these fields exactly as they appear in the original resume:
- Candidate's name, email, phone, location, LinkedIn/portfolio URLs
- All company names (do not rebrand, abbreviate, or "correct" them)
- Employment dates and tenure (start date, end date, duration)
- Job titles at each company (do not inflate or reword titles)
- School names, degrees earned, graduation dates, majors
- Certification names and issuing bodies
- Any numeric facts the candidate stated (team sizes, revenue figures, percentages, etc.)

You MUST NOT:
- Invent metrics, percentages, dollar amounts, team sizes, or outcomes that are not in the original
- Add skills, tools, or technologies the candidate did not mention
- Claim experience with things the candidate did not claim experience with
- Change the chronological order of jobs
- Merge or split roles at the same company in ways that misrepresent the history
- Add certifications, degrees, or credentials

# WHAT YOU MAY REWRITE

- Bullet point phrasing (verbs, structure, clarity) — keep the underlying fact, change how it is described
- The professional summary / objective section (if one exists, or add a concise one if missing)
- Skills section ordering and terminology — you may reorder to lead with what the JD prioritizes, and you may use the JD's preferred terminology when it refers to the same thing (e.g. "stakeholder management" vs "client management") provided the candidate actually did that work
- Section ordering (within reason — standard ATS-friendly order: Summary, Skills, Experience, Education, Certifications)

# KEYWORD INCORPORATION STRATEGY

Do NOT copy phrases verbatim from the JD. Do NOT keyword-stuff. Do NOT add a "Keywords" section.

Instead:
1. Identify the 10-20 most load-bearing terms in the JD (technologies, methodologies, domain terms, soft skills that appear repeatedly)
2. For each, check: did the candidate actually do this work, even if they described it differently?
3. If yes — rewrite the relevant bullet to use the JD's terminology naturally. The sentence should read as if the candidate wrote it themselves.
4. If no — do not include it. Missing keywords are better than false claims.

Prefer incorporating keywords into existing bullets rather than adding new ones. When you do add a bullet, it must be supported by context already in the resume.

# QUANTIFICATION

If a bullet describes an achievement but has no metric, and the original resume or JD context makes a specific number unknowable, do NOT invent one. Instead, keep the bullet qualitative but sharper, OR flag it in the `needs_user_input` field so the candidate can fill in the number themselves.

# STYLE

- Active voice, strong action verbs, past tense for past roles, present tense for current role
- Each bullet one line where possible, max two
- No personal pronouns ("I", "my")
- No em-dashes used as stylistic flourishes; keep punctuation clean and ATS-parseable
- Plain text formatting — no tables, columns, text boxes, or graphics
- Use standard section headers: "Professional Summary", "Skills", "Experience", "Education", "Certifications"

# OUTPUT

Return the formatted resume as plain text (newlines preserved), plus a structured list of the changes you made and the rationale for each. Be honest in the `rationale` — if you used JD terminology, say so.
"""


class ChangeItem(BaseModel):
    section: str = Field(description="Which resume section this change is in (e.g. 'Summary', 'Experience - Acme Corp').")
    change_type: str = Field(description="One of: 'rephrased', 'reordered', 'keyword_integrated', 'summary_added', 'quantification_suggested'.")
    before: str = Field(description="The original text (or 'N/A' if newly added).")
    after: str = Field(description="The rewritten text.")
    rationale: str = Field(description="Why this change helps ATS matching, referencing the JD where relevant.")


class NeedsUserInput(BaseModel):
    location: str = Field(description="Where in the resume a metric or detail should be added.")
    suggestion: str = Field(description="What the candidate should fill in (e.g. 'team size you managed', 'percentage revenue increase').")


class FormatResult(BaseModel):
    formatted_resume: str = Field(description="The full rewritten resume as plain text, with section headers and line breaks preserved.")
    keywords_incorporated: List[str] = Field(description="JD terms or concepts that were woven into the resume.")
    keywords_skipped: List[str] = Field(description="JD terms that were NOT included because the candidate didn't actually have that experience.")
    changes: List[ChangeItem] = Field(description="Every substantive edit made to the resume.")
    needs_user_input: List[NeedsUserInput] = Field(description="Places where the candidate should add a number or detail the model couldn't infer.")


def extract_text_from_upload(file_storage) -> Optional[str]:
    if not file_storage or not file_storage.filename:
        return None

    filename = file_storage.filename.lower()
    data = file_storage.read()

    if filename.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()

    if filename.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs).strip()

    if filename.endswith(".txt"):
        return data.decode("utf-8", errors="replace").strip()

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/format", methods=["POST"])
def format_resume():
    resume_text = (request.form.get("resume_text") or "").strip()
    jd_text = (request.form.get("jd_text") or "").strip()

    resume_file = request.files.get("resume_file")
    if resume_file and not resume_text:
        extracted = extract_text_from_upload(resume_file)
        if extracted:
            resume_text = extracted

    jd_file = request.files.get("jd_file")
    if jd_file and not jd_text:
        extracted = extract_text_from_upload(jd_file)
        if extracted:
            jd_text = extracted

    if not resume_text:
        return jsonify({"error": "Resume is required. Paste the text or upload a PDF/DOCX/TXT file."}), 400
    if not jd_text:
        return jsonify({"error": "Job description is required."}), 400

    user_message = (
        "# Resume (original)\n\n"
        f"{resume_text}\n\n"
        "# Job Description\n\n"
        f"{jd_text}\n\n"
        "Rewrite the resume following all constraints in your instructions. "
        "Return the result in the required structured format."
    )

    try:
        response = get_client().models.generate_content(
            model=MODEL,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=FormatResult,
                max_output_tokens=8000,
            ),
            contents=user_message,
        )
    except genai_errors.ClientError as e:
        code = getattr(e, "code", 0)
        msg = getattr(e, "message", str(e))
        if code == 429:
            return jsonify({"error": "Rate limited by Gemini API. Please wait a moment and retry."}), 429
        if code in (401, 403):
            return jsonify({"error": "Google API key is missing or invalid. Check GOOGLE_API_KEY."}), 500
        return jsonify({"error": f"Request rejected: {msg}"}), 400
    except genai_errors.ServerError as e:
        code = getattr(e, "code", 0)
        msg = getattr(e, "message", str(e))
        return jsonify({"error": f"Gemini server error ({code}): {msg}"}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

    if not response.text:
        return jsonify({"error": "Model returned an empty response. Try again."}), 502

    try:
        result = FormatResult.model_validate_json(response.text)
    except Exception:
        return jsonify({"error": "Model did not return a valid structured response. Try again."}), 502

    return jsonify(result.model_dump())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
