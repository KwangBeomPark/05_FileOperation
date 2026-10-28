"""파일 변환(Bypass) 작업 계획 로직.

UI와 무관한 순수 로직만 담습니다: 원본 폴더 스캔, 확장자 필터링,
대상 경로 계산(원본 위치 교체 / 별도 저장 폴더 + 하위 폴더 구조 미러링),
대상 파일명 충돌 판정.
"""
import os

from src.core.task_contracts import TaskValidationError

SCAN_EXTENSIONS = ('.xlsx', '.xls', '.xlsm', '.pptx', '.ppt', '.pptm', '.docx', '.doc', '.docm', '.pdf')
EXCLUDE_DIR_NAMES = frozenset({"original backup", "$recycle.bin", ".git", "__pycache__", ".svn", "node_modules"})

PDF_ZIP_HTML_CHOICE = ".zip + .html"


def normalize_path(path):
    return os.path.normcase(os.path.abspath(path))


def _is_same_or_under(norm_path, norm_root):
    return norm_path == norm_root or norm_path.startswith(norm_root + os.sep)


def _is_under_commonpath(norm_root, norm_path):
    try:
        return os.path.commonpath([norm_root, norm_path]) == norm_root
    except ValueError:
        return False


def resolve_exclude_root(custom_mode, target_text):
    """별도 저장 폴더 모드에서 스캔/목록에서 제외할 대상 폴더(정규화 경로)를 반환합니다."""
    if custom_mode and os.path.isdir(target_text):
        return normalize_path(target_text)
    return ""


def target_extension_for(source_ext, excel_ext, ppt_ext, word_ext, pdf_choice):
    """원본 확장자에 대한 변환 대상 확장자. 지원하지 않으면 빈 문자열."""
    source_ext = source_ext.lower()
    if source_ext in ('.xlsx', '.xls', '.xlsm'):
        return excel_ext
    if source_ext in ('.pptx', '.ppt', '.pptm'):
        return ppt_ext
    if source_ext in ('.docx', '.doc', '.docm'):
        return word_ext
    if source_ext == '.pdf':
        if pdf_choice == PDF_ZIP_HTML_CHOICE:
            return ".zip"
        return pdf_choice
    return ""


def display_target_extension(source_ext, target_ext, pdf_choice):
    """테이블 표시용 대상 확장자 (PDF zip+html 조합은 그대로 표기)."""
    if source_ext == '.pdf' and pdf_choice == PDF_ZIP_HTML_CHOICE:
        return PDF_ZIP_HTML_CHOICE
    return target_ext


def is_pdf_dual_output(source_ext, pdf_choice, html_checked, legacy_flag=False):
    """PDF를 .zip과 HTML 뷰어로 함께 출력하는지 여부."""
    return source_ext == '.pdf' and (
        pdf_choice == PDF_ZIP_HTML_CHOICE or (pdf_choice == ".zip" and html_checked) or legacy_flag
    )


def scan_source_files(src_dir, recursive=False, exclude_root=""):
    """원본 폴더에서 변환 가능한 파일을 (경로, 크기) 목록으로 수집합니다.

    심볼릭 링크/정션과 원본 폴더 밖으로 해석되는 경로, 백업·시스템 폴더,
    exclude_root(별도 저장 폴더) 하위는 제외합니다.
    """
    is_junction_fn = getattr(os.path, 'isjunction', lambda p: False)
    src_real = os.path.realpath(src_dir)
    src_prefix = src_real if src_real.endswith(os.sep) else src_real + os.sep

    def inside_source(path):
        real = os.path.realpath(path)
        return real == src_real or real.startswith(src_prefix)

    def excluded(path):
        return bool(exclude_root) and _is_same_or_under(normalize_path(path), exclude_root)

    def entry(path):
        return (path, os.path.getsize(path) if os.path.exists(path) else 0)

    discovered = []
    if recursive:
        for root, dirs, files in os.walk(src_dir, followlinks=False):
            pruned_dirs = []
            for d in dirs:
                if d.lower() in EXCLUDE_DIR_NAMES:
                    continue
                full_d = os.path.join(root, d)
                if os.path.islink(full_d) or is_junction_fn(full_d):
                    continue
                if not inside_source(full_d) or excluded(full_d):
                    continue
                pruned_dirs.append(d)
            dirs[:] = pruned_dirs

            for file_name in files:
                full_f = os.path.join(root, file_name)
                if os.path.islink(full_f) or not inside_source(full_f) or excluded(full_f):
                    continue
                _, ext = os.path.splitext(file_name.lower())
                if ext in SCAN_EXTENSIONS:
                    discovered.append(entry(full_f))
    else:
        for file_name in os.listdir(src_dir):
            file_path = os.path.join(src_dir, file_name)
            if os.path.islink(file_path) or not os.path.isfile(file_path):
                continue
            if not inside_source(file_path) or excluded(file_path):
                continue
            _, ext = os.path.splitext(file_name.lower())
            if ext in SCAN_EXTENSIONS:
                discovered.append(entry(file_path))
    return discovered


