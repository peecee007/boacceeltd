from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
from email.message import EmailMessage
import math
import os, random, string, secrets, smtplib

import pyotp
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "boac-super-secret-2024-change-me")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://boacadmin:password@db:5432/boacceeltd")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=3)
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads", "kyc")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

db = SQLAlchemy(app)

CURRENCIES = ["HUF", "EUR", "USD", "CNY"]
ACCOUNT_TYPES = ["personal", "corporate"]
LANGUAGES = {"zh": "简体中文", "en": "English"}
ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
SERVICE_CONTENT = {
    "online_banking": {
        "title_zh": "网上银行",
        "title_en": "Online Banking",
        "intro_zh": "参考匈牙利中行英文站的首页与网银结构，这里集中展示登录、账户服务、安全工具与快捷入口。",
        "intro_en": "Based on the Bank of China Hungary English site homepage and e-banking structure, this page centralizes sign-in, account services, security tools, and quick actions.",
        "items_zh": ["个人网银登录", "企业网银登录", "双重验证安全中心", "交易历史 PDF 导出", "账户设置与通知"],
        "items_en": ["Personal online banking sign-in", "Corporate online banking sign-in", "Two-factor security center", "Transaction history PDF export", "Account settings and notifications"],
    },
    "personal_banking": {
        "title_zh": "个人金融服务",
        "title_en": "Personal Banking",
        "intro_zh": "参考个人金融栏目，聚合个人账户、存款、贷款申请、KYC 上传和利息计算器等功能。",
        "intro_en": "Inspired by the personal banking section, this page groups personal accounts, deposits, loan applications, KYC uploads, and the interest calculator.",
        "items_zh": ["个人账户开户", "账户中心与余额查询", "贷款申请", "利息计算器", "KYC 身份认证上传"],
        "items_en": ["Personal account opening", "Dashboard and balance inquiry", "Loan application", "Interest calculator", "KYC identity upload"],
    },
    "corporate_banking": {
        "title_zh": "公司金融服务",
        "title_en": "Corporate Banking",
        "intro_zh": "参考公司金融栏目，聚合企业账户、转账控制、国际汇款申请以及后台审批能力。",
        "intro_en": "Inspired by the corporate banking section, this page groups corporate accounts, transfer controls, international remittance requests, and admin approval capabilities.",
        "items_zh": ["企业账户开户", "企业转账申请", "国际汇款申请", "多币种余额管理", "管理员审批控制"],
        "items_en": ["Corporate account opening", "Corporate transfer requests", "International remittance requests", "Multi-currency balance management", "Admin approval controls"],
    },
    "customer_service": {
        "title_zh": "客户服务",
        "title_en": "Customer Service",
        "intro_zh": "参考客户服务栏目，提供常见问题、联系渠道、通知提醒与合规文件入口。",
        "intro_en": "Based on the customer service area, this page provides FAQs, contact channels, notifications, and compliance entry points.",
        "items_zh": ["客服热线", "登录提醒通知", "KYC 文件上传", "交易记录导出", "管理后台支持"],
        "items_en": ["Support hotline", "Login notifications", "KYC document upload", "Transaction export", "Admin support controls"],
    },
    "about_us": {
        "title_zh": "关于我们",
        "title_en": "About Us",
        "intro_zh": "参考关于我们栏目，介绍本平台的中东欧服务定位、个人与企业业务能力以及管理功能。",
        "intro_en": "Inspired by the About Us section, this page introduces the platform's Central and Eastern Europe positioning, personal and corporate capabilities, and management features.",
        "items_zh": ["平台简介", "个人与企业开户", "国际汇款与转账流程", "安全与合规功能", "管理员运营后台"],
        "items_en": ["Platform overview", "Personal and corporate onboarding", "Transfers and international remittance flows", "Security and compliance features", "Administrative operations console"],
    },
}

# ─────────────────────────── MODELS ───────────────────────────

class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    full_name     = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    account_type  = db.Column(db.String(20), default="personal")
    account_no    = db.Column(db.String(20), unique=True)
    balance       = db.Column(db.Float, default=0.0)
    currency      = db.Column(db.String(10), default="HUF")
    is_active     = db.Column(db.Boolean, default=True)
    is_admin      = db.Column(db.Boolean, default=False)
    is_frozen     = db.Column(db.Boolean, default=False)
    phone         = db.Column(db.String(30), default="")
    address       = db.Column(db.String(200), default="")
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime, nullable=True)
    notes         = db.Column(db.Text, default="")
    preferred_lang = db.Column(db.String(5), default="zh")
    email_notifications_enabled = db.Column(db.Boolean, default=True)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(64), default="")
    kyc_status = db.Column(db.String(20), default="not_submitted")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class LoginLog(db.Model):
    __tablename__ = "login_logs"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    user       = db.relationship("User", backref="logs")
    ip_address = db.Column(db.String(50))
    success    = db.Column(db.Boolean)
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    __tablename__ = "transactions"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"))
    user        = db.relationship("User", backref="transactions")
    type        = db.Column(db.String(30))   # credit | debit | adjustment
    amount      = db.Column(db.Float)
    currency    = db.Column(db.String(10), default="HUF")
    description = db.Column(db.String(200))
    status      = db.Column(db.String(20), default="approved")
    channel     = db.Column(db.String(30), default="admin")
    beneficiary_name = db.Column(db.String(120), default="")
    beneficiary_account = db.Column(db.String(120), default="")
    destination_bank = db.Column(db.String(120), default="")
    destination_country = db.Column(db.String(120), default="")
    swift_code  = db.Column(db.String(40), default="")
    reference_no = db.Column(db.String(80), default="")
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    created_by  = db.Column(db.String(80), default="system")


