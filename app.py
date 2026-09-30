from datetime import datetime
from functools import wraps
from pathlib import Path
import csv
import io
import os
import re
import secrets
import tempfile
from types import SimpleNamespace

from dotenv import dotenv_values
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect, FlaskForm
from markupsafe import Markup
from sqlalchemy import Index
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional

BASE_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG = dotenv_values(BASE_DIR / ".env")


def configured_value(name, default=None):
    return os.environ.get(name) or LOCAL_CONFIG.get(name) or default


DEFAULT_INSTANCE_DIR = (
    Path(tempfile.gettempdir()) / "spc-online-clearance"
    if os.environ.get("VERCEL") == "1"
    else BASE_DIR / "instance"
)
INSTANCE_DIR = Path(configured_value("INSTANCE_DIR", str(DEFAULT_INSTANCE_DIR)))
UPLOAD_DIR = Path(configured_value("UPLOAD_DIR", str(INSTANCE_DIR / "uploads")))
PROFILE_PHOTO_DIR = Path(
    configured_value("PROFILE_PHOTO_DIR", str(INSTANCE_DIR / "profile_photos"))
)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=configured_value("SECRET_KEY", "dev-only-change-this-secret"),
    SQLALCHEMY_DATABASE_URI=f"sqlite:///{INSTANCE_DIR / 'clearance.db'}",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    GOOGLE_CLIENT_ID=configured_value("GOOGLE_CLIENT_ID"),
    GOOGLE_CLIENT_SECRET=configured_value("GOOGLE_CLIENT_SECRET"),
    GOOGLE_ALLOWED_DOMAINS=configured_value(
        "GOOGLE_ALLOWED_DOMAINS", "students.spus.edu.ph"
    ).lower(),
)
ALLOWED_GOOGLE_DOMAINS = frozenset(
    domain.strip().removeprefix("@").lower()
    for domain in app.config["GOOGLE_ALLOWED_DOMAINS"].split(",")
    if domain.strip()
)
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
oauth = OAuth(app)
google = oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    client_kwargs={"scope": "openid email profile"},
)

