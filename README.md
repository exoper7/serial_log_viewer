# Serial Log Viewer

Podgląd i zbieranie logów z portu COM (ESP-IDF i podobne formaty).

```powershell
pip install -r requirements.txt
python serial_log_viewer.py            # albo: python serial_log_viewer.py plik.log
```

## Funkcje

- **Lista wątków po lewej** – budowana na bieżąco z tagów ESP-IDF (`I (123) TAG: ...`).
  Klik = pokaż/ukryj, dwuklik = tylko ten wątek, prawy klik = menu (odwróć, ukryj wszystkie…).
  Nowe wątki są domyślnie widoczne.
- **Filtr poziomów** – Error / Warning / Info / Debug / Verbose / Inne (z licznikami).
  Prawy klik na poziomie = tylko ten poziom.
- **Wyszukiwanie** (Ctrl+F) – tekst lub regex (`.*`), opcjonalnie z wielkością liter (`Aa`).
- **Szczegóły wpisu** – panel pod logiem; JSON w wiadomości jest formatowany.
- **Zapis do pliku** – każde połączenie zapisuje surowy log z czasem hosta do `logs/<PORT>_<data>.log`.
  Te pliki (i dowolne inne logi tekstowe) można wczytać z powrotem (Ctrl+O).
- **Auto-połączenie** – po resecie/odłączeniu USB port jest otwierany ponownie.
- **Reset ESP** – impuls na RTS (EN). Port otwierany jest z DTR/RTS nieaktywnymi, jak w `idf.py monitor`.
- Śledzenie końca logu wyłącza się samo po przewinięciu w górę; `End` włącza je z powrotem.

Rozpoznawane formaty: ESP-IDF (z kolorami ANSI), `[ERR]/[WRN]/[INF]/[DBG]`, `DEBUG:/ERROR:`,
linie ROM/bootloadera (`rst:` jako Warning – widać restarty), panic (Guru Meditation, Backtrace) jako Error.
Linie sklejone przez równoległe logowanie z kilku wątków są rozdzielane.

W pamięci trzymane jest do 300 000 wpisów (najstarsze są usuwane); plik logu zawiera wszystko.
