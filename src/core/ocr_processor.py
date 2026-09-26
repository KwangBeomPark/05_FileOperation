import pytesseract
from PIL import Image
import re
import os

from src.core.windows_ocr import extract_text_with_windows_ocr, windows_ocr_available

class OCRProcessor:
    """이미지에서 텍스트를 추출하고 프로모션 번호를 찾는 클래스.

    Tesseract를 우선 사용하고, 설치되어 있지 않거나 실행에 실패하면 Windows
    내장 OCR(Windows.Media.Ocr)로 폴백합니다.
    """
    
    def __init__(self, config_manager):
        """
        Args:
            config_manager: ConfigManager 인스턴스
        """
        self.config_manager = config_manager
        self.setup_tesseract()
        
    def setup_tesseract(self):
        """Tesseract 경로 설정"""
        tesseract_path = self.config_manager.get('tesseract_path', '')
        
        if tesseract_path and os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        else:
            # 기본 경로 시도 (Windows)
            default_paths = [
                r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            ]
            
            for path in default_paths:
                if os.path.exists(path):
                    pytesseract.pytesseract.tesseract_cmd = path
                    # 설정에 저장
                    self.config_manager.set('tesseract_path', path)
                    break
    
    def check_tesseract_installed(self):
        """Tesseract 설치 여부 확인
        
        Returns:
            bool: 설치되어 있으면 True
        """
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def check_windows_ocr_available(self):
        ok, _detail = windows_ocr_available()
        return ok

    def check_ocr_available(self):
        return self.check_tesseract_installed() or self.check_windows_ocr_available()

    def describe_available_ocr(self):
        if self.check_tesseract_installed():
            return "Tesseract OCR 사용 가능"
        ok, detail = windows_ocr_available()
        if ok:
            return "Windows 내장 OCR fallback 사용 가능"
        return f"사용 가능한 OCR 엔진이 없습니다: {detail}"
    
    def extract_text(self, image_path):
        """이미지에서 텍스트 추출
        
        Args:
            image_path: 이미지 파일 경로
            
        Returns:
            str: 추출된 텍스트
            
        Raises:
            Exception: OCR 실패 시
        """
        errors = []

        if self.check_tesseract_installed():
            try:
                with Image.open(image_path) as image:
                    text = pytesseract.image_to_string(image, lang='eng')
                return text.strip()
            except Exception as e:
                errors.append(f"Tesseract 실패: {e}")

        try:
            text = extract_text_with_windows_ocr(image_path)
            return text.strip()
        except Exception as e:
            errors.append(f"Windows OCR 실패: {e}")

        raise Exception("OCR 텍스트 추출 실패: " + " / ".join(errors))
    
    EXTRACTION_PRESETS = {
        "promotion": r"PL-[A-Z]TS[A-Z]-202\d{5}-\d{4}",
        "invoice_number": r"\b(?:INVOICE|INV|DOC|NO|번호)[ \t#:._-]*([A-Z0-9-]*\d[A-Z0-9-]{2,24})",
        "date_ymd": r"(20\d{2}[-./]\d{2}[-./]\d{2})",
        "digits": r"\b(\d{6,16})\b",
    }

    @staticmethod
    def sanitize_filename_token(token: str, max_len: int = 80) -> str:
        """Windows 파일명에 사용할 수 없는 특수문자를 안전하게 정제합니다."""
        cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(token or "")).strip()
        cleaned = re.sub(r"\s+", "_", cleaned).strip("._-")
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rstrip("._-")
        return cleaned

    def find_promotion_number(self, text):
        """텍스트에서 프로모션 번호 찾기
        
        Args:
            text: 검색할 텍스트
            
        Returns:
            str or None: 찾은 프로모션 번호, 없으면 None
        """
        pattern = self.config_manager.get('promotion_regex', self.EXTRACTION_PRESETS["promotion"])
        try:
            match = re.search(pattern, text)
        except re.error as e:
            # 설정된 정규식이 잘못되었을 경우 에러 로깅 후 기본 정규식으로 폴백
            from src.utils.logger import get_logger
            get_logger().error(f"Invalid regex pattern '{pattern}' in configuration: {e}. Falling back to default pattern.")
            default_pattern = self.EXTRACTION_PRESETS["promotion"]
            try:
                match = re.search(default_pattern, text)
            except re.error:
                match = None
                
        if match:
            return match.group(0)
        else:
            return None

    def extract_by_rule(self, text: str, rule_mode: str = "promotion", custom_pattern: str = "") -> str | None:
        """지정된 추출 규칙(프리셋 또는 커스텀 정규식)에 따라 텍스트에서 핵심 키워드를 추출합니다."""
        mode = (rule_mode or "promotion").strip()
        if mode == "promotion" and not custom_pattern:
            return self.find_promotion_number(text)

        if mode == "full_text_txt":
            return "TEXT_EXTRACTED" if (text and text.strip()) else None

        if mode == "first_line":
            for line in (text or "").splitlines():
                token = self.sanitize_filename_token(line, max_len=45)
                if token:
                    return token
            return None

        pattern = custom_pattern.strip() if mode == "custom_regex" and custom_pattern.strip() else self.EXTRACTION_PRESETS.get(mode, custom_pattern.strip() or self.EXTRACTION_PRESETS["promotion"])
        try:
            match = re.search(pattern, text or "", re.IGNORECASE)
        except re.error as e:
            from src.utils.logger import get_logger
            get_logger().error(f"Invalid regex pattern '{pattern}' for mode '{mode}': {e}")
            return None

        if not match:
            return None
        raw_val = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
        return self.sanitize_filename_token(raw_val) or None

    @classmethod
    def format_rename_filename(
        cls,
        image_path: str,
        extracted_value: str,
        rename_template: str = "{match}",
        seq: int = 1,
        now_date: str | None = None,
    ) -> str:
        """변수 템플릿({match}, {original}, {date}, {seq})을 바탕으로 새 파일명(확장자 포함)을 생성합니다."""
        from datetime import datetime

        orig_basename = os.path.basename(image_path)
        orig_stem, ext = os.path.splitext(orig_basename)
        safe_match = cls.sanitize_filename_token(extracted_value) or orig_stem
        date_str = now_date or datetime.now().strftime("%Y%m%d")
        seq_str = f"{max(1, int(seq)):03d}"

        template = (rename_template or "{match}").strip()
        if not template:
            template = "{match}"

        rendered = (
            template.replace("{match}", safe_match)
            .replace("{promo}", safe_match)
            .replace("{original}", orig_stem)
            .replace("{date}", date_str)
            .replace("{seq}", seq_str)
        )
        rendered = cls.sanitize_filename_token(rendered, max_len=120) or safe_match
        if rendered.lower().endswith(ext.lower()):
            return rendered
        return f"{rendered}{ext}"

    @staticmethod
    def export_text_file(image_path: str, extracted_text: str) -> str:
        """추출된 OCR 전문을 이미지와 같은 위치의 .txt 파일로 저장합니다."""
        stem, _ = os.path.splitext(image_path)
        txt_path = f"{stem}.txt"
        with open(txt_path, "w", encoding="utf-8") as fp:
            fp.write(extracted_text or "")
        return txt_path

    def process_image(
        self,
        image_path: str,
        rule_mode: str | None = None,
        custom_pattern: str | None = None,
        export_txt: bool = False,
    ):
        """이미지 처리: 텍스트 추출 + 규칙 기반 값 추출 (하위 호환 보장)
        
        Args:
            image_path: 이미지 파일 경로
            rule_mode: 추출 규칙 모드 (None이면 설정값 또는 'promotion')
            custom_pattern: 사용자 정의 정규식 패턴
            export_txt: 추출된 전문을 .txt 파일로 함께 저장할지 여부
            
        Returns:
            tuple: (success, extracted_value, extracted_text, error_message)
        """
        try:
            text = self.extract_text(image_path)
            effective_mode = rule_mode or self.config_manager.get("ocr_rule_mode", "promotion")
            effective_pattern = (
                custom_pattern
                if custom_pattern is not None
                else self.config_manager.get("ocr_custom_pattern", "")
            )
            should_export_txt = bool(export_txt or effective_mode == "full_text_txt" or self.config_manager.get("ocr_export_txt", False))

            if should_export_txt:
                self.export_text_file(image_path, text)

            if effective_mode == "full_text_txt":
                orig_stem, _ = os.path.splitext(os.path.basename(image_path))
                return (True, orig_stem, text, None)

            extracted_val = self.extract_by_rule(text, effective_mode, effective_pattern)
            if extracted_val:
                return (True, extracted_val, text, None)
            else:
                return (False, None, text, "프로모션 번호를 찾을 수 없습니다")
        except Exception as e:
            return (False, None, "", str(e))