class CurrencyBalance(db.Model):
    __tablename__ = "currency_balances"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    currency   = db.Column(db.String(10), nullable=False)
    amount     = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship("User", backref="currency_balances")


class Notification(db.Model):
    __tablename__ = "notifications"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject    = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    kind       = db.Column(db.String(30), default="info")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship("User", backref="notifications")


class LoanApplication(db.Model):
    __tablename__ = "loan_applications"
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount         = db.Column(db.Float, nullable=False)
    term_months    = db.Column(db.Integer, nullable=False)
    annual_rate    = db.Column(db.Float, nullable=False)
    purpose        = db.Column(db.String(200), default="")
    monthly_income = db.Column(db.Float, default=0.0)
    status         = db.Column(db.String(20), default="pending")
    notes          = db.Column(db.Text, default="")
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    user           = db.relationship("User", backref="loan_applications")


class KycDocument(db.Model):
    __tablename__ = "kyc_documents"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    filename   = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    status     = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship("User", backref="kyc_documents")


# ─────────────────────────── HELPERS ───────────────────────────

def gen_account_no():
    return "BOAC" + "".join(random.choices(string.digits, k=8))


def current_lang():
    lang = session.get("lang")
    if lang in LANGUAGES:
        return lang
    if session.get("user_id"):
        user = User.query.get(session["user_id"])
        if user and user.preferred_lang in LANGUAGES:
            return user.preferred_lang
    return "zh"


def tr(zh, en=None):
    english = en if en is not None else zh
    return zh if current_lang() == "zh" else english


@app.context_processor
def inject_helpers():
    return {
        "tr": tr,
        "current_lang": current_lang(),
        "languages": LANGUAGES,
        "currencies": CURRENCIES,
    }


def allowed_upload(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def create_notification(user_id, subject_zh, subject_en, message_zh, message_en, kind="info"):
    db.session.add(Notification(
        user_id=user_id,
        subject=tr(subject_zh, subject_en),
        message=tr(message_zh, message_en),
        kind=kind,
    ))


def send_email_notification(user, subject_zh, subject_en, body_zh, body_en):
    create_notification(user.id, subject_zh, subject_en, body_zh, body_en, "email")

    if not user.email_notifications_enabled:
        return False

    smtp_host = os.environ.get("SMTP_HOST")
    if not smtp_host:
        app.logger.info("SMTP not configured; storing notification only for %s", user.email)
        return False

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_sender = os.environ.get("SMTP_SENDER", smtp_user or "no-reply@boacceeltd.com")
    use_tls = os.environ.get("SMTP_TLS", "true").lower() == "true"

    message = EmailMessage()
    message["Subject"] = tr(subject_zh, subject_en)
    message["From"] = smtp_sender
    message["To"] = user.email
    message.set_content(tr(body_zh, body_en))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if use_tls:
                server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(message)
        return True
    except Exception as exc:
        app.logger.warning("Failed to send email to %s: %s", user.email, exc)
        return False


def get_or_create_currency_balance(user, currency):
    wallet = CurrencyBalance.query.filter_by(user_id=user.id, currency=currency).first()
    if not wallet:
        wallet = CurrencyBalance(user_id=user.id, currency=currency, amount=0.0)
        db.session.add(wallet)
    return wallet


def sync_primary_balance(user):
    user.balance = get_or_create_currency_balance(user, user.currency).amount


def submit_transfer_request(user, amount, currency, description, channel, beneficiary_name, beneficiary_account, destination_bank, destination_country, swift_code):
    txn = Transaction(
        user_id=user.id,
        type="debit",
        amount=amount,
        currency=currency,
        description=description,
        created_by=user.full_name,
        status="pending",
        channel=channel,
        beneficiary_name=beneficiary_name,
        beneficiary_account=beneficiary_account,
        destination_bank=destination_bank,
        destination_country=destination_country,
        swift_code=swift_code,
        reference_no="TXN-" + secrets.token_hex(5).upper(),
    )
    db.session.add(txn)
    create_notification(
        user.id,
        "转账申请已提交",
        "Transfer request submitted",
        f"您的{description}申请已提交，等待管理员审批。",
        f"Your {description} request has been submitted and is awaiting admin approval.",
        "transfer",
    )
    return txn


def apply_approved_transaction(txn):
    user = txn.user
    wallet = get_or_create_currency_balance(user, txn.currency)
    if txn.type == "debit":
        wallet.amount -= txn.amount
    elif txn.type == "credit":
        wallet.amount += txn.amount
    sync_primary_balance(user)


def initialize_user_wallets(user, opening_balance=None):
    for currency in CURRENCIES:
        get_or_create_currency_balance(user, currency)
    db.session.flush()
    if opening_balance is not None:
        get_or_create_currency_balance(user, user.currency).amount = opening_balance
    sync_primary_balance(user)


def complete_login(user, ip_address):
    session.permanent = True
    session["user_id"] = user.id
    session["user_name"] = user.full_name
    session["account_type"] = user.account_type
    session["is_admin"] = user.is_admin
    session["lang"] = user.preferred_lang or "zh"
    user.last_login = datetime.utcnow()
    db.session.add(LoginLog(user_id=user.id, ip_address=ip_address, success=True))
    send_email_notification(
        user,
        "登录提醒",
        "Login notification",
        f"您的账户 {user.email} 刚刚完成登录。如非本人操作，请立即修改密码。",
        f"Your account {user.email} has just signed in. If this was not you, please change your password immediately.",
    )
    db.session.commit()


def build_pdf_for_transactions(user, transactions):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"Transaction History - {user.full_name}")
    y -= 22
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Account: {user.account_no}")
    y -= 16
    pdf.drawString(40, y, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 24
    headers = ["Date", "Type", "Currency", "Amount", "Description"]
    x_positions = [40, 130, 200, 280, 360]
    pdf.setFont("Helvetica-Bold", 10)
    for idx, header in enumerate(headers):
        pdf.drawString(x_positions[idx], y, header)
    y -= 14
    pdf.setFont("Helvetica", 9)
    for txn in transactions:
        if y < 60:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 9)
        row = [
            txn.created_at.strftime("%Y-%m-%d"),
            txn.type,
            txn.currency,
            f"{txn.amount:,.2f}",
            (txn.description or "")[:35],
        ]
        for idx, value in enumerate(row):
            pdf.drawString(x_positions[idx], y, str(value))
        y -= 14
    pdf.save()
    buffer.seek(0)
    return buffer


