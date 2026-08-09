from __future__ import annotations

from typing import Any

from src.ui.i18n import normalize_language


TOPIC_ORDER = (
    "getting_started",
    "tasks",
    "sync",
    "eml",
    "pdf",
    "ocr",
    "bypass",
    "settings",
)


MANUAL_CONTENT: dict[str, dict[str, dict[str, Any]]] = {
    "en": {
        "getting_started": {
            "title": "Getting Started",
            "summary": "FileOps Hub collects repeatable file operations in one place. Configure a feature first, verify it, and then run it directly or from Run Tasks.",
            "steps": [
                "Open the feature tab you need and enter its folders or files.",
                "Review the preview, selected files, or task list shown on that tab.",
                "Run the feature directly once and confirm its output.",
                "For repeat work, select the feature in Run Tasks and optionally enable a daily schedule.",
            ],
            "tips": [
                "A disabled button means an earlier requirement is missing. Point to it to see what is needed.",
                "Run Diagnostics checks paths and required programs without changing source files.",
            ],
            "cautions": [
                "Keep FileOps Hub running in the notification area for scheduled tasks.",
            ],
        },
        "tasks": {
            "title": "Run Tasks",
            "summary": "Run several configured features in order, manually or once per day.",
            "steps": [
                "Configure each feature in its own tab.",
                "Select only the features you want in the Run column.",
                "Check Readiness and fix any row marked Needs setup.",
                "Run the selected tasks now, or enable the daily schedule and choose a time.",
            ],
            "tips": [
                "Click Run Diagnostics when a dependency such as Office, OCR, or a network folder is uncertain.",
                "Open Run History to review earlier manual and scheduled reports.",
            ],
            "cautions": [
                "The application must remain running for a daily schedule to start.",
                "Scheduled source backup moves require the separate consent shown on this screen.",
            ],
        },
        "sync": {
            "title": "Sync Folders",
            "summary": "Compare two or more folders in a group, preview every planned change, and then synchronize them.",
            "steps": [
                "Create or select a synchronization group.",
                "Add at least two folders to the group.",
                "Select Preview Sync and review the planned copies, archives, and conflicts.",
                "When the preview is current, select Synchronize All and confirm the run.",
            ],
            "tips": [
                "Use separate groups for folder sets that should run together.",
                "Changing a folder invalidates the previous preview and requires a new preview.",
            ],
            "cautions": [
                "Files with competing recent changes are preserved as conflict backups instead of being overwritten silently.",
            ],
        },
        "eml": {
            "title": "Convert EML",
            "summary": "Save EML messages from one or more source folders as images.",
            "steps": [
                "Add a task and give it an easy-to-recognize name.",
                "Choose the EML source folder and the image output folder.",
                "Review the task list, then select Start Batch Conversion.",
                "Check the status column and detailed log when the run finishes.",
            ],
            "tips": [
                "Drag a folder onto the task table to start a task with its source path filled in.",
                "Output image width is available in Settings.",
            ],
            "cautions": [
                "EML image conversion needs the browser component prepared by FileOps Hub. If it is missing, the app will guide you or try to prepare it automatically.",
            ],
        },
        "pdf": {
            "title": "Convert PDF",
            "summary": "Convert each page of selected PDF files into an image.",
            "steps": [
                "Add one or more PDF files.",
                "Choose the folder where generated images will be saved.",
                "Select Start Conversion.",
                "Review or open generated images in the results list.",
            ],
            "tips": [
                "You can add several PDFs before starting one batch.",
                "Double-click a generated image to preview it.",
            ],
            "cautions": [
                "Make sure the output folder has enough free space for all PDF pages.",
            ],
        },
        "ocr": {
            "title": "Read Images",
            "summary": "Read promotion numbers from images and rename recognized files.",
            "steps": [
                "Add image files or drag them onto the window.",
                "Use the checkboxes to select the images that should be processed.",
                "Select Start OCR and Rename.",
                "Review renamed and failed items in the log.",
            ],
            "tips": [
                "Clear a checkbox to keep that image out of the next run.",
                "The promotion-number pattern and Tesseract path are available in Settings.",
            ],
            "cautions": [
                "OCR results depend on image quality. Failed recognition leaves the original file name unchanged.",
            ],
        },
        "bypass": {
            "title": "Convert Files",
            "summary": "Convert supported Office and PDF files while applying explicit output and source-handling rules.",
            "steps": [
                "Choose the source folder and, when needed, a separate output folder.",
                "Review target formats and source backup options.",
                "Scan the folder and review every file and target format.",
                "Select Start File Conversion and review the result log.",
            ],
            "tips": [
                "Changing a target format clears the old scan so the preview cannot become stale.",
                "Original Backup / Recovery opens the recovery screen for safely moved sources.",
            ],
            "cautions": [
                "Moving sources to Original Backup happens only after a valid non-empty output is created.",
                "Office conversions require the matching Microsoft Office application on this computer.",
            ],
        },
        "settings": {
            "title": "Settings",
            "summary": "Change shared application options. These sections are independent and do not need to be completed in order.",
            "steps": [
                "Choose the display language used by menus, tips, and this manual.",
                "Set an optional Tesseract path and EML image width when those features are used.",
                "Configure GitHub updates only when private-repository access is required.",
                "Configure SMTP only when result email delivery is needed, then save.",
            ],
            "tips": [
                "Leave optional fields empty when the related feature is not used.",
                "Language changes are applied after Settings is saved.",
            ],
            "cautions": [
                "Use an app password rather than a normal mailbox password when your email provider requires it.",
            ],
        },
    },
    "ko": {
        "getting_started": {
            "title": "처음 시작하기",
            "summary": "FileOps Hub는 반복되는 파일 작업을 한곳에서 처리하는 프로그램입니다. 먼저 기능별 화면에서 설정하고 한 번 확인한 뒤, 작업 실행 화면에서 수동 또는 예약 실행하는 방식이 가장 안전합니다.",
            "steps": [
                "필요한 기능 탭을 열고 폴더나 파일을 등록합니다.",
                "해당 화면에 표시되는 미리보기, 선택 파일 또는 작업 목록을 확인합니다.",
                "처음에는 기능 화면에서 직접 한 번 실행하고 결과를 확인합니다.",
                "반복 작업은 작업 실행 탭에서 기능을 선택하고 필요하면 매일 실행을 설정합니다.",
            ],
            "tips": [
                "버튼이 비활성화되어 있으면 앞 단계의 필수 입력이 부족한 상태입니다. 마우스를 올리면 필요한 내용을 확인할 수 있습니다.",
                "진단 및 복구는 원본 파일을 변경하지 않고 경로와 필수 프로그램을 검사합니다.",
            ],
            "cautions": [
                "예약 작업을 사용하려면 FileOps Hub가 알림 영역에서 계속 실행 중이어야 합니다.",
            ],
        },
        "tasks": {
            "title": "작업 실행",
            "summary": "설정해 둔 여러 기능을 정해진 순서로 한 번에 실행하거나 매일 자동 실행합니다.",
            "steps": [
                "먼저 각 기능 탭에서 실행할 폴더와 파일을 설정합니다.",
                "실행 열에서 실제로 돌릴 기능만 선택합니다.",
                "실행 준비 점검을 눌러 '설정 필요' 항목을 모두 해결합니다.",
                "선택한 작업을 바로 시작하거나, 매일 자동 실행을 켜고 시각을 지정합니다.",
            ],
            "tips": [
                "Office, OCR, 브라우저 또는 네트워크 폴더가 의심되면 진단 및 복구를 실행하세요.",
                "실행 이력에서 이전 수동·예약 실행의 상세 보고서를 확인할 수 있습니다.",
            ],
            "cautions": [
                "매일 자동 실행은 프로그램이 실행 중일 때만 시작됩니다.",
                "예약 파일 변환에서 원본을 백업 폴더로 옮기려면 이 화면의 별도 동의가 필요합니다.",
            ],
        },
        "sync": {
            "title": "폴더 동기화",
            "summary": "한 그룹에 등록한 두 개 이상의 폴더를 비교하고, 변경 예정 내용을 미리 확인한 뒤 동기화합니다.",
            "steps": [
                "동기화 그룹을 새로 만들거나 기존 그룹을 선택합니다.",
                "그룹에 동기화할 폴더를 최소 두 개 등록합니다.",
                "동기화 미리보기를 눌러 복사, 구버전 보관, 충돌 항목을 확인합니다.",
                "현재 미리보기가 유효한 상태에서 전체 동기화를 누르고 실행을 확인합니다.",
            ],
            "tips": [
                "항상 함께 동기화할 폴더 묶음별로 그룹을 나누면 관리하기 쉽습니다.",
                "폴더를 추가하거나 제거하면 이전 미리보기는 자동으로 무효화되므로 다시 분석해야 합니다.",
            ],
            "cautions": [
                "여러 위치에서 동시에 수정된 파일은 조용히 덮어쓰지 않고 충돌 백업으로 보존합니다.",
            ],
        },
        "eml": {
            "title": "EML 변환",
            "summary": "하나 이상의 원본 폴더에 있는 EML 메일을 이미지로 저장합니다.",
            "steps": [
                "작업 추가를 누르고 알아보기 쉬운 작업 이름을 입력합니다.",
                "EML 원본 폴더와 이미지 저장 폴더를 선택합니다.",
                "등록된 작업 목록을 확인하고 일괄 변환 시작을 누릅니다.",
                "완료 후 진행 상태 열과 상세 로그에서 결과를 확인합니다.",
            ],
            "tips": [
                "폴더를 작업 표로 끌어 놓으면 원본 경로가 입력된 작업 추가 창이 열립니다.",
                "출력 이미지 너비는 설정 화면에서 변경할 수 있습니다.",
            ],
            "cautions": [
                "EML 이미지 변환에는 FileOps Hub용 브라우저 구성 요소가 필요합니다. 구성 요소가 없으면 프로그램이 설치를 안내하거나 자동으로 준비합니다.",
            ],
        },
        "pdf": {
            "title": "PDF 변환",
            "summary": "선택한 PDF의 각 페이지를 이미지 파일로 변환합니다.",
            "steps": [
                "PDF 추가를 눌러 한 개 이상의 PDF를 선택합니다.",
                "생성된 이미지를 저장할 출력 폴더를 선택합니다.",
                "변환 시작을 누릅니다.",
                "변환 결과 목록에서 생성 이미지를 확인하거나 열어 봅니다.",
            ],
            "tips": [
                "여러 PDF를 추가한 뒤 한 번에 변환할 수 있습니다.",
                "생성된 이미지를 두 번 클릭하면 미리 볼 수 있습니다.",
            ],
            "cautions": [
                "PDF의 모든 페이지가 이미지로 생성될 수 있도록 출력 폴더의 여유 공간을 확인하세요.",
            ],
        },
        "ocr": {
            "title": "이미지 읽기",
            "summary": "이미지에서 프로모션 번호를 읽고, 인식에 성공한 파일의 이름을 변경합니다.",
            "steps": [
                "이미지 파일을 추가하거나 화면으로 끌어 놓습니다.",
                "체크박스로 실제 처리할 이미지를 선택합니다.",
                "OCR 및 이름 변경 시작을 누릅니다.",
                "로그에서 이름 변경 성공 항목과 인식 실패 항목을 확인합니다.",
            ],
            "tips": [
                "이번 실행에서 제외할 이미지는 체크를 해제하면 됩니다.",
                "프로모션 번호 규칙과 Tesseract 경로는 설정 화면에서 변경할 수 있습니다.",
            ],
            "cautions": [
                "OCR 정확도는 이미지 품질에 영향을 받습니다. 인식 실패 시 원래 파일 이름은 유지됩니다.",
            ],
        },
        "bypass": {
            "title": "파일 변환",
            "summary": "지원되는 Office·PDF 파일을 명시한 출력 형식과 원본 처리 규칙에 따라 변환합니다.",
            "steps": [
                "원본 폴더를 선택하고, 필요한 경우 별도의 저장 폴더를 선택합니다.",
                "파일 종류별 변환 형식과 원본 백업 옵션을 확인합니다.",
                "대상 파일 스캔을 실행하고 파일별 변환 형식을 검토합니다.",
                "파일 변환 시작을 누르고 작업 로그에서 결과를 확인합니다.",
            ],
            "tips": [
                "변환 형식을 바꾸면 오래된 미리보기를 사용하지 않도록 기존 스캔 결과가 초기화됩니다.",
                "Original Backup 확인·복구에서 안전하게 이동된 원본 파일을 복구할 수 있습니다.",
            ],
            "cautions": [
                "원본 백업 이동은 정상적이고 비어 있지 않은 출력 파일이 만들어진 뒤에만 실행됩니다.",
                "Office 파일 변환에는 해당 Microsoft Office 프로그램이 이 PC에 설치되어 있어야 합니다.",
            ],
        },
        "settings": {
            "title": "설정",
            "summary": "프로그램 전체에서 사용하는 공통 옵션을 변경합니다. 각 설정 묶음은 서로 독립적이므로 순서대로 입력할 필요가 없습니다.",
            "steps": [
                "메뉴, 사용 팁과 매뉴얼에 적용할 표시 언어를 선택합니다.",
                "해당 기능을 사용할 때만 Tesseract 경로와 EML 이미지 너비를 설정합니다.",
                "비공개 저장소 접근이 필요한 경우에만 GitHub 업데이트 정보를 설정합니다.",
                "결과 이메일이 필요할 때만 SMTP 정보를 입력한 뒤 저장합니다.",
            ],
            "tips": [
                "사용하지 않는 기능과 관련된 선택 항목은 비워 두어도 됩니다.",
                "표시 언어 변경은 설정을 저장한 직후 화면과 도움말에 반영됩니다.",
            ],
            "cautions": [
                "메일 서비스가 요구하는 경우 일반 비밀번호 대신 앱 비밀번호를 사용하세요.",
            ],
        },
    },
    "pl": {
        "getting_started": {
            "title": "Pierwsze kroki",
            "summary": "FileOps Hub łączy powtarzalne operacje na plikach. Najpierw skonfiguruj i sprawdź funkcję, a potem uruchom ją bezpośrednio lub z karty Zadań.",
            "steps": ["Otwórz potrzebną kartę i dodaj foldery lub pliki.", "Sprawdź podgląd, zaznaczone pliki lub listę zadań.", "Za pierwszym razem uruchom funkcję bezpośrednio i sprawdź wynik.", "Dla pracy cyklicznej wybierz funkcję w Zadań i opcjonalnie ustaw harmonogram."],
            "tips": ["Wyłączony przycisk oznacza brak wcześniejszego wymagania. Najedź na niego, aby zobaczyć wyjaśnienie.", "Diagnostyka sprawdza ścieżki i wymagane programy bez zmiany plików źródłowych."],
            "cautions": ["Dla zadań zaplanowanych FileOps Hub musi działać w obszarze powiadomień."],
        },
        "tasks": {
            "title": "Uruchamianie zadań",
            "summary": "Uruchamiaj kilka skonfigurowanych funkcji po kolei, ręcznie lub raz dziennie.",
            "steps": ["Skonfiguruj każdą funkcję na jej karcie.", "W kolumnie Uruchom wybierz tylko potrzebne funkcje.", "Sprawdź gotowość i popraw pozycje Wymaga konfiguracji.", "Uruchom zadania teraz albo włącz harmonogram i wybierz godzinę."],
            "tips": ["Użyj Diagnostyki, gdy nie masz pewności co do Office, OCR, przeglądarki lub folderu sieciowego.", "Historia uruchomień zawiera wcześniejsze raporty."],
            "cautions": ["Harmonogram działa tylko wtedy, gdy aplikacja jest uruchomiona.", "Zaplanowane przenoszenie źródeł wymaga osobnej zgody."],
        },
        "sync": {
            "title": "Synchronizacja folderów",
            "summary": "Porównaj co najmniej dwa foldery, sprawdź plan zmian, a następnie wykonaj synchronizację.",
            "steps": ["Utwórz lub wybierz grupę synchronizacji.", "Dodaj do grupy co najmniej dwa foldery.", "Wybierz Podgląd synchronizacji i sprawdź kopie, archiwizacje oraz konflikty.", "Gdy podgląd jest aktualny, wybierz Synchronizuj wszystko i potwierdź."],
            "tips": ["Twórz osobne grupy dla folderów uruchamianych razem.", "Zmiana folderu unieważnia poprzedni podgląd."],
            "cautions": ["Konkurencyjne zmiany są zachowywane jako kopie konfliktu zamiast cichego nadpisania."],
        },
        "eml": {
            "title": "Konwersja EML",
            "summary": "Zapisuj wiadomości EML z jednego lub kilku folderów jako obrazy.",
            "steps": ["Dodaj zadanie i nadaj mu czytelną nazwę.", "Wybierz folder źródłowy EML i folder obrazów.", "Sprawdź listę i rozpocznij konwersję wsadową.", "Po zakończeniu sprawdź stan oraz dziennik."],
            "tips": ["Przeciągnij folder na tabelę, aby rozpocząć dodawanie zadania.", "Szerokość obrazu ustawisz w Ustawieniach."],
            "cautions": ["Konwersja EML wymaga składnika przeglądarki przygotowanego przez FileOps Hub. Jeśli go brakuje, aplikacja wyświetli instrukcję lub spróbuje przygotować go automatycznie."],
        },
        "pdf": {
            "title": "Konwersja PDF",
            "summary": "Konwertuj każdą stronę wybranych plików PDF na obraz.",
            "steps": ["Dodaj jeden lub więcej plików PDF.", "Wybierz folder zapisu obrazów.", "Rozpocznij konwersję.", "Sprawdź lub otwórz obrazy na liście wyników."],
            "tips": ["Możesz przetworzyć kilka plików PDF w jednej partii.", "Kliknij obraz dwukrotnie, aby zobaczyć podgląd."],
            "cautions": ["Sprawdź wolne miejsce dla obrazów ze wszystkich stron."],
        },
        "ocr": {
            "title": "Odczyt obrazów",
            "summary": "Odczytuj numery promocji z obrazów i zmieniaj nazwy rozpoznanych plików.",
            "steps": ["Dodaj obrazy lub przeciągnij je do okna.", "Zaznacz obrazy do przetworzenia.", "Rozpocznij OCR i zmianę nazw.", "Sprawdź udane i nieudane pozycje w dzienniku."],
            "tips": ["Odznacz obraz, aby pominąć go w następnym uruchomieniu.", "Wzorzec numeru i ścieżka Tesseract są w Ustawieniach."],
            "cautions": ["Jakość obrazu wpływa na OCR; nieudane rozpoznanie zachowuje pierwotną nazwę."],
        },
        "bypass": {
            "title": "Konwersja plików",
            "summary": "Konwertuj obsługiwane pliki Office i PDF według jawnych reguł wyniku i obsługi źródła.",
            "steps": ["Wybierz folder źródłowy i w razie potrzeby osobny folder wynikowy.", "Sprawdź formaty docelowe oraz opcje kopii źródeł.", "Przeskanuj folder i sprawdź każdy plik oraz format.", "Rozpocznij konwersję i sprawdź dziennik."],
            "tips": ["Zmiana formatu usuwa stary wynik skanowania.", "Original Backup / Recovery umożliwia przywracanie przeniesionych źródeł."],
            "cautions": ["Źródło jest przenoszone dopiero po utworzeniu prawidłowego, niepustego wyniku.", "Konwersje Office wymagają odpowiedniej aplikacji Microsoft Office."],
        },
        "settings": {
            "title": "Ustawienia",
            "summary": "Zmieniaj wspólne opcje aplikacji. Sekcje są niezależne i nie wymagają wypełniania po kolei.",
            "steps": ["Wybierz język menu, wskazówek i podręcznika.", "Ustaw opcjonalną ścieżkę Tesseract i szerokość EML.", "Dane GitHub podaj tylko dla prywatnego repozytorium.", "SMTP skonfiguruj tylko dla wysyłki raportów i zapisz."],
            "tips": ["Pola nieużywanych funkcji mogą pozostać puste.", "Zmiana języka działa po zapisaniu Ustawień."],
            "cautions": ["Jeśli dostawca poczty tego wymaga, użyj hasła aplikacji."],
        },
    },
}


def manual_topics(language: str) -> list[tuple[str, dict[str, Any]]]:
    selected = normalize_language(language) or "en"
    catalog = MANUAL_CONTENT.get(selected, MANUAL_CONTENT["en"])
    return [(topic_id, catalog[topic_id]) for topic_id in TOPIC_ORDER]


def manual_topic(topic_id: str, language: str) -> dict[str, Any]:
    selected = normalize_language(language) or "en"
    catalog = MANUAL_CONTENT.get(selected, MANUAL_CONTENT["en"])
    return catalog.get(topic_id, catalog["getting_started"])
