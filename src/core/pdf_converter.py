import os
from datetime import datetime

import fitz  # PyMuPDF
from PIL import Image


class PDFConversionError(Exception):
    """PDF or thumbnail processing failed."""


class PDFConverter:
    """PDF를 JPEG 이미지로 변환하는 클래스"""
    
    def __init__(self, config_manager):
        """
        Args:
            config_manager: ConfigManager 인스턴스
        """
        self.config_manager = config_manager
        
    def get_page_count(self, pdf_path):
        """PDF 페이지 수 반환
        
        Args:
            pdf_path: PDF 파일 경로
            
        Returns:
            int: 페이지 수
        """
        try:
            with fitz.open(pdf_path) as doc:
                return len(doc)
        except Exception as e:
            raise PDFConversionError(f"PDF 페이지 수를 읽을 수 없습니다: {e!s}") from e
    
    def get_optimal_dpi(self, page_width, page_height):
        """페이지 크기에 따라 최적 DPI 결정
        
        Args:
            page_width: 페이지 너비 (포인트)
            page_height: 페이지 높이 (포인트)
            
        Returns:
            int: DPI 값
        """
        threshold = self.config_manager.get('dpi_threshold', 842)
        dpi_large = self.config_manager.get('dpi_large', 100)
        dpi_small = self.config_manager.get('dpi_small', 150)
        
        if page_width > threshold or page_height > threshold:
            return dpi_large
        else:
            return dpi_small
    
    def convert(self, pdf_path, output_folder, progress_callback=None):
        """PDF를 JPEG 이미지로 변환
        
        Args:
            pdf_path: PDF 파일 경로
            output_folder: 출력 폴더 경로
            progress_callback: 진행률 콜백 함수 (current, total, message)
            
        Returns:
            list: 생성된 이미지 파일 경로 리스트
            
        Raises:
            Exception: 변환 실패 시
        """
        if not os.path.exists(pdf_path):
            raise PDFConversionError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        
        try:
            with fitz.open(pdf_path) as doc:
                pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
                # Preserve the local wall-clock timestamp in output filenames.
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
                total_pages = len(doc)
                image_files = []

                for i, page in enumerate(doc):
                    if progress_callback:
                        progress_callback(i, total_pages, f'{i+1}/{total_pages} 페이지 변환 중...')

                    dpi = self.get_optimal_dpi(page.rect.width, page.rect.height)
                    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
                    output_filename = f"{pdf_name}_{i+1:02d}_{timestamp}.jpg"
                    output_path = os.path.join(output_folder, output_filename)
                    pix.save(output_path)
                    image_files.append(output_path)
            
            # 완료 콜백
            if progress_callback:
                progress_callback(total_pages, total_pages, f'변환 완료! {total_pages}개 이미지 생성')
            
            return image_files
            
        except Exception as e:
            raise PDFConversionError(f"PDF 변환 중 오류 발생: {e!s}") from e
    
    def create_thumbnail(self, image_path, size=(150, 150)):
        """이미지 썸네일 생성
        
        Args:
            image_path: 원본 이미지 경로
            size: 썸네일 크기 (width, height)
            
        Returns:
            PIL.Image: 썸네일 이미지 객체
        """
        try:
            img = Image.open(image_path)
            img.thumbnail(size, Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            raise PDFConversionError(f"썸네일 생성 실패: {e!s}") from e
