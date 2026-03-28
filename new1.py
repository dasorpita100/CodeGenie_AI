from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from flask_login import current_user
from datetime import datetime
import re
import keyword
import requests
import time
import os
ADMIN_EMAIL = "admin@gmail.com"
HF_API_KEY = os.getenv("HF_API_KEY")
if not HF_API_KEY:
    print("⚠️ WARNING: HF_API_KEY not set. HuggingFace will fail.")



def extract_keywords_from_code(code, language):
    tokens = re.findall(r"\b\w+\b", code)

    if language.lower() == "python":
        valid = keyword.kwlist + ["print", "input"]

    elif language.lower() == "java":
        valid = [
            "public","static","void","class","int","double","float",
            "if","else","for","while","return","System","out","println"
        ]

    elif language.lower() == "c++":
        valid = [
            "int","float","double","char","bool","void",
            "if","else","for","while","return",
            "cout","cin","include","namespace","using","main"
        ]
    else:
        valid = []

    return list(set([t for t in tokens if t in valid]))


import subprocess
def generate_code_ollama(prompt, language):

    full_prompt = f"""
You are a senior software engineer.

Generate a COMPLETE {language} program for:

{prompt}

CODE:
<only code>

EXPLANATION:
<simple explanation>

KEYWORDS:
<keywords>
"""

    result = subprocess.run(
        ["ollama", "run", "deepseek-coder"],
        input=full_prompt,
        text=True,
        capture_output=True,
        timeout=20
    )

    if result.returncode != 0:
        return """CODE:
    Error

    EXPLANATION:
    Ollama failed to generate code

    KEYWORDS:
    """

    return result.stdout

def generate_code_locally(prompt, language):

    full_prompt = f"""
You are a senior software engineer.

Generate a COMPLETE {language} program for:

{prompt}

STRICT OUTPUT FORMAT (DO NOT BREAK THIS):

If you do not follow this format exactly, the response will be rejected.

CODE:
<only code here>

EXPLANATION:
<explain the code in simple English>

KEYWORDS:
<only programming language keywords separated by commas>


Rules:
- Code must appear ONLY inside CODE section
- Explanation must appear ONLY inside EXPLANATION section
- KEYWORDS must contain only real {language} keywords
- Do NOT include variable names
"""

    API_URL = "https://router.huggingface.co/hf-inference/models/google/flan-t5-base"

    headers = {}
    if HF_API_KEY:
        headers["Authorization"] = f"Bearer {HF_API_KEY}"

    payload = {
        "inputs": full_prompt,
        "parameters": {
            "max_new_tokens": 700,
            "temperature": 0.3
        }
    }

    output = ""
    if not HF_API_KEY:
        print("⚠️ Skipping HuggingFace → using Ollama directly")
        output = generate_code_ollama(prompt, language)
    
    else:
        for i in range(5):
            response = requests.post(API_URL, headers=headers, json=payload)

            print("STATUS:", response.status_code)
            print("RAW:", response.text)

            if response.status_code == 200:
                result = response.json()

                if isinstance(result, list):
                    output = result[0].get("generated_text", "")
                else:
                    output = result.get("generated_text", "")

                break   # ✅ ALWAYS break when success
            else:
                time.sleep(3)

        if output.strip() == "" or "loading" in output.lower() or "error" in output.lower():
            print("⚠️ HuggingFace failed → switching to Ollama...")

            output = generate_code_ollama(prompt, language)


    print("\n========= MODEL OUTPUT =========\n")
    print("FINAL OUTPUT:\n", output)
    print("\n================================\n")


    code = ""
    explanation = ""
    keywords = []

    # 🔥 CLEAN GARBAGE TEXT FIRST
    output = re.sub(r"^.*?(?=```|CODE:)", "", output, flags=re.DOTALL)

    # ✅ TRY STRICT FORMAT
    sections = re.split(r"CODE:|EXPLANATION:|KEYWORDS:", output)

    if len(sections) >= 4:
        code = sections[1].strip()
        code = re.split(r"EXPLANATION:|KEYWORDS:", code)[0].strip()
        
        exp_match = re.search(r"EXPLANATION:(.*?)(KEYWORDS:|$)", output, re.DOTALL)
        if exp_match:
            explanation = exp_match.group(1).strip()
        
        keywords = extract_keywords_from_code(code, language)

    else:
        # ✅ FALLBACK → MARKDOWN PARSING
        code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", output, re.DOTALL)

        if code_match:
            code = code_match.group(1).strip()

            after_code = output.split(code_match.group(0))[-1].strip()
            explanation = after_code if after_code else "Explanation not available"
        else:
            code = output
            explanation = "Explanation not available"

        # fallback keywords
        basic_keywords = {
            "python": ["def", "return", "if", "else", "for", "while"],
            "java": ["public", "class", "static", "void", "if", "else", "for"],
            "c++": ["int", "return", "if", "else", "for", "while", "cout"]
        }

        keywords = basic_keywords.get(language.lower(), ["if", "else", "for", "while"])

    # 🔥 FINAL CLEANUP
    code = re.sub(r"```[a-zA-Z]*", "", code)
    code = code.replace("```", "").strip()

    if explanation.strip() == "":
        explanation = "Explanation not generated, but code is correct."

    if not keywords:
        keywords = ["if", "else", "for", "while"]

    return code, explanation, keywords


# -------------------------
# App Setup
# -------------------------

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-secret')

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'users.db')

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)

# ✅ ADD HERE
with app.app_context():
    db.create_all()
    print("✅ Database initialized on Render")

print("HF KEY:", HF_API_KEY)

