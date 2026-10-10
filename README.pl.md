*Przeczytaj w innych językach: [English](README.md), [한국어](README.ko.md), [Polski](README.pl.md)*

# 📁 FileOps Hub: Dystrybucja dokumentów międzyzespołowych i automatyczna synchronizacja folderów

<p align="center">
  <img src="assets/fileops_hub_infographic.jpg" width="950" alt="FileOps Hub - Architektura i kluczowe korzyści biznesowe">
</p>

> **Synchronizacja dokumentów zespołowych · Automatyczna dystrybucja harmonogramowana · Eliminacja duplikatów**

**FileOps Hub** to narzędzie desktopowe przeznaczone do zarządzania dystrybucją dokumentów i automatyczną synchronizacją folderów między wieloma zespołami oraz zasobami sieciowymi.

Gdy nad projektami pracuje kilka działów, łatwo o powstawanie duplikatów plików i rozbieżności wersji. Program automatyzuje dwukierunkową synchronizację i zaplanowane udostępnianie plików między folderami działowymi a wspólnym dyskiem, zapewniając sprawny przepływ najnowszych materiałów i wniosków bez opóźnień operacyjnych.

## Cel i zastosowanie

1. **Centrum dystrybucji dokumentów zespołowych**: Dwukierunkowa synchronizacja oraz jednokierunkowa dystrybucja plików między folderami działowymi a wspólnymi zasobami sieciowymi.
2. **Konwersja formatów dokumentów**: Konwersja plików Excel, PowerPoint, Word i PDF z zachowaniem oryginalnych znaczników czasu modyfikacji.
3. **Przetwarzanie dokumentacji rozliczeniowej**: Wsadowe renderowanie wiadomości e-mail (.eml) i plików PDF do obrazów, odczyt numerów referencyjnych przez OCR i porządkowanie nazw plików.
4. **Harmonogramowanie i raportowanie**: Codzienne uruchamianie zaplanowanych zadań w tle i automatyczne wysyłanie raportów z wykonania przez e-mail (SMTP).

> Aplikacja nie modyfikuje uprawnień dostępu Windows ani ACL. Działa ściśle w ramach uprawnień zalogowanego użytkownika Windows.

---

## Główne moduły i funkcje

1. **Tasks (Zadania i harmonogram)**: Sekwencyjne wykonywanie skonfigurowanych operacji w ramach planu `RunPlan` z automatyczną weryfikacją wstępną. Codzienne automatyczne uruchamianie w tle i raportowanie e-mail przez SMTP.
2. **Sync (Synchronizacja folderów)**: Dwukierunkowa synchronizacja lub jednokierunkowa dystrybucja z filtrowaniem podfolderów, wykluczeniami i bezpieczną kopią zapasową nadpisywanych wersji.
3. **EML (Renderowanie wiadomości e-mail)**: Konwersja plików e-mail `.eml` do obrazów PNG przy użyciu silnika Chromium, z automatycznym pomijaniem niezmienionych plików.
4. **PDF (Renderowanie stron PDF)**: Zapisywanie stron dokumentów PDF jako wysokiej jakości pliki JPG do weryfikacji i archiwizacji.
5. **OCR (Ekstrakcja tekstu i zmiana nazw)**: Lokalne rozpoznawanie znaków OCR (Windows OCR lub Tesseract) w celu wyodrębnienia numerów promocyjnych i unifikacji nazw plików.
6. **Convert Files (Konwersja Office i pakowanie PDF)**: Wsadowa konwersja dokumentów Excel, Word i PowerPoint przez Office COM oraz pakowanie PDF do archiwów ZIP, z obsługą kopii zapasowych i bezpiecznego przywracania.

---

## 🚀 Pobieranie i instalacja

1. Przejdź do zakładki **[Releases](https://github.com/KwangBeomPark/05_FileOperation/releases)**.
2. Pobierz instalator **`App05_FileOps_Setup_vX.Y.Z.exe`** (oraz towarzyszące pliki manifestu i sum kontrolnych).
3. Uruchom instalator (instalacja do profilu użytkownika, nie wymaga uprawnień administratora UAC).
4. Dostępna jest opcja autostartu przy uruchomieniu systemu Windows (`--tray`) do bezobsługowej pracy w tle.

---

## 📄 Licencja

Projekt jest objęty licencją MIT. Szczegóły w pliku [LICENSE](LICENSE).
