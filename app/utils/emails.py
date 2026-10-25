from flask_mail import Message
from app.extensions import mail
from flask import current_app

def send_reset_email(to, subject, body):
    msg = Message(
        subject,
        recipients=[to],
        body=body
    )
    mail.send(msg)
