from flask import current_app
from flask_mail import Message
from app.extensions import mail


# ── Helper ────────────────────────────────────────────────────────────────────

def _send(subject, recipients, body_text, body_html=None):
    """
    Internal send helper.
    All public functions route through here.
    Failures are logged but never re-raised —
    email never blocks a DB operation.
    """
    try:
        msg = Message(
            subject    = subject,
            recipients = recipients if isinstance(recipients, list)
                         else [recipients],
            body       = body_text,
            html       = body_html,
        )
        mail.send(msg)
        print(f"[EMAIL] Sent '{subject}' → {recipients}")
    except Exception as e:
        print(f"[EMAIL] Failed to send '{subject}' → {recipients}: {e}")


# ── 1. Checkout confirmation ──────────────────────────────────────────────────

def send_checkout_email(member, txn, book):
    """
    Sent immediately after a successful checkout.
    """
    subject = f"Checkout Confirmed — {book.title}"

    body_text = f"""
Hi {member.full_name},

You have successfully checked out the following book:

  Title      : {book.title}
  Author     : {book.author}
  Copy Code  : {txn.book_copy_id}
  Txn Code   : {txn.txn_code}
  Due Date   : {txn.due_date.strftime("%d %B %Y")}

Please return the book by the due date to avoid fines.
Late returns are charged ₹5 per day (max ₹100 per book).

Member Code : {member.member_code}
Library     : Central Branch

Thank you!
Central Branch Library
""".strip()

    body_html = f"""
<p>Hi <strong>{member.full_name}</strong>,</p>
<p>You have successfully checked out the following book:</p>
<table style="border-collapse:collapse;">
  <tr><td style="padding:4px 12px;"><strong>Title</strong></td>
      <td style="padding:4px 12px;">{book.title}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Author</strong></td>
      <td style="padding:4px 12px;">{book.author}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Transaction</strong></td>
      <td style="padding:4px 12px;">{txn.txn_code}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Due Date</strong></td>
      <td style="padding:4px 12px;color:#e53e3e;">
          <strong>{txn.due_date.strftime("%d %B %Y")}</strong></td></tr>
</table>
<p>Please return the book by the due date to avoid fines.<br>
Late returns are charged <strong>₹5 per day</strong>
(max <strong>₹100</strong> per book).</p>
<p>Member Code: <strong>{member.member_code}</strong></p>
<p>Thank you!<br>Central Branch Library</p>
""".strip()

    _send(subject, member.email, body_text, body_html)


# ── 2. Return confirmation ────────────────────────────────────────────────────

def send_return_email(member, txn, book, fine_created=False):
    """
    Sent after a successful book return.
    If a fine was created, the email mentions it.
    """
    subject = f"Book Returned — {book.title}"

    fine_note_text = ""
    fine_note_html = ""
    if fine_created:
        fine_note_text = (
            "\nNote: This book was returned overdue. "
            "A fine has been added to your account. "
            "Please log in to your member portal to view and pay your fine.\n"
        )
        fine_note_html = """
<p style="color:#e53e3e;">
  <strong>Note:</strong> This book was returned overdue.
  A fine has been added to your account.
  Please log in to your member portal to view and pay your fine.
</p>
"""

    body_text = f"""
Hi {member.full_name},

You have successfully returned the following book:

  Title      : {book.title}
  Author     : {book.author}
  Txn Code   : {txn.txn_code}
  Returned At: {txn.returned_at.strftime("%d %B %Y, %I:%M %p")}
{fine_note_text}
Thank you for returning the book!
Central Branch Library
""".strip()

    body_html = f"""
<p>Hi <strong>{member.full_name}</strong>,</p>
<p>You have successfully returned the following book:</p>
<table style="border-collapse:collapse;">
  <tr><td style="padding:4px 12px;"><strong>Title</strong></td>
      <td style="padding:4px 12px;">{book.title}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Author</strong></td>
      <td style="padding:4px 12px;">{book.author}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Transaction</strong></td>
      <td style="padding:4px 12px;">{txn.txn_code}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Returned At</strong></td>
      <td style="padding:4px 12px;">
          {txn.returned_at.strftime("%d %B %Y, %I:%M %p")}</td></tr>
</table>
{fine_note_html}
<p>Thank you for returning the book!<br>Central Branch Library</p>
""".strip()

    _send(subject, member.email, body_text, body_html)


