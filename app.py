from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
import resend
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
from email.message import EmailMessage
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from urllib.parse import urlparse
import math
import json
import time
import os, random, string, secrets, smtplib

import pyotp
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from email_template import build_login_email_html

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY", "boac-super-secret-2024-change-me")
app.config["PREFERRED_URL_SCHEME"] = os.environ.get("PREFERRED_URL_SCHEME", "https")


def get_database_url():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    return f"sqlite:///{os.path.join(app.root_path, 'boac.db')}"


DATABASE_URL = get_database_url()

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=3)
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", os.path.join(app.root_path, "uploads", "kyc"))
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
        "subpages": [
            {
                "endpoint": "personal_saving_account",
                "title_zh": "Personal Saving Account",
                "title_en": "Personal Saving Account",
                "description_zh": "View currencies, minimum balances, identity-document requirements, and paper instruction guidance for individual current accounts.",
                "description_en": "View currencies, minimum balances, identity-document requirements, and paper instruction guidance for individual current accounts.",
            }
        ],
    },
    "corporate_banking": {
        "title_zh": "公司金融服务",
        "title_en": "Corporate Banking",
        "intro_zh": "参考公司金融栏目，聚合企业账户、转账控制、国际汇款申请以及后台审批能力。",
        "intro_en": "Inspired by the corporate banking section, this page groups corporate accounts, transfer controls, international remittance requests, and admin approval capabilities.",
        "items_zh": ["企业账户开户", "企业转账申请", "国际汇款申请", "多币种余额管理", "管理员审批控制"],
        "items_en": ["Corporate account opening", "Corporate transfer requests", "International remittance requests", "Multi-currency balance management", "Admin approval controls"],
        "subpages": [
            {
                "endpoint": "corporate_time_deposits",
                "title_zh": "Corporate Time Deposits",
                "title_en": "Corporate Time Deposits",
                "description_zh": "View terms, minimum balances, renewal rules, and large cash-withdrawal notice requirements for HUF, EUR, USD, and CNY corporate time deposits.",
                "description_en": "View terms, minimum balances, renewal rules, and large cash-withdrawal notice requirements for HUF, EUR, USD, and CNY corporate time deposits.",
            }
        ],
    },
    "customer_service": {
        "title_zh": "客户服务",
        "title_en": "Customer Service",
        "intro_zh": "参考客户服务栏目，提供常见问题、联系渠道、通知提醒与合规文件入口。",
        "intro_en": "Based on the customer service area, this page provides FAQs, contact channels, notifications, and compliance entry points.",
        "items_zh": ["客服热线", "登录提醒通知", "KYC 文件上传", "交易记录导出", "管理后台支持"],
        "items_en": ["Support contact", "Login notifications", "KYC document upload", "Transaction export", "Admin support controls"],
    },
    "about_us": {
        "title_zh": "关于我们",
        "title_en": "About Us",
        "intro_zh": "参考关于我们栏目，介绍本平台的中东欧服务定位、个人与企业业务能力以及管理功能。",
        "intro_en": "Inspired by the About Us section, this page introduces the platform's Central and Eastern Europe positioning, personal and corporate capabilities, and management features.",
        "items_zh": ["平台简介", "个人与企业开户", "国际汇款与转账流程", "安全与合规功能", "管理员运营后台"],
        "items_en": ["BOC news", "Bank outline and service map", "Regulations and complaints handling", "Financial reports and consumer protection", "Corporate social responsibility and support"],
        "sections": [
            {
                "title_zh": "BOC News",
                "title_en": "BOC News",
                "bullets_zh": [
                    "Hungary to situation bonds in yuan to draw Chinese language buyers【The Times】",
                    "Hungary to issue bonds in yuan to attract Chinese investors【AP】",
                    "Hungarian Government Supports BOC as the Local RMB Clearing Bank",
                ],
                "bullets_en": [
                    "Hungary to situation bonds in yuan to draw Chinese language buyers【The Times】",
                    "Hungary to issue bonds in yuan to attract Chinese investors【AP】",
                    "Hungarian Government Supports BOC as the Local RMB Clearing Bank",
                ],
                "footer_zh": "more >",
                "footer_en": "more >",
            },
            {
                "title_zh": "Outline",
                "title_en": "Outline",
                "paragraphs_zh": [
                    "Bank of China (Central and Eastern Europe), wholly owned by Bank of China, was opened in February 2003. It is the first commercial financial institution established by Bank of China in Central and Eastern Europe. With years of finance experience and deep understanding of markets, we are sincerely at your service.",
                    "Bank of China (Central and Eastern Europe) Limited. Service Map",
                ],
                "paragraphs_en": [
                    "Bank of China (Central and Eastern Europe), wholly owned by Bank of China, was opened in February 2003. It is the first commercial financial institution established by Bank of China in Central and Eastern Europe. With years of finance experience and deep understanding of markets, we are sincerely at your service.",
                    "Bank of China (Central and Eastern Europe) Limited. Service Map",
                ],
                "footer_zh": "more >",
                "footer_en": "more >",
            },
            {
                "title_zh": "Regulations",
                "title_en": "Regulations",
                "bullets_zh": [
                    "Regulation on Handling of Complaints",
                    "The National Deposit Insurance Fund of Hungary-NDIF (Az Országos Betétbiztosítási Alap-OBA)",
                    "Cut-Off Time for Payment Orders, Incoming Payments And Fulfilment Orders",
                    "Business Rules on Keeping Bank Accounts, Collecting Deposits and Providing Other Financial Services (Effective from March 20, 2026)",
                ],
                "bullets_en": [
                    "Regulation on Handling of Complaints",
                    "The National Deposit Insurance Fund of Hungary-NDIF (Az Országos Betétbiztosítási Alap-OBA)",
                    "Cut-Off Time for Payment Orders, Incoming Payments And Fulfilment Orders",
                    "Business Rules on Keeping Bank Accounts, Collecting Deposits and Providing Other Financial Services (Effective from March 20, 2026)",
                ],
                "footer_zh": "more >",
                "footer_en": "more >",
            },
            {
                "title_zh": "Corporate Social Responsibility",
                "title_en": "Corporate Social Responsibility",
                "bullets_zh": [
                    "Welcome Global Runners to the Bank of China Beijing International Running Festival Beijing Half Marathon 2026",
                    "Welcome Global Runners with Exclusive Benefits to BANK OF CHINA YANGZHOU HALF MARATHON 2026",
                    "Welcome Global Runners to 2026 BANK OF CHINA WUHAN MARATHON",
                    "Bank of China Welcomes Global Runners to 2025 Guangzhou Marathon",
                ],
                "bullets_en": [
                    "Welcome Global Runners to the Bank of China Beijing International Running Festival Beijing Half Marathon 2026",
                    "Welcome Global Runners with Exclusive Benefits to BANK OF CHINA YANGZHOU HALF MARATHON 2026",
                    "Welcome Global Runners to 2026 BANK OF CHINA WUHAN MARATHON",
                    "Bank of China Welcomes Global Runners to 2025 Guangzhou Marathon",
                ],
                "footer_zh": "more >",
                "footer_en": "more >",
            },
            {
                "title_zh": "Contact and Branches",
                "title_en": "Contact and Branches",
                "bullets_zh": [
                    "(Central and Eastern Europe) Limited.",
                    "Address: Jozsef Nador ter 7. 1051 Budapest, Hungary",
                    "Email: cs@bocceeltd.vip",
                ],
                "bullets_en": [
                    "(Central and Eastern Europe) Limited.",
                    "Address: Jozsef Nador ter 7. 1051 Budapest, Hungary",
                    "Email: cs@bocceeltd.vip",
                ],
            },
            {
                "title_zh": "Branches",
                "title_en": "Branches",
                "paragraphs_zh": [
                    "Bank of China (CEE) Ltd. Vienna Branch Information",
                    "2023-03-03",
                ],
                "paragraphs_en": [
                    "Bank of China (CEE) Ltd. Vienna Branch Information",
                    "2023-03-03",
                ],
                "bullets_zh": [
                    "Name: Bank of China (CEE) Ltd. Vienna Branch",
                    "Address: Börseplatz 6, A-1010 Vienna, Austria",
                    "SWIFT CODE: BKCHATWWXXX",
                ],
                "bullets_en": [
                    "Name: Bank of China (CEE) Ltd. Vienna Branch",
                    "Address: Börseplatz 6, A-1010 Vienna, Austria",
                    "SWIFT CODE: BKCHATWWXXX",
                ],
            },
            {
                "title_zh": "Financial Report and Consumer Rights Protection",
                "title_en": "Financial Report and Consumer Rights Protection",
                "bullets_zh": [
                    "Bank of China (CEE) Ltd. Financial Statements - 2024 (English/Hungarian)",
                    "Disclosure Report of Bank of China (CEE) Ltd. - 2024",
                    "Consumer Rights Protection",
                    "Information About Online Fraud / Online Csalassal Kapcsolatos Informaciok",
                ],
                "bullets_en": [
                    "Bank of China (CEE) Ltd. Financial Statements - 2024 (English/Hungarian)",
                    "Disclosure Report of Bank of China (CEE) Ltd. - 2024",
                    "Consumer Rights Protection",
                    "Information About Online Fraud / Online Csalassal Kapcsolatos Informaciok",
                ],
            },
        ],
    },
    "personal_saving_account": {
        "title_zh": "Personal Saving Account",
        "title_en": "Personal Saving Account",
        "intro_zh": "Individual customers can open current accounts in HUF, USD, EUR and CNY with the bank. The minimum balances are 10,000 HUF, 100 USD, 100 EUR and 1,000 CNY respectively.",
        "intro_en": "Individual customers can open current accounts in HUF, USD, EUR and CNY with the bank. The minimum balances are 10,000 HUF, 100 USD, 100 EUR and 1,000 CNY respectively.",
        "items_zh": ["Currencies and minimum balances", "No passbook", "Cash deposit and withdrawal", "Identity documents", "Paper instructions"],
        "items_en": ["Currencies and minimum balances", "No passbook", "Cash deposit and withdrawal", "Identity documents", "Paper instructions"],
        "sections": [
            {
                "title_zh": "Account Overview",
                "title_en": "Account Overview",
                "paragraphs_zh": [
                    "Individual customers can open current accounts in HUF, USD, EUR and CNY with the bank.",
                    "The minimum balances of current accounts in each currency are 10,000 HUF, 100 USD, 100 EUR and 1,000 CNY respectively.",
                    "There is no passbook for the account.",
                ],
                "paragraphs_en": [
                    "Individual customers can open current accounts in HUF, USD, EUR and CNY with the bank.",
                    "The minimum balances of current accounts in each currency are 10,000 HUF, 100 USD, 100 EUR and 1,000 CNY respectively.",
                    "There is no passbook for the account.",
                ],
            },
            {
                "title_zh": "Features",
                "title_en": "Features",
                "bullets_zh": [
                    "Current accounts can be used for cash deposit and withdrawal, internal transfer between the accounts of the same customer or between the accounts of different customers (including the currency exchange), inward or outward remittance.",
                    "Cash withdrawal of 1 million Forint (including) or equivalent foreign currency requires one day notice. Over 1 million Forint (including) to 5 million Forint or equivalent foreign currency requires two-days notice. Over 5 million (including) requires three days notice.",
                ],
                "bullets_en": [
                    "Current accounts can be used for cash deposit and withdrawal, internal transfer between the accounts of the same customer or between the accounts of different customers (including the currency exchange), inward or outward remittance.",
                    "Cash withdrawal of 1 million Forint (including) or equivalent foreign currency requires one day notice. Over 1 million Forint (including) to 5 million Forint or equivalent foreign currency requires two-days notice. Over 5 million (including) requires three days notice.",
                ],
            },
            {
                "title_zh": "Identity Documents",
                "title_en": "Identity Documents",
                "paragraphs_zh": [
                    "For the first current account with the bank, customers need to go to the bank counters in person with valid identity documents such as Hungarian ID card, passport, driver's license and address card, or a foreign passport with valid visa.",
                    "If customers want to open an account in another currency, the account holder can apply at the counters in person.",
                ],
                "paragraphs_en": [
                    "For the first current account with the bank, customers need to go to the bank counters in person with valid identity documents such as Hungarian ID card, passport, driver's license and address card, or a foreign passport with valid visa.",
                    "If customers want to open an account in another currency, the account holder can apply at the counters in person.",
                ],
            },
            {
                "title_zh": "Instructions",
                "title_en": "Instructions",
                "paragraphs_zh": [
                    "For paper-based transfer instructions, the account holder or the authorized person of the account can submit them at the counters of the bank in person.",
                ],
                "paragraphs_en": [
                    "For paper-based transfer instructions, the account holder or the authorized person of the account can submit them at the counters of the bank in person.",
                ],
            },
        ],
    },
    "corporate_time_deposits": {
        "title_zh": "Corporate Time Deposits",
        "title_en": "Corporate Time Deposits",
        "intro_zh": "Customers may open time deposit accounts in HUF, EUR, USD and CNY separately. The periods for HUF, USD and EUR are one week, one month, three months, six months and twelve months. For CNY there is one term only: one month.",
        "intro_en": "Customers may open time deposit accounts in HUF, EUR, USD and CNY separately. The periods for HUF, USD and EUR are one week, one month, three months, six months and twelve months. For CNY there is one term only: one month.",
        "items_zh": ["Currencies and terms", "Paper-based minimum balances", "NetBank minimum balances", "Renewal and early withdrawal rules", "Large cash-withdrawal notice"],
        "items_en": ["Currencies and terms", "Paper-based minimum balances", "NetBank minimum balances", "Renewal and early withdrawal rules", "Large cash-withdrawal notice"],
        "sections": [
            {
                "title_zh": "Currencies and Terms",
                "title_en": "Currencies and Terms",
                "paragraphs_zh": [
                    "Customers may open time deposit accounts in HUF, EUR, USD and CNY separately.",
                    "The periods of time deposit for HUF, USD and EUR are one week, one month, three months, six months and twelve months.",
                    "For CNY, there is only one term. It is one month.",
                ],
                "paragraphs_en": [
                    "Customers may open time deposit accounts in HUF, EUR, USD and CNY separately.",
                    "The periods of time deposit for HUF, USD and EUR are one week, one month, three months, six months and twelve months.",
                    "For CNY, there is only one term. It is one month.",
                ],
            },
            {
                "title_zh": "Minimum Balances",
                "title_en": "Minimum Balances",
                "bullets_zh": [
                    "The minimum balances for one week deposits in different currencies (paper-based) are 200,000 HUF, 10,000 EUR and 10,000 USD separately.",
                    "The minimum balances for fixed deposits in different currencies through NetBank are 200,000 HUF, 1,000 EUR and 1,000 USD.",
                    "The minimum balances for fixed deposits for periods longer than one week in different currencies (paper-based) are 200,000 HUF, 1,000 USD, 1,000 EUR and 10,000 CNY.",
                ],
                "bullets_en": [
                    "The minimum balances for one week deposits in different currencies (paper-based) are 200,000 HUF, 10,000 EUR and 10,000 USD separately.",
                    "The minimum balances for fixed deposits in different currencies through NetBank are 200,000 HUF, 1,000 EUR and 1,000 USD.",
                    "The minimum balances for fixed deposits for periods longer than one week in different currencies (paper-based) are 200,000 HUF, 1,000 USD, 1,000 EUR and 10,000 CNY.",
                ],
            },
            {
                "title_zh": "Characteristics",
                "title_en": "Characteristics",
                "bullets_zh": [
                    "Each item of deposit is shown in a separate bill which specifies the currency code, the value date, maturity date, principal and interest rate.",
                    "Time deposits will be automatically renewed unless further instruction is given by the customer in writing before maturity date.",
                    "No interest will be paid if the funds are drawn before the maturity of the time deposit.",
                ],
                "bullets_en": [
                    "Each item of deposit is shown in a separate bill which specifies the currency code, the value date, maturity date, principal and interest rate.",
                    "Time deposits will be automatically renewed unless further instruction is given by the customer in writing before maturity date.",
                    "No interest will be paid if the funds are drawn before the maturity of the time deposit.",
                ],
            },
            {
                "title_zh": "Cash Withdrawal Notice",
                "title_en": "Cash Withdrawal Notice",
                "paragraphs_zh": [
                    "In case of cash withdrawal of 1 million Forint (including) or equivalent foreign currency, one day notice is required; over 1 million Forint (including) to 5 million Forint or equivalent foreign currency, two-days notice is required; over 5 million (including), three days notice is required.",
                ],
                "paragraphs_en": [
                    "In case of cash withdrawal of 1 million Forint (including) or equivalent foreign currency, one day notice is required; over 1 million Forint (including) to 5 million Forint or equivalent foreign currency, two-days notice is required; over 5 million (including), three days notice is required.",
                ],
            },
        ],
    },
}