EXTRACTION_PRESETS = OCRProcessor.EXTRACTION_PRESETS
sanitize_filename_token = OCRProcessor.sanitize_filename_token
export_text_file = OCRProcessor.export_text_file


def extract_by_rule(text: str, rule_mode: str = "promotion", custom_pattern: str = "") -> str | None:
    mode = (rule_mode or "promotion").strip()
    if mode == "full_text_txt":
        return sanitize_filename_token(" ".join((text or "").split()), max_len=60) if (text and text.strip()) else None

    if mode == "first_line":
        for line in (text or "").splitlines():
            token = sanitize_filename_token(line, max_len=45)
            if token:
                return token
        return None

    if mode == "promotion" and not custom_pattern:
        pattern = r"PL-[A-Z]TS[A-Z]-202\d{5}-\d{4}|\b202\d{5}-\d{4}\b|\b\d{6}-\d{2}\b"
    elif mode == "custom_regex" and custom_pattern.strip():
        pattern = custom_pattern.strip()
    else:
        pattern = EXTRACTION_PRESETS.get(mode, EXTRACTION_PRESETS["promotion"])

    try:
        match = re.search(pattern, text or "", re.IGNORECASE)
    except re.error:
        return None

    if not match:
        return None
    raw_val = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
    return sanitize_filename_token(raw_val) or None


def format_rename_filename(
    rename_template: str,
    original_filename: str,
    match_token: str,
    seq_index: int = 1,
    now_date: str | None = None,
) -> str:
    return OCRProcessor.format_rename_filename(
        image_path=original_filename,
        extracted_value=match_token,
        rename_template=rename_template,
        seq=seq_index,
        now_date=now_date,
    )
