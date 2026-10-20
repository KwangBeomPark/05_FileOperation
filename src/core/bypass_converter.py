import os
import shutil
import zipfile
import base64
import html
import ctypes
from ctypes import wintypes
import logging
from send2trash import send2trash

from src.core.task_contracts import SourceDisposition
from src.core.backup_recovery import record_backup_move

logger = logging.getLogger(__name__)

MAX_PDF_HTML_SIZE_BYTES = 50 * 1024 * 1024  # 50MB 상한 (브라우저 메모리 폭증 방지)

HTML_VIEWER_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{doc_title}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{ width: 100%; height: 100%; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #1e1e1e; color: #f0f0f0; }}
        #header {{ height: 44px; background-color: #252526; border-bottom: 1px solid #3c3c3c; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; font-size: 13px; }}
        .doc-info {{ display: flex; align-items: center; gap: 8px; max-width: 60%; overflow: hidden; }}
        .badge {{ background-color: #0e639c; color: #ffffff; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; white-space: nowrap; flex-shrink: 0; letter-spacing: 0.3px; }}
        .doc-title {{ font-weight: 600; color: #cccccc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .actions {{ display: flex; gap: 8px; align-items: center; }}
        .btn {{ background-color: #0078d4; color: #ffffff; border: none; border-radius: 4px; padding: 6px 14px; font-size: 12px; font-weight: 500; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; transition: background-color 0.2s; }}
        .btn:hover {{ background-color: #106ebe; }}
        .btn-secondary {{ background-color: #3a3d41; }}
        .btn-secondary:hover {{ background-color: #4e5157; }}
        #viewer-container {{ width: 100%; height: calc(100% - 44px); background-color: #525659; position: relative; }}
        iframe {{ width: 100%; height: 100%; border: none; }}
        #loading {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #ffffff; font-size: 14px; }}
        #fallback {{ display: none; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; color: #ffffff; }}
        @media print {{
            #header {{ display: none !important; }}
            #viewer-container {{ height: 100% !important; margin: 0 !important; padding: 0 !important; }}
            iframe {{ width: 100% !important; height: 100% !important; }}
        }}
    </style>
</head>
<body>
    <div id="header">
        <div class="doc-info">
            <span class="badge" id="security-badge">오프라인 웹 뷰어</span>
            <span class="doc-title" id="title-text" title="{doc_title}">{doc_title}</span>
        </div>
        <div class="actions">
            <button id="btn-print" class="btn btn-secondary" type="button" title="Ctrl+P">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                <span id="btn-print-text">인쇄</span>
            </button>
            <a id="btn-download" class="btn" href="#" download="{doc_filename}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                <span id="btn-download-text">PDF 다운로드</span>
            </a>
        </div>
    </div>
    <div id="viewer-container">
        <div id="loading">PDF 문서를 로드하는 중입니다...</div>
        <div id="fallback">
            <p id="fallback-msg" style="margin-bottom: 12px;">이 브라우저에서 인라인 PDF 보기를 지원하지 않습니다.</p>
            <a id="btn-fallback-download" class="btn" href="#" download="{doc_filename}">PDF 다운로드</a>
        </div>
        <iframe id="pdf-frame" style="display:none;"></iframe>
    </div>
    <script>
        (function() {{
            var lang = (navigator.language || 'en').slice(0, 2).toLowerCase();
            var i18n = {{
                ko: {{ download: 'PDF 다운로드', print: '인쇄', badge: '오프라인 웹 뷰어', loading: 'PDF 문서를 로드하는 중입니다...', fallback: '이 브라우저에서 인라인 PDF 보기를 지원하지 않습니다.', print_hint: '새 탭에서 원본 PDF를 열어 인쇄(Ctrl+P)를 진행합니다.', popup_blocked: '인쇄용 탭을 열지 못했습니다. 브라우저의 팝업 차단을 해제해 주세요.' }},
                pl: {{ download: 'Pobierz PDF', print: 'Drukuj', badge: 'Przeglądarka offline', loading: 'Trwa ładowanie dokumentu PDF...', fallback: 'Ta przeglądarka nie obsługuje wbudowanego podglądu PDF.', print_hint: 'Otwórz w nowej karcie, aby wydrukować (Ctrl+P).', popup_blocked: 'Nie udało się otworzyć karty do druku. Odblokuj wyskakujące okna.' }},
                en: {{ download: 'Download PDF', print: 'Print', badge: 'Offline Web Viewer', loading: 'Loading PDF document...', fallback: 'This browser does not support inline PDF viewing.', print_hint: 'Opens original PDF in a new tab for printing (Ctrl+P).', popup_blocked: 'Failed to open printing tab. Please allow popups for this page.' }}
            }};
            var t = i18n[lang] || i18n.en;
            document.documentElement.lang = lang;
            var loading = document.getElementById('loading');
            var fallbackMsg = document.getElementById('fallback-msg');
            var downloadText = document.getElementById('btn-download-text');
            var printText = document.getElementById('btn-print-text');
            var securityBadge = document.getElementById('security-badge');
            var fallbackBtn = document.getElementById('btn-fallback-download');
            var printBtn = document.getElementById('btn-print');
            if (loading) loading.textContent = t.loading;
            if (fallbackMsg) fallbackMsg.textContent = t.fallback;
            if (downloadText) downloadText.textContent = t.download;
            if (printText) printText.textContent = t.print;
            if (securityBadge) securityBadge.textContent = t.badge;
            if (fallbackBtn) fallbackBtn.textContent = t.download;
            if (printBtn) printBtn.title = t.print_hint;

            var pdfBlobUrl = null;
            function triggerPrint() {{
                if (pdfBlobUrl) {{
                    var printWin = window.open(pdfBlobUrl, '_blank');
                    if (printWin) {{
                        try {{ printWin.focus(); }} catch (e) {{}}
                    }} else {{
                        alert(t.popup_blocked);
                    }}
                }}
            }}

            if (printBtn) {{
                printBtn.addEventListener('click', triggerPrint);
            }}

            window.addEventListener('keydown', function(e) {{
                if ((e.ctrlKey || e.metaKey) && (e.key === 'p' || e.key === 'P')) {{
                    e.preventDefault();
                    triggerPrint();
                }}
            }});

            var b64Data = "{base64_data}";
            function b64ToBlob(b64) {{
                var byteCharacters = atob(b64);
                var byteNumbers = new Uint8Array(byteCharacters.length);
                for (var i = 0; i < byteCharacters.length; i++) {{
                    byteNumbers[i] = byteCharacters.charCodeAt(i);
                }}
                return new Blob([byteNumbers], {{ type: 'application/pdf' }});
            }}
            try {{
                var blob = b64ToBlob(b64Data);
                pdfBlobUrl = URL.createObjectURL(blob);
                var frame = document.getElementById('pdf-frame');
                var downloadBtn = document.getElementById('btn-download');
                if (downloadBtn) downloadBtn.href = pdfBlobUrl;
                if (fallbackBtn) fallbackBtn.href = pdfBlobUrl;

                var supportsPdf = ('pdfViewerEnabled' in navigator) ? navigator.pdfViewerEnabled : true;
                if (!supportsPdf) {{
                    if (loading) loading.style.display = 'none';
                    var fb = document.getElementById('fallback');
                    if (fb) fb.style.display = 'block';
                    return;
                }}

                frame.src = pdfBlobUrl;
                frame.onload = function() {{
                    loading.style.display = 'none';
                    frame.style.display = 'block';
                }};
                setTimeout(function() {{
                    if (loading.style.display !== 'none') {{
                        loading.style.display = 'none';
                        frame.style.display = 'block';
                    }}
                }}, 1000);
            }} catch (err) {{
                console.error("PDF Blob generation error:", err);
                loading.style.display = 'none';
                document.getElementById('fallback').style.display = 'block';
            }}
        }})();
    </script>
</body>
</html>
"""

# Windows API constants for SetFileTime
KERNEL32 = ctypes.windll.kernel32 if hasattr(ctypes, 'windll') else None
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_WRITE_ATTRIBUTES = 0x0100
INVALID_HANDLE_VALUE = -1

def set_file_timestamps_windows(file_path, creation_time, access_time, modification_time):
    """
    Windows OS 레벨에서 파일의 생성 시간(Creation Time), 마지막 접근 시간(Access Time),
    마지막 수정 시간(Modification Time)을 지정된 값(epoch float)으로 강밀 복구 설정합니다.
    """
    if not KERNEL32:
        # Windows가 아닌 환경에서는 os.utime으로 수정/액세스만 설정
        os.utime(file_path, (access_time, modification_time))
        return False

    def get_filetime(epoch_time):
        # Epoch(1970년 1월 1일)과 Windows FILETIME Epoch(1601년 1월 1일) 차이 보정
        # FILETIME은 100나노초 단위의 정수 값
        val = int((epoch_time + 11644473600) * 10000000)
        low = val & 0xFFFFFFFF
        high = (val >> 32) & 0xFFFFFFFF
        return wintypes.FILETIME(low, high)

    ft_creation = get_filetime(creation_time)
    ft_access = get_filetime(access_time)
    ft_modification = get_filetime(modification_time)

    # 쓰기 특성 권한으로 파일 개방
    handle = KERNEL32.CreateFileW(
        os.path.abspath(file_path),
        FILE_WRITE_ATTRIBUTES,
        0, # sharing mode
        None,
        OPEN_EXISTING,
        0,
        None
    )

    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.GetLastError()
        logger.error(f"Failed to open file handle to set timestamps ({file_path}), Error code: {err}")
        return False

    try:
        success = KERNEL32.SetFileTime(
            handle,
            ctypes.byref(ft_creation),
            ctypes.byref(ft_access),
            ctypes.byref(ft_modification)
        )
        if not success:
            err = ctypes.GetLastError()
            logger.error(f"SetFileTime failed for {file_path}, Error code: {err}")
            return False
        return True
    finally:
        KERNEL32.CloseHandle(handle)


class BypassConverter:
    """
    Office 파일(Excel, PowerPoint, Word) 및 PDF 파일을
    보안 정책 우회용 포맷으로 변환하고 메타데이터를 유지하는 코어 비즈니스 엔진
    """

    def __init__(self):
        self._office_installed_cache = {}

    def is_file_locked(self, file_path):
        """파일이 다른 프로세스에 의해 단독으로 열려 있거나 잠겨 있는지 검사합니다."""
        if not os.path.exists(file_path):
            return False
        try:
            # 쓰기 모드로 오픈을 시도하여 파일 락 여부 점검
            # 이미 다른 곳에서 독점 열기 상태면 PermissionError 발생
            with open(file_path, 'r+'):
                pass
            return False
        except IOError:
            return True

    def check_office_installed(self, app_name):
        """특정 Office 프로그램(Excel.Application 등)의 COM 호출 가능 여부 검사"""
        if app_name in self._office_installed_cache:
            return self._office_installed_cache[app_name]

        import win32com.client
        import pythoncom

        pythoncom.CoInitialize()
        try:
            app = win32com.client.DispatchEx(app_name)
            app.Quit()
            self._office_installed_cache[app_name] = True
            return True
        except Exception as e:
            logger.warning(f"{app_name} is not available/installed: {e}")
            self._office_installed_cache[app_name] = False
            return False
        finally:
            pythoncom.CoUninitialize()

    @staticmethod
    def _same_path(first_path, second_path):
        return os.path.normcase(os.path.abspath(first_path)) == os.path.normcase(os.path.abspath(second_path))

    @staticmethod
    def _source_fingerprint(stat_result):
        """Return fields that reveal a replaced or edited source file."""
        return (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_size,
            stat_result.st_mtime_ns,
        )

    @staticmethod
    def _validate_replacement_output(tgt_path, target_ext):
        """Perform format-aware checks before an irreversible source removal."""
        try:
            if not os.path.isfile(tgt_path):
                return False, f"OUTPUT_NOT_CREATED|{tgt_path}"
            if os.path.getsize(tgt_path) == 0:
                return False, f"OUTPUT_EMPTY|{tgt_path}"

            target_ext = target_ext.lower()
            package_main_parts = {
                ".xlsx": "xl/workbook.xml",
                ".xlsm": "xl/workbook.xml",
                ".xlsb": "xl/workbook.bin",
                ".pptx": "ppt/presentation.xml",
                ".pptm": "ppt/presentation.xml",
                ".docx": "word/document.xml",
                ".docm": "word/document.xml",
            }
            if target_ext in package_main_parts:
                if not zipfile.is_zipfile(tgt_path):
                    return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|invalid Office package"
                with zipfile.ZipFile(tgt_path, "r") as archive:
                    if archive.testzip() is not None:
                        return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|damaged Office package"
                    names = {name.lower() for name in archive.namelist()}
                required = {"[content_types].xml", package_main_parts[target_ext]}
                if not required.issubset(names):
                    return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|required Office content is missing"
            elif target_ext == ".zip":
                if not zipfile.is_zipfile(tgt_path):
                    return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|invalid ZIP archive"
                with zipfile.ZipFile(tgt_path, "r") as archive:
                    if archive.testzip() is not None:
                        return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|damaged ZIP archive"
            elif target_ext == ".pdf":
                with open(tgt_path, "rb") as output_file:
                    if output_file.read(5) != b"%PDF-":
                        return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|invalid PDF header"
            elif target_ext == ".html":
                with open(tgt_path, "r", encoding="utf-8", errors="ignore") as output_file:
                    header = output_file.read(4096).lower()
                    if "<!doctype html" not in header and "<html" not in header:
                        return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|invalid HTML markup"
            elif target_ext in {".xls", ".ppt", ".doc"}:
                with open(tgt_path, "rb") as output_file:
                    if output_file.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                        return False, f"OUTPUT_FORMAT_INVALID|{tgt_path}|invalid legacy Office header"
        except (OSError, zipfile.BadZipFile) as validation_error:
            return False, f"OUTPUT_VALIDATION_FAILED|{tgt_path}|{validation_error}"
        return True, ""

    @staticmethod
    def _unique_backup_path(src_path, backup_folder_name="Original Backup"):
        backup_dir = os.path.join(os.path.dirname(src_path), backup_folder_name)
        filename = os.path.basename(src_path)
        name, ext = os.path.splitext(filename)
        candidate = os.path.join(backup_dir, filename)
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(backup_dir, f"{name}_{counter}{ext}")
            counter += 1
        return candidate

    @classmethod
    def _generate_pdf_html_viewer(cls, src_pdf_path, tgt_html_path):
        """PDF 파일을 자체 포함형(Standalone) HTML 독립형 웹 뷰어로 패키징합니다."""
        created = False
        try:
            if os.path.getsize(src_pdf_path) > MAX_PDF_HTML_SIZE_BYTES:
                logger.warning("PDF exceeds maximum HTML viewer size (50MB): %s", src_pdf_path)
                return False, f"PDF_EXCEEDS_HTML_SIZE_LIMIT|{src_pdf_path}"

            with open(src_pdf_path, "rb") as f:
                pdf_bytes = f.read()
            if not pdf_bytes:
                return False, "SOURCE_EMPTY"
            if not pdf_bytes.startswith(b"%PDF-"):
                return False, "INVALID_PDF_HEADER"

            b64_data = base64.b64encode(pdf_bytes).decode("ascii")
            raw_filename = os.path.basename(src_pdf_path)
            doc_title = html.escape(raw_filename)
            doc_filename = html.escape(raw_filename, quote=True)

            html_content = HTML_VIEWER_TEMPLATE.format(
                doc_title=doc_title,
                doc_filename=doc_filename,
                base64_data=b64_data,
            )

            if os.path.exists(tgt_html_path):
                return False, f"TARGET_ALREADY_EXISTS|{tgt_html_path}"
            with open(tgt_html_path, "x", encoding="utf-8") as f:
                created = True
                f.write(html_content)

            return True, "성공"
        except FileExistsError:
            return False, f"TARGET_ALREADY_EXISTS|{tgt_html_path}"
        except Exception as e:
            logger.error("Failed to generate PDF HTML viewer %s -> %s: %s", src_pdf_path, tgt_html_path, e)
            if created and os.path.exists(tgt_html_path):
                try:
                    os.remove(tgt_html_path)
                except OSError:
                    pass
            return False, str(e)

    def convert_file(
        self,
        src_path,
        tgt_path,
        target_ext,
        preserve_meta=True,
        source_disposition=SourceDisposition.KEEP,
        delete_original=None,
        generate_pdf_html=False,
    ):
        """
        단일 파일을 변환하고 메타데이터를 보존합니다. 원본 처리 방식에 따라
        보존, 복구 가능한 백업 이동 또는 검증 후 교체를 수행합니다.

        Returns:
            tuple: (success, message)
        """
        try:
            src_path = os.path.normpath(os.fspath(src_path))
            tgt_path = os.path.normpath(os.fspath(tgt_path))
        except (TypeError, ValueError) as path_error:
            return False, f"INVALID_PATH|{path_error}"
        if not isinstance(target_ext, str) or not target_ext.strip().startswith("."):
            return False, f"INVALID_TARGET_EXTENSION|{target_ext}"

        # Old callers may still pass delete_original=True. Preserve compatibility
        # without preserving the destructive behavior: True now means backup.
        if delete_original is not None:
            source_disposition = SourceDisposition.BACKUP if delete_original else SourceDisposition.KEEP
        try:
            source_disposition = SourceDisposition(source_disposition)
        except (TypeError, ValueError):
            return False, f"INVALID_SOURCE_DISPOSITION|{source_disposition}"

        if not os.path.isfile(src_path):
            return False, f"원본 파일을 찾을 수 없습니다: {src_path}"

        if self._same_path(src_path, tgt_path):
            return False, f"SOURCE_TARGET_SAME|{src_path}"

        if os.path.exists(tgt_path):
            return False, f"TARGET_ALREADY_EXISTS|{tgt_path}"

        normalized_target_ext = target_ext.strip().lower()
        actual_target_ext = os.path.splitext(tgt_path)[1].lower()
        if actual_target_ext != normalized_target_ext:
            return False, f"TARGET_EXTENSION_MISMATCH|{tgt_path}|{normalized_target_ext}"

        if self.is_file_locked(src_path):
            return False, f"파일이 이미 다른 프로그램에서 사용 중입니다 (Locked): {os.path.basename(src_path)}"

        # 메타데이터 미리 백업
        source_stat = os.stat(src_path)
        source_fingerprint = self._source_fingerprint(source_stat)
        creation_time = source_stat.st_ctime
        modification_time = source_stat.st_mtime
        access_time = source_stat.st_atime

        _, src_ext = os.path.splitext(src_path.lower())
        target_ext = normalized_target_ext

        if generate_pdf_html and src_ext == '.pdf' and target_ext != '.html':
            cand_html = os.path.splitext(tgt_path)[0] + ".html"
            if os.path.exists(cand_html):
                return False, f"TARGET_ALREADY_EXISTS|{cand_html}"

        # 대상 폴더 생성
        os.makedirs(os.path.dirname(os.path.abspath(tgt_path)), exist_ok=True)

        success = False
        err_msg = ""

        # 1. 파일 유형별 알맞은 변환 실행
        try:
            if src_ext in ('.xlsx', '.xls', '.xlsm'):
                success, err_msg = self._convert_excel(src_path, tgt_path, target_ext)
            elif src_ext in ('.pptx', '.ppt', '.pptm'):
                success, err_msg = self._convert_powerpoint(src_path, tgt_path, target_ext)
            elif src_ext in ('.docx', '.doc', '.docm'):
                success, err_msg = self._convert_word(src_path, tgt_path, target_ext)
            elif src_ext == '.pdf':
                success, err_msg = self._convert_pdf(src_path, tgt_path, target_ext, generate_pdf_html=generate_pdf_html)
            else:
                success, err_msg = False, f"지원하지 않는 원본 파일 형식입니다: {src_ext}"
        except Exception as ex:
            success = False
            err_msg = f"변환 실패 (알 수 없는 오류): {str(ex)}"
            logger.exception("Exception in convert_file")

        if not success:
            return False, err_msg

        # Never move or remove a source until the converter has produced a real
        # output file. REPLACE performs additional format-aware validation below.
        if not os.path.isfile(tgt_path):
            return False, f"OUTPUT_NOT_CREATED|{tgt_path}"
        if os.path.getsize(tgt_path) == 0:
            return False, f"OUTPUT_EMPTY|{tgt_path}"

        # 2. 메타데이터 (시간 타임스탬프) 복구 적용
        if preserve_meta:
            if os.path.exists(tgt_path):
                try:
                    set_file_timestamps_windows(tgt_path, creation_time, access_time, modification_time)
                except Exception as meta_ex:
                    logger.error(f"Failed to restore metadata for {tgt_path}: {meta_ex}")
                    # 메타데이터 보존 실패는 파일 자체의 변환 성공을 무효화하지는 않음 (경고만 기록)
            if generate_pdf_html and src_ext == '.pdf':
                html_path = os.path.splitext(tgt_path)[0] + ".html"
                if os.path.exists(html_path):
                    try:
                        set_file_timestamps_windows(html_path, creation_time, access_time, modification_time)
                    except Exception as meta_ex:
                        logger.error(f"Failed to restore metadata for {html_path}: {meta_ex}")

        # 3. Validate the output structure and confirm that the source has not
        # changed while Office was working. Prefer the Windows Recycle Bin; if
        # the shell cannot recycle this path, use the explicitly documented
        # permanent-delete fallback.
        if source_disposition == SourceDisposition.REPLACE:
            output_ok, output_error = self._validate_replacement_output(tgt_path, target_ext)
            if not output_ok:
                return False, output_error
            if generate_pdf_html and src_ext == '.pdf':
                html_path = os.path.splitext(tgt_path)[0] + ".html"
                html_ok, html_error = self._validate_replacement_output(html_path, ".html")
                if not html_ok:
                    return False, html_error
            try:
                current_source_stat = os.stat(src_path)
            except FileNotFoundError:
                return False, f"SOURCE_MISSING_BEFORE_REPLACE|{src_path}"
            except OSError as source_check_error:
                return False, f"SOURCE_REPLACE_CHECK_FAILED|{src_path}|{source_check_error}"
            if self._source_fingerprint(current_source_stat) != source_fingerprint:
                return False, f"SOURCE_CHANGED_DURING_CONVERSION|{src_path}"
            recycle_error = ""
            try:
                send2trash(src_path)
                if not os.path.exists(src_path):
                    return True, f"SOURCE_RECYCLED|{tgt_path}"
                recycle_error = "Recycle Bin operation returned but the source still exists"
            except Exception as recycle_exception:
                recycle_error = str(recycle_exception)
                logger.warning("Could not move replaced source to Recycle Bin %s: %s", src_path, recycle_exception)
                if not os.path.exists(src_path):
                    return True, f"SOURCE_RECYCLED_WARNING|{tgt_path}|{recycle_error}"
            try:
                os.remove(src_path)
                if os.path.exists(src_path):
                    return False, f"SOURCE_REPLACE_FAILED|{src_path}|source still exists after fallback"
                return True, f"SOURCE_DELETED_FALLBACK|{tgt_path}|{recycle_error}"
            except OSError as replace_error:
                if not os.path.exists(src_path):
                    return True, f"SOURCE_DELETED_FALLBACK|{tgt_path}|{recycle_error}; {replace_error}"
                logger.error("Failed to remove replaced source file %s: %s", src_path, replace_error)
                return False, f"SOURCE_REPLACE_FAILED|{src_path}|Recycle Bin: {recycle_error}; delete: {replace_error}"

        # 4. 요청된 경우 원본을 복구 가능한 백업 폴더로 이동
        if source_disposition == SourceDisposition.BACKUP:
            try:
                backup_path = self._unique_backup_path(src_path)
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.move(src_path, backup_path)
                manifest_ok, manifest_error = record_backup_move(src_path, backup_path)
                if not manifest_ok:
                    logger.warning("Source backup manifest could not be updated for %s: %s", backup_path, manifest_error)
                    return True, f"SOURCE_BACKED_UP_MANIFEST_WARNING|{backup_path}|{manifest_error}"
                return True, f"SOURCE_BACKED_UP|{backup_path}"
            except Exception as backup_ex:
                logger.error(f"Failed to move original file to backup {src_path}: {backup_ex}")
                return False, f"SOURCE_BACKUP_FAILED|{str(backup_ex)}"

        return True, "SOURCE_KEPT"

    def _convert_excel(self, src_path, tgt_path, target_ext):
        """Excel COM 자동화를 이용한 바이너리/매크로 형식 변환"""
        if not self.check_office_installed("Excel.Application"):
            return False, "Microsoft Excel이 이 컴퓨터에 설치되어 있지 않거나 COM 실행이 불가능합니다."

        import win32com.client
        import pythoncom

        # Excel 파일 형식 매핑
        # xlExcel12 = 50 (.xlsb)
        # xlOpenXMLWorkbook = 51 (.xlsx)
        # xlOpenXMLWorkbookMacroEnabled = 52 (.xlsm)
        # xlExcel8 = 56 (.xls)
        fmt_map = {
            ".xlsb": 50,
            ".xlsx": 51,
            ".xlsm": 52,
            ".xls": 56
        }
        file_format = fmt_map.get(target_ext, 50)

        pythoncom.CoInitialize()
        excel = None
        wb = None
        try:
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.DisplayAlerts = False
            excel.Visible = False

            wb = excel.Workbooks.Open(os.path.abspath(src_path))
            wb.SaveAs(os.path.abspath(tgt_path), FileFormat=file_format)
            wb.Close(SaveChanges=False)
            return True, "성공"
        except Exception as e:
            logger.error(f"Excel conversion failed: {e}")
            return False, f"Excel 변환 중 오류: {str(e)}"
        finally:
            try:
                if excel:
                    excel.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    def _convert_powerpoint(self, src_path, tgt_path, target_ext):
        """PowerPoint COM 자동화를 이용한 매크로 활성화 형식 변환"""
        if not self.check_office_installed("PowerPoint.Application"):
            return False, "Microsoft PowerPoint가 이 컴퓨터에 설치되어 있지 않거나 COM 실행이 불가능합니다."

        import win32com.client
        import pythoncom

        # PPT 파일 형식 매핑
        # ppSaveAsOpenXMLPresentation = 24 (.pptx)
        # ppSaveAsOpenXMLPresentationMacroEnabled = 25 (.pptm)
        # ppSaveAsPresentation = 1 (.ppt)
        fmt_map = {
            ".pptx": 24,
            ".pptm": 25,
            ".ppt": 1
        }
        file_format = fmt_map.get(target_ext, 25)

        pythoncom.CoInitialize()
        powerpoint = None
        pres = None
        try:
            powerpoint = win32com.client.DispatchEx("PowerPoint.Application")

            # PowerPoint는 WithWindow=False로 열어야 백그라운드로 실행됨
            pres = powerpoint.Presentations.Open(os.path.abspath(src_path), WithWindow=False)
            pres.SaveAs(os.path.abspath(tgt_path), FileFormat=file_format)
            pres.Close()
            return True, "성공"
        except Exception as e:
            logger.error(f"PowerPoint conversion failed: {e}")
            return False, f"PowerPoint 변환 중 오류: {str(e)}"
        finally:
            try:
                if powerpoint:
                    powerpoint.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    def _convert_word(self, src_path, tgt_path, target_ext):
        """Word COM 자동화를 이용한 매크로 활성화 형식 변환"""
        if not self.check_office_installed("Word.Application"):
            return False, "Microsoft Word가 이 컴퓨터에 설치되어 있지 않거나 COM 실행이 불가능합니다."

        import win32com.client
        import pythoncom

        # Word 파일 형식 매핑
        # wdFormatDocument = 0 (.doc)
        # wdFormatXMLDocument = 12 (.docx)
        # wdFormatXMLDocumentMacroEnabled = 13 (.docm)
        fmt_map = {
            ".docx": 12,
            ".docm": 13,
            ".doc": 0
        }
        file_format = fmt_map.get(target_ext, 13)

        pythoncom.CoInitialize()
        word = None
        doc = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.DisplayAlerts = 0
            word.Visible = False

            doc = word.Documents.Open(os.path.abspath(src_path))
            doc.SaveAs2(os.path.abspath(tgt_path), FileFormat=file_format)
            doc.Close(SaveChanges=False)
            return True, "성공"
        except Exception as e:
            logger.error(f"Word conversion failed: {e}")
            return False, f"Word 변환 중 오류: {str(e)}"
        finally:
            try:
                if word:
                    word.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    def _convert_pdf(self, src_path, tgt_path, target_ext, generate_pdf_html=False):
        """PDF 파일을 지정된 형식(ZIP, HTML 등)으로 변환하며, 옵션에 따라 브라우저 열람용 HTML을 함께 생성합니다."""
        target_ext = target_ext.lower()
        if target_ext == '.html':
            html_success, html_err = self._generate_pdf_html_viewer(src_path, tgt_path)
            if not html_success:
                return False, f"PDF -> HTML 변환 실패: {html_err}"
            return True, "성공"

        primary_success = False
        primary_msg = ""
        if target_ext == '.zip':
            try:
                # PDF 파일을 ZIP 아카이브에 압축 포장
                with zipfile.ZipFile(tgt_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(src_path, arcname=os.path.basename(src_path))
                primary_success = True
                primary_msg = "성공"
            except Exception as e:
                logger.error(f"PDF ZIP conversion failed: {e}")
                return False, f"PDF -> ZIP 압축 중 오류: {str(e)}"
        else:
            # 우회하지 않고 단순 복제 처리
            try:
                shutil.copy2(src_path, tgt_path)
                primary_success = True
                primary_msg = "성공"
            except Exception as e:
                return False, f"PDF 복제 오류: {str(e)}"

        if not primary_success:
            return False, primary_msg

        if generate_pdf_html:
            html_path = os.path.splitext(tgt_path)[0] + ".html"
            if os.path.exists(html_path):
                if os.path.exists(tgt_path):
                    try:
                        os.remove(tgt_path)
                    except OSError:
                        pass
                return False, f"TARGET_ALREADY_EXISTS|{html_path}"
            html_success, html_err = self._generate_pdf_html_viewer(src_path, html_path)
            if not html_success:
                if os.path.exists(tgt_path):
                    try:
                        os.remove(tgt_path)
                    except OSError:
                        pass
                return False, f"PDF HTML 뷰어 생성 실패: {html_err}"

        return True, "성공"