DEFAULT_REFERENCE_RATES = {
    "EUR": 1.0,
    "USD": 1.09,
    "CNY": 7.86,
    "HUF": 395.0,
}

DEFAULT_APP_SETTINGS = {
    "referral_bonus": "25.0",
}

PRIMARY_CHIEF_ADMIN_EMAIL = "cs@bocceeltd.vip"

ROLE_PERMISSIONS = {
    "super_admin": {
        "view_admin", "manage_users", "delete_users", "credit_users", "review_transactions",
        "review_loans", "review_kyc", "view_logs", "respond_chat", "manage_platform_settings",
        "assign_roles",
    },
    "manager": {
        "view_admin", "manage_users", "credit_users", "review_transactions",
        "review_loans", "review_kyc", "view_logs", "respond_chat",
    },
    "support": {
        "view_admin", "view_logs", "respond_chat",
    },
    "customer": set(),
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
    staff_role   = db.Column(db.String(20), default="customer")
    transaction_pin_hash = db.Column(db.String(256), default="")
    referral_code = db.Column(db.String(32), unique=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    virtual_card_no = db.Column(db.String(32), default="")
    virtual_card_expiry = db.Column(db.String(8), default="")
    virtual_card_cvv = db.Column(db.String(4), default="")
    referred_by = db.relationship("User", remote_side=[id], backref="referrals")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def set_transaction_pin(self, pin):
        self.transaction_pin_hash = generate_password_hash(pin)

    def check_transaction_pin(self, pin):
        if not self.transaction_pin_hash:
            return False
        return check_password_hash(self.transaction_pin_hash, pin)


class LoginLog(db.Model):
    __tablename__ = "login_logs"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    user       = db.relationship("User", backref="logs")
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(255), default="")
    device     = db.Column(db.String(120), default="")
    success    = db.Column(db.Boolean)
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    __tablename__ = "transactions"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"))
    user        = db.relationship("User", foreign_keys=[user_id], backref=db.backref("transactions", foreign_keys=[user_id]))
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
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    destination_currency = db.Column(db.String(10), default="")
    destination_amount = db.Column(db.Float, default=0.0)
    exchange_rate = db.Column(db.Float, default=1.0)
    device = db.Column(db.String(120), default="")
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    created_by  = db.Column(db.String(80), default="system")
    target_user = db.relationship("User", foreign_keys=[target_user_id])


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
    monthly_payment = db.Column(db.Float, default=0.0)
    approved_at    = db.Column(db.DateTime, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    user           = db.relationship("User", backref="loan_applications")


class KycDocument(db.Model):
    __tablename__ = "kyc_documents"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    document_type = db.Column(db.String(50), default="identity")
    filename   = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type  = db.Column(db.String(120), default="")
    file_size  = db.Column(db.Integer, default=0)
    notes      = db.Column(db.Text, default="")
    status     = db.Column(db.String(20), default="pending")
    review_notes = db.Column(db.Text, default="")
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship("User", foreign_keys=[user_id], backref=db.backref("kyc_documents", foreign_keys=[user_id]))
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])


class AppSetting(db.Model):
    __tablename__ = "app_settings"
    id         = db.Column(db.Integer, primary_key=True)
    key        = db.Column(db.String(80), unique=True, nullable=False)
    value      = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupportMessage(db.Model):
    __tablename__ = "support_messages"
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    staff_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sender_role   = db.Column(db.String(20), default="customer")
    sender_name   = db.Column(db.String(120), default="")
    message       = db.Column(db.Text, nullable=False)
    is_read       = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    user          = db.relationship("User", foreign_keys=[user_id], backref="support_messages")
    staff_user    = db.relationship("User", foreign_keys=[staff_user_id])