def ensure_schema():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.create_all()
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_lang VARCHAR(5) DEFAULT 'zh'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_notifications_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_secret VARCHAR(64) DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS kyc_status VARCHAR(20) DEFAULT 'not_submitted'",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'approved'",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS channel VARCHAR(30) DEFAULT 'admin'",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS beneficiary_name VARCHAR(120) DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS beneficiary_account VARCHAR(120) DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS destination_bank VARCHAR(120) DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS destination_country VARCHAR(120) DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS swift_code VARCHAR(40) DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reference_no VARCHAR(80) DEFAULT ''",
    ]
    with db.engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session:
            flash(tr("请先登录。", "Please log in first."), "warning")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session:
            return redirect(url_for("login"))
        u = User.query.get(session["user_id"])
        if not u or not u.is_admin:
            flash(tr("需要管理员权限。", "Admin access required."), "error")
            return redirect(url_for("dashboard"))
        return f(*a, **kw)
    return dec


@app.route("/set-language/<lang>")
def set_language(lang):
    if lang in LANGUAGES:
        session["lang"] = lang
        if session.get("user_id"):
            user = User.query.get(session["user_id"])
            if user:
                user.preferred_lang = lang
                db.session.commit()
    next_url = request.args.get("next") or request.referrer or url_for("index")
    return redirect(next_url)

# ─────────────────────────── PUBLIC ROUTES ───────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/online-banking")
def online_banking():
    return render_template("service_page.html", key="online_banking", page=SERVICE_CONTENT["online_banking"])


@app.route("/personal-banking")
def personal_banking():
    return render_template("service_page.html", key="personal_banking", page=SERVICE_CONTENT["personal_banking"])


@app.route("/corporate-banking")
def corporate_banking():
    return render_template("service_page.html", key="corporate_banking", page=SERVICE_CONTENT["corporate_banking"])


@app.route("/customer-service")
def customer_service():
    return render_template("service_page.html", key="customer_service", page=SERVICE_CONTENT["customer_service"])


@app.route("/about-us")
def about_us():
    return render_template("service_page.html", key="about_us", page=SERVICE_CONTENT["about_us"])


@app.route("/interest-calculator", methods=["GET", "POST"])
def interest_calculator():
    result = None
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        principal = float(request.form.get("principal", 0) or 0)
        annual_rate = float(request.form.get("annual_rate", 0) or 0)
        term_months = int(request.form.get("term_months", 0) or 0)
        monthly_rate = annual_rate / 100 / 12
        monthly_payment = 0
        if term_months > 0:
            if monthly_rate == 0:
                monthly_payment = principal / term_months
            else:
                monthly_payment = principal * monthly_rate / (1 - math.pow(1 + monthly_rate, -term_months))
        total_payment = monthly_payment * term_months
        result = {
            "principal": principal,
            "annual_rate": annual_rate,
            "term_months": term_months,
            "monthly_payment": monthly_payment,
            "total_payment": total_payment,
            "total_interest": total_payment - principal,
        }
    return render_template("interest_calculator.html", form=form, result=result)

# ─────────────────────────── AUTH ───────────────────────────

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        full_name    = request.form.get("full_name","").strip()
        email        = request.form.get("email","").strip().lower()
        password     = request.form.get("password","")
        confirm      = request.form.get("confirm_password","")
        account_type = request.form.get("account_type","personal").strip().lower()
        phone        = request.form.get("phone","").strip()
        address      = request.form.get("address","").strip()
        currency     = request.form.get("currency", "HUF").strip().upper()
        preferred_lang = request.form.get("preferred_lang", current_lang()).strip()

        errors = []
        if not full_name:           errors.append(tr("姓名不能为空。", "Full name is required."))
        if not email or "@" not in email: errors.append(tr("请输入有效邮箱。", "Valid email required."))
        if len(password) < 8:       errors.append(tr("密码至少需要 8 位。", "Password must be at least 8 characters."))
        if password != confirm:     errors.append(tr("两次输入的密码不一致。", "Passwords do not match."))
        if account_type not in ACCOUNT_TYPES:
            errors.append(tr("请选择个人账户或企业账户。", "Please choose either a personal or corporate account."))
        if currency not in CURRENCIES:
            errors.append(tr("请选择有效币种。", "Please choose a valid currency."))
        if User.query.filter_by(email=email).first():
            errors.append(tr("该邮箱已注册。", "Email already registered."))

        if errors:
            for e in errors: flash(e, "error")
            return render_template("register.html", form=request.form)

        u = User(full_name=full_name, email=email, account_type=account_type,
                 account_no=gen_account_no(), phone=phone, address=address,
                 currency=currency,
                 preferred_lang=preferred_lang if preferred_lang in LANGUAGES else current_lang())
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        initialize_user_wallets(u, 0.0)
        db.session.commit()
        flash(tr("账户创建成功，请登录。", "Account created! Please log in."), "success")
        return redirect(url_for("login"))

    return render_template("register.html", form={})