def filter_discovered_files(discovered, target_extension_for_ext, inplace_mode, exclude_root=""):
    """현재 모드/대상 형식 기준으로 변환할 파일만 남깁니다.

    Returns:
        (filtered, already_target_count): (경로, 크기) 목록과, 원본 교체 모드에서
        이미 대상 형식이라 제외된 파일 수.
    """
    filtered = []
    already_target_count = 0
    for item in discovered:
        if isinstance(item, tuple):
            file_path, size_cached = item
        else:
            file_path, size_cached = item, (os.path.getsize(item) if os.path.exists(item) else 0)

        if exclude_root and _is_same_or_under(normalize_path(file_path), exclude_root):
            continue
        _, ext = os.path.splitext(file_path.lower())
        if inplace_mode and ext == target_extension_for_ext(ext):
            already_target_count += 1
            continue
        filtered.append((file_path, size_cached))
    return filtered, already_target_count


def resolve_dest_dir(src_file, src_dir, tgt_dir, inplace_mode):
    """출력 폴더: 원본 교체 모드는 원본과 같은 폴더, 별도 저장은 하위 폴더 구조를 미러링."""
    if inplace_mode:
        return os.path.dirname(src_file)
    rel_dir = os.path.relpath(os.path.dirname(src_file), src_dir)
    return tgt_dir if rel_dir == "." else os.path.join(tgt_dir, rel_dir)


def ensure_source_inside(src_file, src_dir):
    """원본 파일이 현재 소스 폴더 하위인지 검증합니다 (Stale Cache 방어)."""
    if not _is_under_commonpath(normalize_path(src_dir), normalize_path(src_file)):
        raise TaskValidationError(
            f"파일 변환 원본 파일이 현재 소스 폴더 외부에 있습니다: {src_file}",
            message_key="bypass_source_file_outside",
            values={"path": src_file},
        )


def ensure_dest_inside_target(dest_dir, tgt_dir):
    if not _is_under_commonpath(normalize_path(tgt_dir), normalize_path(dest_dir)):
        raise TaskValidationError(
            f"대상 출력 경로가 지정된 타깃 폴더를 벗어났습니다: {dest_dir}",
            message_key="bypass_target_path_escaped",
            values={"path": dest_dir},
        )


def html_viewer_path(path):
    """PDF 출력에 대응하는 HTML 뷰어 경로."""
    return os.path.splitext(path)[0] + ".html"


def target_collides(cand_file, source_ext, reserved_targets, check_pdf_html):
    """후보 대상 파일이 디스크에 존재하거나 이번 실행에서 이미 예약되었는지 판정합니다."""
    if os.path.exists(cand_file) or normalize_path(cand_file) in reserved_targets:
        return True
    if check_pdf_html and source_ext.lower() == '.pdf':
        cand_html = html_viewer_path(cand_file)
        if os.path.exists(cand_html) or normalize_path(cand_html) in reserved_targets:
            return True
    return False


def allocate_target_path(src_file, dest_dir, tgt_ext, reserved_targets, check_pdf_html):
    """충돌하지 않는 대상 파일 경로를 결정합니다.

    대상이 원본 자신이면 `_converted`(필요 시 `_converted_N`), 기존 파일/예약과
    겹치면 `_N` 접미사를 붙입니다.
    """
    name_no_ext, source_ext = os.path.splitext(os.path.basename(src_file))
    source_ext = source_ext.lower()

    def collides(path):
        return target_collides(path, source_ext, reserved_targets, check_pdf_html)

    tgt_file = os.path.join(dest_dir, f"{name_no_ext}{tgt_ext}")
    if normalize_path(tgt_file) == normalize_path(src_file):
        tgt_file = os.path.join(dest_dir, f"{name_no_ext}_converted{tgt_ext}")
        counter = 1
        while collides(tgt_file):
            tgt_file = os.path.join(dest_dir, f"{name_no_ext}_converted_{counter}{tgt_ext}")
            counter += 1
    elif collides(tgt_file):
        counter = 1
        while True:
            tgt_file = os.path.join(dest_dir, f"{name_no_ext}_{counter}{tgt_ext}")
            if not collides(tgt_file):
                break
            counter += 1
    return tgt_file


def reserve_target(reserved_targets, tgt_file, include_html):
    reserved_targets.add(normalize_path(tgt_file))
    if include_html:
        reserved_targets.add(normalize_path(html_viewer_path(tgt_file)))