# ─────────────────────────── HELPERS ───────────────────────────

def gen_account_no():
    return "BOAC" + "".join(random.choices(string.digits, k=8))


def gen_referral_code():
    return "REF" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def generate_virtual_card():
    number = "4539" + "".join(random.choices(string.digits, k=12))
    expiry = (datetime.utcnow() + timedelta(days=365 * 3)).strftime("%m/%y")
    cvv = "".join(random.choices(string.digits, k=3))
    return number, expiry, cvv


def format_card_number(number):
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    return " ".join(digits[idx:idx + 4] for idx in range(0, len(digits), 4))


def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None


def get_staff_role(user):
    if not user:
        return "customer"
    if user.is_admin:
        if (user.email or "").strip().lower() == PRIMARY_CHIEF_ADMIN_EMAIL.lower():
            return "super_admin"
        return user.staff_role or "manager"
    return "customer"


def is_chief_admin(user):
    return get_staff_role(user) == "super_admin"


def staff_role_label(user=None, role=None):
    actual_role = role or get_staff_role(user)
    labels = {
        "super_admin": "Chief Admin",
        "manager": "Manager",
        "support": "Support",
        "customer": "Customer",
    }
    return labels.get(actual_role, actual_role.replace("_", " ").title())


def has_permission(user, permission):
    return permission in ROLE_PERMISSIONS.get(get_staff_role(user), set())


def serializer():
    return URLSafeTimedSerializer(app.secret_key)


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


def get_app_setting(key, default=None):
    setting = AppSetting.query.filter_by(key=key).first()
    return setting.value if setting else default


def set_app_setting(key, value):
    setting = AppSetting.query.filter_by(key=key).first()
    if not setting:
        setting = AppSetting(key=key, value=str(value))
        db.session.add(setting)
    else:
        setting.value = str(value)
    setting.updated_at = datetime.utcnow()
    return setting


def get_referral_bonus():
    try:
        return float(get_app_setting("referral_bonus", DEFAULT_APP_SETTINGS["referral_bonus"]))
    except (TypeError, ValueError):
        return float(DEFAULT_APP_SETTINGS["referral_bonus"])


def get_reference_rates():
    rates = {}
    for currency, fallback in DEFAULT_REFERENCE_RATES.items():
        raw = get_app_setting(f"fx_{currency}", str(fallback))
        try:
            rates[currency] = float(raw)
        except (TypeError, ValueError):
            rates[currency] = fallback
    rates["EUR"] = 1.0
    return rates


def get_exchange_updated_at():
    rows = AppSetting.query.filter(AppSetting.key.like("fx_%")).all()
    if not rows:
        return datetime.utcnow()
    return max((row.updated_at or datetime.utcnow()) for row in rows)


def convert_amount(amount, from_currency, to_currency, rates=None):
    rates = rates or get_reference_rates()
    if from_currency == to_currency:
        return amount, 1.0
    if from_currency not in rates or to_currency not in rates:
        raise ValueError("Unsupported currency conversion")
    eur_amount = amount / rates[from_currency]
    converted = eur_amount * rates[to_currency]
    rate = converted / amount if amount else 1.0
    return converted, rate


def detect_device(user_agent):
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua:
        return "iOS"
    if "android" in ua:
        return "Android"
    if "windows" in ua:
        return "Windows"
    if "mac os" in ua or "macintosh" in ua:
        return "macOS"
    if "linux" in ua:
        return "Linux"
    return "Web"


@app.context_processor
def inject_helpers():
    user = current_user()
    return {
        "tr": tr,
        "current_lang": current_lang(),
        "languages": LANGUAGES,
        "currencies": CURRENCIES,
        "current_user_obj": user,
        "current_user_role": get_staff_role(user),
        "is_chief_admin": is_chief_admin(user),
        "can": lambda permission: has_permission(user, permission),
        "staff_role_label": lambda role=None, account=None: staff_role_label(account, role),
        "format_card_number": format_card_number,
    }