@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        user     = User.query.filter_by(email=email).first()
        ip       = request.remote_addr

        if user and user.check_password(password) and user.is_active and not user.is_frozen:
            if user.two_factor_enabled and user.two_factor_secret:
                session["pending_2fa_user_id"] = user.id
                session["pending_2fa_ip"] = ip
                flash(tr("请输入双重验证验证码。", "Please enter your two-factor authentication code."), "info")
                return redirect(url_for("two_factor_verify"))
            complete_login(user, ip)
            flash(tr(f"欢迎回来，{user.full_name}！", f"Welcome back, {user.full_name}!"), "success")
            return redirect(url_for("admin_dashboard") if user.is_admin else url_for("dashboard"))
        else:
            if user:
                db.session.add(LoginLog(user_id=user.id, ip_address=ip, success=False))
                db.session.commit()
            msg = tr("账户已被冻结，请联系支持。", "Account is frozen. Contact support.") if (user and user.is_frozen) else tr("邮箱或密码错误。", "Invalid email or password.")
            flash(msg, "error")

    return render_template("login.html")


@app.route("/two-factor", methods=["GET", "POST"])
def two_factor_verify():
    pending_user_id = session.get("pending_2fa_user_id")
    if not pending_user_id:
        return redirect(url_for("login"))

    user = User.query.get_or_404(pending_user_id)
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if pyotp.TOTP(user.two_factor_secret).verify(code, valid_window=1):
            ip = session.pop("pending_2fa_ip", request.remote_addr)
            session.pop("pending_2fa_user_id", None)
            complete_login(user, ip)
            flash(tr("双重验证成功。", "Two-factor verification successful."), "success")
            return redirect(url_for("admin_dashboard") if user.is_admin else url_for("dashboard"))
        flash(tr("验证码无效，请重试。", "Invalid verification code. Please try again."), "error")
    return render_template("two_factor_verify.html")


@app.route("/logout")
def logout():
    session.clear()
    flash(tr("您已安全退出。", "You have been logged out."), "info")
    return redirect(url_for("login"))

# ─────────────────────────── USER DASHBOARD ───────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    user = User.query.get(session["user_id"])
    if user.is_admin:
        return redirect(url_for("admin_dashboard"))
    txns = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).limit(10).all()
    wallets = CurrencyBalance.query.filter_by(user_id=user.id).order_by(CurrencyBalance.currency.asc()).all()
    notifications = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(5).all()
    loans = LoanApplication.query.filter_by(user_id=user.id).order_by(LoanApplication.created_at.desc()).limit(5).all()
    docs = KycDocument.query.filter_by(user_id=user.id).order_by(KycDocument.created_at.desc()).limit(5).all()
    return render_template("dashboard.html", user=user, txns=txns, wallets=wallets, notifications=notifications, loans=loans, docs=docs)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = User.query.get_or_404(session["user_id"])
    if request.method == "POST":
        preferred_lang = request.form.get("preferred_lang", user.preferred_lang)
        currency = request.form.get("currency", user.currency).strip().upper()
        user.email_notifications_enabled = request.form.get("email_notifications_enabled") == "on"
        if preferred_lang in LANGUAGES:
            user.preferred_lang = preferred_lang
            session["lang"] = preferred_lang
        if currency in CURRENCIES:
            user.currency = currency
            sync_primary_balance(user)
        db.session.commit()
        flash(tr("账户设置已更新。", "Account settings updated."), "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", user=user)


@app.route("/security", methods=["GET", "POST"])
@login_required
def security():
    user = User.query.get_or_404(session["user_id"])
    if not user.two_factor_secret:
        user.two_factor_secret = pyotp.random_base32()
        db.session.commit()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "enable":
            code = request.form.get("code", "").strip()
            if pyotp.TOTP(user.two_factor_secret).verify(code, valid_window=1):
                user.two_factor_enabled = True
                db.session.commit()
                flash(tr("双重验证已启用。", "Two-factor authentication enabled."), "success")
            else:
                flash(tr("验证码无效。", "Invalid verification code."), "error")
        elif action == "disable":
            user.two_factor_enabled = False
            db.session.commit()
            flash(tr("双重验证已关闭。", "Two-factor authentication disabled."), "success")
        elif action == "regenerate":
            user.two_factor_secret = pyotp.random_base32()
            user.two_factor_enabled = False
            db.session.commit()
            flash(tr("新的 2FA 密钥已生成。", "A new 2FA secret has been generated."), "success")
        return redirect(url_for("security"))
    otpauth_uri = pyotp.TOTP(user.two_factor_secret).provisioning_uri(name=user.email, issuer_name="BOACCEELTD")
    return render_template("security.html", user=user, otpauth_uri=otpauth_uri)


@app.route("/transactions/export/pdf")
@login_required
def export_transactions_pdf():
    user = User.query.get_or_404(session["user_id"])
    txns = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).all()
    pdf_buffer = build_pdf_for_transactions(user, txns)
    return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=True, download_name=f"{user.account_no}-transactions.pdf")