OFFICE_NAMES = ["Registrar", "Accounting", "Library", "Student Affairs", "Guidance Office", "Clinic", "Department Office", "Laboratory"]
ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx"}
STATUS_LABELS = {"pending": "Pending", "approved": "Approved", "rejected": "Rejected", "requires_action": "Requires Action", "completed": "Completed", "cancelled": "Cancelled", "in_progress": "In Progress"}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    student = db.relationship("Student", back_populates="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    student_id = db.Column(db.String(40), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    middle_name = db.Column(db.String(80), default="")
    last_name = db.Column(db.String(80), nullable=False)
    contact_number = db.Column(db.String(30), default="")
    program = db.Column(db.String(120), nullable=False)
    year_level = db.Column(db.String(30), nullable=False)
    section = db.Column(db.String(50), default="")
    profile_photo_path = db.Column(db.String(255))
    academic_year = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    user = db.relationship("User", back_populates="student")
    clearances = db.relationship("ClearanceRequest", back_populates="student", cascade="all, delete-orphan")

    @property
    def full_name(self):
        return " ".join(part for part in [self.first_name, self.middle_name, self.last_name] if part)


class Office(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(255), default="")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    staff = db.relationship("OfficeStaff", back_populates="office", cascade="all, delete-orphan")


class OfficeStaff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    office_id = db.Column(db.Integer, db.ForeignKey("office.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User")
    office = db.relationship("Office", back_populates="staff")
    __table_args__ = (db.UniqueConstraint("user_id", "office_id", name="uq_staff_office"),)


class ClearanceRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    student = db.relationship("Student", back_populates="clearances")
    items = db.relationship("ClearanceItem", back_populates="clearance", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_clearance_status_year", "status", "academic_year"),)

    @property
    def progress(self):
        active_items = [item for item in self.items if item.status != "cancelled"]
        total = len(active_items)
        approved = sum(item.status == "approved" for item in active_items)
        return round((approved / total) * 100) if total else 0

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status.title())

    def refresh_status(self):
        active_statuses = {item.status for item in self.items if item.status != "cancelled"}
        if not active_statuses:
            self.status = "cancelled"
            self.completed_at = None
            return
        statuses = active_statuses
        if statuses and statuses == {"approved"}:
            self.status = "completed"
            self.completed_at = self.completed_at or datetime.utcnow()
        elif "rejected" in statuses:
            self.status = "rejected"
            self.completed_at = None
        elif "requires_action" in statuses:
            self.status = "requires_action"
            self.completed_at = None
        elif "approved" in statuses:
            self.status = "in_progress"
            self.completed_at = None
        else:
            self.status = "pending"
            self.completed_at = None


class ClearanceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clearance_request_id = db.Column(db.Integer, db.ForeignKey("clearance_request.id"), nullable=False)
    office_id = db.Column(db.Integer, db.ForeignKey("office.id"), nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False)
    remarks = db.Column(db.Text, default="")
    document_name = db.Column(db.String(255))
    document_path = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    clearance = db.relationship("ClearanceRequest", back_populates="items")
    office = db.relationship("Office")
    reviewer = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("clearance_request_id", "office_id", name="uq_clearance_office"),)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User")


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User")


class LoginForm(FlaskForm):
    username = StringField("Username or email", validators=[DataRequired(), Length(max=160)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign in")


class RegisterForm(FlaskForm):
    student_id = StringField("Student ID", validators=[DataRequired(), Length(max=40)])
    first_name = StringField("First name", validators=[DataRequired(), Length(max=80)])
    middle_name = StringField("Middle name", validators=[Optional(), Length(max=80)])
    last_name = StringField("Last name", validators=[DataRequired(), Length(max=80)])
    contact_number = StringField("Contact number", validators=[Optional(), Length(max=30)])
    program = StringField("Program", validators=[DataRequired(), Length(max=120)])
    year_level = StringField("Year level", validators=[DataRequired(), Length(max=30)])
    section = StringField("Section", validators=[Optional(), Length(max=50)])
    academic_year = StringField("Academic year", validators=[DataRequired(), Length(max=20)])
    submit = SubmitField("Create student account")


class ReviewForm(FlaskForm):
    status = SelectField("Decision", choices=[("approved", "Approve"), ("rejected", "Reject"), ("requires_action", "Requires action")], validators=[DataRequired()])
    remarks = StringField("Remarks", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Save decision")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def log_action(action, description, user=None):
    db.session.add(ActivityLog(user_id=(user or current_user).id if (user or current_user).is_authenticated else None, action=action, description=description))


def notify(user, title, message):
    db.session.add(Notification(user_id=user.id, title=title, message=message))


def seed_defaults():
    for name in OFFICE_NAMES:
        if not Office.query.filter_by(name=name).first():
            db.session.add(Office(name=name, description=f"{name} clearance review"))
    retired_office = Office.query.filter_by(name="Property/Equipment Office").first()
    if retired_office:
        ClearanceItem.query.filter_by(office_id=retired_office.id).delete(synchronize_session=False)
        OfficeStaff.query.filter_by(office_id=retired_office.id).delete(synchronize_session=False)
        db.session.delete(retired_office)
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", email="admin@spc-surigao.edu.ph", role="admin")
        admin.set_password("Admin123!")
        db.session.add(admin)
    db.session.commit()
    for office in Office.query.filter(
        Office.is_active.is_(True), Office.name.in_(OFFICE_NAMES)
    ).order_by(Office.id).all():
        username = f"{office.name.lower().replace('/', '-').replace(' ', '-')}.staff"
        staff_user = User.query.filter_by(username=username).first()
        if not staff_user:
            staff_user = User(username=username, email=f"{username}@spc-surigao.edu.ph", role="staff")
            staff_user.set_password("Staff123!")
            db.session.add(staff_user)
            db.session.flush()
        if not OfficeStaff.query.filter_by(user_id=staff_user.id, office_id=office.id).first():
            db.session.add(OfficeStaff(user_id=staff_user.id, office_id=office.id))
    db.session.commit()


def initialize_database():
    with app.app_context():
        db.create_all()
        columns = {column["name"] for column in db.inspect(db.engine).get_columns("clearance_item")}
        for name, definition in {"document_name": "VARCHAR(255)", "document_path": "VARCHAR(255)", "uploaded_at": "DATETIME"}.items():
            if name not in columns:
                db.session.execute(db.text(f"ALTER TABLE clearance_item ADD COLUMN {name} {definition}"))
        student_columns = {column["name"] for column in db.inspect(db.engine).get_columns("student")}
        if "profile_photo_path" not in student_columns:
            db.session.execute(db.text("ALTER TABLE student ADD COLUMN profile_photo_path VARCHAR(255)"))
        db.session.commit()
        seed_defaults()


@app.context_processor
def inject_layout_data():
    unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count() if current_user.is_authenticated else 0
    return {
        "unread_notifications": unread,
        "status_labels": STATUS_LABELS,
        "google_allowed_domains": sorted(ALLOWED_GOOGLE_DOMAINS),
    }


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/admission")
def admission():
    requirement_sets = {
        "new-student": {
            "label": "New Student",
            "items": [
                "Copy of Grade 12 Report Card",
                "Certificate of Good Moral Character",
                "Original Birth Certificate (PSA)",
                "Character Certificate",
                "2 pcs. 2×2 picture",
                "Upon enrolment, minimum payment of ₱3,000 to the Finance Office",
            ],
        },
        "transferee": {
            "label": "Transferee",
            "items": [
                "Copy of Transcript of Records",
                "Honorable Dismissal",
                "Certificate of Good Moral Character",
                "Original Birth Certificate (PSA)",
                "Character Certificate",
                "2 pcs. 2×2 picture",
                "Upon enrolment, minimum payment of ₱3,000 to the Finance Office",
            ],
        },
        "graduate": {
            "label": "Graduate School",
            "items": [
                "Transfer of Credentials / Transcript of Records",
                "Original Birth Certificate (PSA)",
                "Marriage Contract (if married)",
                "Character Certificate",
                "2 pcs. 2×2 picture",
                "Upon enrolment, minimum payment of ₱3,000 to the Finance Office",
            ],
        },
    }
    applicant_type = request.args.get("type", "new-student")
    if applicant_type not in requirement_sets:
        applicant_type = "new-student"
    requirement_tabs = [
        {
            "key": key,
            "label": details["label"],
            "is_active": key == applicant_type,
        }
        for key, details in requirement_sets.items()
    ]
    return render_template(
        "admission.html",
        applicant_type=applicant_type,
        requirement_tabs=requirement_tabs,
        requirement_sets=requirement_sets,
        active_requirements=requirement_sets[applicant_type],
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    session.pop("pending_student_identity", None)
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter((User.username == form.username.data.strip()) | (User.email == form.username.data.strip().lower())).first()
        if user and user.role != "student" and user.is_active and user.check_password(form.password.data):
            login_user(user)
            log_action("User logged in", f"{user.username} signed in.", user)
            db.session.commit()
            return redirect(url_for("dashboard"))
        flash("Staff/admin sign-in details were not recognized.", "danger")
    return render_template("auth/login.html", form=form)


@app.route("/auth/google")
def google_login():
    session.pop("pending_student_identity", None)
    missing_settings = [
        name for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
        if not app.config[name]
    ]
    if missing_settings:
        flash(
            f"Google sign-in is missing {', '.join(missing_settings)}. "
            "Add the value(s) to the project .env file and restart the app.",
            "danger",
        )
        return redirect(url_for("login"))
    callback_url = url_for("google_callback", _external=True)
    return google.authorize_redirect(callback_url, prompt="select_account")


@app.route("/auth/google/callback")
def google_callback():
    try:
        token = google.authorize_access_token()
    except OAuthError:
        flash("Google sign-in could not be completed. Please try again.", "danger")
        return redirect(url_for("login"))

    identity = token.get("userinfo") or {}
    email = (identity.get("email") or "").strip().lower()
    email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    if not identity.get("email_verified") or email_domain not in ALLOWED_GOOGLE_DOMAINS:
        allowed_domains = " or ".join(f"@{domain}" for domain in sorted(ALLOWED_GOOGLE_DOMAINS))
        flash(f"Use your verified {allowed_domains} Google account to continue.", "danger")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first()
    if user:
        if user.role != "student" or not user.student or not user.is_active:
            flash("This Google account is not enabled for student access.", "danger")
            return redirect(url_for("login"))
        session.pop("pending_student_identity", None)
        login_user(user)
        log_action("User logged in", f"{user.username} signed in with Google.", user)
        db.session.commit()
        return redirect(url_for("dashboard"))

    session["pending_student_identity"] = {"email": email, "name": identity.get("name", "")}
    return redirect(url_for("register"))


@app.route("/register", methods=["GET", "POST"])
def register():
    identity = session.get("pending_student_identity")
    identity_email = (identity.get("email") or "").strip().lower() if identity else ""
    identity_domain = identity_email.rsplit("@", 1)[-1] if "@" in identity_email else ""
    if not identity or identity_domain not in ALLOWED_GOOGLE_DOMAINS:
        flash("Sign in with your school Google account before completing registration.", "info")
        return redirect(url_for("login"))
    form = RegisterForm()
    if form.validate_on_submit():
        email = identity["email"]
        student_id = form.student_id.data.strip()
        if User.query.filter((User.email == email) | (User.username == student_id)).first() or Student.query.filter_by(student_id=student_id).first():
            flash("That school email or student ID is already registered.", "danger")
        else:
            user = User(username=student_id, email=email, role="student")
            user.set_password(secrets.token_urlsafe(32))
            student = Student(user=user, student_id=student_id, first_name=form.first_name.data.strip(), middle_name=form.middle_name.data.strip(), last_name=form.last_name.data.strip(), contact_number=form.contact_number.data.strip(), program=form.program.data.strip(), year_level=form.year_level.data.strip(), section=form.section.data.strip(), academic_year=form.academic_year.data.strip())
            db.session.add(user)
            db.session.flush()
            log_action("Student registered", f"Student {student.student_id} created an account.", user)
            db.session.commit()
            session.pop("pending_student_identity", None)
            login_user(user)
            return redirect(url_for("dashboard"))
    return render_template("auth/register.html", form=form, school_email=identity["email"])


@app.route("/auth/cancel-registration")
def cancel_registration():
    session.pop("pending_student_identity", None)
    return redirect(url_for("login"))


@app.route("/logout")
@login_required
def logout():
    log_action("User logged out", f"{current_user.username} signed out.")
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "student":
        return redirect(url_for("student_dashboard"))
    if current_user.role == "staff":
        return redirect(url_for("staff_dashboard"))
    return redirect(url_for("admin_dashboard"))


def student_clearance_summary(student):
    requests_for_year = ClearanceRequest.query.filter_by(
        student_id=student.id,
        academic_year=student.academic_year,
    ).filter(ClearanceRequest.status != "cancelled").order_by(ClearanceRequest.created_at.asc()).all()
    if not requests_for_year:
        return None

    items = sorted(
        (
            item
            for clearance in requests_for_year
            for item in clearance.items
            if item.status != "cancelled" and item.office.is_active
        ),
        key=lambda item: (item.created_at, item.id),
    )
    statuses = {item.status for item in items}
    if statuses == {"approved"}:
        status = "completed"
    elif "rejected" in statuses:
        status = "rejected"
    elif "requires_action" in statuses:
        status = "requires_action"
    elif "approved" in statuses:
        status = "in_progress"
    else:
        status = "pending"
    approved_count = sum(item.status == "approved" for item in items)
    completed_dates = [clearance.completed_at for clearance in requests_for_year if clearance.completed_at]
    return SimpleNamespace(
        id=requests_for_year[-1].id,
        student=student,
        academic_year=student.academic_year,
        items=items,
        status=status,
        status_label=STATUS_LABELS.get(status, status.title()),
        progress=round(approved_count / len(items) * 100) if items else 0,
        submitted_at=requests_for_year[0].submitted_at,
        completed_at=max(completed_dates) if status == "completed" and completed_dates else None,
    )


@app.route("/student/dashboard")
@login_required
@role_required("student")
def student_dashboard():
    clearance = student_clearance_summary(current_user.student)
    offices = Office.query.filter_by(is_active=True).order_by(Office.name).all()
    approved_office_ids = {
        office_id
        for (office_id,) in db.session.query(ClearanceItem.office_id)
        .join(ClearanceRequest)
        .filter(
            ClearanceRequest.student_id == current_user.student.id,
            ClearanceRequest.academic_year == current_user.student.academic_year,
            ClearanceItem.status == "approved",
        )
        .distinct()
        .all()
    }
    requested_office_ids = set()
    if clearance and clearance.status not in {"completed", "cancelled"}:
        requested_office_ids = {item.office_id for item in clearance.items}
    unavailable_office_ids = requested_office_ids | approved_office_ids
    available_offices = [office for office in offices if office.id not in unavailable_office_ids]
    approved_offices = [office for office in offices if office.id in approved_office_ids]
    return render_template("student/dashboard.html", clearance=clearance, offices=available_offices, approved_offices=approved_offices)


@app.route("/student/clearance/start", methods=["POST"])
@login_required
@role_required("student")
def start_clearance():
    existing = ClearanceRequest.query.filter_by(student_id=current_user.student.id, academic_year=current_user.student.academic_year).filter(ClearanceRequest.status.notin_(["completed", "cancelled"])).first()
    selected_ids = {int(value) for value in request.form.getlist("office_ids") if value.isdigit()}
    offices = Office.query.filter(Office.is_active.is_(True), Office.id.in_(selected_ids)).order_by(Office.name).all()
    approved_office_ids = {
        office_id
        for (office_id,) in db.session.query(ClearanceItem.office_id)
        .join(ClearanceRequest)
        .filter(
            ClearanceRequest.student_id == current_user.student.id,
            ClearanceRequest.academic_year == current_user.student.academic_year,
            ClearanceItem.status == "approved",
        )
        .distinct()
        .all()
    }
    offices = [office for office in offices if office.id not in approved_office_ids]
    if existing:
        requested_ids = {item.office_id for item in existing.items}
        offices = [office for office in offices if office.id not in requested_ids]
    if not offices:
        flash("Choose at least one office that has not already been requested or approved this academic year.", "danger")
        return redirect(url_for("student_dashboard"))
    clearance = existing
    if not existing:
        clearance = ClearanceRequest(student=current_user.student, academic_year=current_user.student.academic_year)
        db.session.add(clearance)
        db.session.flush()
    clearance.items.extend(ClearanceItem(office=office) for office in offices)
    clearance.refresh_status()
    action = "Student added clearance offices" if existing else "Student submitted clearance"
    log_action(action, f"Clearance #{clearance.id} was updated by {current_user.student.student_id} with {len(offices)} office(s).")
    notify(current_user, "Clearance updated" if existing else "Clearance submitted", f"Your clearance request was sent to {len(offices)} selected office(s).")
    db.session.commit()
    flash("The selected offices have been added to your clearance." if existing else "Your clearance request has been submitted.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/student/clearance")
@login_required
@role_required("student")
def student_clearance():
    clearance = student_clearance_summary(current_user.student)
    return render_template("student/clearance.html", clearance=clearance)


@app.route("/student/clearance/cancel", methods=["POST"])
@login_required
@role_required("student")
def cancel_clearance():
    clearance = ClearanceRequest.query.filter_by(student_id=current_user.student.id).order_by(ClearanceRequest.created_at.desc()).first()
    if not clearance or clearance.status in {"completed", "cancelled"}:
        flash("This clearance cannot be cancelled.", "info")
    else:
        clearance.status = "cancelled"
        clearance.completed_at = None
        for item in clearance.items:
            item.status = "cancelled"
        log_action("Student cancelled clearance", f"Clearance #{clearance.id} was cancelled by {current_user.student.student_id}.")
        notify(current_user, "Clearance cancelled", "Your clearance request was cancelled. You may start a new request when ready.")
        db.session.commit()
        flash("Your clearance request was cancelled.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/student/clearances/cancel-all", methods=["POST"])
@login_required
@role_required("student")
def cancel_all_clearances():
    active_clearances = ClearanceRequest.query.filter(
        ClearanceRequest.student_id == current_user.student.id,
        ClearanceRequest.status.notin_(["completed", "cancelled"]),
    ).all()
    if not active_clearances:
        flash("There are no unfinished clearance requests to cancel.", "info")
        return redirect(url_for("student_dashboard"))
    for clearance in active_clearances:
        clearance.status = "cancelled"
        clearance.completed_at = None
        for item in clearance.items:
            item.status = "cancelled"
            item.reviewed_by = None
            item.reviewed_at = None
    log_action("Student cancelled all clearances", f"{current_user.student.student_id} cancelled {len(active_clearances)} unfinished clearance request(s).")
    notify(current_user, "All clearance requests cancelled", "All of your unfinished clearance requests were cancelled.")
    db.session.commit()
    flash("All unfinished clearance requests were cancelled.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/student/clearance/item/<int:item_id>/cancel", methods=["POST"])
@login_required
@role_required("student")
def cancel_clearance_item(item_id):
    item = db.session.get(ClearanceItem, item_id)
    if not item or item.clearance.student_id != current_user.student.id:
        abort(404)
    if item.clearance.status == "completed" or item.status in {"approved", "cancelled"}:
        flash("This office request cannot be cancelled.", "info")
    else:
        item.status = "cancelled"
        item.reviewed_by = None
        item.reviewed_at = None
        item.clearance.refresh_status()
        log_action("Student cancelled office request", f"{current_user.student.student_id} cancelled the {item.office.name} request for clearance #{item.clearance.id}.")
        notify(current_user, "Office request cancelled", f"Your {item.office.name} clearance request was cancelled.")
        db.session.commit()
        flash(f"The {item.office.name} request was cancelled.", "success")
    return redirect(url_for("student_clearance"))


@app.route("/student/clearance/item/<int:item_id>/upload", methods=["POST"])
@login_required
@role_required("student")
def upload_requirement(item_id):
    item = db.session.get(ClearanceItem, item_id)
    if not item or item.clearance.student_id != current_user.student.id:
        abort(404)
    if item.clearance.status in {"completed", "cancelled"} or item.status == "cancelled":
        flash("This clearance cannot be changed.", "info")
        return redirect(url_for("student_clearance"))
    uploaded_file = request.files.get("document")
    if not uploaded_file or not uploaded_file.filename:
        flash("Choose a requirement file first.", "danger")
        return redirect(url_for("student_clearance"))
    original_name = secure_filename(uploaded_file.filename)
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        flash("Allowed files: PDF, Word documents, JPG, PNG.", "danger")
        return redirect(url_for("student_clearance"))
    stored_name = f"clearance-{item.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{extension}"
    uploaded_file.save(UPLOAD_DIR / stored_name)
    item.document_name = original_name
    item.document_path = stored_name
    item.uploaded_at = datetime.utcnow()
    item.status = "pending"
    item.reviewed_by = None
    item.reviewed_at = None
    item.clearance.refresh_status()
    log_action("Student uploaded requirement", f"{current_user.student.student_id} uploaded a requirement for {item.office.name}.")
    notify(item.office.staff[0].user, "Requirement submitted", f"A requirement was uploaded for {item.clearance.student.full_name}.") if item.office.staff else None
    db.session.commit()
    flash(f"Requirement sent to {item.office.name}.", "success")
    return redirect(url_for("student_clearance"))


@app.route("/clearance/item/<int:item_id>/document")
@login_required
def download_requirement(item_id):
    item = db.session.get(ClearanceItem, item_id)
    if not item or not item.document_path:
        abort(404)
    is_owner = current_user.role == "student" and item.clearance.student_id == current_user.student.id
    is_assigned = current_user.role == "staff" and OfficeStaff.query.filter_by(user_id=current_user.id, office_id=item.office_id).first()
    if current_user.role != "admin" and not is_owner and not is_assigned:
        abort(403)
    return send_from_directory(UPLOAD_DIR, item.document_path, download_name=item.document_name, as_attachment=False)


@app.route("/student/clearance/print")
@login_required
@role_required("student")
def print_clearance():
    clearance = student_clearance_summary(current_user.student)
    if not clearance or clearance.status != "completed":
        abort(404)
    return render_template("student/print_clearance.html", clearance=clearance)


@app.route("/staff/dashboard")
@login_required
@role_required("staff")
def staff_dashboard():
    office_ids = [assignment.office_id for assignment in OfficeStaff.query.filter_by(user_id=current_user.id).all()]
    items = ClearanceItem.query.join(ClearanceRequest).filter(ClearanceItem.office_id.in_(office_ids), ClearanceItem.status != "cancelled", ClearanceRequest.status != "cancelled").order_by(ClearanceItem.updated_at.desc()).all() if office_ids else []
    return render_template("staff/dashboard.html", items=items)


@app.route("/staff/clearance/<int:item_id>", methods=["GET", "POST"])
@login_required
@role_required("staff")
def review_clearance(item_id):
    item = db.session.get(ClearanceItem, item_id)
    assigned = OfficeStaff.query.filter_by(user_id=current_user.id, office_id=item.office_id).first() if item else None
    if not item or not assigned:
        abort(404)
    if item.clearance.status == "cancelled" or item.status == "cancelled":
        abort(404)
    form = ReviewForm(obj=item)
    if form.validate_on_submit():
        old_status = item.status
        item.status = form.status.data
        item.remarks = form.remarks.data.strip()
        item.reviewed_by = current_user.id
        item.reviewed_at = datetime.utcnow()
        clearance = item.clearance
        clearance.refresh_status()
        log_action(f"Office {item.status}", f"{item.office.name} changed clearance #{clearance.id} for {clearance.student.student_id} from {old_status} to {item.status}.")
        notify(clearance.student.user, f"{item.office.name}: {STATUS_LABELS[item.status]}", item.remarks or f"Your {item.office.name} clearance item was updated.")
        if clearance.status == "completed":
            notify(clearance.student.user, "Clearance completed", "All required offices have approved your clearance. You may now print it.")
        db.session.commit()
        flash("The clearance item was updated.", "success")
        return redirect(url_for("staff_dashboard"))
    return render_template("staff/review.html", item=item, form=form)


@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    active_clearances = ClearanceRequest.query.filter(ClearanceRequest.status != "cancelled")
    stats = {"students": Student.query.count(), "clearances": active_clearances.count(), "pending": active_clearances.filter(ClearanceRequest.status.in_(["pending", "in_progress", "requires_action"])).count(), "completed": active_clearances.filter(ClearanceRequest.status == "completed").count(), "rejected": active_clearances.filter(ClearanceRequest.status == "rejected").count()}
    return render_template("admin/dashboard.html", stats=stats, recent_logs=ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(8).all())


@app.route("/admin/students")
@login_required
@role_required("admin")
def admin_students():
    query = request.args.get("q", "").strip()
    students_query = Student.query.order_by(Student.last_name, Student.first_name)
    if query:
        students_query = students_query.filter((Student.student_id.ilike(f"%{query}%")) | (Student.first_name.ilike(f"%{query}%")) | (Student.last_name.ilike(f"%{query}%")))
    return render_template("admin/students.html", students=students_query.all(), query=query)


@app.route("/admin/clearances")
@login_required
@role_required("admin")
def admin_clearances():
    status = request.args.get("status", "").strip()
    query = ClearanceRequest.query.join(Student).filter(ClearanceRequest.status != "cancelled").order_by(ClearanceRequest.created_at.desc())
    if status:
        query = query.filter(ClearanceRequest.status == status)
    return render_template("admin/clearances.html", clearances=query.all(), selected_status=status)


@app.route("/admin/offices", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_offices():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        staff_username = request.form.get("staff_username", "").strip()
        staff_password = request.form.get("staff_password", "")
        existing_staff = User.query.filter_by(username=staff_username).first() if staff_username else None
        staff_email = f"{staff_username}@spc-surigao.edu.ph" if staff_username else None
        email_exists = User.query.filter_by(email=staff_email).first() if staff_email and not existing_staff else None
        error = None

        if not name:
            error = "Enter an office or teacher name."
        elif Office.query.filter_by(name=name).first():
            error = "Enter a unique office or teacher name."
        elif staff_username and not re.fullmatch(r"[A-Za-z0-9._-]{3,80}", staff_username):
            error = "Staff usernames may contain letters, numbers, periods, underscores, and hyphens."
        elif staff_password and not staff_username:
            error = "Enter a staff username to use an initial password."
        elif existing_staff and existing_staff.role != "staff":
            error = "That username belongs to a non-staff account."
        elif existing_staff and staff_password:
            error = "Leave the initial password blank for an existing staff account."
        elif staff_username and not existing_staff and len(staff_password) < 8:
            error = "New staff accounts require an initial password of at least 8 characters."
        elif email_exists:
            error = "The generated staff email is already in use."

        if error:
            flash(error, "danger")
        else:
            office = Office(name=name, description=description)
            db.session.add(office)
            db.session.flush()
            if staff_username:
                staff_user = existing_staff or User(
                    username=staff_username,
                    email=staff_email,
                    role="staff",
                )
                if not existing_staff:
                    staff_user.set_password(staff_password)
                    db.session.add(staff_user)
                    db.session.flush()
                db.session.add(OfficeStaff(user_id=staff_user.id, office_id=office.id))
            assignment_detail = f" Staff account {staff_username} was assigned." if staff_username else ""
            log_action("Admin created office", f"Office {name} was added.{assignment_detail}")
            db.session.commit()
            flash("Office and staff assignment added." if staff_username else "Office added.", "success")
    return render_template("admin/offices.html", offices=Office.query.order_by(Office.name).all())


@app.route("/admin/offices/<int:office_id>/toggle", methods=["POST"])
@login_required
@role_required("admin")
def admin_toggle_office(office_id):
    office = db.session.get(Office, office_id)
    if not office:
        abort(404)
    office.is_active = not office.is_active
    action = "restored" if office.is_active else "removed"
    log_action(f"Admin {action} office", f"Office {office.name} was {action} from active use.")
    db.session.commit()
    flash(f"{office.name} {action}.", "success")
    return redirect(url_for("admin_offices"))


@app.route("/admin/reports")
@login_required
@role_required("admin")
def admin_reports():
    office_stats = []
    for office in Office.query.order_by(Office.name).all():
        items = ClearanceItem.query.join(ClearanceRequest).filter(ClearanceItem.office_id == office.id, ClearanceItem.status != "cancelled", ClearanceRequest.status != "cancelled").all()
        office_stats.append({"office": office, "total": len(items), "approved": sum(i.status == "approved" for i in items), "pending": sum(i.status == "pending" for i in items)})
    return render_template("admin/reports.html", office_stats=office_stats)


@app.route("/admin/logs")
@login_required
@role_required("admin")
def admin_logs():
    return render_template("admin/logs.html", logs=ActivityLog.query.order_by(ActivityLog.created_at.desc()).all())


@app.route("/notifications")
@login_required
def notifications():
    rows = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html", notifications=rows)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if current_user.role == "student":
        student = current_user.student
        if request.method == "POST":
            photo_action = request.form.get("profile_action")
            if photo_action == "remove_photo":
                photo_path = PROFILE_PHOTO_DIR / f"{current_user.id}.jpg"
                if photo_path.exists():
                    photo_path.unlink()
                student.profile_photo_path = None
                db.session.commit()
                flash("Your profile photo was removed.", "success")
                return redirect(url_for("profile"))
            if photo_action == "photo":
                uploaded_photo = request.files.get("profile_photo")
                if not uploaded_photo or not uploaded_photo.filename:
                    flash("Choose a photo to upload.", "danger")
                    return redirect(url_for("profile"))
                photo_data = uploaded_photo.read(5 * 1024 * 1024 + 1)
                if len(photo_data) > 5 * 1024 * 1024:
                    flash("Choose a photo smaller than 5 MB.", "danger")
                    return redirect(url_for("profile"))
                try:
                    image = Image.open(io.BytesIO(photo_data))
                    if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 40_000_000:
                        raise ValueError("Unsupported image format or dimensions")
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                    image.save(PROFILE_PHOTO_DIR / f"{current_user.id}.jpg", "JPEG", quality=82, optimize=True)
                    student.profile_photo_path = f"{current_user.id}.jpg"
                except (UnidentifiedImageError, OSError, ValueError):
                    flash("Upload a valid JPEG, PNG, or WebP photo under 5 MB.", "danger")
                    return redirect(url_for("profile"))
                db.session.commit()
                flash("Your profile photo was updated.", "success")
                return redirect(url_for("profile"))
            if photo_action != "details":
                abort(400)
            profile_values = {
                "first_name": request.form.get("first_name", "").strip(),
                "middle_name": request.form.get("middle_name", "").strip(),
                "last_name": request.form.get("last_name", "").strip(),
                "contact_number": request.form.get("contact_number", "").strip(),
                "program": request.form.get("program", "").strip(),
                "year_level": request.form.get("year_level", "").strip(),
            }
            field_limits = {
                "first_name": 80,
                "middle_name": 80,
                "last_name": 80,
                "contact_number": 30,
                "program": 120,
                "year_level": 30,
            }
            required_fields = ("first_name", "last_name", "program", "year_level")
            if any(not profile_values[name] for name in required_fields) or any(
                len(profile_values[name]) > limit
                for name, limit in field_limits.items()
            ):
                flash("Complete the required fields and check their lengths.", "danger")
                return render_template(
                    "profile.html", student=student, profile_editing=True
                )
            for field, value in profile_values.items():
                setattr(student, field, value)
            log_action(
                "Student updated profile",
                f"Student {student.student_id} updated their profile details.",
            )
            db.session.commit()
            flash("Your profile was updated.", "success")
            return redirect(url_for("profile"))
        return render_template(
            "profile.html", student=student, profile_editing=False
        )
    return render_template("profile.html", student=None)


@app.route("/profile/photo")
@login_required
def profile_photo():
    if current_user.role != "student" or not current_user.student.profile_photo_path:
        abort(404)
    return send_from_directory(PROFILE_PHOTO_DIR, current_user.student.profile_photo_path, mimetype="image/jpeg", max_age=3600)


@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    notification.is_read = True
    db.session.commit()
    return redirect(url_for("notifications"))


@app.route("/admin/clearances.csv")
@login_required
@role_required("admin")
def export_clearances():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Student", "Academic Year", "Status", "Progress", "Submitted"])
    for clearance in ClearanceRequest.query.join(Student).filter(ClearanceRequest.status != "cancelled").order_by(ClearanceRequest.created_at.desc()).all():
        writer.writerow([clearance.student.student_id, clearance.student.full_name, clearance.academic_year, clearance.status_label, f"{clearance.progress}%", clearance.submitted_at.strftime("%Y-%m-%d")])
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv", as_attachment=True, download_name="clearances.csv")


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message="You do not have permission to access this page."), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="The page you requested could not be found."), 404


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return render_template("error.html", code=500, message="Something went wrong while processing your request."), 500


initialize_database()

if __name__ == "__main__":
    app.run(debug=True)
