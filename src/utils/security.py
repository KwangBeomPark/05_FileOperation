import sys
import base64
import logging
from src.app_identity import SECURITY_DESCRIPTION

logger = logging.getLogger(__name__)

# Windows 환경에서만 DPAPI(crypt32.dll) 임포트 및 정의
_is_windows = (sys.platform == 'win32')

if _is_windows:
    import ctypes
    from ctypes import wintypes

    # Win32 DATA_BLOB 구조체 정의
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte))
        ]

    # API 함수 원형 바인딩
    try:
        crypt32 = ctypes.windll.crypt32
        
        CryptProtectData = crypt32.CryptProtectData
        CryptProtectData.argtypes = [
            ctypes.c_void_p,            # pDataIn (POINTER(DATA_BLOB))
            wintypes.LPCWSTR,           # szDataDescr
            ctypes.c_void_p,            # pOptionalEntropy (POINTER(DATA_BLOB))
            wintypes.LPVOID,            # pvReserved
            wintypes.LPVOID,            # pPromptStruct
            wintypes.DWORD,             # dwFlags
            ctypes.c_void_p             # pDataOut (POINTER(DATA_BLOB))
        ]
        CryptProtectData.restype = wintypes.BOOL

        CryptUnprotectData = crypt32.CryptUnprotectData
        CryptUnprotectData.argtypes = [
            ctypes.c_void_p,            # pDataIn (POINTER(DATA_BLOB))
            ctypes.POINTER(wintypes.LPWSTR), # ppszDataDescr
            ctypes.c_void_p,            # pOptionalEntropy (POINTER(DATA_BLOB))
            wintypes.LPVOID,            # pvReserved
            wintypes.LPVOID,            # pPromptStruct
            wintypes.DWORD,             # dwFlags
            ctypes.c_void_p             # pDataOut (POINTER(DATA_BLOB))
        ]
        CryptUnprotectData.restype = wintypes.BOOL
        
    except Exception as e:
        logger.error(f"Failed to load crypt32.dll DPAPI functions: {e}")
        _is_windows = False


def encrypt_data(plain_text: str) -> str:
    """
    Windows DPAPI를 사용하여 평문 문자열을 암호화하고 base64 문자열로 반환합니다.
    Windows가 아닐 경우 경고를 남기고 단순 base64 인코딩(난독화) 처리합니다.
    """
    if not plain_text:
        return ""
        
    if not _is_windows:
        # Non-Windows fallback (Not secure, but prevents application crash)
        logger.warning("Encryption called on non-Windows environment. Fallback to base64 encoding.")
        return base64.b64encode(plain_text.encode('utf-8')).decode('utf-8')

    data_out = DATA_BLOB()
    try:
        data_bytes = plain_text.encode('utf-8')
        data_in = DATA_BLOB()
        data_in.cbData = len(data_bytes)
        data_in.pbData = (ctypes.c_ubyte * len(data_bytes))(*data_bytes)

        # dwFlags: 1 = CRYPTPROTECT_UI_FORBIDDEN (UI 팝업 방지)
        success = CryptProtectData(
            ctypes.byref(data_in),
            SECURITY_DESCRIPTION,
            None,
            None,
            None,
            1,
            ctypes.byref(data_out)
        )
        
        if not success:
            raise ctypes.WinError()

        # 암호화된 바이트 배열 추출
        result_bytes = ctypes.string_at(data_out.pbData, data_out.cbData)
        
        # base64로 인코딩하여 저장 가능한 문자열로 변환
        return base64.b64encode(result_bytes).decode('utf-8')
        
    except Exception as e:
        logger.error(f"DPAPI Encryption failed: {e}")
        return base64.b64encode(plain_text.encode('utf-8')).decode('utf-8')
    finally:
        if _is_windows and data_out.pbData:
            try:
                ctypes.windll.kernel32.LocalFree(data_out.pbData)
            except Exception as free_err:
                logger.error(f"Failed to release DPAPI memory: {free_err}")


def decrypt_data(cipher_text: str) -> str:
    """
    Windows DPAPI로 암호화된 base64 문자열을 받아 복호화된 평문 문자열을 반환합니다.
    Windows가 아니거나 복호화가 실패하면 단순 base64 디코딩 처리합니다.
    """
    if not cipher_text:
        return ""

    if not _is_windows:
        logger.warning("Decryption called on non-Windows environment. Fallback to base64 decoding.")
        try:
            return base64.b64decode(cipher_text.encode('utf-8')).decode('utf-8')
        except Exception:
            return cipher_text

    data_out = DATA_BLOB()
    try:
        cipher_bytes = base64.b64decode(cipher_text.encode('utf-8'))
        
        data_in = DATA_BLOB()
        data_in.cbData = len(cipher_bytes)
        data_in.pbData = (ctypes.c_ubyte * len(cipher_bytes))(*cipher_bytes)
        
        success = CryptUnprotectData(
            ctypes.byref(data_in),
            None,
            None,
            None,
            None,
            1,
            ctypes.byref(data_out)
        )
        
        if not success:
            raise ctypes.WinError()
            
        result_bytes = ctypes.string_at(data_out.pbData, data_out.cbData)
        return result_bytes.decode('utf-8')
        
    except Exception as e:
        logger.error(f"DPAPI Decryption failed: {e}")
        try:
            return base64.b64decode(cipher_text.encode('utf-8')).decode('utf-8')
        except Exception:
            return cipher_text
    finally:
        if _is_windows and data_out.pbData:
            try:
                ctypes.windll.kernel32.LocalFree(data_out.pbData)
            except Exception as free_err:
                logger.error(f"Failed to release DPAPI memory: {free_err}")