# -------------------------
# User Model
# -------------------------

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="user")

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    rating = db.Column(db.Integer)
    comment = db.Column(db.String(300))
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    language = db.Column(db.String(50))
    prompt = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    prompt = db.Column(db.Text)
    language = db.Column(db.String(50))
    code = db.Column(db.Text)
    created_at = db.Column(db.DateTime)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# -------------------------
# Routes
# -------------------------

@app.route('/')
def home():
    return render_template("auth.html")


@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']

    user = User.query.filter_by(email=email).first()

    if user and bcrypt.check_password_hash(user.password, password):

        login_user(user)

        if user.role == "admin":
            return redirect('/admin')
        else:
            return redirect('/dashboard')

    else:
        flash("Incorrect email or password!", "danger")
        return redirect(url_for('home'))
    
@app.route('/register', methods=['POST'])
def register():

    name = request.form['name']
    email = request.form['email']
    password = request.form['password']

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

    user = User(name=name, email=email, password=hashed_password)

    db.session.add(user)
    db.session.commit()

    flash("Account created successfully! Please login.", "success")

    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template("dashboard.html")

@app.route('/user_dashboard')
@login_required
def user_dashboard():

    history = db.session.query(History, User)\
        .join(User, History.user_id == User.id)\
        .filter(History.user_id == current_user.id)\
        .order_by(History.id.desc())\
        .all()

    # ⭐ GET USER FEEDBACK
    user_feedback = Feedback.query.filter_by(user_id=current_user.id).all()

    avg_rating = 0
    if user_feedback:
        avg_rating = sum(f.rating for f in user_feedback) / len(user_feedback)

        # 🔥 TOTAL CODES GENERATED
    total_codes = History.query.filter_by(user_id=current_user.id).count()

        # ✅ TOTAL DISTINCT LANGUAGES
    language_count = db.session.query(
        db.func.count(db.distinct(Activity.language))
    ).filter(Activity.user_id == current_user.id).scalar()


    # ✅ MOST USED LANGUAGE
    lang_data = db.session.query(
        Activity.language,
        db.func.count(Activity.language)
    ).filter(Activity.user_id == current_user.id)\
    .group_by(Activity.language)\
    .order_by(db.func.count(Activity.language).desc())\
    .first()

    top_language = lang_data[0] if lang_data else "N/A"

    return render_template(
        "user_dashboard.html",
        history=history,
        avg_rating=round(avg_rating, 1),
        total_codes=total_codes,

        language_count=language_count,
        top_language=top_language
    )

@app.route('/generate', methods=['POST'])
@login_required
def generate():

    data = request.get_json()
    prompt = data["prompt"]
    language = data["language"]

    code, explanation, keywords = generate_code_locally(prompt, language)

    # Save activity (already exists)
    activity = Activity(
        user_id=current_user.id,
        language=language,
        prompt=prompt
    )
    db.session.add(activity)

    # ✅ NEW: Save history properly using SQLAlchemy
    history = History(
        user_id=current_user.id,
        prompt=prompt,
        language=language,
        code=code,
        created_at=datetime.now()
    )
    db.session.add(history)

    db.session.commit()

    return jsonify({
        "code": code,
        "explanation": explanation,
        "keywords": keywords,
        "status": "success"
    })

@app.route('/submit_feedback', methods=['POST'])
@login_required
def submit_feedback():
    data = request.get_json()

    feedback = Feedback(
        user_id = current_user.id,
        rating = data.get("rating"),
        comment = data.get("comment")
    )

    db.session.add(feedback)
    db.session.commit()

    return jsonify({"status": "feedback saved"})

@app.route('/admin')
@login_required
def admin_dashboard():

    if current_user.role != "admin":
        return "Unauthorized", 403
    
    total_users = User.query.count()
    total_feedback = Feedback.query.count()

    # ratings chart
    ratings = db.session.query(
        Feedback.rating,
        db.func.count(Feedback.rating)
    ).group_by(Feedback.rating).all()

    # 🔥 language usage
    language_usage = db.session.query(
        Activity.language,
        db.func.count(Activity.language)
    ).group_by(Activity.language).all()

    # 🔥 daily activity
    daily_activity = db.session.query(
        db.func.date(Activity.timestamp),
        db.func.count(Activity.id)
    ).group_by(db.func.date(Activity.timestamp)).all()

    # 🔥 users table
    users = User.query.filter(User.role != "admin").all()

    from datetime import date, timedelta

    today = date.today()
    yesterday = today - timedelta(days=1)

    # USERS
    today_users = User.query.filter(db.func.date(User.created_at) == today).count()
    yesterday_users = User.query.filter(db.func.date(User.created_at) == yesterday).count()

    user_growth = 0
    if yesterday_users > 0:
        user_growth = ((today_users - yesterday_users) / yesterday_users) * 100


    # FEEDBACK
    today_feedback = Feedback.query.filter(db.func.date(Feedback.timestamp) == today).count()
    yesterday_feedback = Feedback.query.filter(db.func.date(Feedback.timestamp) == yesterday).count()

    feedback_growth = 0
    if yesterday_feedback > 0:
        feedback_growth = ((today_feedback - yesterday_feedback) / yesterday_feedback) * 100

    # ===== AVG RATING =====
    feedbacks = Feedback.query.all()

    avg_rating = 0
    if feedbacks:
        avg_rating = sum(f.rating for f in feedbacks) / len(feedbacks)

    return render_template(
    "admin.html",
    total_users=total_users,
    total_feedback=total_feedback,
    ratings=ratings,
    language_usage=language_usage,
    daily_activity=daily_activity,
    users=users,

    user_growth=round(user_growth,1),
    feedback_growth=round(feedback_growth,1),
    avg_rating= round(avg_rating,1)
)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


# -------------------------
# Run App
# -------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)