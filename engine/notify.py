"""
notify.py — sends Adi a short Hebrew summary after every workflow run (and an immediate alert on failure).

Channels (each optional; configure one or both via GitHub secrets):
  NTFY_TOPIC                         push notification to phone (ntfy.sh app, no account needed)
  MAIL_USERNAME + MAIL_APP_PASSWORD  email through Gmail SMTP (MAIL_TO optional, defaults to MAIL_USERNAME)
If neither is set, the message is just printed in the log.

Usage: python -m engine.notify <generate|seo|report> <status> <logfile>
  status = job status from GitHub (success / failure / cancelled)
"""
import os, re, sys, smtplib, urllib.request
from email.mime.text import MIMEText
from email.header import Header


def _lines(path):
    try:
        return open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except Exception:
        return []


def build(kind, status, log):
    L = _lines(log)
    run_url = os.environ.get("RUN_URL", "")
    out = []
    ok = status == "success"
    if kind == "generate":
        pushed = [re.search(r"pushed → (\S+)", l).group(1) for l in L if "pushed →" in l]
        failed = [l.strip() for l in L if "⚠ failed" in l]
        done = next((l for l in L if l.startswith("[done]")), "")
        total = re.search(r"Total completed: (\d+)", done)
        title = "Golden: pages run " + ("OK" if ok else "FAILED")
        out.append("✅ הרצת יצירת עמודים הסתיימה" if ok else "❌ הרצת יצירת עמודים נכשלה")
        out.append(f"מספר עמודים חדשים שנוצרו: {len(pushed)}")
        if total:
            out.append(f"סך הכל הושלמו: {total.group(1)}")
        for u in pushed:
            out.append(u)
        if failed:
            out.append(f"עמודים שנכשלו ({len(failed)}), ינסו שוב בהרצה הבאה:")
            out += failed[:5]
    elif kind == "seo":
        g = lambda p: next((l.strip() for l in L if p in l), "")
        title = "Golden: SEO loop " + ("OK" if ok else "FAILED")
        out.append("✅ לולאת ה-SEO השבועית הסתיימה" if ok else "❌ לולאת ה-SEO נכשלה")
        s = re.search(r"indexed (\d+)/(\d+)", g("[summary]"))
        if s:
            out.append(f"באינדקס של גוגל: {s.group(1)} מתוך {s.group(2)}")
        m = re.search(r"impressions (\d+) \(prev (\d+)\) clicks (\d+)", g("[gsc]"))
        if m:
            out.append(f"חשיפות: {m.group(1)} (קודם {m.group(2)}), קליקים: {m.group(3)}")
        ins = g("[insights]")
        if ins:
            out.append("ניתוח: " + ins.replace("[insights]", "").strip())
        ex = g("[expand]")
        if ex and "added 0" not in ex:
            out.append("נוספו מקומות חדשים למפה:")
            out.append(ex.replace("[expand]", "").strip())
        rl = g("[relink]")
        if "updated" in rl:
            out.append("קישורים פנימיים עודכנו: " + rl.replace("[relink]", "").strip())
        errs = [l.strip() for l in L if "[gsc] HTTP" in l or "HTTP 4" in l or "HTTP 5" in l]
        if errs:
            out.append("שגיאות מול גוגל:")
            out += errs[:3]
    else:
        title = "Golden: monthly report " + ("ready" if ok else "FAILED")
        out.append("✅ הדוח החודשי מוכן" if ok else "❌ בניית הדוח החודשי נכשלה")
        out.append("הקבצים בתיקיית הדוחות בריפו ובהרצה עצמה")
    if not ok:
        out.append("יש לבדוק את ההרצה:")
    if run_url:
        out.append(run_url)
    return title, "\n".join(out), ok


def send_ntfy(topic, title, body, urgent):
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), method="POST",
                                 headers={"Title": title, "Priority": "high" if urgent else "default",
                                          "Tags": "warning" if urgent else "white_check_mark"})
    urllib.request.urlopen(req, timeout=20).read()


def send_mail(user, pw, to, title, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"], msg["To"] = user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pw)
        s.send_message(msg)


def main():
    kind, status, log = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""
    title, body, ok = build(kind, status, log)
    print(title + "\n" + body)
    sent = False
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        try:
            send_ntfy(topic, title, body, not ok); sent = True; print("[notify] push sent")
        except Exception as e:
            print(f"[notify] push failed: {e}")
    u, p = os.environ.get("MAIL_USERNAME", "").strip(), os.environ.get("MAIL_APP_PASSWORD", "").strip()
    if u and p:
        try:
            send_mail(u, p, os.environ.get("MAIL_TO", "").strip() or u, title, body); sent = True
            print("[notify] email sent")
        except Exception as e:
            print(f"[notify] email failed: {e}")
    if not sent:
        print("[notify] no channel configured (set NTFY_TOPIC or MAIL_* secrets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
