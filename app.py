# app.py
# Module 0 - Common Foundation imports - Authentication & User Profile
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response, abort, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import os
import random
import csv
import io
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer as Serializer
from PIL import Image

# Module 0 - Load environment variables for configuration
load_dotenv()

# Module 0 - Initialize Flask application
app = Flask(__name__)

# Module 0 - Configuration settings for the application
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-this')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///food_waste.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Module 0 - Email configuration settings
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'noreply@foodshare.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'password')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@foodshare.com')

# Module 0 - File upload configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Module 0 - Initialize Flask extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
mail = Mail(app)

# Module 0 - Database Models for User Authentication and Profiles
class User(UserMixin, db.Model):
    # Module 0 - Base user authentication fields
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'donor', 'ngo'
    is_active = db.Column(db.Boolean, default=True)
    profile_pic = db.Column(db.String(200), default='default.jpg')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Module 0 - User relationships
    food_listings = db.relationship('FoodListing', backref='donor', lazy=True, cascade='all, delete-orphan')
    claims = db.relationship('Claim', backref='receiver', lazy=True, cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade='all, delete-orphan')
    
    # Module 0 - User authentication methods
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_role_display(self):
        role_names = {
            'donor': 'Food Donor',
            'ngo': 'NGO/Organization'
        }
        return role_names.get(self.role, self.role)
    
    @property
    def unread_notifications(self):
        return Notification.query.filter_by(user_id=self.id, is_read=False).count()
    
    @property
    def average_rating(self):
        """Calculate average rating received by this user"""
        reviews = Review.query.filter_by(to_user_id=self.id).all()
        if not reviews:
            return None
        return sum(review.rating for review in reviews) / len(reviews)
    
    @property
    def total_reviews(self):
        """Get total number of reviews received by this user"""
        return Review.query.filter_by(to_user_id=self.id).count()
    
    def generate_reset_token(self, expires_sec=1800):
        s = Serializer(app.config['SECRET_KEY'], expires_sec)
        return s.dumps({'user_id': self.id}).decode('utf-8')
    
    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token)['user_id']
        except:
            return None
        return db.session.get(User, user_id)

# Module 0 - Donor Profile Table - Separate table for donor-specific information
class Donor(db.Model):
    # Module 0 - Donor profile fields
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organization = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Module 0 - Relationship with User model
    user = db.relationship('User', backref=db.backref('donor_profile', uselist=False, cascade='all, delete-orphan'))

# Module 0 - NGO Profile Table - Separate table for NGO-specific information  
class NGO(db.Model):
    # Module 0 - NGO profile fields
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organization = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    verified = db.Column(db.Boolean, default=False)
    registration_number = db.Column(db.String(100))
    ngo_type = db.Column(db.String(100))  # e.g., 'Charity', 'Community Center', 'Shelter'
    capacity = db.Column(db.Integer)  # Number of people they can serve
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Module 0 - Relationship with User model
    user = db.relationship('User', backref=db.backref('ngo_profile', uselist=False, cascade='all, delete-orphan'))

# Module 0 - Admin authentication model for admin users
class Admin(UserMixin, db.Model):
    # Module 0 - Admin authentication fields
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(50), default='editor')  # 'viewer', 'editor', 'superadmin'
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Module 0 - Admin authentication methods
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def generate_reset_token(self, expires_sec=1800):
        s = Serializer(app.config['SECRET_KEY'], expires_sec)
        return s.dumps({'admin_id': self.id}).decode('utf-8')
    
    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.config['SECRET_KEY'])
        try:
            admin_id = s.loads(token)['admin_id']
        except:
            return None
        return db.session.get(Admin, admin_id)

# Module 1 - Donor Operations: Food Listing Model
class FoodListing(db.Model):
    # Module 1 - Food donation fields
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    food_type = db.Column(db.String(50))
    quantity = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(300), nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    pickup_address = db.Column(db.Text)
    pickup_start = db.Column(db.DateTime, nullable=False)
    pickup_end = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='available')
    allergens = db.Column(db.Text)
    image = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Module 1 - Freshness calculator fields
    cooked_time = db.Column(db.DateTime, nullable=True)  # When the food was cooked
    expires_in_hours = db.Column(db.Integer, default=4)  # Default 4 hours freshness
    expiry_time = db.Column(db.DateTime, nullable=True)  # Calculated expiry time
    is_deleted = db.Column(db.Boolean, default=False)  # Soft delete flag
    
    # Module 1 - Food listing relationships
    donor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    claims = db.relationship('Claim', backref='food_listing', lazy=True, cascade='all, delete-orphan')
    
    def calculate_freshness(self):
        """Calculate expiry time based on cooked time and freshness duration"""
        if self.cooked_time and self.expires_in_hours:
            self.expiry_time = self.cooked_time + timedelta(hours=self.expires_in_hours)
            return self.expiry_time
        return None
    
    def get_freshness_status(self):
        """Get current freshness status"""
        if not self.expiry_time:
            return "unknown"
        
        now = datetime.utcnow()
        time_remaining = (self.expiry_time - now).total_seconds() / 3600  # hours
        
        if time_remaining <= 0:
            return "expired"
        elif time_remaining <= 1:
            return "critical"
        elif time_remaining <= 2:
            return "warning"
        else:
            return "fresh"

# Module 3 - Transaction & Verification: Claim Model
class Claim(db.Model):
    # Module 3 - Claim transaction fields
    id = db.Column(db.Integer, primary_key=True)
    food_listing_id = db.Column(db.Integer, db.ForeignKey('food_listing.id'), nullable=False)
    ngo_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    pickup_time = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    people_served = db.Column(db.Integer)
    otp_code = db.Column(db.String(4), nullable=True)
    otp_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Module 0 - Global Notification Model