@app.route("/transfer-funds", methods=["GET", "POST"])
@login_required
def transfer_funds():
    user = User.query.get_or_404(session["user_id"])
    wallets = CurrencyBalance.query.filter_by(user_id=user.id).order_by(CurrencyBalance.currency.asc()).all()
    if request.method == "POST":
        amount = float(request.form.get("amount", 0) or 0)
        currency = request.form.get("currency", user.currency).strip().upper()
        beneficiary_name = request.form.get("beneficiary_name", "").strip()
        beneficiary_account = request.form.get("beneficiary_account", "").strip()
        description = request.form.get("description", "").strip() or "Transfer request"
        if amount <= 0 or currency not in CURRENCIES or not beneficiary_name or not beneficiary_account:
            flash(tr("请填写完整的转账信息。", "Please complete the transfer form."), "error")
            return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=False)
        submit_transfer_request(user, amount, currency, description, "local_transfer", beneficiary_name, beneficiary_account, "", "", "")
        db.session.commit()
        flash(tr("转账申请已提交，等待管理员审批。", "Transfer request submitted for admin approval."), "success")
        return redirect(url_for("transfer_funds"))
    return render_template("transfer_funds.html", user=user, wallets=wallets, form={}, remittance=False)


@app.route("/international-remittance", methods=["GET", "POST"])
@login_required
def international_remittance():
    user = User.query.get_or_404(session["user_id"])
    wallets = CurrencyBalance.query.filter_by(user_id=user.id).order_by(CurrencyBalance.currency.asc()).all()
    if request.method == "POST":
        amount = float(request.form.get("amount", 0) or 0)
        currency = request.form.get("currency", user.currency).strip().upper()
        beneficiary_name = request.form.get("beneficiary_name", "").strip()
        beneficiary_account = request.form.get("beneficiary_account", "").strip()
        destination_bank = request.form.get("destination_bank", "").strip()
        destination_country = request.form.get("destination_country", "").strip()
        swift_code = request.form.get("swift_code", "").strip()
        description = request.form.get("description", "").strip() or "International remittance"
        if amount <= 0 or currency not in CURRENCIES or not all([beneficiary_name, beneficiary_account, destination_bank, destination_country, swift_code]):
            flash(tr("请填写完整的国际汇款信息。", "Please complete the international remittance form."), "error")
            return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=True)
        submit_transfer_request(user, amount, currency, description, "international_remittance", beneficiary_name, beneficiary_account, destination_bank, destination_country, swift_code)
        db.session.commit()
        flash(tr("国际汇款申请已提交，等待管理员审批。", "International remittance request submitted for admin approval."), "success")
        return redirect(url_for("international_remittance"))
    return render_template("transfer_funds.html", user=user, wallets=wallets, form={}, remittance=True)


@app.route("/loan-application", methods=["GET", "POST"])
@login_required
def loan_application():
    user = User.query.get_or_404(session["user_id"])
    if request.method == "POST":
        amount = float(request.form.get("amount", 0) or 0)
        term_months = int(request.form.get("term_months", 0) or 0)
        annual_rate = float(request.form.get("annual_rate", 0) or 0)
        monthly_income = float(request.form.get("monthly_income", 0) or 0)
        purpose = request.form.get("purpose", "").strip()
        if amount <= 0 or term_months <= 0 or annual_rate < 0:
            flash(tr("请填写有效的贷款申请信息。", "Please provide valid loan application details."), "error")
            return render_template("loan_application.html", user=user, loans=user.loan_applications, form=request.form)
        db.session.add(LoanApplication(user_id=user.id, amount=amount, term_months=term_months, annual_rate=annual_rate, monthly_income=monthly_income, purpose=purpose))
        create_notification(user.id, "贷款申请已提交", "Loan application submitted", f"您的贷款申请已提交，申请金额为 {amount:,.2f}。", f"Your loan application has been submitted for {amount:,.2f}.", "loan")
        db.session.commit()
        flash(tr("贷款申请已提交。", "Loan application submitted."), "success")
        return redirect(url_for("loan_application"))
    loans = LoanApplication.query.filter_by(user_id=user.id).order_by(LoanApplication.created_at.desc()).all()
    return render_template("loan_application.html", user=user, loans=loans, form={})


@app.route("/kyc", methods=["GET", "POST"])
@login_required
def kyc_upload():
    user = User.query.get_or_404(session["user_id"])
    if request.method == "POST":
        file = request.files.get("document")
        if not file or not file.filename:
            flash(tr("请选择要上传的文件。", "Please choose a file to upload."), "error")
            return redirect(url_for("kyc_upload"))
        if not allowed_upload(file.filename):
            flash(tr("仅支持 PDF、PNG、JPG、JPEG 文件。", "Only PDF, PNG, JPG, and JPEG files are supported."), "error")
            return redirect(url_for("kyc_upload"))
        safe_name = secure_filename(file.filename)
        stored_name = f"{user.id}-{secrets.token_hex(8)}-{safe_name}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], stored_name))
        db.session.add(KycDocument(user_id=user.id, filename=safe_name, stored_name=stored_name, status="pending"))
        user.kyc_status = "pending"
        create_notification(user.id, "KYC 文件已上传", "KYC document uploaded", f"您的文件 {safe_name} 已上传，正在等待审核。", f"Your document {safe_name} has been uploaded and is awaiting review.", "kyc")
        db.session.commit()
        flash(tr("KYC 文件上传成功。", "KYC document uploaded successfully."), "success")
        return redirect(url_for("kyc_upload"))
    docs = KycDocument.query.filter_by(user_id=user.id).order_by(KycDocument.created_at.desc()).all()
    return render_template("kyc.html", user=user, docs=docs)

