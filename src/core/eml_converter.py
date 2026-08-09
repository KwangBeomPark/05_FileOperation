import html
import os
import sys
import tempfile
import logging
import subprocess
from email import policy
from email.parser import BytesParser

logger = logging.getLogger(__name__)

class EMLConverter:
    """
    EML 메일 파일을 HTML로 추출하고 Playwright를 사용하여
    고해상도 이미지(PNG)로 렌더링 및 캡처를 수행하는 코어 클래스.
    """

    def __init__(self, config_manager):
        """
        Args:
            config_manager: ConfigManager 인스턴스
        """
        self.config_manager = config_manager
        self.is_cancelled = False
        self.playwright_install_failed = False

    def cancel(self):
        """작업 취소 플래그 설정"""
        self.is_cancelled = True
        logger.info("EML conversion cancellation requested.")

    def extract_html_from_eml(self, eml_path: str) -> str:
        """
        EML 파일에서 HTML 혹은 text 본문을 추출합니다.
        
        Args:
            eml_path: EML 파일 경로
            
        Returns:
            str: HTML 내용 문자열
        """
        if not os.path.exists(eml_path):
            raise FileNotFoundError(f"EML 파일을 찾을 수 없습니다: {eml_path}")

        try:
            with open(eml_path, 'rb') as f:
                msg = BytesParser(policy=policy.default).parse(f)
        except Exception as e:
            raise Exception(f"EML 파일 파싱 오류: {str(e)}") from e

        html_content = None
        text_content = None

        # 이메일 본문 탐색 (멀티파트 구조 포함)
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # 첨부파일 파트는 이미지화 대상에서 제외
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/html":
                    try:
                        html_content = part.get_content()
                        break
                    except Exception as e:
                        logger.error(f"HTML 파트 추출 중 오류: {e}")
                elif content_type == "text/plain" and text_content is None:
                    try:
                        text_content = part.get_content()
                    except Exception as e:
                        logger.error(f"Text 파트 추출 중 오류: {e}")
        else:
            # 단일 파트 구조
            content_type = msg.get_content_type()
            if content_type == "text/html":
                html_content = msg.get_content()
            elif content_type == "text/plain":
                text_content = msg.get_content()

        # 결과 조립 및 포맷팅
        if html_content:
            return html_content
        elif text_content:
            # 텍스트만 있는 경우 HTML 템플릿으로 감싸 줄바꿈과 폰트 유지
            escaped_text = html.escape(text_content)
            return f"""
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ 
                        font-family: 'Malgun Gothic', sans-serif; 
                        padding: 30px; 
                        white-space: pre-wrap; 
                        line-height: 1.6;
                        color: #333333;
                    }}
                </style>
            </head>
            <body>{escaped_text}</body>
            </html>
            """
        else:
            return "<html><body><h1>본문을 찾을 수 없습니다.</h1></body></html>"

    def install_playwright_browsers(self):
        """
        Playwright 브라우저 바이너리(Chromium)를 백그라운드로 안전하게 설치합니다.
        네트워크 미연결 시 예외를 남깁니다.
        """
        logger.info("Installing Playwright Chromium browser...")
        try:
            # Frozen EXE에서는 bundled Playwright driver를 직접 호출합니다.
            command, env = self._get_playwright_install_command()
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            logger.info("Playwright Chromium browser installed successfully.")
        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to auto-install Playwright chromium browser. stdout=%s stderr=%s",
                e.stdout,
                e.stderr,
            )
            raise Exception("메일 이미지 변환용 브라우저 구성 요소를 자동으로 준비하지 못했습니다. 네트워크 연결 상태를 확인해 주세요.") from e
        except Exception as e:
            logger.error(f"Failed to auto-install Playwright chromium browser: {e}")
            raise Exception("메일 이미지 변환용 브라우저 구성 요소를 자동으로 준비하지 못했습니다. 네트워크 연결 상태를 확인해 주세요.") from e

    def _get_playwright_install_command(self):
        try:
            from playwright._impl._driver import compute_driver_executable, get_driver_env

            node_path, cli_path = compute_driver_executable()
            if os.path.exists(node_path) and os.path.exists(cli_path):
                return [node_path, cli_path, "install", "chromium"], get_driver_env()
        except Exception as driver_err:
            logger.warning(f"Failed to resolve Playwright bundled driver: {driver_err}")

        if getattr(sys, "frozen", False):
            raise FileNotFoundError("Bundled Playwright driver was not found in the frozen application.")

        return [sys.executable, "-m", "playwright", "install", "chromium"], os.environ.copy()

    def convert_eml_to_image(self, eml_path: str, output_path: str, width: int = 1024) -> bool:
        """
        EML 파일을 로드하여 렌더링하고 스크린샷 이미지로 저장합니다.
        
        Args:
            eml_path: 대상 EML 파일 경로
            output_path: 저장할 PNG 이미지 파일 경로
            width: 브라우저 뷰포트 너비
            
        Returns:
            bool: 성공 여부
        """
        if (
            self.config_manager.get("eml_incremental", True)
            and os.path.exists(eml_path)
            and os.path.exists(output_path)
            and os.path.getmtime(output_path) >= os.path.getmtime(eml_path)
        ):
            logger.info(f"Skipping unchanged EML: {eml_path}")
            return True

        from playwright.sync_api import sync_playwright
        
        # 1. HTML 추출 및 임시 저장
        html_content = self.extract_html_from_eml(eml_path)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html', encoding='utf-8') as tmp_file:
            tmp_file.write(html_content)
            tmp_path = tmp_file.name

        browser = None
        try:
            with sync_playwright() as p:
                custom_browser_path = self.config_manager.get('offline_chromium_path', '')
                
                launch_kwargs = {"headless": True}
                if custom_browser_path and os.path.exists(custom_browser_path):
                    launch_kwargs["executable_path"] = custom_browser_path
                    logger.info(f"Using custom chromium binary path: {custom_browser_path}")

                try:
                    browser = p.chromium.launch(**launch_kwargs)
                except Exception as browser_err:
                    if "Executable doesn't exist" in str(browser_err) or "playwright install" in str(browser_err):
                        if self.playwright_install_failed:
                            raise Exception("메일 이미지 변환용 브라우저 구성 요소가 없고 이전 준비 시도도 실패했습니다. 인터넷 연결 또는 오프라인 브라우저 설정을 확인하세요.") from browser_err
                        
                        logger.warning("Chromium executable not found. Attempting automatic installation...")
                        try:
                            self.install_playwright_browsers()
                        except Exception as inst_err:
                            self.playwright_install_failed = True
                            raise inst_err
                        browser = p.chromium.launch(**launch_kwargs)
                    else:
                        raise browser_err

                try:
                    page = browser.new_page()
                    page.set_viewport_size({"width": width, "height": 800})

                    file_url = f"file:///{os.path.abspath(tmp_path).replace(os.sep, '/')}"
                    page.goto(file_url)
                    page.wait_for_timeout(1000)
                    page.screenshot(path=output_path, full_page=True)
                    logger.info(f"EML successfully converted to image: {output_path}")
                    return True
                finally:
                    if browser:
                        try:
                            browser.close()
                        except Exception as close_err:
                            logger.error(f"Failed to close playwright browser: {close_err}")

        except Exception as e:
            logger.error(f"Error during EML to Image conversion for '{eml_path}': {e}")
            raise e
        finally:
            # 임시 파일 자원 수거
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