# ── 3. Overdue reminder ───────────────────────────────────────────────────────

def send_overdue_email(member, fine, days_overdue):
    """
    Sent by the daily cron for each newly fined overdue transaction.
    """
    subject = "Overdue Book Notice — Fine Applied"

    body_text = f"""
Hi {member.full_name},

This is a reminder that you have an overdue book.

  Days Overdue : {days_overdue} day(s)
  Fine Amount  : ₹{float(fine.amount):.2f}
  Fine Code    : {fine.fine_code}
  Fine Status  : {fine.status}

Please return the book and clear your fine at the earliest.
You can pay your fine online via the member portal.

Outstanding Balance : ₹{float(member.current_fines):.2f}
Member Code         : {member.member_code}

Central Branch Library
""".strip()

    body_html = f"""
<p>Hi <strong>{member.full_name}</strong>,</p>
<p>This is a reminder that you have an <strong>overdue book</strong>.</p>
<table style="border-collapse:collapse;">
  <tr><td style="padding:4px 12px;"><strong>Days Overdue</strong></td>
      <td style="padding:4px 12px;color:#e53e3e;">
          <strong>{days_overdue} day(s)</strong></td></tr>
  <tr><td style="padding:4px 12px;"><strong>Fine Amount</strong></td>
      <td style="padding:4px 12px;">₹{float(fine.amount):.2f}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Fine Code</strong></td>
      <td style="padding:4px 12px;">{fine.fine_code}</td></tr>
</table>
<p>Please return the book and clear your fine at the earliest.<br>
You can pay your fine online via the <strong>member portal</strong>.</p>
<p>Outstanding Balance: <strong>₹{float(member.current_fines):.2f}</strong></p>
<p>Central Branch Library</p>
""".strip()

    _send(subject, member.email, body_text, body_html)


# ── 4. Payment receipt ────────────────────────────────────────────────────────

def send_receipt_email(member, payment, fine):
    """
    Sent after a successful Razorpay payment.
    """
    subject = f"Payment Receipt — {payment.payment_code}"

    body_text = f"""
Hi {member.full_name},

Your fine payment has been received successfully.

  Receipt No     : {payment.receipt_number}
  Payment Code   : {payment.payment_code}
  Amount Paid    : ₹{float(payment.amount):.2f}
  Payment Date   : {payment.payment_date.strftime("%d %B %Y, %I:%M %p")}
  Razorpay ID    : {payment.razorpay_payment_id}
  Fine Code      : {fine.fine_code}
  Fine Status    : {fine.status}

Outstanding Balance : ₹{float(member.current_fines):.2f}
Member Code         : {member.member_code}

Thank you for your payment!
Central Branch Library
""".strip()

    body_html = f"""
<p>Hi <strong>{member.full_name}</strong>,</p>
<p>Your fine payment has been received successfully.</p>
<table style="border-collapse:collapse;">
  <tr><td style="padding:4px 12px;"><strong>Receipt No</strong></td>
      <td style="padding:4px 12px;">
          <strong>{payment.receipt_number}</strong></td></tr>
  <tr><td style="padding:4px 12px;"><strong>Amount Paid</strong></td>
      <td style="padding:4px 12px;">
          <strong>₹{float(payment.amount):.2f}</strong></td></tr>
  <tr><td style="padding:4px 12px;"><strong>Payment Date</strong></td>
      <td style="padding:4px 12px;">
          {payment.payment_date.strftime("%d %B %Y, %I:%M %p")}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Razorpay ID</strong></td>
      <td style="padding:4px 12px;">{payment.razorpay_payment_id}</td></tr>
  <tr><td style="padding:4px 12px;"><strong>Fine Code</strong></td>
      <td style="padding:4px 12px;">{fine.fine_code}</td></tr>
</table>
<p>Outstanding Balance:
   <strong>₹{float(member.current_fines):.2f}</strong></p>
<p>Thank you for your payment!<br>Central Branch Library</p>
""".strip()

    _send(subject, member.email, body_text, body_html)