# ─────────────────────────── ADMIN ───────────────────────────

@app.route("/admin")
@admin_required
def admin_dashboard():
    total_users   = User.query.filter_by(is_admin=False).count()
    active_users  = User.query.filter_by(is_active=True, is_admin=False).count()
    frozen_users  = User.query.filter_by(is_frozen=True).count()
    total_txns    = Transaction.query.count()
    recent_users  = User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).limit(5).all()
    recent_logs   = LoginLog.query.order_by(LoginLog.timestamp.desc()).limit(8).all()
    recent_loans  = LoanApplication.query.order_by(LoanApplication.created_at.desc()).limit(5).all()
    recent_kyc    = KycDocument.query.order_by(KycDocument.created_at.desc()).limit(5).all()
    return render_template("admin/dashboard.html",
        total_users=total_users, active_users=active_users,
        frozen_users=frozen_users, total_txns=total_txns,
        recent_users=recent_users, recent_logs=recent_logs,
        recent_loans=recent_loans, recent_kyc=recent_kyc)


@app.route("/admin/users")
@admin_required
def admin_users():
    q      = request.args.get("q","").strip()
    filter = request.args.get("filter","all")
    query  = User.query.filter_by(is_admin=False)
    if q:
        query = query.filter(
            (User.full_name.ilike(f"%{q}%")) |
            (User.email.ilike(f"%{q}%")) |
            (User.account_no.ilike(f"%{q}%"))
        )
    if filter == "active":   query = query.filter_by(is_active=True, is_frozen=False)
    if filter == "frozen":   query = query.filter_by(is_frozen=True)
    if filter == "inactive": query = query.filter_by(is_active=False)
    users = query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users, q=q, filter=filter)


@app.route("/admin/users/<int:uid>")
@admin_required
def admin_user_detail(uid):
    user = User.query.get_or_404(uid)
    txns = Transaction.query.filter_by(user_id=uid).order_by(Transaction.created_at.desc()).all()
    logs = LoginLog.query.filter_by(user_id=uid).order_by(LoginLog.timestamp.desc()).limit(20).all()
    wallets = CurrencyBalance.query.filter_by(user_id=uid).order_by(CurrencyBalance.currency.asc()).all()
    loans = LoanApplication.query.filter_by(user_id=uid).order_by(LoanApplication.created_at.desc()).all()
    docs = KycDocument.query.filter_by(user_id=uid).order_by(KycDocument.created_at.desc()).all()
    return render_template("admin/user_detail.html", user=user, txns=txns, logs=logs, wallets=wallets, loans=loans, docs=docs)


@app.route("/admin/users/<int:uid>/edit", methods=["GET","POST"])
@admin_required
def admin_user_edit(uid):
    user = User.query.get_or_404(uid)
    if request.method == "POST":
        full_name    = request.form.get("full_name", user.full_name).strip()
        email        = request.form.get("email", user.email).strip().lower()
        phone        = request.form.get("phone","").strip()
        address      = request.form.get("address","").strip()
        account_type = request.form.get("account_type", user.account_type).strip().lower()
        currency     = request.form.get("currency", user.currency).strip().upper()
        notes        = request.form.get("notes","").strip()
        new_pw = request.form.get("new_password","").strip()
        if not full_name:
            flash(tr("姓名不能为空。", "Full name is required."), "error")
            return render_template("admin/user_edit.html", user=user)
        if not email or "@" not in email:
            flash(tr("请输入有效邮箱。", "Valid email required."), "error")
            return render_template("admin/user_edit.html", user=user)
        existing = User.query.filter(User.email == email, User.id != user.id).first()
        if existing:
            flash(tr("邮箱已存在。", "Email already exists."), "error")
            return render_template("admin/user_edit.html", user=user)
        if account_type not in ACCOUNT_TYPES:
            flash(tr("请选择有效账户类型。", "Choose a valid account type."), "error")
            return render_template("admin/user_edit.html", user=user)
        if currency not in CURRENCIES:
            flash(tr("请选择有效币种。", "Choose a valid currency."), "error")
            return render_template("admin/user_edit.html", user=user)
        if new_pw:
            if len(new_pw) < 8:
                flash(tr("密码至少需要 8 位。", "Password must be at least 8 characters."), "error")
                return render_template("admin/user_edit.html", user=user)
            user.set_password(new_pw)
        user.full_name = full_name
        user.email = email
        user.phone = phone
        user.address = address
        user.account_type = account_type
        user.currency = currency
        user.notes = notes
        initialize_user_wallets(user)
        sync_primary_balance(user)
        db.session.commit()
        flash(tr(f"用户 {user.full_name} 已更新。", f"User {user.full_name} updated."), "success")
        return redirect(url_for("admin_user_detail", uid=uid))
    return render_template("admin/user_edit.html", user=user)


@app.route("/admin/users/<int:uid>/toggle-freeze", methods=["POST"])
@admin_required
def admin_toggle_freeze(uid):
    user = User.query.get_or_404(uid)
    user.is_frozen = not user.is_frozen
    db.session.commit()
    flash(tr("账户冻结状态已更新。", "Account freeze status updated."), "success")
    return redirect(url_for("admin_user_detail", uid=uid))