class Notification(db.Model):
    # Module 0 - Notification fields
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    notification_type = db.Column(db.String(50))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Module 4 - Fulfillment & Logistics: Review Model
class Review(db.Model):
    # Module 4 - Review fields for fulfillment feedback
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    claim_id = db.Column(db.Integer, db.ForeignKey('claim.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Module 4 - Fulfillment & Logistics: Archive Model
class ArchiveClaim(db.Model):
    # Module 4 - Archive completed claims for history and reporting
    id = db.Column(db.Integer, primary_key=True)
    original_claim_id = db.Column(db.Integer, nullable=False)  # Reference to original claim
    food_listing_id = db.Column(db.Integer, db.ForeignKey('food_listing.id'), nullable=False)
    donor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ngo_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Food details (archived from original listing)
    food_title = db.Column(db.String(200), nullable=False)
    food_description = db.Column(db.Text)
    food_type = db.Column(db.String(50))
    quantity = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    pickup_address = db.Column(db.Text)
    
    # Claim details
    status = db.Column(db.String(20), default='picked_up')  # Always picked_up for archived
    people_served = db.Column(db.Integer)
    otp_verified = db.Column(db.Boolean, default=True)
    
    # Timestamps
    claim_created_at = db.Column(db.DateTime, nullable=False)
    pickup_time = db.Column(db.DateTime, nullable=False)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Notes and additional info
    notes = db.Column(db.Text)
    
    # Relationships
    food_listing = db.relationship('FoodListing', backref='archived_claims')
    donor = db.relationship('User', foreign_keys=[donor_id], backref='donated_archived')
    ngo = db.relationship('User', foreign_keys=[ngo_id], backref='received_archived')

# Module 5 - Admin & Analytics: City Master Model
class CityMaster(db.Model):
    # Module 5 - City management for registration dropdown
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    state = db.Column(db.String(50), nullable=False)
    country = db.Column(db.String(50), default='India')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Module 5 - Admin & Analytics: Report Model
class Report(db.Model):
    # Module 5 - Content moderation reports
    id = db.Column(db.Integer, primary_key=True)
    food_listing_id = db.Column(db.Integer, db.ForeignKey('food_listing.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, reviewed, resolved, dismissed
    admin_notes = db.Column(db.Text)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('admin.id'))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    food_listing = db.relationship('FoodListing', backref='reports')
    reporter = db.relationship('User', backref='reports_filed')
    reviewer = db.relationship('Admin', backref='reports_reviewed')

# Module 0 - User loader for authentication system
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Helper functions
def generate_otp():
    return ''.join([str(random.randint(0,9)) for _ in range(4)])

def send_email(recipient, subject, body):
    try:
        msg = Message(subject, recipients=[recipient], body=body)
        mail.send(msg)
        print(f"Email sent to {recipient}: {subject}")
    except Exception as e:
        print(f"Email error: {e}")
        # For development, just print the email instead of failing
        print(f"MOCK EMAIL - To: {recipient}, Subject: {subject}")
        print(f"Body: {body}")
        return True

def calculate_distance(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def format_datetime(value, format='%b %d, %Y %I:%M %p'):
    if value is None:
        return ""
    return value.strftime(format)

app.jinja_env.filters['datetime'] = format_datetime

# =============== ROUTES ===============

@app.route('/')
def index():
    total_donations = FoodListing.query.filter_by(is_deleted=False).count()
    total_meals = db.session.query(db.func.sum(FoodListing.quantity)).filter(FoodListing.is_deleted == False).scalar() or 0
    total_ngos = User.query.filter_by(role='ngo').count()
    total_donors = User.query.filter_by(role='donor').count()
    return render_template('index.html', 
                         total_donations=total_donations,
                         total_meals=total_meals,
                         total_ngos=total_ngos,
                         total_donors=total_donors)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = request.form.get('role')
        organization = request.form.get('organization', '')
        phone = request.form.get('phone', '')
        address = request.form.get('address', '')
        city = request.form.get('city', '')
        state = request.form.get('state', '')
        zip_code = request.form.get('zip_code', '')
        
        errors = []
        if password != confirm_password:
            errors.append('Passwords do not match')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters long')
        if not any(c.isupper() for c in password):
            errors.append('Password must contain at least 1 uppercase letter')
        if not any(c.isdigit() or not c.isalnum() for c in password):
            errors.append('Password must contain at least 1 number or special character')
        if phone and (not phone.isdigit() or len(phone) != 10):
            errors.append('Phone number must be exactly 10 digits')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered')
        if User.query.filter_by(username=username).first():
            errors.append('Username already taken')
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html')
        
        # Create base user - NGOs are inactive by default (pending approval)
        is_active = True if role == 'donor' else False
        user = User(
            username=username,
            email=email,
            role=role,
            is_active=is_active
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        # Create role-specific profile
        if role == 'donor':
            donor_profile = Donor(
                user_id=user.id,
                organization=organization,
                phone=phone,
                address=address,
                city=city,
                state=state,
                zip_code=zip_code
            )
            db.session.add(donor_profile)
        elif role == 'ngo':
            ngo_profile = NGO(
                user_id=user.id,
                organization=organization,
                phone=phone,
                address=address,
                city=city,
                state=state,
                zip_code=zip_code
            )
            db.session.add(ngo_profile)
        
        db.session.commit()
        
        # Different success messages based on role
        if role == 'donor':
            flash('Registration successful! Please login.', 'success')
        else:
            flash('Registration successful! Your account is pending admin approval. You will be notified once approved.', 'info')
        
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/register/donor')
def register_donor():
    return render_template('register_donor.html')

@app.route('/register/ngo')
def register_ngo():
    return render_template('register_ngo.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# =============== ADMIN REGISTRATION & LOGIN ===============
@app.route('/admin/register', methods=['GET', 'POST'])
def admin_register():
    # Check if admin already logged in
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        admin_key = request.form.get('admin_key')
        
        # Admin registration key for security
        ADMIN_REGISTRATION_KEY = os.getenv('ADMIN_REGISTRATION_KEY', 'admin-secret-key')
        
        errors = []
        if admin_key != ADMIN_REGISTRATION_KEY:
            errors.append('Invalid admin registration key')
        if password != confirm_password:
            errors.append('Passwords do not match')
        if Admin.query.filter_by(email=email).first():
            errors.append('Email already registered')
        if Admin.query.filter_by(username=username).first():
            errors.append('Username already taken')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('admin/register.html')
        
        admin = Admin(
            username=username,
            email=email,
            full_name=full_name,
            role='editor'
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        flash('Admin registration successful! Please login.', 'success')
        return redirect(url_for('admin_login'))
    
    return render_template('admin/register.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    # Check if admin already logged in
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        admin = Admin.query.filter_by(email=email).first()
        if admin and admin.check_password(password) and admin.is_active:
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            if remember:
                session.permanent = True
            admin.last_login = datetime.utcnow()
            db.session.commit()
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_username', None)
    flash('Admin logged out successfully.', 'info')
    return redirect(url_for('index'))

def admin_login_required(f):
    """Decorator to require admin login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Please login as admin first', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'donor':
        return redirect(url_for('donor_dashboard'))
    elif current_user.role == 'ngo':
        return redirect(url_for('ngo_dashboard'))
    else:
        flash('Invalid user role', 'danger')
        return redirect(url_for('index'))

# =============== PROFILE ===============
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # Update base user info
        current_user.username = request.form.get('username')
        current_user.email = request.form.get('email')
        
        errors = []
        
        # Update role-specific profile
        if current_user.role == 'donor':
            donor_profile = current_user.donor_profile
            if donor_profile:
                phone = request.form.get('phone')
                if phone and (not phone.isdigit() or len(phone) != 10):
                    errors.append('Phone number must be exactly 10 digits')
                donor_profile.organization = request.form.get('organization')
                donor_profile.phone = phone
                donor_profile.address = request.form.get('address')
                donor_profile.city = request.form.get('city')
                donor_profile.state = request.form.get('state')
                donor_profile.zip_code = request.form.get('zip_code')
                donor_profile.latitude = float(request.form.get('latitude', 0)) if request.form.get('latitude') else None
                donor_profile.longitude = float(request.form.get('longitude', 0)) if request.form.get('longitude') else None
        elif current_user.role == 'ngo':
            ngo_profile = current_user.ngo_profile
            if ngo_profile:
                phone = request.form.get('phone')
                if phone and (not phone.isdigit() or len(phone) != 10):
                    errors.append('Phone number must be exactly 10 digits')
                ngo_profile.organization = request.form.get('organization')
                ngo_profile.phone = phone
                ngo_profile.address = request.form.get('address')
                ngo_profile.city = request.form.get('city')
                ngo_profile.state = request.form.get('state')
                ngo_profile.zip_code = request.form.get('zip_code')
                ngo_profile.latitude = float(request.form.get('latitude', 0)) if request.form.get('latitude') else None
                ngo_profile.longitude = float(request.form.get('longitude', 0)) if request.form.get('longitude') else None
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('profile.html', user=current_user)
        
        # Handle profile picture with image resizing
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file.filename != '':
                filename = secure_filename(f"user_{current_user.id}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Open and resize image
                img = Image.open(file)
                img = img.resize((300, 300), Image.Resampling.LANCZOS)
                img.save(filepath, optimize=True, quality=85)
                
                current_user.profile_pic = filename
        
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile'))
    
    return render_template('profile.html', user=current_user)

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    old = request.form.get('old_password')
    new = request.form.get('new_password')
    
    errors = []
    if len(new) < 8:
        errors.append('Password must be at least 8 characters long')
    if not any(c.isupper() for c in new):
        errors.append('Password must contain at least 1 uppercase letter')
    if not any(c.isdigit() or not c.isalnum() for c in new):
        errors.append('Password must contain at least 1 number or special character')
    
    if errors:
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('profile'))
    
    if current_user.check_password(old):
        current_user.set_password(new)
        db.session.commit()
        flash('Password changed.', 'success')
    else:
        flash('Incorrect old password.', 'danger')
    return redirect(url_for('profile'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            # Generate OTP and store in session with expiry
            otp = generate_otp()
            session['reset_otp'] = otp
            session['reset_email'] = email
            session['reset_otp_expiry'] = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
            
            # Send OTP via email
            send_email(user.email, 'Password Reset OTP',
                       f'Your OTP for password reset is: {otp}\nThis OTP will expire in 10 minutes.')
            flash('OTP sent to your email. Please enter it to reset your password.', 'info')
            return redirect(url_for('verify_reset_otp'))
        else:
            flash('Email not found.', 'danger')
    return render_template('forgot_password.html')

@app.route('/verify_reset_otp', methods=['GET', 'POST'])
def verify_reset_otp():
    if 'reset_otp' not in session:
        flash('Please request an OTP first.', 'warning')
        return redirect(url_for('forgot_password'))
    
    # Check if OTP expired
    expiry = datetime.fromisoformat(session.get('reset_otp_expiry'))
    if datetime.utcnow() > expiry:
        session.pop('reset_otp', None)
        session.pop('reset_email', None)
        session.pop('reset_otp_expiry', None)
        flash('OTP has expired. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        if otp_entered == session.get('reset_otp'):
            # OTP verified, redirect to reset password
            return redirect(url_for('reset_password_with_otp'))
        else:
            flash('Invalid OTP. Please try again.', 'danger')
    
    return render_template('verify_reset_otp.html')

@app.route('/reset_password_with_otp', methods=['GET', 'POST'])
def reset_password_with_otp():
    if 'reset_email' not in session:
        flash('Session expired. Please start over.', 'warning')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html')
        
        email = session.get('reset_email')
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(password)
            db.session.commit()
            
            # Clear session
            session.pop('reset_otp', None)
            session.pop('reset_email', None)
            session.pop('reset_otp_expiry', None)
            
            flash('Password reset successful. Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('User not found.', 'danger')
            return redirect(url_for('forgot_password'))
    
    return render_template('reset_password.html')

# =============== DONOR ROUTES ===============
@app.route('/donor/dashboard')
@login_required
def donor_dashboard():
    if current_user.role != 'donor':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    listings = FoodListing.query.filter_by(donor_id=current_user.id, is_deleted=False)\
        .order_by(FoodListing.created_at.desc()).limit(5).all()
    claims = Claim.query.join(FoodListing)\
        .filter(FoodListing.donor_id == current_user.id, FoodListing.is_deleted == False)\
        .order_by(Claim.created_at.desc()).limit(5).all()
    total_listings = FoodListing.query.filter_by(donor_id=current_user.id, is_deleted=False).count()
    available_listings = FoodListing.query.filter_by(donor_id=current_user.id, status='available', is_deleted=False).count()
    claimed_listings = FoodListing.query.filter_by(donor_id=current_user.id, status='claimed', is_deleted=False).count()
    total_meals_result = db.session.query(db.func.sum(FoodListing.quantity))\
        .filter(FoodListing.donor_id == current_user.id, FoodListing.status == 'picked_up', FoodListing.is_deleted == False).first()
    total_meals = total_meals_result[0] or 0 if total_meals_result else 0
    return render_template('donor/donor_dashboard.html',
                         listings=listings,
                         claims=claims,
                         total_listings=total_listings,
                         available_listings=available_listings,
                         claimed_listings=claimed_listings,
                         total_meals=total_meals)

@app.route('/create_listing', methods=['GET', 'POST'])
@login_required
def create_listing():
    if current_user.role != 'donor':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    copy_id = request.args.get('copy_from')
    copy_listing = None
    if copy_id:
        copy_listing = db.session.get(FoodListing, copy_id)
        if copy_listing and copy_listing.donor_id != current_user.id:
            copy_listing = None

    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        food_type = request.form.get('food_type')
        quantity = int(request.form.get('quantity'))
        location = request.form.get('location')
        pickup_address = request.form.get('pickup_address')
        pickup_start_str = request.form.get('pickup_start')
        pickup_end_str = request.form.get('pickup_end')
        allergens = request.form.get('allergens', '')
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        
        # Freshness calculator fields
        cooked_time_str = request.form.get('cooked_time')
        expires_in_hours = int(request.form.get('expires_in_hours', 4))
        
        # Auto-generate pickup times if not provided
        if pickup_start_str and pickup_end_str:
            pickup_start = datetime.fromisoformat(pickup_start_str.replace('Z', '+00:00'))
            pickup_end = datetime.fromisoformat(pickup_end_str.replace('Z', '+00:00'))
        else:
            # Automatic: Start = now, End = +2 hours (using local time)
            pickup_start = datetime.now()
            pickup_end = pickup_start + timedelta(hours=2)
        
        listing = FoodListing(
            title=title,
            description=description,
            food_type=food_type,
            quantity=quantity,
            location=location,
            pickup_address=pickup_address,
            pickup_start=pickup_start,
            pickup_end=pickup_end,
            allergens=allergens,
            expires_in_hours=expires_in_hours,
            donor_id=current_user.id
        )
        
        # Handle cooked time and calculate freshness
        if cooked_time_str:
            listing.cooked_time = datetime.fromisoformat(cooked_time_str.replace('Z', '+00:00'))
            listing.calculate_freshness()
        
        # Add GPS coordinates if provided
        if latitude and longitude:
            listing.latitude = float(latitude)
            listing.longitude = float(longitude)
        
        # Handle image upload with compression
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                filename = secure_filename(f"food_{datetime.utcnow().timestamp()}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Open and compress image
                img = Image.open(file)
                img = img.resize((800, 600), Image.Resampling.LANCZOS)
                img.save(filepath, optimize=True, quality=80)
                
                listing.image = filename
        
        db.session.add(listing)
        db.session.commit()
        
        # Notify NGOs (optional, can be heavy)
        flash('Food listing created successfully!', 'success')
        return redirect(url_for('donor_dashboard'))
    
    now = datetime.now()  # Use local time instead of UTC
    default_start = now.strftime('%Y-%m-%dT%H:%M')
    default_end = (now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
    
    # Also create formatted display times
    display_start = now.strftime('%b %d, %Y %I:%M %p')
    display_end = (now + timedelta(hours=2)).strftime('%b %d, %Y %I:%M %p')
    
    return render_template('donor/create_listing.html',
                         default_start=default_start,
                         default_end=default_end,
                         display_start=display_start,
                         display_end=display_end,
                         copy=copy_listing)

@app.route('/my_listings')
@login_required
def my_listings():
    if current_user.role != 'donor':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    listings = FoodListing.query.filter_by(donor_id=current_user.id, is_deleted=False)\
        .order_by(FoodListing.created_at.desc()).all()
    return render_template('donor/my_listings.html', listings=listings)

@app.route('/listing/<int:listing_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_listing(listing_id):
    if current_user.role != 'donor':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    listing = FoodListing.query.get_or_404(listing_id)
    if listing.donor_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('my_listings'))
    if listing.status != 'available':
        flash('Only available listings can be edited', 'warning')
        return redirect(url_for('my_listings'))
    if request.method == 'POST':
        listing.title = request.form.get('title')
        listing.quantity = int(request.form.get('quantity'))
        pickup_end_str = request.form.get('pickup_end')
        listing.pickup_end = datetime.fromisoformat(pickup_end_str.replace('Z', '+00:00'))
        db.session.commit()
        flash('Listing updated successfully!', 'success')
        return redirect(url_for('my_listings'))
    return render_template('donor/edit_listing.html', listing=listing)

@app.route('/listing/<int:listing_id>/delete', methods=['POST'])
@login_required
def delete_listing(listing_id):
    if current_user.role != 'donor':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    listing = FoodListing.query.get_or_404(listing_id)
    if listing.donor_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('my_listings'))
    
    # Soft delete - just mark as deleted instead of removing from database
    listing.is_deleted = True
    listing.status = 'removed'
    db.session.commit()
    flash('Food listing removed successfully!', 'success')
    return redirect(url_for('donor_dashboard'))

@app.route('/listing/<int:listing_id>/view')
@login_required
def view_listing(listing_id):
    listing = FoodListing.query.get_or_404(listing_id)
    if current_user.role == 'donor' and listing.donor_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('donor_dashboard'))
    return render_template('donor/view_listing.html', listing=listing)

@app.route('/active_orders')
@login_required
def active_orders():
    if current_user.role != 'donor':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get active orders (claimed listings)
    active_orders = Claim.query.join(FoodListing)\
        .filter(FoodListing.donor_id == current_user.id)\
        .filter(Claim.status.in_(['pending', 'confirmed']))\
        .filter(FoodListing.pickup_end > datetime.utcnow())\
        .order_by(FoodListing.pickup_end.asc())\
        .all()
    
    # Filter orders by status for stats
    pending_orders = [o for o in active_orders if o.status == 'pending']
    confirmed_orders = [o for o in active_orders if o.status == 'confirmed']
    ready_orders = [o for o in active_orders if o.status == 'confirmed' and o.food_listing.pickup_start <= datetime.utcnow()]
    
    # Get completed pickups today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    completed_today = Claim.query.join(FoodListing)\
        .filter(FoodListing.donor_id == current_user.id)\
        .filter(Claim.status == 'picked_up')\
        .filter(Claim.pickup_time >= today_start)\
        .order_by(Claim.pickup_time.desc())\
        .all()
    
    return render_template('donor/active_orders.html', 
                         active_orders=active_orders,
                         pending_orders=pending_orders,
                         confirmed_orders=confirmed_orders,
                         ready_orders=ready_orders,
                         completed_today=completed_today,
                         datetime=datetime)

# =============== NGO ROUTES ===============
@app.route('/ngo/dashboard')
@login_required
def ngo_dashboard():
    if current_user.role != 'ngo':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    available_listings = FoodListing.query.filter_by(status='available', is_deleted=False)\
        .filter(FoodListing.pickup_end > datetime.utcnow())\
        .order_by(FoodListing.created_at.desc()).limit(3).all()
    my_claims = Claim.query.filter_by(ngo_id=current_user.id)\
        .order_by(Claim.created_at.desc()).limit(5).all()
    total_claims = Claim.query.filter_by(ngo_id=current_user.id).count()
    active_claims = Claim.query.filter_by(ngo_id=current_user.id)\
        .filter(Claim.status.in_(['pending', 'confirmed'])).count()
    completed_claims = Claim.query.filter_by(ngo_id=current_user.id, status='picked_up')\
        .join(FoodListing).all()
    total_meals_claimed = sum(claim.food_listing.quantity for claim in completed_claims)
    return render_template('ngo/ngo_dashboard.html',
                         available_listings=available_listings,
                         my_claims=my_claims,
                         total_claims=total_claims,
                         active_claims=active_claims,
                         total_meals_claimed=total_meals_claimed)

@app.route('/available_food')
@login_required
def available_food():
    if current_user.role != 'ngo':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    listings = FoodListing.query.filter_by(status='available', is_deleted=False)\
        .filter(FoodListing.pickup_end > datetime.utcnow())\
        .order_by(FoodListing.created_at.desc()).all()
    
    # Calculate distances if NGO has coordinates
    if current_user.latitude and current_user.longitude:
        for listing in listings:
            if listing.latitude and listing.longitude:
                listing.distance = calculate_distance(
                    current_user.latitude, current_user.longitude,
                    listing.latitude, listing.longitude
                )
            else:
                listing.distance = float('inf')
        
        # Sort by distance (closest first)
        listings.sort(key=lambda x: x.distance)
    
    return render_template('ngo/available_food.html', 
                         listings=listings,
                         datetime=datetime)

@app.route('/claim/<int:listing_id>', methods=['POST'])
@login_required
def claim_food(listing_id):
    if current_user.role != 'ngo':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    # Atomic lock to prevent double claim
    listing = FoodListing.query.filter_by(id=listing_id, status='available', is_deleted=False).with_for_update().first()
    if not listing:
        flash('This listing is no longer available', 'danger')
        return redirect(url_for('available_food'))
    
    existing_claim = Claim.query.filter_by(
        food_listing_id=listing_id,
        ngo_id=current_user.id
    ).first()
    if existing_claim:
        flash('You have already claimed this listing', 'warning')
        return redirect(url_for('ngo_dashboard'))
    
    claim = Claim(
        food_listing_id=listing_id,
        ngo_id=current_user.id,
        status='pending',
        otp_code=generate_otp()  # Generate OTP on claim
    )
    listing.status = 'claimed'
    
    notification = Notification(
        user_id=listing.donor_id,
        title='Food Claimed!',
        message=f'{current_user.organization or current_user.username} has claimed your listing: {listing.title}',
        notification_type='claim_update'
    )
    db.session.add(claim)
    db.session.add(notification)
    db.session.commit()
    
    # Send email
    send_email(listing.donor.email,
               'Food Claimed',
               f'{current_user.organization} has claimed {listing.title}. Please coordinate pickup.')
    
    flash('Food claimed successfully! Please contact the donor for pickup.', 'success')
    return redirect(url_for('ngo_dashboard'))

@app.route('/my_claims')
@login_required
def my_claims():
    if current_user.role != 'ngo':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    claims = Claim.query.filter_by(ngo_id=current_user.id)\
        .order_by(Claim.created_at.desc()).all()
    return render_template('ngo/my_claims.html', 
                         claims=claims,
                         datetime=datetime)

@app.route('/my_pickups')
@login_required
def my_pickups():
    if current_user.role != 'ngo':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get active pickups (pending, confirmed, or recently picked up)
    active_pickups = Claim.query.filter_by(ngo_id=current_user.id)\
        .filter(Claim.status.in_(['pending', 'confirmed']))\
        .join(FoodListing)\
        .filter(FoodListing.pickup_end > datetime.utcnow())\
        .order_by(FoodListing.pickup_end.asc())\
        .all()
    
    # Filter pickups by status for stats
    pending_pickups = [p for p in active_pickups if p.status == 'pending']
    confirmed_pickups = [p for p in active_pickups if p.status == 'confirmed']
    ready_pickups = [p for p in active_pickups if p.status == 'confirmed' and p.food_listing.pickup_start <= datetime.utcnow()]
    
    # Get completed pickups today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    completed_today = Claim.query.filter_by(ngo_id=current_user.id)\
        .filter(Claim.status == 'picked_up')\
        .filter(Claim.pickup_time >= today_start)\
        .order_by(Claim.pickup_time.desc())\
        .all()
    
    return render_template('ngo/my_pickups.html', 
                         active_pickups=active_pickups,
                         pending_pickups=pending_pickups,
                         confirmed_pickups=confirmed_pickups,
                         ready_pickups=ready_pickups,
                         completed_today=completed_today,
                         datetime=datetime)

@app.route('/claim/<int:claim_id>/update_status', methods=['POST'])
@login_required
def update_claim_status(claim_id):
    print(f"Update status called for claim {claim_id} by user {current_user.id}")
    if current_user.role != 'ngo':
        print("Permission denied: not NGO")
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    claim = Claim.query.get_or_404(claim_id)
    if claim.ngo_id != current_user.id:
        print("Permission denied: not claim owner")
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    data = request.get_json()
    print(f"Received data: {data}")
    new_status = data.get('status')
    notes = data.get('notes', '')
    people_served = data.get('people_served')
    
    if new_status in ['confirmed', 'picked_up', 'cancelled']:
        print(f"Updating claim status to: {new_status}")
        claim.status = new_status
        claim.notes = notes
        
        if new_status == 'confirmed':
            # Notify donor (without OTP)
            notification = Notification(
                user_id=claim.food_listing.donor_id,
                title='Claim Confirmed',
                message=f'{current_user.organization} has confirmed pickup for {claim.food_listing.title}',
                notification_type='claim_update'
            )
            db.session.add(notification)
            send_email(claim.food_listing.donor.email,
                       'Pickup Confirmed',
                       f'NGO {current_user.organization} confirmed they will pick up {claim.food_listing.title}.')
        elif new_status == 'picked_up':
            claim.pickup_time = datetime.utcnow()
            claim.food_listing.status = 'picked_up'
            claim.people_served = people_served or claim.food_listing.quantity
            notification = Notification(
                user_id=claim.food_listing.donor_id,
                title='Food Picked Up!',
                message=f'{current_user.organization} has picked up {claim.food_listing.title}',
                notification_type='claim_update'
            )
            db.session.add(notification)
        elif new_status == 'cancelled':
            claim.food_listing.status = 'available'
        
        db.session.commit()
        print("Database committed successfully")
        return jsonify({'success': True})
    print(f"Invalid status: {new_status}")
    return jsonify({'success': False, 'error': 'Invalid status'}), 400

@app.route('/claim/<int:claim_id>/reject', methods=['POST'])
@login_required
def reject_claim(claim_id):
    if current_user.role != 'donor':
        abort(403)
    claim = Claim.query.get_or_404(claim_id)
    if claim.food_listing.donor_id != current_user.id:
        abort(403)
    if claim.status in ['pending', 'confirmed']:
        claim.status = 'cancelled'
        claim.food_listing.status = 'available'
        db.session.commit()
        flash('Claim rejected.', 'success')
    else:
        flash('Cannot reject this claim.', 'danger')
    return redirect(url_for('donor_dashboard'))

@app.route('/claim/<int:claim_id>/cancel', methods=['POST'])
@login_required
def cancel_claim(claim_id):
    if current_user.role != 'ngo':
        abort(403)
    claim = Claim.query.get_or_404(claim_id)
    if claim.ngo_id != current_user.id:
        abort(403)
    if claim.status in ['pending', 'confirmed']:
        claim.status = 'cancelled'
        claim.food_listing.status = 'available'
        
        # Notify donor about cancellation
        notification = Notification(
            user_id=claim.food_listing.donor_id,
            title='Claim Cancelled',
            message=f'{current_user.organization or current_user.username} has cancelled their claim for {claim.food_listing.title}. The food is now available again.',
            notification_type='claim_update'
        )
        db.session.add(notification)
        db.session.commit()
        
        flash('Claim cancelled successfully. The food is now available again.', 'success')
    else:
        flash('Cannot cancel this claim.', 'danger')
    return redirect(url_for('ngo_dashboard'))

@app.route('/claim/<int:claim_id>/verify_otp', methods=['POST'])
@login_required
def verify_otp(claim_id):
    claim = Claim.query.get_or_404(claim_id)
    if claim.food_listing.donor_id != current_user.id:
        abort(403)
    
    data = request.get_json()
    if data.get('otp') == claim.otp_code:
        claim.status = 'picked_up'
        claim.pickup_time = datetime.utcnow()
        claim.food_listing.status = 'picked_up'
        claim.otp_verified = True
        claim.people_served = data.get('people_served') or claim.food_listing.quantity
        db.session.commit()
        
        # Archive the completed claim
        archive_claim = ArchiveClaim(
            original_claim_id=claim.id,
            food_listing_id=claim.food_listing_id,
            donor_id=claim.food_listing.donor_id,
            ngo_id=claim.ngo_id,
            food_title=claim.food_listing.title,
            food_description=claim.food_listing.description,
            food_type=claim.food_listing.food_type,
            quantity=claim.food_listing.quantity,
            location=claim.food_listing.location,
            pickup_address=claim.food_listing.pickup_address,
            people_served=claim.people_served,
            claim_created_at=claim.created_at,
            pickup_time=claim.pickup_time,
            notes=claim.notes
        )
        db.session.add(archive_claim)
        
        # Create notification for NGO
        notification = Notification(
            user_id=claim.ngo_id,
            title='Pickup Verified!',
            message=f'Your pickup for {claim.food_listing.title} has been verified by the donor. Thank you!',
            notification_type='claim_update'
        )
        db.session.add(notification)
        db.session.commit()
        
        # Send confirmation email to NGO
        send_email(claim.ngo.email,
                   'Pickup Completed Successfully',
                   f'Your pickup for {claim.food_listing.title} has been verified by {claim.food_listing.donor.organization or claim.food_listing.donor.username}. Thank you for your service!')
        
        return jsonify({
            'success': True, 
            'message': 'OTP verified successfully! Pickup completed.',
            'receipt_url': url_for('generate_receipt', claim_id=claim_id)
        })
    else:
        return jsonify({'success': False, 'message': 'Invalid OTP'})

@app.route('/verify_otp/<int:claim_id>', methods=['GET', 'POST'])
@login_required
def verify_otp_page(claim_id):
    claim = Claim.query.get_or_404(claim_id)
    if claim.food_listing.donor_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('donor_dashboard'))
    
    if claim.status != 'confirmed':
        flash('This claim cannot be verified. Status must be "confirmed".', 'warning')
        return redirect(url_for('donor_dashboard'))
    
    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        if otp_entered == claim.otp_code:
            claim.status = 'picked_up'
            claim.pickup_time = datetime.utcnow()
            claim.food_listing.status = 'picked_up'
            claim.otp_verified = True
            db.session.commit()
            
            # Create notification for NGO
            notification = Notification(
                user_id=claim.ngo_id,
                title='Pickup Verified!',
                message=f'Your pickup for {claim.food_listing.title} has been verified by the donor.',
                notification_type='claim_update'
            )
            db.session.add(notification)
            db.session.commit()
            
            flash('✅ OTP verified successfully! Pickup confirmed.', 'success')
            return redirect(url_for('donor_dashboard'))
        else:
            flash('❌ Invalid OTP. Please try again.', 'danger')
    
    return render_template('donor/verify_otp.html', claim=claim)

@app.route('/receipt/<int:claim_id>')
@login_required
def generate_receipt(claim_id):
    claim = Claim.query.get_or_404(claim_id)
    
    # Only donor can view receipt for their own listings
    if current_user.role != 'donor' or claim.food_listing.donor_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    # Only generate receipt for completed pickups
    if claim.status != 'picked_up':
        flash('Receipt is only available for completed pickups', 'warning')
        return redirect(url_for('active_orders'))
    
    return render_template('donor/receipt.html', 
                         claim=claim, 
                         datetime=datetime)

@app.route('/review/<int:claim_id>')
@login_required
def create_review(claim_id):
    claim = Claim.query.get_or_404(claim_id)
    
    # Only allow reviews for completed pickups
    if claim.status != 'picked_up':
        flash('Reviews can only be created for completed pickups.', 'warning')
        return redirect(url_for('dashboard'))
    
    # Check if user is involved in this claim (donor or NGO)
    if current_user.id not in [claim.food_listing.donor_id, claim.ngo_id]:
        flash('You can only review pickups you were involved in.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Check if review already exists
    existing_review = Review.query.filter_by(
        claim_id=claim_id,
        from_user_id=current_user.id
    ).first()
    
    if existing_review:
        flash('You have already reviewed this pickup.', 'info')
        return redirect(url_for('view_reviews', claim_id=claim_id))
    
    return render_template('review/create_review.html', claim=claim)

@app.route('/review/<int:claim_id>/submit', methods=['POST'])
@login_required
def submit_review(claim_id):
    claim = Claim.query.get_or_404(claim_id)
    
    # Only allow reviews for completed pickups
    if claim.status != 'picked_up':
        return jsonify({'success': False, 'message': 'Reviews can only be created for completed pickups.'})
    
    # Check if user is involved in this claim
    if current_user.id not in [claim.food_listing.donor_id, claim.ngo_id]:
        return jsonify({'success': False, 'message': 'You can only review pickups you were involved in.'})
    
    # Check if review already exists
    existing_review = Review.query.filter_by(
        claim_id=claim_id,
        from_user_id=current_user.id
    ).first()
    
    if existing_review:
        return jsonify({'success': False, 'message': 'You have already reviewed this pickup.'})
    
    data = request.get_json()
    rating = data.get('rating')
    comment = data.get('comment', '').strip()
    
    if not rating or rating < 1 or rating > 5:
        return jsonify({'success': False, 'message': 'Please provide a valid rating between 1 and 5.'})
    
    # Determine who is being reviewed
    if current_user.id == claim.food_listing.donor_id:
        # Donor is reviewing NGO
        to_user_id = claim.ngo_id
        review_type = 'donor_to_ngo'
    else:
        # NGO is reviewing donor
        to_user_id = claim.food_listing.donor_id
        review_type = 'ngo_to_donor'
    
    review = Review(
        rating=rating,
        comment=comment,
        from_user_id=current_user.id,
        to_user_id=to_user_id,
        claim_id=claim_id
    )
    
    db.session.add(review)
    db.session.commit()
    
    # Create notification for the reviewed user
    reviewed_user = db.session.get(User, to_user_id)
    notification = Notification(
        user_id=to_user_id,
        title='New Review Received',
        message=f'{current_user.organization or current_user.username} left you a {rating}-star review for {claim.food_listing.title}.',
        notification_type='review'
    )
    db.session.add(notification)
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': 'Review submitted successfully!',
        'redirect_url': url_for('view_reviews', claim_id=claim_id)
    })

@app.route('/reviews/<int:claim_id>')
@login_required
def view_reviews(claim_id):
    claim = Claim.query.get_or_404(claim_id)
    
    # Check if user is involved in this claim
    if current_user.id not in [claim.food_listing.donor_id, claim.ngo_id]:
        flash('You can only view reviews for pickups you were involved in.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get all reviews for this claim
    reviews = Review.query.filter_by(claim_id=claim_id).order_by(Review.created_at.desc()).all()
    
    return render_template('review/view_reviews.html', claim=claim, reviews=reviews)

@app.route('/my_reviews')
@login_required
def my_reviews():
    # Get reviews given by current user
    given_reviews = Review.query.filter_by(from_user_id=current_user.id)\
        .order_by(Review.created_at.desc()).all()
    
    # Get reviews received by current user
    received_reviews = Review.query.filter_by(to_user_id=current_user.id)\
        .order_by(Review.created_at.desc()).all()
    
    return render_template('review/my_reviews.html', 
                         given_reviews=given_reviews,
                         received_reviews=received_reviews)

@app.route('/admin')
@admin_login_required
def admin_dashboard():
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    total_users = User.query.count()
    total_listings = FoodListing.query.count()
    total_claims = Claim.query.count()
    pending_ngos = User.query.filter_by(role='ngo', verified=False).count()
    
    # Get monthly donation data for the chart
    from sqlalchemy import extract
    current_year = datetime.now().year
    monthly_donations = []
    for month in range(1, 4):  # Jan, Feb, Mar for the chart
        donations_count = FoodListing.query.filter(
            extract('year', FoodListing.created_at) == current_year,
            extract('month', FoodListing.created_at) == month
        ).count()
        monthly_donations.append(donations_count)
    
    return render_template('admin/dashboard.html',
                           admin=admin,
                           total_users=total_users,
                           total_listings=total_listings,
                           total_claims=total_claims,
                           pending_ngos=pending_ngos,
                           monthly_donations=monthly_donations)

@app.route('/admin/users')
@admin_login_required
def admin_users():
    users = User.query.all()
    return render_template('admin/user.html', users=users)

@app.route('/admin/verify_ngo/<int:user_id>', methods=['POST'])
@admin_login_required
def verify_ngo(user_id):
    user = User.query.get_or_404(user_id)
    user.verified = True
    db.session.commit()
    flash(f'{user.organization} verified.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/ngo_verification')
@admin_login_required
def ngo_verification():
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    
    # Get all NGOs with their profiles
    ngos = db.session.query(User, NGO).join(NGO, User.id == NGO.user_id).filter(User.role == 'ngo').all()
    
    # Separate pending and approved NGOs
    pending_ngos = [(u, n) for u, n in ngos if not u.is_active]
    approved_ngos = [(u, n) for u, n in ngos if u.is_active]
    
    return render_template('admin/ngo_verification.html', admin=admin, pending_ngos=pending_ngos, approved_ngos=approved_ngos)

@app.route('/admin/ngo/<int:user_id>/toggle_status', methods=['POST'])
@admin_login_required
def toggle_ngo_status(user_id):
    user = User.query.get_or_404(user_id)
    ngo_profile = NGO.query.filter_by(user_id=user_id).first()
    
    if not ngo_profile:
        flash('NGO profile not found.', 'danger')
        return redirect(url_for('ngo_verification'))
    
    # Toggle activation status
    user.is_active = not user.is_active
    db.session.commit()
    
    status = "approved" if user.is_active else "deactivated"
    flash(f'{user.organization} has been {status}.', 'success')
    
    # Send notification to NGO
    if user.is_active:
        notification = Notification(
            user_id=user_id,
            title='Account Approved',
            message=f'Your NGO account has been approved! You can now login and start claiming food donations.',
            notification_type='approval'
        )
        # Send email notification
        send_email(user.email, 'NGO Account Approved',
                   f'Your NGO account has been approved! You can now login and start claiming food donations.')
    else:
        notification = Notification(
            user_id=user_id,
            title='Account Deactivated',
            message=f'Your NGO account has been deactivated by admin.',
            notification_type='admin_update'
        )
    
    db.session.add(notification)
    db.session.commit()
    
    return redirect(url_for('ngo_verification'))

@app.route('/admin/ngo/<int:user_id>/view_documents')
@admin_login_required
def view_ngo_documents(user_id):
    user = User.query.get_or_404(user_id)
    ngo_profile = NGO.query.filter_by(user_id=user_id).first()
    
    if not ngo_profile:
        flash('NGO profile not found.', 'danger')
        return redirect(url_for('ngo_verification'))
    
    return render_template('admin/view_ngo_documents.html', user=user, ngo_profile=ngo_profile)

@app.route('/admin/toggle_user/<int:user_id>', methods=['POST'])
@admin_login_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    
    action = "banned" if not user.is_active else "unbanned"
    flash(f'User {user.username} has been {action}.', 'success')
    
    # Log the action
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    
    # Send notification to user if they were banned
    if not user.is_active:
        notification = Notification(
            user_id=user_id,
            title='Account Suspended',
            message='Your account has been suspended by the administrator. Please contact support for more information.',
            notification_type='admin_action'
        )
        db.session.add(notification)
    
    db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/user_management')
@admin_login_required
def user_management():
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    
    # Get all users with their profiles
    users = User.query.order_by(User.created_at.desc()).all()
    
    return render_template('admin/user_management.html', admin=admin, users=users)

@app.route('/admin/city_master')
@admin_login_required
def city_master():
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    
    cities = CityMaster.query.order_by(CityMaster.state, CityMaster.name).all()
    
    return render_template('admin/city_master.html', admin=admin, cities=cities)

@app.route('/admin/city_master/add', methods=['POST'])
@admin_login_required
def add_city():
    name = request.form.get('name', '').strip()
    state = request.form.get('state', '').strip()
    country = request.form.get('country', 'India').strip()
    
    if not name or not state:
        flash('City name and state are required.', 'danger')
        return redirect(url_for('city_master'))
    
    # Check if city already exists
    existing_city = CityMaster.query.filter_by(name=name, state=state).first()
    if existing_city:
        flash('City already exists in this state.', 'warning')
        return redirect(url_for('city_master'))
    
    city = CityMaster(name=name, state=state, country=country)
    db.session.add(city)
    db.session.commit()
    
    flash(f'City {name}, {state} added successfully.', 'success')
    return redirect(url_for('city_master'))

@app.route('/admin/city_master/<int:city_id>/edit', methods=['POST'])
@admin_login_required
def edit_city(city_id):
    city = CityMaster.query.get_or_404(city_id)
    
    name = request.form.get('name', '').strip()
    state = request.form.get('state', '').strip()
    country = request.form.get('country', 'India').strip()
    is_active = request.form.get('is_active') == 'on'
    
    if not name or not state:
        flash('City name and state are required.', 'danger')
        return redirect(url_for('city_master'))
    
    # Check if another city with same name/state exists
    existing_city = CityMaster.query.filter(
        CityMaster.name == name,
        CityMaster.state == state,
        CityMaster.id != city_id
    ).first()
    
    if existing_city:
        flash('Another city with the same name and state already exists.', 'warning')
        return redirect(url_for('city_master'))
    
    city.name = name
    city.state = state
    city.country = country
    city.is_active = is_active
    city.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    flash(f'City {name}, {state} updated successfully.', 'success')
    return redirect(url_for('city_master'))

@app.route('/admin/city_master/<int:city_id>/delete', methods=['POST'])
@admin_login_required
def delete_city(city_id):
    city = CityMaster.query.get_or_404(city_id)
    
    # Check if city is being used by any users
    users_using_city = User.query.filter_by(city=city.name).count()
    if users_using_city > 0:
        flash(f'Cannot delete city. {users_using_city} users are currently using this city.', 'danger')
        return redirect(url_for('city_master'))
    
    city_name = city.name
    db.session.delete(city)
    db.session.commit()
    
    flash(f'City {city_name} deleted successfully.', 'success')
    return redirect(url_for('city_master'))

@app.route('/admin/city_master/<int:city_id>/toggle', methods=['POST'])
@admin_login_required
def toggle_city(city_id):
    city = CityMaster.query.get_or_404(city_id)
    
    city.is_active = not city.is_active
    city.updated_at = datetime.utcnow()
    db.session.commit()
    
    status = "activated" if city.is_active else "deactivated"
    flash(f'City {city.name} has been {status}.', 'success')
    return redirect(url_for('city_master'))

@app.route('/admin/listings')
@admin_login_required
def admin_listings():
    listings = FoodListing.query.order_by(FoodListing.created_at.desc()).all()
    return render_template('admin/listing.html', listings=listings)

@app.route('/admin/claims')
@admin_login_required
def admin_claims():
    claims = Claim.query.order_by(Claim.created_at.desc()).all()
    return render_template('admin/claims.html', claims=claims)

@app.route('/admin/reports')
@admin_login_required
def admin_reports():
    # Get statistics for reports
    total_users = User.query.count()
    total_donors = User.query.filter_by(role='donor').count()
    total_ngos = User.query.filter_by(role='ngo').count()
    total_listings = FoodListing.query.count()
    total_claims = Claim.query.count()
    completed_claims = Claim.query.filter_by(status='picked_up').count()
    
    # Calculate total meals donated and claimed (Impact Analytics)
    total_meals_donated = db.session.query(db.func.sum(FoodListing.quantity)).scalar() or 0
    total_meals_claimed = db.session.query(db.func.sum(Claim.people_served)).scalar() or 0
    total_meals_distributed = db.session.query(db.func.sum(Claim.people_served))\
        .filter(Claim.status == 'picked_up').scalar() or 0
    
    # Calculate impact metrics
    avg_meals_per_donation = total_meals_donated / total_listings if total_listings > 0 else 0
    fulfillment_rate = (completed_claims / total_claims * 100) if total_claims > 0 else 0
    
    # Get monthly data for charts with enhanced metrics
    from sqlalchemy import extract
    current_year = datetime.now().year
    
    monthly_donations = []
    monthly_meals = []
    monthly_distributed = []
    monthly_claims = []
    
    for month in range(1, 13):
        # Donations count
        donations_count = FoodListing.query.filter(
            extract('year', FoodListing.created_at) == current_year,
            extract('month', FoodListing.created_at) == month
        ).count()
        monthly_donations.append(donations_count)
        
        # Meals donated (SUM aggregation)
        meals_donated = db.session.query(db.func.sum(FoodListing.quantity)).filter(
            extract('year', FoodListing.created_at) == current_year,
            extract('month', FoodListing.created_at) == month
        ).scalar() or 0
        monthly_meals.append(meals_donated)
        
        # Meals distributed (SUM aggregation where status=Distributed)
        meals_distributed = db.session.query(db.func.sum(Claim.people_served)).filter(
            extract('year', Claim.pickup_time) == current_year,
            extract('month', Claim.pickup_time) == month,
            Claim.status == 'picked_up'
        ).scalar() or 0
        monthly_distributed.append(meals_distributed)
        
        # Claims count
        claims_count = Claim.query.filter(
            extract('year', Claim.created_at) == current_year,
            extract('month', Claim.created_at) == month
        ).count()
        monthly_claims.append(claims_count)
    
    # City-wise distribution
    city_stats = db.session.query(
        FoodListing.location,
        db.func.count(FoodListing.id).label('donations'),
        db.func.sum(FoodListing.quantity).label('meals')
    ).group_by(FoodListing.location).order_by(db.desc('meals')).limit(10).all()
    
    # Top donors by impact
    top_donors = db.session.query(
        User.username,
        db.func.count(FoodListing.id).label('donations'),
        db.func.sum(FoodListing.quantity).label('meals')
    ).join(FoodListing, User.id == FoodListing.donor_id)\
     .group_by(User.id, User.username)\
     .order_by(db.desc('meals')).limit(10).all()
    
    # Top NGOs by meals served
    top_ngos = db.session.query(
        User.username,
        db.func.count(Claim.id).label('pickups'),
        db.func.sum(Claim.people_served).label('meals_served')
    ).join(Claim, User.id == Claim.ngo_id)\
     .filter(Claim.status == 'picked_up')\
     .group_by(User.id, User.username)\
     .order_by(db.desc('meals_served')).limit(10).all()
    
    # Get recent activity
    recent_listings = FoodListing.query.order_by(FoodListing.created_at.desc()).limit(5).all()
    recent_claims = Claim.query.order_by(Claim.created_at.desc()).limit(5).all()
    
    return render_template('admin/reports.html',
                           total_users=total_users,
                           total_donors=total_donors,
                           total_ngos=total_ngos,
                           total_listings=total_listings,
                           total_claims=total_claims,
                           completed_claims=completed_claims,
                           total_meals_donated=total_meals_donated,
                           total_meals_claimed=total_meals_claimed,
                           total_meals_distributed=total_meals_distributed,
                           avg_meals_per_donation=avg_meals_per_donation,
                           fulfillment_rate=fulfillment_rate,
                           monthly_donations=monthly_donations,
                           monthly_meals=monthly_meals,
                           monthly_distributed=monthly_distributed,
                           monthly_claims=monthly_claims,
                           city_stats=city_stats,
                           top_donors=top_donors,
                           top_ngos=top_ngos,
                           recent_listings=recent_listings,
                           recent_claims=recent_claims,
                           current_year=current_year)
    listing = FoodListing.query.get_or_404(listing_id)
    db.session.delete(listing)
    db.session.commit()
    flash('Listing deleted.', 'success')
    return redirect(url_for('admin_listings'))

@app.route('/admin/notifications')
@admin_login_required
def admin_notifications():
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    
    # Get all notifications with user information
    notifications = db.session.query(Notification, User)\
        .join(User, Notification.user_id == User.id)\
        .order_by(Notification.created_at.desc()).all()
    
    return render_template('admin/notifications.html', admin=admin, notifications=notifications)

@app.route('/admin/export')
@admin_login_required
def export_data():
    export_type = request.args.get('type', 'listings')
    month = request.args.get('month')
    year = request.args.get('year', datetime.now().year)
    
    if export_type == 'listings':
        return export_listings(month, year)
    elif export_type == 'claims':
        return export_claims(month, year)
    elif export_type == 'impact':
        return export_impact_report(month, year)
    elif export_type == 'users':
        return export_users()
    else:
        return export_listings(month, year)

def export_listings(month=None, year=None):
    si = io.StringIO()
    cw = csv.writer(si)
    
    headers = ['ID', 'Title', 'Description', 'Food Type', 'Quantity', 'Location', 
               'Pickup Address', 'Pickup Start', 'Pickup End', 'Status', 
               'Donor Name', 'Donor Email', 'Donor Phone', 'Created At']
    cw.writerow(headers)
    
    query = FoodListing.query
    if month and year:
        from sqlalchemy import extract
        query = query.filter(
            extract('year', FoodListing.created_at) == int(year),
            extract('month', FoodListing.created_at) == int(month)
        )
    
    listings = query.order_by(FoodListing.created_at.desc()).all()
    
    for listing in listings:
        donor_name = listing.donor.organization or listing.donor.username
        donor_phone = listing.donor.donor_profile.phone if listing.donor.donor_profile else ''
        
        row = [
            listing.id,
            listing.title,
            listing.description or '',
            listing.food_type or '',
            listing.quantity,
            listing.location,
            listing.pickup_address or '',
            listing.pickup_start.strftime('%Y-%m-%d %H:%M'),
            listing.pickup_end.strftime('%Y-%m-%d %H:%M'),
            listing.status,
            donor_name,
            listing.donor.email,
            donor_phone,
            listing.created_at.strftime('%Y-%m-%d %H:%M')
        ]
        cw.writerow(row)
    
    output = si.getvalue()
    filename = f'food_listings_{year or "all"}_{month or "all"}.csv'
    
    response = make_response(output)
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    return response

def export_claims(month=None, year=None):
    si = io.StringIO()
    cw = csv.writer(si)
    
    headers = ['Claim ID', 'Food Title', 'Quantity', 'NGO Name', 'NGO Email', 
               'Donor Name', 'Status', 'People Served', 'Pickup Time', 
               'OTP Verified', 'Created At']
    cw.writerow(headers)
    
    query = Claim.query.join(FoodListing, Claim.food_listing_id == FoodListing.id)
    if month and year:
        from sqlalchemy import extract
        query = query.filter(
            extract('year', Claim.created_at) == int(year),
            extract('month', Claim.created_at) == int(month)
        )
    
    claims = query.order_by(Claim.created_at.desc()).all()
    
    for claim in claims:
        ngo_name = claim.ngo.organization or claim.ngo.username
        donor_name = claim.food_listing.donor.organization or claim.food_listing.donor.username
        
        row = [
            claim.id,
            claim.food_listing.title,
            claim.food_listing.quantity,
            ngo_name,
            claim.ngo.email,
            donor_name,
            claim.status,
            claim.people_served or '',
            claim.pickup_time.strftime('%Y-%m-%d %H:%M') if claim.pickup_time else '',
            'Yes' if claim.otp_verified else 'No',
            claim.created_at.strftime('%Y-%m-%d %H:%M')
        ]
        cw.writerow(row)
    
    output = si.getvalue()
    filename = f'claims_{year or "all"}_{month or "all"}.csv'
    
    response = make_response(output)
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    return response

def export_impact_report(month=None, year=None):
    si = io.StringIO()
    cw = csv.writer(si)
    
    # Impact summary
    cw.writerow(['IMPACT ANALYSIS REPORT'])
    cw.writerow(['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    cw.writerow(['Period:', f'{month or "All"}-{year or "All"}'])
    cw.writerow([])
    
    # Summary statistics
    total_meals = db.session.query(db.func.sum(FoodListing.quantity))
    if month and year:
        from sqlalchemy import extract
        total_meals = total_meals.filter(
            extract('year', FoodListing.created_at) == int(year),
            extract('month', FoodListing.created_at) == int(month)
        )
    total_meals = total_meals.scalar() or 0
    
    total_distributed = db.session.query(db.func.sum(Claim.people_served))
    if month and year:
        from sqlalchemy import extract
        total_distributed = total_distributed.filter(
            extract('year', Claim.pickup_time) == int(year),
            extract('month', Claim.pickup_time) == int(month),
            Claim.status == 'picked_up'
        )
    total_distributed = total_distributed.scalar() or 0
    
    cw.writerow(['SUMMARY STATISTICS'])
    cw.writerow(['Total Meals Donated', total_meals])
    cw.writerow(['Total Meals Distributed', total_distributed])
    cw.writerow(['Impact Rate (%)', f'{(total_distributed/total_meals*100):.1f}%' if total_meals > 0 else '0%'])
    cw.writerow([])
    
    # City-wise breakdown
    cw.writerow(['CITY-WISE DISTRIBUTION'])
    cw.writerow(['City', 'Donations Count', 'Meals Donated'])
    
    city_query = db.session.query(
        FoodListing.location,
        db.func.count(FoodListing.id).label('donations'),
        db.func.sum(FoodListing.quantity).label('meals')
    ).group_by(FoodListing.location)
    
    if month and year:
        from sqlalchemy import extract
        city_query = city_query.filter(
            extract('year', FoodListing.created_at) == int(year),
            extract('month', FoodListing.created_at) == int(month)
        )
    
    city_stats = city_query.order_by(db.desc('meals')).all()
    
    for city in city_stats:
        cw.writerow([city.location, city.donations, city.meals or 0])
    
    output = si.getvalue()
    filename = f'impact_report_{year or "all"}_{month or "all"}.csv'
    
    response = make_response(output)
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    return response

def export_users():
    si = io.StringIO()
    cw = csv.writer(si)
    
    headers = ['User ID', 'Username', 'Email', 'Role', 'Organization', 'Phone', 
               'City', 'State', 'Verified', 'Active', 'Created At']
    cw.writerow(headers)
    
    users = User.query.order_by(User.created_at.desc()).all()
    
    for user in users:
        if user.role == 'donor' and user.donor_profile:
            profile = user.donor_profile
        elif user.role == 'ngo' and user.ngo_profile:
            profile = user.ngo_profile
        else:
            profile = None
        
        row = [
            user.id,
            user.username,
            user.email,
            user.role,
            profile.organization if profile else '',
            profile.phone if profile else '',
            profile.city if profile else '',
            profile.state if profile else '',
            'Yes' if (profile and hasattr(profile, 'verified') and profile.verified) else 'No',
            'Yes' if user.is_active else 'No',
            user.created_at.strftime('%Y-%m-%d %H:%M')
        ]
        cw.writerow(row)
    
    output = si.getvalue()
    filename = f'users_{datetime.now().strftime("%Y%m%d")}.csv'
    
    response = make_response(output)
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    return response

@app.route('/admin/content_moderation')
@admin_login_required
def content_moderation():
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    
    # Get all reports with their listings
    reports = db.session.query(Report, FoodListing, User)\
        .join(FoodListing, Report.food_listing_id == FoodListing.id)\
        .join(User, Report.reporter_id == User.id)\
        .order_by(Report.created_at.desc()).all()
    
    return render_template('admin/content_moderation.html', admin=admin, reports=reports)

@app.route('/admin/report/<int:report_id>/review', methods=['POST'])
@admin_login_required
def review_report(report_id):
    report = Report.query.get_or_404(report_id)
    action = request.form.get('action')
    admin_notes = request.form.get('admin_notes', '').strip()
    
    admin_id = session.get('admin_id')
    admin = db.session.get(Admin, admin_id)
    
    report.admin_notes = admin_notes
    report.reviewed_by = admin_id
    report.reviewed_at = datetime.utcnow()
    
    if action == 'delete_post':
        # Delete the reported food listing
        listing = report.food_listing
        listing_title = listing.title
        
        # Notify the donor
        notification = Notification(
            user_id=listing.donor_id,
            title='Content Removed',
            message=f'Your food listing "{listing_title}" has been removed by administrators due to policy violations.',
            notification_type='admin_action'
        )
        db.session.add(notification)
        
        # Delete the listing and related claims
        Claim.query.filter_by(food_listing_id=listing.id).delete()
        db.session.delete(listing)
        
        report.status = 'resolved'
        flash(f'Food listing "{listing_title}" has been deleted.', 'success')
        
    elif action == 'dismiss_report':
        report.status = 'dismissed'
        flash('Report has been dismissed.', 'info')
        
    elif action == 'warn_user':
        # Send warning to the donor
        notification = Notification(
            user_id=report.food_listing.donor_id,
            title='Content Warning',
            message=f'Your food listing "{report.food_listing.title}" has received a warning. Please ensure all content complies with our policies.',
            notification_type='admin_warning'
        )
        db.session.add(notification)
        
        report.status = 'reviewed'
        flash('Warning sent to user.', 'warning')
    
    db.session.commit()
    return redirect(url_for('content_moderation'))

@app.route('/report_listing/<int:listing_id>', methods=['POST'])
@login_required
def report_listing(listing_id):
    listing = FoodListing.query.get_or_404(listing_id)
    
    # Check if user already reported this listing
    existing_report = Report.query.filter_by(
        food_listing_id=listing_id,
        reporter_id=current_user.id
    ).first()
    
    if existing_report:
        flash('You have already reported this listing.', 'warning')
        return redirect(url_for('available_food'))
    
    reason = request.form.get('reason')
    description = request.form.get('description', '').strip()
    
    if not reason:
        flash('Please provide a reason for reporting.', 'danger')
        return redirect(url_for('available_food'))
    
    report = Report(
        food_listing_id=listing_id,
        reporter_id=current_user.id,
        reason=reason,
        description=description
    )
    
    db.session.add(report)
    db.session.commit()
    
    flash('Thank you for your report. Our administrators will review it.', 'success')
    return redirect(url_for('available_food'))

# =============== TTL AUTO-CANCELLATION ===============
@app.route('/admin/cleanup_expired_claims')
@admin_login_required
def cleanup_expired_claims():
    """Auto-cancel claims older than 2 hours without OTP verification"""
    expired_time = datetime.utcnow() - timedelta(hours=2)
    
    expired_claims = Claim.query.filter(
        Claim.created_at < expired_time,
        Claim.status.in_(['pending', 'confirmed']),
        Claim.otp_verified == False
    ).all()
    
    cancelled_count = 0
    for claim in expired_claims:
        claim.status = 'cancelled'
        claim.food_listing.status = 'available'
        
        # Notify NGO about auto-cancellation
        notification = Notification(
            user_id=claim.ngo_id,
            title='Claim Auto-Cancelled',
            message=f'Your claim for {claim.food_listing.title} was auto-cancelled due to timeout (2 hours)',
            notification_type='claim_update'
        )
        db.session.add(notification)
        cancelled_count += 1
    
    db.session.commit()
    flash(f'Auto-cancelled {cancelled_count} expired claims.', 'info')
    return redirect(url_for('admin_dashboard'))

# =============== API ENDPOINTS ===============
@app.route('/api/notifications')
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .order_by(Notification.created_at.desc()).limit(10).all()
    return jsonify({
        'count': len(notifications),
        'notifications': [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'created_at': n.created_at.isoformat()
        } for n in notifications]
    })

@app.route('/api/notifications/mark_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    notification.is_read = True
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/user/<int:user_id>/contact', methods=['GET'])
@login_required
def get_user_contact(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Get user profile information
    contact_info = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'phone': None,
        'organization': None
    }
    
    if user.role == 'donor' and user.donor_profile:
        contact_info['phone'] = user.donor_profile.phone
        contact_info['organization'] = user.donor_profile.organization
    elif user.role == 'ngo' and user.ngo_profile:
        contact_info['phone'] = user.ngo_profile.phone
        contact_info['organization'] = user.ngo_profile.organization
    
    return jsonify({'success': True, 'user': contact_info})

@app.route('/api/listings/<int:listing_id>', methods=['DELETE'])
@login_required
def delete_listing_api(listing_id):
    listing = FoodListing.query.get_or_404(listing_id)
    if listing.donor_id != current_user.id:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    if listing.status != 'available':
        return jsonify({'success': False, 'error': 'Only available listings can be deleted'}), 400
    Claim.query.filter_by(food_listing_id=listing_id).delete()
    db.session.delete(listing)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/stats/total_meals')
def get_total_meals():
    total_meals = db.session.query(db.func.sum(FoodListing.quantity)).filter(FoodListing.is_deleted == False).scalar() or 0
    total_donations = FoodListing.query.filter_by(is_deleted=False).count()
    return jsonify({
        'total_meals': total_meals,
        'total_donations': total_donations,
        'total_claims': Claim.query.count(),
        'completed_claims': Claim.query.filter_by(status='picked_up').count()
    })

@app.route('/api/listings/available')
@login_required
def get_available_listings():
    listings = FoodListing.query.filter_by(status='available', is_deleted=False)\
        .filter(FoodListing.pickup_end > datetime.utcnow())\
        .order_by(FoodListing.created_at.desc()).all()
    result = []
    for listing in listings:
        result.append({
            'id': listing.id,
            'title': listing.title,
            'description': listing.description,
            'food_type': listing.food_type,
            'quantity': listing.quantity,
            'location': listing.location,
            'pickup_address': listing.pickup_address,
            'pickup_start': listing.pickup_start.isoformat(),
            'pickup_end': listing.pickup_end.isoformat(),
            'allergens': listing.allergens,
            'image': listing.image,
            'donor': {
                'id': listing.donor.id,
                'organization': listing.donor.organization or listing.donor.username,
                'email': listing.donor.email,
                'phone': listing.donor.phone
            }
        })
    return jsonify({'listings': result})

# =============== ERROR HANDLERS ===============
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('403.html'), 403

# =============== HELPER PAGES ===============
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        newsletter = request.form.get('newsletter')
        
        # Here you would typically:
        # 1. Validate the form data
        # 2. Send an email notification
        # 3. Save to database
        # 4. Send confirmation to user
        
        flash('Thank you for your message! We will get back to you within 24 hours.', 'success')
        return redirect(url_for('contact'))
    
    return render_template('contact.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/food-safety')
def food_safety():
    return render_template('food_safety.html')

# =============== UTILITY ===============
def cleanup_expired_listings():
    # Find all expired listings regardless of current status
    expired_listings = FoodListing.query.filter(
        FoodListing.pickup_end < datetime.utcnow()
    ).all()
    
    for listing in expired_listings:
        # Only update if not already expired
        if listing.status != 'expired':
            listing.status = 'expired'
            
            # Clean up old "Food Claimed!" notifications for expired listings
            old_notifications = Notification.query.filter_by(
                user_id=listing.donor_id,
                title='Food Claimed!',
                is_read=False
            ).all()
            
            for notification in old_notifications:
                if listing.title in notification.message:
                    # Mark old notification as read and create a new one
                    notification.is_read = True
                    
                    # Create corrected notification
                    corrected_notification = Notification(
                        user_id=listing.donor_id,
                        title='Food Listing Expired',
                        message=f'Your listing "{listing.title}" has expired and is no longer available.',
                        notification_type='claim_update'
                    )
                    db.session.add(corrected_notification)
                    break  # Only create one corrected notification per expired listing
        
    if expired_listings:
        db.session.commit()
        return len(expired_listings)
    return 0

def cleanup_expired_claims():
    """Auto-cancel claims older than 2 hours without OTP verification"""
    expired_time = datetime.utcnow() - timedelta(hours=2)
    
    expired_claims = Claim.query.filter(
        Claim.created_at < expired_time,
        Claim.status.in_(['pending', 'confirmed']),
        Claim.otp_verified == False
    ).all()
    
    cancelled_count = 0
    for claim in expired_claims:
        claim.status = 'cancelled'
        claim.food_listing.status = 'available'
        
        # Notify NGO about auto-cancellation
        notification = Notification(
            user_id=claim.ngo_id,
            title='Claim Auto-Cancelled',
            message=f'Your claim for {claim.food_listing.title} was auto-cancelled due to timeout (2 hours)',
            notification_type='claim_update'
        )
        db.session.add(notification)
        
        # Notify donor that the claim was cancelled and food is available again
        donor_notification = Notification(
            user_id=claim.food_listing.donor_id,
            title='Claim Cancelled - Food Available Again',
            message=f'The claim for {claim.food_listing.title} was cancelled. Your listing is available again.',
            notification_type='claim_update'
        )
        db.session.add(donor_notification)
        
        cancelled_count += 1
    
    if expired_claims:
        db.session.commit()
    return cancelled_count

def cleanup_completed_claims():
    """Archive and remove completed claims older than 30 days from active table"""
    cleanup_time = datetime.utcnow() - timedelta(days=30)
    
    # Find completed claims older than 30 days that haven't been archived
    old_completed_claims = Claim.query.filter(
        Claim.status == 'picked_up',
        Claim.pickup_time < cleanup_time
    ).all()
    
    archived_count = 0
    for claim in old_completed_claims:
        # Check if already archived
        existing_archive = ArchiveClaim.query.filter_by(original_claim_id=claim.id).first()
        if not existing_archive:
            # Archive the claim
            archive_claim = ArchiveClaim(
                original_claim_id=claim.id,
                food_listing_id=claim.food_listing_id,
                donor_id=claim.food_listing.donor_id,
                ngo_id=claim.ngo_id,
                food_title=claim.food_listing.title,
                food_description=claim.food_listing.description,
                food_type=claim.food_listing.food_type,
                quantity=claim.food_listing.quantity,
                location=claim.food_listing.location,
                pickup_address=claim.food_listing.pickup_address,
                people_served=claim.people_served,
                claim_created_at=claim.created_at,
                pickup_time=claim.pickup_time,
                notes=claim.notes
            )
            db.session.add(archive_claim)
            archived_count += 1
        
        # Delete the old claim from active table
        db.session.delete(claim)
    
    if old_completed_claims:
        db.session.commit()
    return archived_count

# =============== INIT ===============
db_initialized = False

@app.before_request
def init_db():
    global db_initialized
    if not db_initialized:
        db.create_all()
        # Create admin user if not exists
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
        admin = Admin.query.filter_by(email=admin_email).first()
        if not admin:
            admin = Admin(
                username='admin',
                email=admin_email,
                full_name='System Administrator',
                role='superadmin'
            )
            admin.set_password(os.getenv('ADMIN_PASSWORD', 'admin123'))
            db.session.add(admin)
            db.session.commit()
        db_initialized = True
    cleanup_expired_listings()
    cleanup_expired_claims()
    cleanup_completed_claims()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)