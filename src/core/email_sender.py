import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.utils.logger import get_logger

logger = get_logger()

def send_email(
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_password: str,
    receiver_emails: list,
    subject: str,
    body_text: str,
    is_html: bool = False
) -> tuple[bool, str]:
    """
    SMTP 서버를 활용하여 이메일을 발송합니다.
    
    Args:
        smtp_server: SMTP 서버 주소
        smtp_port: 포트 번호 (예: 465, 587)
        sender_email: 발신자 이메일 주소
        sender_password: ConfigManager에서 복호화된 발신자 비밀번호/앱 비밀번호
        receiver_emails: 수신자 이메일 주소 리스트 (또는 단일 주소 스트링)
        subject: 이메일 제목
        body_text: 이메일 본문
        is_html: 본문 형식을 HTML로 할지 여부
        
    Returns:
        (success: bool, message: str)
    """
    if not smtp_server or not sender_email or not receiver_emails:
        return False, "필수 이메일 발송 설정 항목이 누락되었습니다."
        
    # 수신자 목록 정규화
    if isinstance(receiver_emails, str):
        # 쉼표나 세미콜론 등으로 구분된 경우 분할
        receiver_emails = [
            r.strip() 
            for r in receiver_emails.replace(';', ',').split(',') 
            if r.strip()
        ]
        
    if not receiver_emails:
        return False, "수신자 이메일 주소가 비어있습니다."
        
    # 메일 메시지 작성
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = ", ".join(receiver_emails)
    msg['Subject'] = subject
    
    # 본문 첨부
    msg.attach(MIMEText(body_text, 'html' if is_html else 'plain', 'utf-8'))
    
    server = None
    try:
        # 465 포트는 대개 SSL 전용
        if smtp_port == 465:
            logger.info(f"Connecting to SMTP server {smtp_server}:{smtp_port} via SSL...")
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        else:
            logger.info(f"Connecting to SMTP server {smtp_server}:{smtp_port} via TLS...")
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            # EHLO 전송 및 STARTTLS 수행
            server.ehlo()
            server.starttls()
            server.ehlo()
            
        # 로그인 및 발송
        if sender_password:
            logger.info("Attempting SMTP login...")
            server.login(sender_email, sender_password)
            
        logger.info(f"Sending email to {receiver_emails}...")
        server.sendmail(sender_email, receiver_emails, msg.as_string())
        logger.info("Email sent successfully.")
        return True, "이메일이 성공적으로 전송되었습니다."
        
    except smtplib.SMTPAuthenticationError:
        err_msg = "SMTP 인증에 실패했습니다. 이메일 주소 또는 비밀번호(앱 비밀번호)를 확인하세요."
        logger.error(err_msg)
        return False, err_msg
    except Exception as e:
        err_msg = f"이메일 전송 중 에러가 발생했습니다: {e!s}"
        logger.error(err_msg)
        return False, err_msg
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass
