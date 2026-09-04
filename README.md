# 🧹 Telegram Metadata Remover Bot

Nowoczesny, w pełni asynchroniczny bot na Telegrama do bezstratnego usuwania ukrytych metadanych (EXIF, współrzędne GPS, model aparatu/telefonu, daty wykonania, dane autora, wersje oprogramowania) z plików graficznych, filmów i dokumentów.

Przystosowany do prostego uruchomienia na VPS za pomocą panelu **Dokploy** (lub Dockera / Docker Compose).

---

## ✨ Cechy i możliwości

- 🛡️ **Bezstratne czyszczenie (ExifTool):** Usuwa metadane in-place bez dekompresji i ponownej kompresji plików – jakość grafiki i wideo pozostaje w 100% nienaruszona.
- ⚡ **Unikalizator wideo (Anti-Duplicate / Bypass Meta ThreatExchange & TikTok):**
  - Oparty na badaniach algorytmów **PDQ, TMK+PDQF i vPDQ** rozwijanych przez Meta (Instagram/Facebook) i TikTok.
  - Aplikuje losowe mikromodyfikacje (mikro-zoom 1-2%, mikro-prędkość, ziarno matrycy, korekta barw i audio), generując zupełnie nowy cyfrowy odcisk percepcyjny.
  - **Tryb Łagodny:** Bezpieczny dla filmów z napisami i twarzami (bez lustra).
  - **Tryb Głęboki:** Zawiera dodatkowo poziome odbicie lustrzane (`hflip`) dla maksymalnego rozbicia sygnatur przestrzennych.
  - Możliwość generowania wielu unikalnych kopii z jednego filmu (dla różnych kont) jednym kliknięciem.
- 📁 **Wielofunkcyjność:** Obsługuje zdjęcia (JPEG, PNG, HEIC, WEBP, TIFF), wideo (MP4, MOV itp.), dokumenty (PDF) i pliki audio.
- 📊 **Szczegółowy raport:** Odsyła plik wraz ze zwięzłym podsumowaniem wykrytych i usuniętych wrażliwych informacji (GPS, model aparatu, czas wykonania, autor).
- 🔒 **Prywatność i bezpieczeństwo:**
  - Whitelist: Dostęp ograniczony tylko do wybranych Telegram ID użytkowników (ochrona Twojego serwera VPS).
  - Zerowa retencja: Pliki są przetwarzane w katalogu tymczasowym i **natychmiast trwale usuwane** po odesłaniu.
- ⚡ **Long Polling:** Nie wymaga otwierania portów, konfigurowania domen ani certyfikatów SSL w Dokploy.

---

## 📋 Co musisz przygotować

1. **Token bota Telegram:**
   - Otwórz na Telegramie bota [@BotFather](https://t.me/BotFather).
   - Wpisz komendę `/newbot`.
   - Podaj nazwę wyświetlaną oraz unikalny username (musi kończyć się na `bot`, np. `my_meta_cleaner_bot`).
   - Skopiuj wygenerowany token (np. `7123456789:AAH...`).

2. **Twoje Telegram User ID:**
   - Wyślij dowolną wiadomość do bota [@userinfobot](https://t.me/userinfobot) na Telegramie.
   - Skopiuj numeryczne pole `Id` (np. `123456789`).
   - *(Jeśli tego nie zrobisz, po uruchomieniu bota napisz do niego `/start`, a on sam wyświetli Twoje ID).*

3. **Repozytorium na GitHub:**
   - Utwórz nowe (np. prywatne) repozytorium na swoim koncie GitHub i wypchnij do niego ten kod.

---

## 🚀 Wdrożenie w Dokploy (krok po kroku)

1. Zaloguj się do swojego panelu **Dokploy** na VPS.
2. W wybranym projekcie kliknij **Create Application**.
3. Wybierz typ źródła: **GitHub** i wskaż swoje repozytorium oraz gałąź (`main`).
4. W sekcji **Build Type** upewnij się, że wybrane jest **Dockerfile** (Dokploy automatycznie wykryje plik [Dockerfile](file:///home/fojciol/Documents/projekty/telegrambot-metadata-remover/Dockerfile)).
5. Przejdź do zakładki **Environment** (Zmienne środowiskowe) i dodaj:
   ```env
   BOT_TOKEN=twoj_token_z_botfather
   ALLOWED_USER_IDS=twoje_telegram_id
   ```
   *(Jeśli chcesz dać dostęp kilku osobom, oddziel ich identyfikatory przecinkami, np. `12345678,98765432`).*
6. Kliknij **Deploy**.
7. Dokploy zbuduje obraz Dockera z ExifTool i uruchomi bota. Gotowe! Bot działa i nasłuchuje w trybie Long Polling.

---

## 🛠️ Uruchomienie lokalne / testowe (Docker Compose)

Jeśli chcesz uruchomić bota lokalnie lub bezpośrednio na serwerze przez terminal:

1. Skopiuj plik ze zmiennymi:
   ```bash
   cp .env.example .env
   ```
2. Uzupełnij w pliku `.env` swój `BOT_TOKEN` oraz `ALLOWED_USER_IDS`.
3. Uruchom kontener:
   ```bash
   docker compose up -d --build
   ```
4. Aby sprawdzić logi:
   ```bash
   docker compose logs -f
   ```

---

## ⚙️ Zmienne środowiskowe

| Zmienna | Wymagana | Domyślnie | Opis |
|---|---|---|---|
| `BOT_TOKEN` | **Tak** | — | Token API bota z @BotFather |
| `ALLOWED_USER_IDS` | Nie | *(puste)* | Numeryczne ID użytkowników Telegrama rozdzielone przecinkami. Jeśli puste, bot odpowiada każdemu. |
| `MAX_FILE_SIZE_MB` | Nie | `30` | Maksymalny dozwolony rozmiar pobieranego pliku (w MB). |
| `TEMP_DIR` | Nie | `/tmp/bot_media` | Ścieżka katalogu tymczasowego w kontenerze. |
| `TELEGRAM_API_SERVER` | Nie | *(chmura Telegrama)* | Adres lokalnego serwera Telegram Bot API (np. `http://telegram-bot-api:8081`). Wymagany dla plików > 20 MB z powodu limitu chmury Telegrama. |

---

## 💡 Jak najlepiej korzystać z bota na Telegramie

- **Dla zdjęć:** Aplikacje mobilne Telegrama domyślnie kompresują wysyłane zdjęcia, usuwając część metadanych jeszcze przed wysyłką. Aby wysłać zdjęcie z pełnymi oryginalnymi danymi EXIF/GPS, wybierz w Telegramie **Wyślij jako plik / dokument (bez kompresji)**.
- **Dla wideo i dokumentów:** Możesz wysłać plik normalnie – bot przetworzy go i odeśle z powrotem.