@app.route("/admin/users/<int:uid>/toggle-active", methods=["POST"])
@admin_required
def admin_toggle_active(uid):
    user = User.query.get_or_404(uid)
    user.is_active = not user.is_active
    db.session.commit()
    flash(tr("账户启用状态已更新。", "Account active status updated."), "success")
    return redirect(url_for("admin_user_detail", uid=uid))


@app.route("/admin/users/<int:uid>/delete", methods=["POST"])
@admin_required
def admin_delete_user(uid):
    user = User.query.get_or_404(uid)
    name = user.full_name
    LoginLog.query.filter_by(user_id=uid).delete()
    Transaction.query.filter_by(user_id=uid).delete()
    CurrencyBalance.query.filter_by(user_id=uid).delete()
    Notification.query.filter_by(user_id=uid).delete()
    LoanApplication.query.filter_by(user_id=uid).delete()
    KycDocument.query.filter_by(user_id=uid).delete()
    db.session.delete(user)
    db.session.commit()
    flash(tr(f"用户 {name} 已删除。", f"User {name} permanently deleted."), "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:uid>/credit", methods=["POST"])
@admin_required
def admin_credit(uid):
    user   = User.query.get_or_404(uid)
    amount = float(request.form.get("amount", 0))
    desc   = request.form.get("description","Admin credit").strip()
    currency = request.form.get("currency", user.currency).strip().upper()
    if amount <= 0 or currency not in CURRENCIES:
        flash(tr("请输入有效金额与币种。", "Enter a valid amount and currency."), "error")
        return redirect(url_for("admin_user_detail", uid=uid))
    wallet = get_or_create_currency_balance(user, currency)
    wallet.amount += amount
    sync_primary_balance(user)
    db.session.add(Transaction(user_id=uid, type="credit", amount=amount,
                               currency=currency, description=desc,
                               created_by=session.get("user_name","admin"),
                               status="approved", channel="admin"))
    db.session.commit()
    flash(tr("入账成功。", "Credit completed."), "success")
    return redirect(url_for("admin_user_detail", uid=uid))


@app.route("/admin/users/<int:uid>/debit", methods=["POST"])
@admin_required
def admin_debit(uid):
    user   = User.query.get_or_404(uid)
    amount = float(request.form.get("amount", 0))
    desc   = request.form.get("description","Admin debit").strip()
    currency = request.form.get("currency", user.currency).strip().upper()
    if amount <= 0 or currency not in CURRENCIES:
        flash(tr("请输入有效金额与币种。", "Enter a valid amount and currency."), "error")
        return redirect(url_for("admin_user_detail", uid=uid))
    wallet = get_or_create_currency_balance(user, currency)
    wallet.amount -= amount
    sync_primary_balance(user)
    db.session.add(Transaction(user_id=uid, type="debit", amount=amount,
                               currency=currency, description=desc,
                               created_by=session.get("user_name","admin"),
                               status="approved", channel="admin"))
    db.session.commit()
    flash(tr("出账成功。", "Debit completed."), "success")
    return redirect(url_for("admin_user_detail", uid=uid))


@app.route("/admin/users/create", methods=["GET","POST"])
@admin_required
def admin_create_user():
    if request.method == "POST":
        full_name    = request.form.get("full_name","").strip()
        email        = request.form.get("email","").strip().lower()
        password     = request.form.get("password","")
        account_type = request.form.get("account_type","personal").strip().lower()
        phone        = request.form.get("phone","").strip()
        address      = request.form.get("address","").strip()
        currency     = request.form.get("currency","HUF").strip().upper()
        preferred_lang = request.form.get("preferred_lang", "zh").strip()

        try:
            balance = float(request.form.get("balance", 0) or 0)
        except ValueError:
            flash(tr("开户余额必须是数字。", "Opening balance must be a valid number."), "error")
            return render_template("admin/create_user.html", form=request.form)

        if not full_name:
            flash(tr("姓名不能为空。", "Full name is required."), "error")
            return render_template("admin/create_user.html", form=request.form)
        if not email or "@" not in email:
            flash(tr("请输入有效邮箱。", "Valid email required."), "error")
            return render_template("admin/create_user.html", form=request.form)
        if len(password) < 8:
            flash(tr("密码至少需要 8 位。", "Password must be at least 8 characters."), "error")
            return render_template("admin/create_user.html", form=request.form)
        if account_type not in ACCOUNT_TYPES:
            flash(tr("请选择有效账户类型。", "Choose a valid account type."), "error")
            return render_template("admin/create_user.html", form=request.form)
        if currency not in CURRENCIES:
            flash(tr("请选择有效币种。", "Choose a valid currency."), "error")
            return render_template("admin/create_user.html", form=request.form)
        if balance < 0:
            flash(tr("开户余额不能为负数。", "Opening balance cannot be negative."), "error")
            return render_template("admin/create_user.html", form=request.form)

        if User.query.filter_by(email=email).first():
            flash(tr("邮箱已存在。", "Email already exists."), "error")
            return render_template("admin/create_user.html", form=request.form)

        u = User(full_name=full_name, email=email, account_type=account_type,
                 account_no=gen_account_no(), phone=phone, address=address,
                 balance=balance, currency=currency, preferred_lang=preferred_lang if preferred_lang in LANGUAGES else "zh")
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        initialize_user_wallets(u, balance)
        db.session.add(Transaction(user_id=u.id, type="credit", amount=balance,
                               currency=currency, description="Opening balance",
                               created_by=session.get("user_name","admin")))
        db.session.commit()
        flash(tr(f"用户 {full_name} 创建成功。", f"User {full_name} created successfully."), "success")
        return redirect(url_for("admin_users"))
    return render_template("admin/create_user.html", form={})


