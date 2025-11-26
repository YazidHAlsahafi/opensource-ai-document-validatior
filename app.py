from flask import Flask, render_template, redirect, request, jsonify
from ollama import ChatResponse, chat
import os, fitz, docx, json
from pydantic import BaseModel
from pathlib import Path
# --- Flask config ---
UPLOAD_FOLDER = Path("uploads")
UPLOAD_FOLDER.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


### --- Base model for the json response ---
class ValidOrNot(BaseModel):
 valid: bool
 reasons: list[str]


### --- Extract text from PDF or DOCX --- 
def extract_text(file_path: Path):
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        text = ""
        pdf = fitz.open(str(file_path))
        for page in pdf:
            text += page.get_text()
        return text

    elif suffix == ".docx":
        doc = docx.Document(str(file_path))
        return "\n".join([p.text for p in doc.paragraphs])

    return None

def validate_text(requirements, valid_examples, invalid_examples, document_text, precent):

    valid_block = valid_examples or "لا توجد أمثلة صالحة."
    invalid_block = invalid_examples or "لا توجد أمثلة غير صالحة."

    prompt = f"""
You are an expert document validator that only responds in arabic.

The user supplied:
1. Validation requirements (mandatory)
2. Optional examples of valid documents
3. Optional examples of invalid documents

Your task is to evaluate the document denoted by " at the start and end leniently:
- Consider a requirement satisfied if it is mostly present.
- Only mark it missing if it is completely absent or clearly incorrect.
- If its missing give it a 0.
- Minor deviations, paraphrasing, or partial content are acceptable.

==================================================
📝 VALIDATION REQUIREMENTS
==================================================
{requirements}

==================================================
🟢 VALID EXAMPLES (optional)
==================================================
{valid_block}

==================================================
🔴 INVALID EXAMPLES (optional)
==================================================
{invalid_block}

==================================================
📄 DOCUMENT TO VALIDATE
==================================================
"{document_text}"

==================================================
🎯 VALIDATION RULES
==================================================
• Compare the document strictly against the user's requirements.
• Score each requirement:
  - 1 point = clearly satisfied.
  - 0 = missing or unclear.

• Final decision:
 - Score each requirement between 0 (missing) and 1 (fully satisfied)
 - Compute overall score = average of all requirement scores
 - Mark document as "valid" if overall score >= {precent}
 - Include reasons explaining any missing or partially satisfied requirements
Output format (strict JSON):
{{
  "valid": true/false,
  "reasons": ["reason 1", "reason 2", ...]
}}
If valid, include one reason that is just your score such as "الوثيقة صحيحة بنسبة **%"
"""
    response = chat(
        model='llama3.1:8b',
        messages=[{'role': 'user', 'content': prompt,}],
        format=ValidOrNot.model_json_schema(),
        options={'temperature': 0},
    )

    content = response.message.content
    try:
       return json.loads(content)
    except Exception:
        return {"valid": False, "reasons": ["Invalid JSON returned from model"]}

# --- Routes ---
@app.route('/')
def index():
    return render_template("index.html")

@app.route("/validate", methods=["POST"])
def validate():
    # Requirements typed by the user
    requirements = request.form.get("requirements", "").strip()
    if not requirements:
        return jsonify({
            "valid": False,
            "reasons": ["لم يتم إدخال متطلبات التحقق."]
        }), 400

    # Document file
    document_file = request.files.get("document")
    if not document_file:
        return jsonify({
            "valid": False,
            "reasons": ["لم يتم رفع المستند المراد التحقق منه."]
        }), 400

    # Save the document using Path
    doc_path = app.config["UPLOAD_FOLDER"] / document_file.filename
    document_file.save(str(doc_path))

    # The valid range precentage
    precent = request.form.get("precent","")
    precent = int(precent)/100
    # Optional example uploads
    valid_examples_text = ""
    invalid_examples_text = ""

    if "valid_examples" in request.files:
        for f in request.files.getlist("valid_examples"):
            if not f.filename:  # ⬅️ Skip empty input
              continue
            try:
                path = app.config["UPLOAD_FOLDER"] / f.filename
                f.save(str(path))
                valid_examples_text += extract_text(path) + "\n\n---\n\n"
                path.unlink(missing_ok=True)
            except Exception as e:
                return jsonify({
                "valid": False,
                "reasons": [f"خطأ أثناء معالجة مثال صحيح: {str(e)}"]
                }), 500

    if "invalid_examples" in request.files:
        for f in request.files.getlist("invalid_examples"):
            if not f.filename:  # ⬅️ Skip empty input
                continue
            try:
                path = app.config["UPLOAD_FOLDER"] / f.filename
                f.save(str(path))
                invalid_examples_text += extract_text(path) + "\n\n---\n\n"
                path.unlink(missing_ok=True)
            except Exception as e:
                return jsonify({
                "valid": False,
                "reasons": [f"خطأ أثناء معالجة مثال غير صحيح: {str(e)}"]
                }), 500

    # Extract text from the main document
    try:
        document_text = extract_text(doc_path)
    except Exception as e:
        doc_path.unlink(missing_ok=True)
        return jsonify({
            "valid": False,
            "reasons": [f"تعذر قراءة المستند: {str(e)}"]
        }), 500

    doc_path.unlink(missing_ok=True)

    result = validate_text(
        requirements=requirements,
        valid_examples=valid_examples_text,
        invalid_examples=invalid_examples_text,
        document_text=document_text,
        precent = precent
    )
    return jsonify(result)



# --- Run app ---
if __name__ == "__main__":
    app.run(debug=True)