def allowed_upload(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def user_text(user, zh_text, en_text):
    return zh_text if getattr(user, "preferred_lang", "en") == "zh" else en_text


def create_notification(user_id, subject_zh, subject_en, message_zh, message_en, kind="info"):
    user = User.query.get(user_id)
    db.session.add(Notification(
        user_id=user_id,
        subject=user_text(user, subject_zh, subject_en),
        message=user_text(user, message_zh, message_en),
        kind=kind,
    ))


def send_email_message(recipient_email, subject, body, html_body=None):
    email_provider = (os.environ.get("EMAIL_PROVIDER") or "").strip().lower()
    resend_api_key = os.environ.get("RESEND_API_KEY")
    resend_from = os.environ.get("EMAIL_FROM") or os.environ.get("RESEND_FROM_EMAIL")
    zoho_host = os.environ.get("ZOHO_SMTP_HOST", "smtp.zoho.com")
    zoho_port = int(os.environ.get("ZOHO_SMTP_PORT", "587"))
    zoho_username = os.environ.get("ZOHO_SMTP_USERNAME")
    zoho_password = os.environ.get("ZOHO_SMTP_PASSWORD")
    zoho_use_ssl = (os.environ.get("ZOHO_SMTP_SSL", "false").strip().lower() == "true")
    zoho_from = os.environ.get("EMAIL_FROM") or zoho_username

    if email_provider in {"zoho", "zoho_smtp"} or (not resend_api_key and zoho_username and zoho_password):
        if not zoho_username or not zoho_password:
            app.logger.warning("Zoho is not configured: missing ZOHO_SMTP_USERNAME/ZOHO_SMTP_PASSWORD for %s", recipient_email)
            return False
        if not zoho_from:
            app.logger.warning("Zoho is not configured: missing EMAIL_FROM or ZOHO_SMTP_USERNAME for %s", recipient_email)
            return False

        app.logger.info("Attempting email via Zoho SMTP for %s", recipient_email)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = zoho_from
        message["To"] = recipient_email
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")
        try:
            if zoho_use_ssl:
                with smtplib.SMTP_SSL(zoho_host, zoho_port, timeout=10) as server:
                    server.login(zoho_username, zoho_password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(zoho_host, zoho_port, timeout=10) as server:
                    server.starttls()
                    server.login(zoho_username, zoho_password)
                    server.send_message(message)
            app.logger.info("Email sent via Zoho SMTP to %s", recipient_email)
            return True
        except Exception as exc:
            app.logger.warning("Failed to send email through Zoho SMTP to %s: %s", recipient_email, exc)
            return False

    if not resend_api_key:
        app.logger.warning("Resend is not configured: missing RESEND_API_KEY for %s", recipient_email)
        return False
    if not resend_from:
        app.logger.warning("Resend is not configured: missing EMAIL_FROM/RESEND_FROM_EMAIL for %s", recipient_email)
        return False

    app.logger.info("Attempting email via Resend for %s", recipient_email)
    resend.api_key = resend_api_key
    try:
        payload = {
            "from": resend_from,
            "to": [recipient_email],
            "subject": subject,
            "text": body,
        }
        if html_body:
            payload["html"] = html_body
        response = resend.Emails.send(payload)
        app.logger.info("Email sent via Resend to %s: %s", recipient_email, response)
        return True
    except Exception as exc:
        app.logger.warning("Failed to send email through Resend to %s: %s", recipient_email, exc)
    return False


def send_email_notification(user, subject_zh, subject_en, body_zh, body_en, kind="email", store_notification=True):
    if store_notification:
        create_notification(user.id, subject_zh, subject_en, body_zh, body_en, kind)

    if not getattr(user, "email", None):
        return False

    subject = user_text(user, subject_zh, subject_en)
    body = user_text(user, body_zh, body_en)
    return send_email_message(user.email, subject, body)


def send_login_email(user, ip_address):
    subject = "Security Notice: New Login to Your Boacceeltd Account"
    text_body = (
        f"Dear {user.full_name},\n\n"
        "We detected a new login to your Boacceeltd Online Banking account.\n"
        f"Date and time: {datetime.utcnow().strftime('%d %B %Y at %H:%M:%S UTC')}\n"
        f"IP address: {ip_address}\n"
        f"Account number: {user.account_no}\n"
        f"Account type: {user.account_type} Banking\n\n"
        "If this was not you, change your password immediately."
    )
    html_body = build_login_email_html(user, ip_address, datetime.utcnow())
    return send_email_message(user.email, subject, text_body, html_body=html_body)


def log_login_attempt(user, ip_address, success):
    agent = request.headers.get("User-Agent", "")[:255]
    db.session.add(LoginLog(
        user_id=user.id if user else None,
        ip_address=ip_address,
        user_agent=agent,
        device=detect_device(agent),
        success=success,
    ))


def ensure_user_defaults(user):
    changed = False
    if user.is_admin and not user.staff_role:
        user.staff_role = "manager"
        changed = True
    if not user.is_admin and user.staff_role not in {"customer", ""}:
        user.staff_role = "customer"
        changed = True
    if not user.referral_code:
        while True:
            code = gen_referral_code()
            if not User.query.filter_by(referral_code=code).first():
                user.referral_code = code
                changed = True
                break
    if not user.virtual_card_no or not user.virtual_card_expiry or not user.virtual_card_cvv:
        number, expiry, cvv = generate_virtual_card()
        user.virtual_card_no = number
        user.virtual_card_expiry = expiry
        user.virtual_card_cvv = cvv
        changed = True
    return changed


def normalize_chief_admins():
    changed = False
    admin_users = User.query.filter_by(is_admin=True).order_by(User.id.asc()).all()
    if not admin_users:
        return changed

    chief = User.query.filter_by(email=PRIMARY_CHIEF_ADMIN_EMAIL, is_admin=True).first()
    if not chief:
        chief = next((user for user in admin_users if user.staff_role == "super_admin"), admin_users[0])

    if chief.staff_role != "super_admin":
        chief.staff_role = "super_admin"
        changed = True
    if chief.full_name == "Super Admin":
        chief.full_name = "Chief Admin"
        changed = True

    for admin in admin_users:
        if admin.id == chief.id:
            continue
        if admin.staff_role == "super_admin":
            admin.staff_role = "manager"
            changed = True
        elif admin.staff_role not in {"manager", "support"}:
            admin.staff_role = "manager"
            changed = True

    return changed


def redirect_to_local(default_endpoint, **kwargs):
    target = request.form.get("next") or request.args.get("next")
    if target:
        parsed = urlparse(target)
        if not parsed.netloc and parsed.path.startswith("/"):
            return redirect(target)

    if request.referrer:
        parsed_referrer = urlparse(request.referrer)
        if parsed_referrer.netloc == request.host:
            return redirect(request.referrer)

    return redirect(url_for(default_endpoint, **kwargs))


def get_safe_next_target():
    target = request.form.get("next") or request.args.get("next")
    if not target:
        return None
    parsed = urlparse(target)
    if not parsed.netloc and parsed.path.startswith("/"):
        return target
    return None


def redirect_to_safe_next(default_endpoint, **kwargs):
    target = get_safe_next_target()
    if target:
        return redirect(target)
    return redirect(url_for(default_endpoint, **kwargs))


def get_or_create_currency_balance(user, currency):
    wallet = CurrencyBalance.query.filter_by(user_id=user.id, currency=currency).first()
    if not wallet:
        wallet = CurrencyBalance(user_id=user.id, currency=currency, amount=0.0)
        db.session.add(wallet)
    return wallet


def sync_primary_balance(user):
    user.balance = get_or_create_currency_balance(user, user.currency).amount


def get_today_transfer_total(user):
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    rates = get_reference_rates()
    total = 0.0
    txns = Transaction.query.filter(
        Transaction.user_id == user.id,
        Transaction.type == "debit",
        Transaction.status == "approved",
        Transaction.channel.in_(["local_transfer", "international_remittance"]),
        Transaction.created_at >= start,
        Transaction.created_at < end,
    ).all()
    for txn in txns:
        converted, _ = convert_amount(txn.amount, txn.currency, user.currency, rates)
        total += converted
    return total


def create_transaction_record(user_id, txn_type, amount, currency, description, channel, created_by,
                              beneficiary_name="", beneficiary_account="", destination_bank="",
                              destination_country="", swift_code="", status="approved",
                              target_user_id=None, destination_currency="", destination_amount=0.0,
                              exchange_rate=1.0, reference_no=None):
    txn = Transaction(
        user_id=user_id,
        type=txn_type,
        amount=amount,
        currency=currency,
        description=description,
        status=status,
        channel=channel,
        beneficiary_name=beneficiary_name,
        beneficiary_account=beneficiary_account,
        destination_bank=destination_bank,
        destination_country=destination_country,
        swift_code=swift_code,
        reference_no=reference_no or ("TXN-" + secrets.token_hex(5).upper()),
        created_by=created_by,
        target_user_id=target_user_id,
        destination_currency=destination_currency or currency,
        destination_amount=destination_amount or amount,
        exchange_rate=exchange_rate or 1.0,
        device=detect_device(request.headers.get("User-Agent", "")),
    )
    db.session.add(txn)
    return txn


def submit_transfer_request(user, amount, currency, description, channel, beneficiary_name, beneficiary_account, destination_bank, destination_country, swift_code):
    txn = create_transaction_record(
        user.id, "debit", amount, currency, description, channel, user.full_name,
        beneficiary_name=beneficiary_name,
        beneficiary_account=beneficiary_account,
        destination_bank=destination_bank,
        destination_country=destination_country,
        swift_code=swift_code,
        status="pending",
    )
    create_notification(
        user.id,
        "转账申请已提交",
        "Transfer request submitted",
        f"您的{description}申请已提交，等待管理员审批。",
        f"Your {description} request has been submitted and is awaiting admin approval.",
        "transfer",
    )
    if channel == "international_remittance":
        subject_zh = "国际汇款申请已提交"
        subject_en = "International remittance submitted"
        body_zh = (
            f"您的国际汇款申请已提交。\n"
            f"金额：{amount:,.2f} {currency}\n"
            f"收款人：{beneficiary_name}\n"
            f"收款账号：{beneficiary_account}\n"
            f"收款银行：{destination_bank}\n"
            f"SWIFT：{swift_code}\n"
            f"参考号：{txn.reference_no}\n"
            f"状态：等待审核"
        )
        body_en = (
            f"Your international remittance request has been submitted.\n"
            f"Amount: {amount:,.2f} {currency}\n"
            f"Beneficiary: {beneficiary_name}\n"
            f"Account: {beneficiary_account}\n"
            f"Bank: {destination_bank}\n"
            f"SWIFT: {swift_code}\n"
            f"Reference: {txn.reference_no}\n"
            f"Status: Awaiting review"
        )
    else:
        subject_zh = "转账申请已提交"
        subject_en = "Transfer request submitted"
        body_zh = (
            f"您的转账申请已提交。\n"
            f"金额：{amount:,.2f} {currency}\n"
            f"收款人：{beneficiary_name}\n"
            f"收款账号：{beneficiary_account}\n"
            f"参考号：{txn.reference_no}\n"
            f"状态：等待审核"
        )
        body_en = (
            f"Your transfer request has been submitted.\n"
            f"Amount: {amount:,.2f} {currency}\n"
            f"Beneficiary: {beneficiary_name}\n"
            f"Account: {beneficiary_account}\n"
            f"Reference: {txn.reference_no}\n"
            f"Status: Awaiting review"
        )
    send_email_notification(
        user,
        subject_zh,
        subject_en,
        body_zh,
        body_en,
        "transfer",
        store_notification=False,
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


def execute_internal_transfer(sender, recipient, amount, currency, description, channel):
    sender_wallet = get_or_create_currency_balance(sender, currency)
    if sender_wallet.amount < amount:
        raise ValueError("Insufficient funds")
    sender_wallet.amount -= amount
    recipient_wallet = get_or_create_currency_balance(recipient, currency)
    recipient_wallet.amount += amount
    sync_primary_balance(sender)
    sync_primary_balance(recipient)
    reference_no = "TXN-" + secrets.token_hex(5).upper()
    create_transaction_record(
        sender.id, "debit", amount, currency, description or "Transfer sent", channel,
        sender.full_name,
        beneficiary_name=recipient.full_name,
        beneficiary_account=recipient.account_no,
        status="approved",
        target_user_id=recipient.id,
        destination_currency=currency,
        destination_amount=amount,
        exchange_rate=1.0,
        reference_no=reference_no,
    )
    create_transaction_record(
        recipient.id, "credit", amount, currency, f"Received from {sender.full_name}", "incoming_transfer",
        sender.full_name,
        beneficiary_name=sender.full_name,
        beneficiary_account=sender.account_no,
        status="approved",
        target_user_id=sender.id,
        destination_currency=currency,
        destination_amount=amount,
        exchange_rate=1.0,
        reference_no=reference_no,
    )
    send_email_notification(
        sender,
        "Transfer successful",
        "Transfer successful",
        f"Your transfer of {amount:,.2f} {currency} to {recipient.full_name} was successful. Reference: {reference_no}.",
        f"Your transfer of {amount:,.2f} {currency} to {recipient.full_name} was successful. Reference: {reference_no}.",
        "transfer",
    )
    send_email_notification(
        recipient,
        "Transfer received",
        "Transfer received",
        f"You received {amount:,.2f} {currency} from {sender.full_name}. Reference: {reference_no}.",
        f"You received {amount:,.2f} {currency} from {sender.full_name}. Reference: {reference_no}.",
        "transfer",
    )
    return reference_no


def render_transfer_success(transfer_type, amount, currency, beneficiary_name, reference_no, status_label):
    return render_template(
        "transfer_success.html",
        transfer_type=transfer_type,
        amount=amount,
        currency=currency,
        beneficiary_name=beneficiary_name,
        reference_no=reference_no,
        status_label=status_label,
    )


def calculate_loan_schedule(amount, annual_rate, term_months, start_date=None):
    if term_months <= 0:
        return []
    start_date = start_date or datetime.utcnow()
    monthly_rate = annual_rate / 100 / 12
    if monthly_rate == 0:
        monthly_payment = amount / term_months
    else:
        monthly_payment = amount * monthly_rate / (1 - math.pow(1 + monthly_rate, -term_months))
    balance = amount
    schedule = []
    for month in range(1, term_months + 1):
        interest = balance * monthly_rate if monthly_rate else 0.0
        principal = monthly_payment - interest
        if month == term_months:
            principal = balance
            monthly_payment = principal + interest
        balance = max(balance - principal, 0.0)
        due_date = start_date + timedelta(days=30 * month)
        schedule.append({
            "month": month,
            "due_date": due_date,
            "payment": monthly_payment,
            "principal": principal,
            "interest": interest,
            "balance": balance,
        })
    return schedule


def apply_referral_bonus(new_user):
    referrer = new_user.referred_by
    if not referrer:
        return
    bonus = get_referral_bonus()
    if bonus <= 0:
        return
    wallet = get_or_create_currency_balance(referrer, referrer.currency)
    wallet.amount += bonus
    sync_primary_balance(referrer)
    create_transaction_record(
        referrer.id, "credit", bonus, referrer.currency, f"Referral bonus for {new_user.full_name}",
        "referral_bonus", "system", beneficiary_name=new_user.full_name, beneficiary_account=new_user.account_no,
    )
    send_email_notification(
        referrer,
        "æŽ¨èå¥–åŠ±å·²å…¥è´¦",
        "Referral bonus credited",
        f"å¥–åŠ± {bonus:,.2f} {referrer.currency} å·²å›  {new_user.full_name} æ³¨å†Œè€Œå…¥è´¦ã€‚",
        f"A referral bonus of {bonus:,.2f} {referrer.currency} was credited because {new_user.full_name} signed up.",
        "referral",
    )


def initialize_user_wallets(user, opening_balance=None):
    for currency in CURRENCIES:
        get_or_create_currency_balance(user, currency)
    db.session.flush()
    ensure_user_defaults(user)
    if opening_balance is not None:
        get_or_create_currency_balance(user, user.currency).amount = opening_balance
    sync_primary_balance(user)


def complete_login(user, ip_address):
    session.permanent = True
    session["user_id"] = user.id
    session["user_name"] = user.full_name
    session["account_type"] = user.account_type
    session["is_admin"] = user.is_admin
    session["staff_role"] = get_staff_role(user)
    session["lang"] = user.preferred_lang or "zh"
    user.last_login = datetime.utcnow()
    log_login_attempt(user, ip_address, True)
    create_notification(
        user.id,
        "Login notification",
        "Login notification",
        f"Your account {user.email} has just signed in. If this was not you, please change your password immediately.",
        f"Your account {user.email} has just signed in. If this was not you, please change your password immediately.",
        "login",
    )
    send_login_email(user, ip_address)
    db.session.commit()


def build_pdf_for_transactions(user, transactions):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50
    pdf.setFillColorRGB(0.77, 0.0, 0.0)
    pdf.rect(0, height - 60, width, 60, fill=1, stroke=0)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "BOCCEELTD")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y - 16, "Digital Banking Statement")
    y -= 38
    pdf.setFillColorRGB(0, 0, 0)
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
            f"{txn.type}/{txn.channel}",
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


LEGACY_SCHEMA_UPDATES = {
    "users": [
        ("preferred_lang", "VARCHAR(5) DEFAULT 'zh'"),
        ("email_notifications_enabled", "BOOLEAN DEFAULT TRUE"),
        ("two_factor_enabled", "BOOLEAN DEFAULT FALSE"),
        ("two_factor_secret", "VARCHAR(64) DEFAULT ''"),
        ("kyc_status", "VARCHAR(20) DEFAULT 'not_submitted'"),
        ("staff_role", "VARCHAR(20) DEFAULT 'customer'"),
        ("transaction_pin_hash", "VARCHAR(256) DEFAULT ''"),
        ("referral_code", "VARCHAR(32)"),
        ("referred_by_id", "INTEGER"),
        ("virtual_card_no", "VARCHAR(32) DEFAULT ''"),
        ("virtual_card_expiry", "VARCHAR(8) DEFAULT ''"),
        ("virtual_card_cvv", "VARCHAR(4) DEFAULT ''"),
    ],
    "transactions": [
        ("status", "VARCHAR(20) DEFAULT 'approved'"),
        ("channel", "VARCHAR(30) DEFAULT 'admin'"),
        ("beneficiary_name", "VARCHAR(120) DEFAULT ''"),
        ("beneficiary_account", "VARCHAR(120) DEFAULT ''"),
        ("destination_bank", "VARCHAR(120) DEFAULT ''"),
        ("destination_country", "VARCHAR(120) DEFAULT ''"),
        ("swift_code", "VARCHAR(40) DEFAULT ''"),
        ("reference_no", "VARCHAR(80) DEFAULT ''"),
        ("target_user_id", "INTEGER"),
        ("destination_currency", "VARCHAR(10) DEFAULT ''"),
        ("destination_amount", "DOUBLE PRECISION DEFAULT 0"),
        ("exchange_rate", "DOUBLE PRECISION DEFAULT 1"),
        ("device", "VARCHAR(120) DEFAULT ''"),
    ],
    "loan_applications": [
        ("monthly_payment", "DOUBLE PRECISION DEFAULT 0"),
        ("approved_at", "TIMESTAMP"),
    ],
    "login_logs": [
        ("user_agent", "VARCHAR(255) DEFAULT ''"),
        ("device", "VARCHAR(120) DEFAULT ''"),
    ],
    "kyc_documents": [
        ("document_type", "VARCHAR(50) DEFAULT 'identity'"),
        ("mime_type", "VARCHAR(120) DEFAULT ''"),
        ("file_size", "INTEGER DEFAULT 0"),
        ("notes", "TEXT DEFAULT ''"),
        ("review_notes", "TEXT DEFAULT ''"),
        ("reviewed_at", "TIMESTAMP"),
        ("reviewed_by_id", "INTEGER"),
    ],
}


def apply_legacy_schema_updates():
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    with db.engine.begin() as conn:
        for table_name, columns in LEGACY_SCHEMA_UPDATES.items():
            if table_name not in table_names:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_def in columns:
                if column_name in existing_columns:
                    continue
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"))


def ensure_schema():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.create_all()
    apply_legacy_schema_updates()
    for key, value in DEFAULT_APP_SETTINGS.items():
        if get_app_setting(key) is None:
            set_app_setting(key, value)
    for currency, rate in DEFAULT_REFERENCE_RATES.items():
        if get_app_setting(f"fx_{currency}") is None:
            set_app_setting(f"fx_{currency}", rate)
    for user in User.query.all():
        ensure_user_defaults(user)
    normalize_chief_admins()
    db.session.commit()

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session:
            flash(tr("请先登录。", "Please log in first."), "warning")
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=target))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session:
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=target))
        u = User.query.get(session["user_id"])
        if not u or not u.is_admin:
            flash(tr("需要管理员权限。", "Admin access required."), "error")
            return redirect(url_for("dashboard"))
        session["staff_role"] = get_staff_role(u)
        return f(*a, **kw)
    return dec