@app.route("/admin/transactions")
@admin_required
def admin_transactions():
    txns = Transaction.query.order_by(Transaction.created_at.desc()).limit(100).all()
    return render_template("admin/transactions.html", txns=txns)


@app.route("/admin/transactions/<int:txn_id>/review", methods=["POST"])
@admin_required
def admin_review_transaction(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    status = request.form.get("status", "pending")
    if txn.status != "pending":
        flash(tr("该交易已处理。", "This transaction has already been processed."), "warning")
        return redirect(url_for("admin_transactions"))
    if status not in {"approved", "rejected"}:
        flash(tr("无效的交易状态。", "Invalid transaction status."), "error")
        return redirect(url_for("admin_transactions"))
    txn.status = status
    txn.created_by = session.get("user_name", "admin")
    if status == "approved":
        wallet = get_or_create_currency_balance(txn.user, txn.currency)
        if txn.type == "debit" and wallet.amount < txn.amount:
            txn.status = "rejected"
            db.session.commit()
            flash(tr("余额不足，交易已拒绝。", "Insufficient funds; transaction rejected."), "error")
            return redirect(url_for("admin_transactions"))
        apply_approved_transaction(txn)
        create_notification(txn.user_id, "交易申请已批准", "Transaction request approved", f"您的交易 {txn.reference_no or txn.id} 已批准。", f"Your transaction {txn.reference_no or txn.id} has been approved.", "transfer")
    else:
        create_notification(txn.user_id, "交易申请被拒绝", "Transaction request rejected", f"您的交易 {txn.reference_no or txn.id} 被拒绝。", f"Your transaction {txn.reference_no or txn.id} has been rejected.", "transfer")
    db.session.commit()
    flash(tr("交易状态已更新。", "Transaction status updated."), "success")
    return redirect(url_for("admin_transactions"))


@app.route("/admin/logs")
@admin_required
def admin_logs():
    logs = LoginLog.query.order_by(LoginLog.timestamp.desc()).limit(100).all()
    return render_template("admin/logs.html", logs=logs)


@app.route("/admin/loans")
@admin_required
def admin_loans():
    loans = LoanApplication.query.order_by(LoanApplication.created_at.desc()).all()
    return render_template("admin/loans.html", loans=loans)


@app.route("/admin/loans/<int:loan_id>/review", methods=["POST"])
@admin_required
def admin_review_loan(loan_id):
    loan = LoanApplication.query.get_or_404(loan_id)
    status = request.form.get("status", "pending")
    if status in {"pending", "approved", "rejected"}:
        loan.status = status
        loan.notes = request.form.get("notes", loan.notes).strip()
        create_notification(loan.user_id, "贷款申请状态更新", "Loan application status updated", f"您的贷款申请状态已更新为：{status}。", f"Your loan application status has been updated to: {status}.", "loan")
        db.session.commit()
    flash(tr("贷款申请状态已更新。", "Loan application status updated."), "success")
    return redirect(url_for("admin_loans"))


@app.route("/admin/kyc")
@admin_required
def admin_kyc():
    docs = KycDocument.query.order_by(KycDocument.created_at.desc()).all()
    return render_template("admin/kyc.html", docs=docs)


@app.route("/admin/kyc/<int:doc_id>/review", methods=["POST"])
@admin_required
def admin_review_kyc(doc_id):
    doc = KycDocument.query.get_or_404(doc_id)
    status = request.form.get("status", "pending")
    if status in {"pending", "approved", "rejected"}:
        doc.status = status
        doc.user.kyc_status = status
        create_notification(doc.user_id, "KYC 审核状态更新", "KYC review status updated", f"您的 KYC 文件状态已更新为：{status}。", f"Your KYC document status has been updated to: {status}.", "kyc")
        db.session.commit()
    flash(tr("KYC 状态已更新。", "KYC status updated."), "success")
    return redirect(url_for("admin_kyc"))


# ─────────────────────────── CLI ───────────────────────────

@app.cli.command("init-db")
def init_db():
    ensure_schema()
    print("✅ Tables created.")

@app.cli.command("create-admin")
def create_admin():
    ensure_schema()
    if not User.query.filter_by(email="admin@boacceeltd.com").first():
        u = User(full_name="Super Admin", email="admin@boacceeltd.com",
                 account_type="corporate", account_no="BOAC00000001",
                 is_admin=True, is_active=True, currency="EUR", preferred_lang="en")
        u.set_password("Admin1234!")
        db.session.add(u)
        db.session.flush()
        initialize_user_wallets(u, 0.0)
        db.session.commit()
        print("✅ Admin created: admin@boacceeltd.com / Admin1234!")
    else:
        print("ℹ️  Admin already exists.")

if __name__ == "__main__":
    with app.app_context():
        ensure_schema()
        # auto-create admin on first run
        if not User.query.filter_by(email="admin@boacceeltd.com").first():
            u = User(full_name="Super Admin", email="admin@boacceeltd.com",
                     account_type="corporate", account_no="BOAC00000001",
                     is_admin=True, is_active=True, currency="EUR", preferred_lang="en")
            u.set_password("Admin1234!")
            db.session.add(u)
            db.session.flush()
            initialize_user_wallets(u, 0.0)
            db.session.commit()
            print("✅ Admin auto-created: admin@boacceeltd.com / Admin1234!")
    app.run(debug=False, host="0.0.0.0", port=5000)
