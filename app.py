from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
import os
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
import re

# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")

# ----------------------------
# Initialize Flask app
# ----------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# ----------------------------
# Database config (Use Render's PostgreSQL)
# ----------------------------
# Get DATABASE_URL from environment (Render provides this automatically)
database_url = os.environ.get('DATABASE_URL', '')

if database_url:
    # Fix for Render's PostgreSQL connection string
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    print("✅ Using PostgreSQL database from DATABASE_URL")
else:
    # Fallback for local development (SQLite)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///local.db'
    print("⚠️  Using SQLite for local development")

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_recycle': 300,
    'pool_pre_ping': True,
}

# ----------------------------
# Extensions
# ----------------------------
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ----------------------------
# Hugging Face client
# ----------------------------
hf_client = InferenceClient(token=HF_TOKEN) if HF_TOKEN else None

# ----------------------------
# User Model
# ----------------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    province = db.Column(db.String(50), nullable=False)
    district = db.Column(db.String(50), nullable=False)
    sector = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ----------------------------
# Initialize database tables
# ----------------------------
def initialize_database():
    try:
        with app.app_context():
            db.create_all()
            print("✅ Database tables created successfully!")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")

# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            existing_email = User.query.filter_by(email=request.form['email']).first()
            existing_phone = User.query.filter_by(phone=request.form['phone']).first()

            if existing_email:
                flash("Email already registered. Please use a different email.", "danger")
                return redirect(url_for("register"))
            if existing_phone:
                flash("Phone number already registered. Please use a different phone.", "danger")
                return redirect(url_for("register"))

            hashed_pw = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')

            user = User(
                name=request.form['name'],
                gender=request.form['gender'],
                province=request.form['province'],
                district=request.form['district'],
                sector=request.form['sector'],
                email=request.form['email'],
                phone=request.form['phone'],
                password=hashed_pw
            )
            db.session.add(user)
            db.session.commit()
            flash("✅ Registration successful! You can now login.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            db.session.rollback()
            flash("❌ Registration failed. Please try again.", "danger")
            print(f"Registration error: {e}")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            user = User.query.filter_by(email=request.form['email']).first()
            if user and bcrypt.check_password_hash(user.password, request.form['password']):
                login_user(user)
                flash("✅ Login successful!", "success")
                return redirect(url_for("symptoms"))
            else:
                flash("❌ Login failed. Check your email/password.", "danger")
        except Exception as e:
            flash("❌ Login error. Please try again.", "danger")
            print(f"Login error: {e}")

    if current_user.is_authenticated:
        return redirect(url_for("symptoms"))

    return render_template("login.html")

@app.route("/symptoms", methods=["GET", "POST"])
@login_required
def symptoms():
    result = None
    if request.method == "POST" and hf_client:
        try:
            user_input = request.form["symptoms"]
            api_result = hf_client.text_classification(user_input)
            label = api_result[0]["label"]
            score = round(api_result[0]["score"], 2)

            advice_mapping = {
                "POSITIVE": "🚨 Seek medical attention and stay hydrated.",
                "NEGATIVE": "✅ Monitor your symptoms, usually mild."
            }
            first_aid = advice_mapping.get(label, "⚠️ Follow general health precautions.")
            result = {"label": label, "score": score, "first_aid": first_aid}
        except Exception as e:
            flash("❌ Error analyzing symptoms. Please try again.", "danger")
            print(f"Symptoms analysis error: {e}")

    return render_template("symptoms.html", result=result)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("✅ You have been logged out.", "success")
    return redirect(url_for("login"))

# ----------------------------
# Initialize app
# ----------------------------
with app.app_context():
    initialize_database()

# ----------------------------
# Run the app
# ----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', False))