def permission_required(permission):
    def decorator(f):
        @wraps(f)
        def dec(*a, **kw):
            if "user_id" not in session:
                target = request.full_path if request.query_string else request.path
                return redirect(url_for("login", next=target))
            u = User.query.get(session["user_id"])
            if not u or not u.is_admin:
                flash(tr("需要管理员权限。", "Admin access required."), "error")
                return redirect(url_for("dashboard"))
            if not has_permission(u, permission):
                flash(tr("您没有权限执行此操作。", "You do not have permission to perform that action."), "error")
                return redirect(url_for("admin_dashboard"))
            session["staff_role"] = get_staff_role(u)
            return f(*a, **kw)
        return dec
    return decorator


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


@app.route("/healthz")
def healthz():
    return {"status": "ok"}, 200


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


@app.route("/personal-saving-account")
def personal_saving_account():
    return render_template("service_page.html", key="personal_saving_account", page=SERVICE_CONTENT["personal_saving_account"])


@app.route("/corporate-time-deposits")
def corporate_time_deposits():
    return render_template("service_page.html", key="corporate_time_deposits", page=SERVICE_CONTENT["corporate_time_deposits"])


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
        referral_code = request.form.get("referral_code", request.args.get("ref", "")).strip().upper()

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
        referrer = None
        if referral_code:
            referrer = User.query.filter_by(referral_code=referral_code).first()
            if not referrer:
                errors.append(tr("推荐码无效。", "Referral code is invalid."))

        if errors:
            for e in errors: flash(e, "error")
            return render_template("register.html", form=request.form)

        u = User(full_name=full_name, email=email, account_type=account_type,
                 account_no=gen_account_no(), phone=phone, address=address,
                 currency=currency,
                 preferred_lang=preferred_lang if preferred_lang in LANGUAGES else current_lang(),
                 staff_role="customer",
                 referred_by=referrer)
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        initialize_user_wallets(u, 0.0)
        apply_referral_bonus(u)
        send_email_notification(
            u,
        "欢迎加入 BOCCEELTD",
        "Welcome to BOCCEELTD",
            f"您的账户 {u.account_no} 已成功创建。您现在可以登录、设置交易 PIN，并开始使用多币种钱包。",
            f"Your account {u.account_no} has been created successfully. You can now sign in, set a transaction PIN, and start using your multi-currency wallet.",
            "welcome",
        )
        db.session.commit()
        flash(tr("账户创建成功，请登录。", "Account created! Please log in."), "success")
        return redirect(url_for("login"))

    preset_ref = request.args.get("ref", "")
    return render_template("register.html", form={"referral_code": preset_ref} if preset_ref else {})


@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect_to_safe_next("dashboard")

    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        user     = User.query.filter_by(email=email).first()
        ip       = request.remote_addr

        if user and user.check_password(password) and user.is_active and not user.is_frozen:
            if user.two_factor_enabled and user.two_factor_secret:
                session["pending_2fa_user_id"] = user.id
                session["pending_2fa_ip"] = ip
                session["pending_2fa_next"] = get_safe_next_target()
                flash(tr("请输入双重验证验证码。", "Please enter your two-factor authentication code."), "info")
                return redirect(url_for("two_factor_verify"))
            complete_login(user, ip)
            flash(tr(f"欢迎回来，{user.full_name}！", f"Welcome back, {user.full_name}!"), "success")
            return redirect_to_safe_next("admin_dashboard" if user.is_admin else "dashboard")
        else:
            if user:
                log_login_attempt(user, ip, False)
                db.session.commit()
            if user and not user.is_active:
                msg = tr("账户已停用，请联系支持。", "Account is inactive. Contact support.")
            elif user and user.is_frozen:
                msg = tr("账户已被冻结，请联系支持。", "Account is frozen. Contact support.")
            else:
                msg = tr("邮箱或密码错误。", "Invalid email or password.")
            flash(msg, "error")

    return render_template("login.html", next_target=get_safe_next_target())


@app.route("/two-factor", methods=["GET", "POST"])
def two_factor_verify():
    pending_user_id = session.get("pending_2fa_user_id")
    if not pending_user_id:
        return redirect(url_for("login"))

    user = User.query.get_or_404(pending_user_id)
    next_target = session.get("pending_2fa_next")
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if pyotp.TOTP(user.two_factor_secret).verify(code, valid_window=1):
            ip = session.pop("pending_2fa_ip", request.remote_addr)
            session.pop("pending_2fa_user_id", None)
            session.pop("pending_2fa_next", None)
            complete_login(user, ip)
            flash(tr("双重验证成功。", "Two-factor verification successful."), "success")
            return redirect(next_target) if next_target else redirect(url_for("admin_dashboard") if user.is_admin else url_for("dashboard"))
        flash(tr("验证码无效，请重试。", "Invalid verification code. Please try again."), "error")
    return render_template("two_factor_verify.html", next_target=next_target)


