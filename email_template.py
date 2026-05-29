from datetime import datetime

from jinja2 import Template


LOGIN_EMAIL_TEMPLATE = Template(
    """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:Arial,Helvetica,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;padding:30px 0;">
  <tr>
    <td align="center">
      <table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #ddd;">

        <tr>
          <td style="background:#c40000;height:4px;font-size:0;">&nbsp;</td>
        </tr>

        <tr>
          <td style="background:#fff;padding:0;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="60" style="padding:16px 0 16px 20px;vertical-align:middle;">
                  <div style="width:50px;height:50px;background:#c40000;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:bold;text-align:center;line-height:1.3;">
                    BOAC<br>CEE<br>LTD
                  </div>
                </td>
                <td style="padding:16px 10px;vertical-align:middle;">
                  <div style="font-size:20px;font-weight:bold;color:#c40000;letter-spacing:0.5px;line-height:1;">
                    Boacceeltd
                  </div>
                  <div style="font-size:11px;color:#888;margin-top:3px;">
                    (Central and Eastern Europe) Limited
                  </div>
                </td>
                <td align="right" style="padding:16px 20px;vertical-align:middle;">
                  <div style="font-size:11px;color:#888;">Customer Care</div>
                  <div style="font-size:13px;font-weight:bold;color:#c40000;">
                    cs@bocceeltd.vip
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="background:#c40000;padding:8px 20px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-size:12px;color:#fff;font-weight:bold;letter-spacing:0.5px;">
                  SECURITY NOTICE &nbsp;›&nbsp; LOGIN ALERT
                </td>
                <td align="right" style="font-size:11px;color:rgba(255,255,255,0.8);">
                  {{ now.strftime('%d %B %Y') }}
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:28px 28px 20px;">
            <p style="margin:0 0 16px;font-size:14px;color:#333;">
              Dear <strong>{{ user.full_name }}</strong>,
            </p>

            <p style="margin:0 0 20px;font-size:13px;color:#555;line-height:1.8;">
              We are writing to inform you that a new login was detected on your
              <strong>Boacceeltd Online Banking</strong> account. Please review
              the details below. If you performed this login, no action is required.
            </p>

            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#fafafa;border:1px solid #e5e5e5;border-left:4px solid #c40000;margin-bottom:20px;">
              <tr>
                <td style="padding:16px 18px;">
                  <div style="font-size:12px;font-weight:bold;color:#c40000;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">
                    Login Details
                  </div>
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td width="140" style="font-size:12px;color:#888;padding:4px 0;vertical-align:top;">
                        Date &amp; Time:
                      </td>
                      <td style="font-size:13px;color:#333;font-weight:600;padding:4px 0;">
                        {{ now.strftime('%d %B %Y at %H:%M:%S UTC') }}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;color:#888;padding:4px 0;vertical-align:top;">
                        IP Address:
                      </td>
                      <td style="font-size:13px;color:#333;font-weight:600;padding:4px 0;">
                        {{ ip }}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;color:#888;padding:4px 0;vertical-align:top;">
                        Account Number:
                      </td>
                      <td style="font-size:13px;color:#c40000;font-weight:700;padding:4px 0;letter-spacing:1px;">
                        {{ user.account_no }}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;color:#888;padding:4px 0;vertical-align:top;">
                        Account Type:
                      </td>
                      <td style="font-size:13px;color:#333;font-weight:600;padding:4px 0;text-transform:capitalize;">
                        {{ user.account_type }} Banking
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;color:#888;padding:4px 0;vertical-align:top;">
                        Status:
                      </td>
                      <td style="padding:4px 0;">
                        <span style="background:#e8f5e9;color:#2e7d32;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600;">
                          ✓ Successful Login
                        </span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <table width="100%" cellpadding="0" cellspacing="0" style="background:#fff8f8;border:1px solid #ffcdd2;margin-bottom:24px;">
              <tr>
                <td style="padding:14px 18px;">
                  <div style="font-size:13px;color:#c62828;font-weight:bold;margin-bottom:6px;">
                    If you did not perform this login:
                  </div>
                  <ul style="margin:0;padding-left:18px;font-size:12px;color:#555;line-height:1.8;">
                    <li>Contact our customer care immediately</li>
                    <li>Change your password as soon as possible</li>
                    <li>Do not share your password with anyone</li>
                  </ul>
                </td>
              </tr>
            </table>

            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
              <tr>
                <td align="center">
                  <a href="https://bocceeltd.vip/dashboard"
                     style="display:inline-block;background:#c40000;color:#fff;padding:12px 36px;text-decoration:none;font-size:13px;font-weight:bold;letter-spacing:0.5px;">
                    VIEW MY ACCOUNT
                  </a>
                  &nbsp;&nbsp;
                  <a href="mailto:cs@bocceeltd.vip"
                     style="display:inline-block;background:#fff;color:#c40000;padding:11px 36px;text-decoration:none;font-size:13px;font-weight:bold;letter-spacing:0.5px;border:1px solid #c40000;">
                    CONTACT SUPPORT
                  </a>
                </td>
              </tr>
            </table>

            <hr style="border:none;border-top:1px solid #eee;margin:0 0 18px;"/>

            <p style="margin:0;font-size:12px;color:#888;line-height:1.7;">
              This is an automated security notification from Boacceeltd
              (Central and Eastern Europe) Limited. Please do not reply to
              this email. For assistance, contact us at
              <a href="mailto:cs@bocceeltd.vip" style="color:#c40000;">cs@bocceeltd.vip</a>.
            </p>
          </td>
        </tr>

        <tr>
          <td style="background:#f7f7f7;border-top:1px solid #eee;padding:14px 28px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-size:11px;color:#888;line-height:1.7;">
                  <strong style="color:#555;">Head Office:</strong>
                  Jozsef Nador ter 7, 1051 Budapest, Hungary<br/>
                  <strong style="color:#555;">Vienna Branch:</strong>
                  Boerseplatz 6, A-1010 Vienna, Austria<br/>
                  <strong style="color:#555;">Prague Branch:</strong>
                  Namesti Republiky 1, Prague, Czech Republic
                </td>
                <td align="right" style="font-size:11px;color:#888;vertical-align:top;line-height:1.7;">
                  <strong style="color:#555;">Swift:</strong> BKCHATWWXXX
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="background:#c40000;height:3px;font-size:0;">&nbsp;</td>
        </tr>

      </table>
    </td>
  </tr>
</table>

</body>
</html>
"""
)


def build_login_email_html(user, ip, now=None):
    return LOGIN_EMAIL_TEMPLATE.render(user=user, ip=ip, now=now or datetime.utcnow())