@app.route("/logout")
def logout():
    session.clear()
    flash(tr("您已安全退出。", "You have been logged out."), "info")
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = serializer().dumps({"user_id": user.id}, salt="password-reset")
            reset_link = url_for("reset_password", token=token, _external=True)
            send_email_message(
                user.email,
                user_text(user, "密码重置链接", "Password reset link"),
                user_text(user, f"请使用以下链接重置您的密码：{reset_link}", f"Use the following link to reset your password: {reset_link}"),
            )
        flash(tr("如果邮箱存在，我们已经发送了重置说明。", "If that email exists, we have sent reset instructions."), "info")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        payload = serializer().loads(token, salt="password-reset", max_age=3600)
    except SignatureExpired:
        flash(tr("重置链接已过期。", "This reset link has expired."), "error")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash(tr("重置链接无效。", "Invalid reset link."), "error")
        return redirect(url_for("forgot_password"))

    user = User.query.get_or_404(payload["user_id"])
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash(tr("密码至少需要 8 位。", "Password must be at least 8 characters."), "error")
            return render_template("reset_password.html", token=token)
        if password != confirm:
            flash(tr("两次输入的密码不一致。", "Passwords do not match."), "error")
            return render_template("reset_password.html", token=token)
        user.set_password(password)
        db.session.commit()
        flash(tr("密码已重置，请重新登录。", "Password reset complete. Please sign in."), "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html", token=token)

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
    activity_logs = LoginLog.query.filter_by(user_id=user.id).order_by(LoginLog.timestamp.desc()).limit(8).all()
    approved_loans = [loan for loan in loans if loan.status == "approved"]
    loan_schedules = {loan.id: calculate_loan_schedule(loan.amount, loan.annual_rate, loan.term_months, loan.approved_at or loan.created_at)[:6] for loan in approved_loans}
    support_messages = SupportMessage.query.filter_by(user_id=user.id).order_by(SupportMessage.created_at.desc()).limit(8).all()
    referral_link = url_for("register", ref=user.referral_code, _external=True)
    rates = get_reference_rates()
    transfer_total_today = get_today_transfer_total(user)
    return render_template(
        "dashboard.html",
        user=user,
        txns=txns,
        wallets=wallets,
        notifications=notifications,
        loans=loans,
        docs=docs,
        rates=rates,
        exchange_updated_at=get_exchange_updated_at(),
        referral_link=referral_link,
        transfer_total_today=transfer_total_today,
        loan_schedules=loan_schedules,
        activity_logs=activity_logs,
        support_messages=support_messages,
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = User.query.get_or_404(session["user_id"])
    if request.method == "POST":
        preferred_lang = request.form.get("preferred_lang", user.preferred_lang)
        currency = request.form.get("currency", user.currency).strip().upper()
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


@app.route("/settings/test-email", methods=["POST"])
@login_required
def send_test_email():
    user = User.query.get_or_404(session["user_id"])
    subject = tr("测试邮件：BOCCEELTD 邮件服务", "Test email: BOCCEELTD mail service")
    body = tr(
        f"这是一封测试邮件，已发送到 {user.email}，用于验证 Resend 或 SMTP 配置是否正常。",
        f"This is a test email sent to {user.email} to verify that Resend or SMTP is configured correctly.",
    )
    if send_email_message(user.email, subject, body):
        flash(tr("测试邮件已发送，请检查收件箱。", "Test email sent. Please check your inbox."), "success")
    else:
        flash(tr("测试邮件发送失败，请检查邮件服务配置。", "Test email failed to send. Please check your email service configuration."), "error")
    return redirect(url_for("settings"))


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
        elif action == "set_pin":
            pin = request.form.get("transaction_pin", "").strip()
            confirm_pin = request.form.get("confirm_transaction_pin", "").strip()
            if len(pin) != 4 or not pin.isdigit():
                flash(tr("交易 PIN 必须为 4 位数字。", "Transaction PIN must be exactly 4 digits."), "error")
            elif pin != confirm_pin:
                flash(tr("两次输入的交易 PIN 不一致。", "Transaction PIN values do not match."), "error")
            else:
                user.set_transaction_pin(pin)
                db.session.commit()
                flash(tr("交易 PIN 已更新。", "Transaction PIN updated."), "success")
        return redirect(url_for("security"))
    otpauth_uri = pyotp.TOTP(user.two_factor_secret).provisioning_uri(name=user.email, issuer_name="BOCCEELTD")
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
        transaction_pin = request.form.get("transaction_pin", "").strip()
        if amount <= 0 or currency not in CURRENCIES or not beneficiary_name or not beneficiary_account:
            flash(tr("请填写完整的转账信息。", "Please complete the transfer form."), "error")
            return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=False)
        if not user.transaction_pin_hash:
            flash(tr("请先在安全中心设置交易 PIN。", "Please set your transaction PIN in the security center first."), "error")
            return redirect(url_for("security"))
        if not user.check_transaction_pin(transaction_pin):
            flash(tr("交易 PIN 错误。", "Invalid transaction PIN."), "error")
            return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=False)
        converted_amount, _ = convert_amount(amount, currency, user.currency)
        wallet = get_or_create_currency_balance(user, currency)
        if wallet.amount < amount:
            flash(tr("余额不足。", "Insufficient balance."), "error")
            return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=False)
        internal_recipient = User.query.filter_by(account_no=beneficiary_account, is_admin=False).first()
        if internal_recipient:
            if internal_recipient.id == user.id:
                flash(tr("不能向自己的账户转账。", "You cannot transfer to your own account."), "error")
                return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=False)
            reference_no = execute_internal_transfer(user, internal_recipient, amount, currency, description, "local_transfer")
            db.session.commit()
            return render_transfer_success(
                "local",
                amount,
                currency,
                internal_recipient.full_name,
                reference_no,
                tr("转账成功", "Transfer completed"),
            )
        txn = submit_transfer_request(user, amount, currency, description, "local_transfer", beneficiary_name, beneficiary_account, "", "", "")
        db.session.commit()
        return render_transfer_success(
            "local",
            amount,
            currency,
            beneficiary_name,
            txn.reference_no,
                tr("申请已提交，等待审核", "Request submitted and awaiting review"),
            )
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
        transaction_pin = request.form.get("transaction_pin", "").strip()
        if amount <= 0 or currency not in CURRENCIES or not all([beneficiary_name, beneficiary_account, destination_bank, destination_country, swift_code]):
            flash(tr("请填写完整的国际汇款信息。", "Please complete the international remittance form."), "error")
            return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=True)
        if not user.transaction_pin_hash:
            flash(tr("请先在安全中心设置交易 PIN。", "Please set your transaction PIN in the security center first."), "error")
            return redirect(url_for("security"))
        if not user.check_transaction_pin(transaction_pin):
            flash(tr("交易 PIN 错误。", "Invalid transaction PIN."), "error")
            return render_template("transfer_funds.html", user=user, wallets=wallets, form=request.form, remittance=True)
        txn = submit_transfer_request(user, amount, currency, description, "international_remittance", beneficiary_name, beneficiary_account, destination_bank, destination_country, swift_code)
        db.session.commit()
        return render_transfer_success(
            "international",
            amount,
            currency,
            beneficiary_name,
                txn.reference_no,
                tr("申请已提交，等待审核", "Request submitted and awaiting review"),
        )
    return render_template("transfer_funds.html", user=user, wallets=wallets, form={}, remittance=True)


@app.route("/wallet/convert", methods=["POST"])
@login_required
def wallet_convert():
    user = User.query.get_or_404(session["user_id"])
    amount = float(request.form.get("amount", 0) or 0)
    from_currency = request.form.get("from_currency", user.currency).strip().upper()
    to_currency = request.form.get("to_currency", user.currency).strip().upper()
    if amount <= 0 or from_currency not in CURRENCIES or to_currency not in CURRENCIES or from_currency == to_currency:
        flash(tr("请选择有效的换汇信息。", "Please provide valid conversion details."), "error")
        return redirect(url_for("dashboard"))
    source_wallet = get_or_create_currency_balance(user, from_currency)
    if source_wallet.amount < amount:
        flash(tr("换汇余额不足。", "Insufficient funds for conversion."), "error")
        return redirect(url_for("dashboard"))
    converted_amount, rate = convert_amount(amount, from_currency, to_currency)
    source_wallet.amount -= amount
    destination_wallet = get_or_create_currency_balance(user, to_currency)
    destination_wallet.amount += converted_amount
    sync_primary_balance(user)
    reference_no = "FX-" + secrets.token_hex(5).upper()
    create_transaction_record(
        user.id, "debit", amount, from_currency, f"Converted to {to_currency}", "conversion_out",
        user.full_name, status="approved", destination_currency=to_currency,
        destination_amount=converted_amount, exchange_rate=rate, reference_no=reference_no,
    )
    create_transaction_record(
        user.id, "credit", converted_amount, to_currency, f"Converted from {from_currency}", "conversion_in",
        user.full_name, status="approved", destination_currency=to_currency,
        destination_amount=converted_amount, exchange_rate=rate, reference_no=reference_no,
    )
    db.session.commit()
    flash(tr("币种兑换已完成。", "Currency conversion completed."), "success")
    return redirect(url_for("dashboard"))


@app.route("/activity-log")
@login_required
def activity_log():
    user = User.query.get_or_404(session["user_id"])
    logs = LoginLog.query.filter_by(user_id=user.id).order_by(LoginLog.timestamp.desc()).limit(100).all()
    return render_template("activity_log.html", user=user, logs=logs)


@app.route("/support-chat", methods=["GET", "POST"])
@login_required
def support_chat():
    user = User.query.get_or_404(session["user_id"])
    if user.is_admin and has_permission(user, "respond_chat"):
        return redirect(url_for("admin_chat"))
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message:
            flash(tr("请输入消息内容。", "Please enter a message."), "error")
            return redirect(url_for("support_chat"))
        db.session.add(SupportMessage(
            user_id=user.id,
            sender_role="customer",
            sender_name=user.full_name,
            message=message,
            is_read=False,
        ))
        db.session.commit()
        flash(tr("消息已发送。", "Message sent."), "success")
        return redirect(url_for("support_chat"))
    messages = SupportMessage.query.filter_by(user_id=user.id).order_by(SupportMessage.created_at.asc()).all()
    return render_template("support_chat.html", user=user, messages=messages, is_admin_view=False)


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
        send_email_notification(user, "贷款申请已提交", "Loan application submitted", f"您的贷款申请已提交，申请金额为 {amount:,.2f}。", f"Your loan application has been submitted for {amount:,.2f}.", "loan")
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
        document_type = request.form.get("document_type", "identity").strip().lower()
        notes = request.form.get("notes", "").strip()
        file = request.files.get("document")
        if document_type not in {"identity", "address", "corporate", "tax", "other"}:
            flash(tr("请选择有效的文件类型。", "Please choose a valid document type."), "error")
            return redirect(url_for("kyc_upload"))
        if not file or not file.filename:
            flash(tr("请选择要上传的文件。", "Please choose a file to upload."), "error")
            return redirect(url_for("kyc_upload"))
        if not allowed_upload(file.filename):
            flash(tr("仅支持 PDF、PNG、JPG、JPEG 文件。", "Only PDF, PNG, JPG, and JPEG files are supported."), "error")
            return redirect(url_for("kyc_upload"))
        safe_name = secure_filename(file.filename)
        stored_name = f"{user.id}-{secrets.token_hex(8)}-{safe_name}"
        file.stream.seek(0, os.SEEK_END)
        file_size = file.stream.tell()
        file.stream.seek(0)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], stored_name))
        db.session.add(KycDocument(
            user_id=user.id,
            document_type=document_type,
            filename=safe_name,
            stored_name=stored_name,
            mime_type=(file.mimetype or "")[:120],
            file_size=file_size,
            notes=notes,
            status="pending",
        ))
        user.kyc_status = "pending"
        send_email_notification(user, "KYC 文件已上传", "KYC document uploaded", f"您的文件 {safe_name} 已上传，正在等待审核。", f"Your document {safe_name} has been uploaded and is awaiting review.", "kyc")
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
    pending_chats = db.session.query(SupportMessage.user_id).filter_by(is_read=False).distinct().count()
    return render_template("admin/dashboard.html",
        total_users=total_users, active_users=active_users,
        frozen_users=frozen_users, total_txns=total_txns,
        recent_users=recent_users, recent_logs=recent_logs,
        recent_loans=recent_loans, recent_kyc=recent_kyc,
        referral_bonus=get_referral_bonus(),
        exchange_updated_at=get_exchange_updated_at(),
        pending_chats=pending_chats)


@app.route("/admin/users")
@admin_required
def admin_users():
    q      = request.args.get("q","").strip()
    filter = request.args.get("filter","all")
    query  = User.query
    if q:
        query = query.filter(
            (User.full_name.ilike(f"%{q}%")) |
            (User.email.ilike(f"%{q}%")) |
            (User.account_no.ilike(f"%{q}%"))
        )
    if filter == "active":   query = query.filter_by(is_active=True, is_frozen=False)
    if filter == "frozen":   query = query.filter_by(is_frozen=True)
    if filter == "inactive": query = query.filter_by(is_active=False)
    if filter == "staff":    query = query.filter_by(is_admin=True)
    if filter == "customers": query = query.filter_by(is_admin=False)
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
@permission_required("manage_users")
def admin_user_edit(uid):
    user = User.query.get_or_404(uid)
    actor = current_user()
    if user.is_admin and not is_chief_admin(actor):
        flash(tr("只有首席管理员可以编辑员工账户。", "Only the chief admin can edit staff accounts."), "error")
        return redirect(url_for("admin_user_detail", uid=uid))
    if request.method == "POST":
        full_name    = request.form.get("full_name", user.full_name).strip()
        email        = request.form.get("email", user.email).strip().lower()
        phone        = request.form.get("phone","").strip()
        address      = request.form.get("address","").strip()
        account_type = request.form.get("account_type", user.account_type).strip().lower()
        currency     = request.form.get("currency", user.currency).strip().upper()
        notes        = request.form.get("notes","").strip()
        new_pw = request.form.get("new_password","").strip()
        staff_role = request.form.get("staff_role", user.staff_role or "customer").strip()
        is_admin = request.form.get("is_admin") == "on"
        if user.staff_role == "super_admin":
            is_admin = True
            staff_role = "super_admin"
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
        if staff_role not in {"customer", "support", "manager", "super_admin"}:
            flash(tr("员工角色无效。", "Invalid staff role."), "error")
            return render_template("admin/user_edit.html", user=user)
        if is_admin and not has_permission(actor, "assign_roles"):
            flash(tr("只有首席管理员可以分配员工角色。", "Only the chief admin can assign staff roles."), "error")
            return render_template("admin/user_edit.html", user=user)
        if is_admin and staff_role == "super_admin" and user.staff_role != "super_admin":
            flash(tr("首席管理员角色不能分配给其他账户。", "The chief admin role cannot be assigned to another account."), "error")
            return render_template("admin/user_edit.html", user=user)
        if user.staff_role == "super_admin" and (not is_admin or staff_role != "super_admin"):
            flash(tr("首席管理员角色不能在这里更改。", "The chief admin role cannot be changed here."), "error")
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
        if user.staff_role == "super_admin":
            user.is_admin = True
            user.staff_role = "super_admin"
        elif has_permission(actor, "assign_roles"):
            user.is_admin = is_admin
            user.staff_role = staff_role if is_admin else "customer"
        initialize_user_wallets(user)
        sync_primary_balance(user)
        db.session.commit()
        flash(tr(f"用户 {user.full_name} 已更新。", f"User {user.full_name} updated."), "success")
        return redirect(url_for("admin_user_detail", uid=uid))
    return render_template("admin/user_edit.html", user=user)


@app.route("/admin/users/<int:uid>/toggle-freeze", methods=["POST"])
@permission_required("manage_users")
def admin_toggle_freeze(uid):
    user = User.query.get_or_404(uid)
    if user.is_admin:
        flash(tr("不能冻结管理员账户。", "Admin accounts cannot be frozen."), "error")
        return redirect_to_local("admin_users")
    user.is_frozen = not user.is_frozen
    db.session.commit()
    flash(
        tr("账户已冻结。" if user.is_frozen else "账户已解冻。", "Account frozen." if user.is_frozen else "Account unfrozen."),
        "success",
    )
    return redirect_to_local("admin_user_detail", uid=uid)


@app.route("/admin/users/<int:uid>/toggle-active", methods=["POST"])
@permission_required("manage_users")
def admin_toggle_active(uid):
    user = User.query.get_or_404(uid)
    if user.is_admin:
        flash(tr("不能停用管理员账户。", "Admin accounts cannot be deactivated."), "error")
        return redirect_to_local("admin_users")
    user.is_active = not user.is_active
    db.session.commit()
    flash(
        tr("账户已重新启用。" if user.is_active else "账户已停用。", "Account reactivated." if user.is_active else "Account deactivated."),
        "success",
    )
    return redirect_to_local("admin_user_detail", uid=uid)


@app.route("/admin/users/<int:uid>/delete", methods=["POST"])
@permission_required("delete_users")
def admin_delete_user(uid):
    user = User.query.get_or_404(uid)
    if user.is_admin:
        flash(tr("不能删除员工账户。", "Staff accounts cannot be deleted here."), "error")
        return redirect(url_for("admin_users"))
    name = user.full_name
    LoginLog.query.filter_by(user_id=uid).delete()
    Transaction.query.filter_by(user_id=uid).delete()
    CurrencyBalance.query.filter_by(user_id=uid).delete()
    Notification.query.filter_by(user_id=uid).delete()
    LoanApplication.query.filter_by(user_id=uid).delete()
    KycDocument.query.filter_by(user_id=uid).delete()
    SupportMessage.query.filter_by(user_id=uid).delete()
    SupportMessage.query.filter_by(staff_user_id=uid).delete()
    db.session.delete(user)
    db.session.commit()
    flash(tr(f"用户 {name} 已删除。", f"User {name} permanently deleted."), "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:uid>/credit", methods=["POST"])
@permission_required("credit_users")
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
    create_transaction_record(uid, "credit", amount, currency, desc, "admin",
                              session.get("user_name","admin"), status="approved")
    send_email_notification(
        user,
        "账户已入账",
        "Account credited",
        f"您的账户已收到 {amount:,.2f} {currency}。说明：{desc}",
        f"Your account has been credited with {amount:,.2f} {currency}. Note: {desc}",
        "account",
    )
    db.session.commit()
    flash(tr("入账成功。", "Credit completed."), "success")
    return redirect(url_for("admin_user_detail", uid=uid))


@app.route("/admin/users/<int:uid>/debit", methods=["POST"])
@permission_required("credit_users")
def admin_debit(uid):
    user   = User.query.get_or_404(uid)
    amount = float(request.form.get("amount", 0))
    desc   = request.form.get("description","Admin debit").strip()
    currency = request.form.get("currency", user.currency).strip().upper()
    if amount <= 0 or currency not in CURRENCIES:
        flash(tr("请输入有效金额与币种。", "Enter a valid amount and currency."), "error")
        return redirect(url_for("admin_user_detail", uid=uid))
    wallet = get_or_create_currency_balance(user, currency)
    if wallet.amount < amount:
        flash(tr("余额不足。", "Insufficient balance."), "error")
        return redirect(url_for("admin_user_detail", uid=uid))
    wallet.amount -= amount
    sync_primary_balance(user)
    create_transaction_record(uid, "debit", amount, currency, desc, "admin",
                              session.get("user_name","admin"), status="approved")
    send_email_notification(
        user,
        "账户已扣款",
        "Account debited",
        f"您的账户已扣除 {amount:,.2f} {currency}。说明：{desc}",
        f"Your account has been debited by {amount:,.2f} {currency}. Note: {desc}",
        "account",
    )
    db.session.commit()
    flash(tr("出账成功。", "Debit completed."), "success")
    return redirect(url_for("admin_user_detail", uid=uid))


@app.route("/admin/users/create", methods=["GET","POST"])
@permission_required("manage_users")
def admin_create_user():
    actor = current_user()
    if request.method == "POST":
        full_name    = request.form.get("full_name","").strip()
        email        = request.form.get("email","").strip().lower()
        password     = request.form.get("password","")
        account_type = request.form.get("account_type","personal").strip().lower()
        phone        = request.form.get("phone","").strip()
        address      = request.form.get("address","").strip()
        currency     = request.form.get("currency","HUF").strip().upper()
        preferred_lang = request.form.get("preferred_lang", "zh").strip()
        is_admin = request.form.get("is_admin") == "on"
        staff_role = request.form.get("staff_role", "customer").strip()

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
        if staff_role not in {"customer", "support", "manager", "super_admin"}:
            flash(tr("员工角色无效。", "Invalid staff role."), "error")
            return render_template("admin/create_user.html", form=request.form)
        if is_admin and not has_permission(actor, "assign_roles"):
            flash(tr("只有首席管理员可以创建员工账户。", "Only the chief admin can create staff accounts."), "error")
            return render_template("admin/create_user.html", form=request.form)
        if is_admin and staff_role not in {"manager", "support"}:
            flash(tr("新员工账户只能分配为经理或客服。", "New staff accounts can only be created as manager or support."), "error")
            return render_template("admin/create_user.html", form=request.form)

        if User.query.filter_by(email=email).first():
            flash(tr("邮箱已存在。", "Email already exists."), "error")
            return render_template("admin/create_user.html", form=request.form)

        u = User(full_name=full_name, email=email, account_type=account_type,
                 account_no=gen_account_no(), phone=phone, address=address,
                 balance=balance, currency=currency, preferred_lang=preferred_lang if preferred_lang in LANGUAGES else "zh",
                 is_admin=is_admin if has_permission(actor, "assign_roles") else False,
                 staff_role=staff_role if is_admin and has_permission(actor, "assign_roles") and staff_role in {"manager", "support"} else "customer")
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        initialize_user_wallets(u, balance)
        create_transaction_record(u.id, "credit", balance, currency, "Opening balance", "admin",
                               session.get("user_name","admin"), status="approved")
        send_email_notification(
            u,
        "欢迎加入 BOCCEELTD",
        "Welcome to BOCCEELTD",
            f"您的账户 {u.account_no} 已由管理员创建。初始余额：{balance:,.2f} {currency}。",
            f"Your account {u.account_no} has been created by an administrator. Opening balance: {balance:,.2f} {currency}.",
            "welcome",
        )
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
@permission_required("review_transactions")
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
        send_email_notification(txn.user, "交易申请已批准", "Transaction request approved", f"您的交易 {txn.reference_no or txn.id} 已批准。", f"Your transaction {txn.reference_no or txn.id} has been approved.", "transfer")
        send_email_message(
            txn.user.email,
            "Transfer completed",
            (
                f"Your transfer {txn.reference_no or txn.id} has been completed successfully.\n"
                f"Amount: {txn.amount:,.2f} {txn.currency}\n"
                f"Status: Completed"
            ),
        )
    else:
        send_email_notification(txn.user, "交易申请被拒绝", "Transaction request rejected", f"您的交易 {txn.reference_no or txn.id} 被拒绝。", f"Your transaction {txn.reference_no or txn.id} has been rejected.", "transfer")
    db.session.commit()
    flash(tr("交易状态已更新。", "Transaction status updated."), "success")
    return redirect(url_for("admin_transactions"))


@app.route("/admin/logs")
@permission_required("view_logs")
def admin_logs():
    logs = LoginLog.query.order_by(LoginLog.timestamp.desc()).limit(100).all()
    return render_template("admin/logs.html", logs=logs)


@app.route("/admin/loans")
@admin_required
def admin_loans():
    loans = LoanApplication.query.order_by(LoanApplication.created_at.desc()).all()
    return render_template("admin/loans.html", loans=loans)


@app.route("/admin/loans/<int:loan_id>/review", methods=["POST"])
@permission_required("review_loans")
def admin_review_loan(loan_id):
    loan = LoanApplication.query.get_or_404(loan_id)
    status = request.form.get("status", "pending")
    if status in {"pending", "approved", "rejected"}:
        previous_status = loan.status
        loan.status = status
        loan.notes = request.form.get("notes", loan.notes).strip()
        if status == "approved" and previous_status != "approved":
            schedule = calculate_loan_schedule(loan.amount, loan.annual_rate, loan.term_months, datetime.utcnow())
            loan.monthly_payment = schedule[0]["payment"] if schedule else 0.0
            loan.approved_at = datetime.utcnow()
            wallet = get_or_create_currency_balance(loan.user, loan.user.currency)
            wallet.amount += loan.amount
            sync_primary_balance(loan.user)
            create_transaction_record(
                loan.user_id, "credit", loan.amount, loan.user.currency, "Loan disbursement",
                "loan_disbursement", session.get("user_name", "admin"), status="approved"
            )
        send_email_notification(loan.user, "贷款申请状态更新", "Loan application status updated", f"您的贷款申请状态已更新为：{status}。", f"Your loan application status has been updated to: {status}.", "loan")
        db.session.commit()
    flash(tr("贷款申请状态已更新。", "Loan application status updated."), "success")
    return redirect(url_for("admin_loans"))


@app.route("/admin/kyc")
@admin_required
def admin_kyc():
    docs = KycDocument.query.order_by(KycDocument.created_at.desc()).all()
    return render_template("admin/kyc.html", docs=docs)


@app.route("/admin/kyc/<int:doc_id>/review", methods=["POST"])
@permission_required("review_kyc")
def admin_review_kyc(doc_id):
    doc = KycDocument.query.get_or_404(doc_id)
    status = request.form.get("status", "pending")
    if status in {"pending", "approved", "rejected"}:
        doc.status = status
        doc.review_notes = request.form.get("review_notes", "").strip()
        doc.reviewed_at = datetime.utcnow()
        doc.reviewed_by_id = session.get("user_id")
        doc.user.kyc_status = status
        send_email_notification(doc.user, "KYC 审核状态更新", "KYC review status updated", f"您的 KYC 文件状态已更新为：{status}。", f"Your KYC document status has been updated to: {status}.", "kyc")
        db.session.commit()
    flash(tr("KYC 状态已更新。", "KYC status updated."), "success")
    return redirect(url_for("admin_kyc"))


@app.route("/admin/chat", methods=["GET", "POST"])
@permission_required("respond_chat")
def admin_chat():
    selected_user_id = request.args.get("user_id", type=int) or request.form.get("user_id", type=int)
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not selected_user_id:
            flash(tr("请选择会话。", "Please select a conversation."), "error")
            return redirect(url_for("admin_chat"))
        if not message:
            flash(tr("请输入消息内容。", "Please enter a message."), "error")
            return redirect(url_for("admin_chat", user_id=selected_user_id))
        db.session.add(SupportMessage(
            user_id=selected_user_id,
            staff_user_id=session["user_id"],
            sender_role=get_staff_role(current_user()),
            sender_name=session.get("user_name", "Staff"),
            message=message,
            is_read=True,
        ))
        db.session.commit()
        return redirect(url_for("admin_chat", user_id=selected_user_id))

    conversation_users = User.query.join(SupportMessage, SupportMessage.user_id == User.id).distinct().all()
    selected_user = User.query.get(selected_user_id) if selected_user_id else (conversation_users[0] if conversation_users else None)
    messages = []
    if selected_user:
        messages = SupportMessage.query.filter_by(user_id=selected_user.id).order_by(SupportMessage.created_at.asc()).all()
        SupportMessage.query.filter_by(user_id=selected_user.id, sender_role="customer", is_read=False).update({"is_read": True})
        db.session.commit()
    return render_template("admin/chat.html", conversation_users=conversation_users, selected_user=selected_user, messages=messages)


@app.route("/admin/platform-settings", methods=["GET", "POST"])
@permission_required("manage_platform_settings")
def admin_platform_settings():
    if request.method == "POST":
        try:
            referral_bonus = float(request.form.get("referral_bonus", get_referral_bonus()) or 0)
            rates = {currency: float(request.form.get(f"fx_{currency}", DEFAULT_REFERENCE_RATES[currency]) or DEFAULT_REFERENCE_RATES[currency]) for currency in CURRENCIES}
        except ValueError:
            flash(tr("请提供有效的数字设置。", "Please provide valid numeric settings."), "error")
            return redirect(url_for("admin_platform_settings"))
        set_app_setting("referral_bonus", referral_bonus)
        for currency, rate in rates.items():
            set_app_setting(f"fx_{currency}", rate)
        db.session.commit()
        flash(tr("平台设置已更新。", "Platform settings updated."), "success")
        return redirect(url_for("admin_platform_settings"))
    return render_template(
        "admin/platform_settings.html",
        referral_bonus=get_referral_bonus(),
        rates=get_reference_rates(),
        exchange_updated_at=get_exchange_updated_at(),
    )


# ─────────────────────────── CLI ───────────────────────────

@app.cli.command("init-db")
def init_db():
    ensure_schema()
    print("✅ Tables created.")

@app.cli.command("create-admin")
def create_admin():
    ensure_schema()
    if ensure_default_chief_admin():
        print(f"✅ Chief Admin created: {PRIMARY_CHIEF_ADMIN_EMAIL}")
    else:
        print("ℹ️  Chief Admin already exists.")


def get_default_admin_password():
    return os.environ.get("DEFAULT_ADMIN_PASSWORD", "Admin1234!")


def ensure_default_chief_admin():
    existing_admin = User.query.filter(
        (User.email == PRIMARY_CHIEF_ADMIN_EMAIL) | (User.account_no == "BOAC00000001")
    ).first()
    if existing_admin:
        if not existing_admin.is_admin or existing_admin.staff_role != "super_admin":
            existing_admin.is_admin = True
            existing_admin.is_active = True
            existing_admin.staff_role = "super_admin"
            if not existing_admin.email:
                existing_admin.email = PRIMARY_CHIEF_ADMIN_EMAIL
            db.session.commit()
        return False

    chief_admin = User(
        full_name="Chief Admin",
        email=PRIMARY_CHIEF_ADMIN_EMAIL,
        account_type="corporate",
        account_no="BOAC00000001",
        is_admin=True,
        is_active=True,
        currency="EUR",
        preferred_lang="en",
        staff_role="super_admin",
    )
    chief_admin.set_password(get_default_admin_password())
    db.session.add(chief_admin)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return False
    initialize_user_wallets(chief_admin, 0.0)
    db.session.commit()
    return True


def bootstrap_application():
    attempts = int(os.environ.get("DB_BOOTSTRAP_ATTEMPTS", "5"))
    delay_seconds = float(os.environ.get("DB_BOOTSTRAP_DELAY_SECONDS", "2"))
    for attempt in range(1, attempts + 1):
        try:
            with app.app_context():
                ensure_schema()
                ensure_default_chief_admin()
            return
        except OperationalError:
            app.logger.exception(
                "Database bootstrap failed on attempt %s/%s",
                attempt,
                attempts,
            )
            if attempt == attempts:
                raise
            time.sleep(delay_seconds)


bootstrap_application()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
