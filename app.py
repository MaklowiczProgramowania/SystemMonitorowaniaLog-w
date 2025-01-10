import sqlite3
from flask import Flask, render_template, render_template_string, request
import folium, re, time, logging
from folium.plugins import MarkerCluster
from datetime import datetime, timedelta
import requests

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize Flask app
app = Flask(__name__)

# Functions for database connection
def polaczZBaza():
    return sqlite3.connect('logs_database.db')

def pobierzAdresyZTabel(tabele):
    zapytanie = " UNION ".join([f"SELECT ip FROM {tabela}" for tabela in tabele])
    with polaczZBaza() as baza:
        kursor = baza.cursor()
        return [wiersz[0] for wiersz in kursor.execute(f"SELECT DISTINCT ip FROM ({zapytanie})").fetchall()]

def pobierzWszystkoZTabeli(tabela):
    zapytanie_schemat = f"PRAGMA table_info({tabela})"
    zapytanie_dane = f"SELECT * FROM {tabela}"
    with polaczZBaza() as baza:
        kursor = baza.cursor()
        nazwy_kolumn = [kolumna[1] for kolumna in kursor.execute(zapytanie_schemat)]
        dane_tabeli = kursor.execute(zapytanie_dane).fetchall()
        return nazwy_kolumn, dane_tabeli

def pobierzPrzetlumaczoneAdresy():
    with polaczZBaza() as baza:
        kursor = baza.cursor()
        return [wiersz[0] for wiersz in kursor.execute("SELECT ip FROM translated_addresses").fetchall()]

def pobierzAdresWykSzer():
    with polaczZBaza() as baza:
        kursor = baza.cursor()
        return [
            {"ip": wiersz[0], "lat": wiersz[1], "lon": wiersz[2]}
            for wiersz in kursor.execute("SELECT ip, lat, lon FROM translated_addresses WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
        ]

def przetlumaczAdresy(adresy):
    wynik = []
    for i in range(0, len(adresy), 100):
        partia = adresy[i:i+100]
        try:
            odpowiedz_api = requests.post("http://ip-api.com/batch", json=partia, timeout=10).json()
        except requests.RequestException as e:
            logging.error(f"Błąd podczas wywołania API: {e}")
            continue
        for wpis in odpowiedz_api:
            if wpis["status"] == "success":
                wynik.append((wpis["query"], wpis["lat"], wpis["lon"]))
            else:
                wynik.append((wpis["query"], None, None))
        time.sleep(1)  # Pauza na potrzeby limitu API
    return wynik

def aktualizujPrzetlumaczoneAdresy(nowe_adresy):
    przetlumaczone_adresy = przetlumaczAdresy(nowe_adresy)
    with polaczZBaza() as baza:
        kursor = baza.cursor()
        kursor.executemany(
            "INSERT INTO translated_addresses (ip, lat, lon) VALUES (?, ?, ?)",
            przetlumaczone_adresy
        )
        baza.commit()

def synchronizujAdresy():
    obecne_adresy = set(pobierzAdresyZTabel(['apache_access_logs', 'nginx_logs']))
    zapisane_adresy = set(pobierzPrzetlumaczoneAdresy())
    nowe_adresy = list(obecne_adresy - zapisane_adresy)
    if nowe_adresy:
        aktualizujPrzetlumaczoneAdresy(nowe_adresy)

# Function for normalizing date format
def normalize_date(log_date):
    pattern = r'(\d{2})/(\w{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2})'
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05",
        "Jun": "06", "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10",
        "Nov": "11", "Dec": "12"
    }
    match = re.match(pattern, log_date)
    if match:
        day, month_str, year, hour, minute, second = match.groups()
        return f"{year}-{months.get(month_str, '01')}-{day} {hour}:{minute}:{second}"
    return None

# Function to fetch logs and filter by date
def get_filtered_logs(start_date, end_date, tabela):
    if not re.match(r'^[a-zA-Z0-9_]+$', tabela):  # Validate table name
        raise ValueError("Invalid table name.")
    
    query = f"SELECT date_time FROM {tabela}"
    with polaczZBaza() as con:
        cursor = con.cursor()
        rows = cursor.execute(query).fetchall()

    return [
        normalize_date(row[0]) for row in rows
        if normalize_date(row[0]) and start_date <= normalize_date(row[0])[:10] <= end_date
    ]

# Function for date range based on period
def get_date_range(period):
    today = datetime.now()
    if period == "popTydzien":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
    elif period == "aktTydzien":
        start = today - timedelta(days=today.weekday())
        end = today
    elif period == "dzisiaj":
        start = end = today
    else:
        return None, None
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

# Grouping logs by different time intervals
def group_logs(filtered_logs, start_date, end_date, group_by="day"):
    log_counts = {}
    start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
    end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)  # End of the day

    if group_by == "day":
        current_date = start_datetime
        while current_date < end_datetime:
            log_counts[current_date.strftime('%Y-%m-%d')] = 0
            current_date += timedelta(days=1)
        for log in filtered_logs:
            date = log[:10]
            if date in log_counts:
                log_counts[date] += 1

    elif group_by == "hour" and len(set(log[:10] for log in filtered_logs)) == 1:
        log_counts = {f"{hour:02d}:00": 0 for hour in range(24)}
        for log in filtered_logs:
            hour = log[11:13] + ":00"
            log_counts[hour] += 1

    elif group_by == "4hour":
        current_datetime = start_datetime
        while current_datetime < end_datetime:
            key = current_datetime.strftime('%Y-%m-%d %H:%M')
            log_counts[key] = 0
            current_datetime += timedelta(hours=4)
        for log in filtered_logs:
            log_time = datetime.strptime(log, '%Y-%m-%d %H:%M:%S')
            for interval_start in log_counts.keys():
                interval_start_dt = datetime.strptime(interval_start, '%Y-%m-%d %H:%M')
                if interval_start_dt <= log_time < interval_start_dt + timedelta(hours=4):
                    log_counts[interval_start] += 1
                    break

    return sorted(log_counts.keys()), [log_counts[key] for key in sorted(log_counts.keys())]

# Flask routes for map and log visualization
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/tabele")
def tabele():
    nazwyTabel = ["nginx_logs", "apache_error_logs", "apache_access_logs"]
    daneZTabel = [
        {
            "tabela": tabela,
            "kolumny": pobierzWszystkoZTabeli(tabela)[0],
            "dane": pobierzWszystkoZTabeli(tabela)[1],
        }
        for tabela in nazwyTabel
    ]
    return render_template("tabele.html", daneZTabel = daneZTabel)

@app.route("/mapaPoloczen")
def mapaPoloczen():
    adresy = pobierzAdresWykSzer()
    if not adresy:
        print("Brak danych do stworzenia mapy.")
        return
    
    attr = ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ''contributors, &copy; <a href="https://cartodb.com/attributions">CartoDB</a>')
    mapa = folium.Map(location=[50, 0], tiles="cartodb positron", attr=attr, width="100vw", height="897px", zoom_start=3, min_zoom=3, max_zoom=8, max_bounds=True)
    
    marker_cluster = MarkerCluster(
        name='1000 clustered icons',
        overlay=True,
        control=False,
        icon_create_function=None
    )

    for adres in adresy:
        location = adres["lat"], adres["lon"]
        marker = folium.Marker(location=location)
        popup = f"IP: {adres['ip']}"
        folium.Popup(popup).add_to(marker)
        marker_cluster.add_child(marker)

    marker_cluster.add_to(mapa)

    iframe = mapa.get_root()._repr_html_()

    return render_template_string(
        """
            {% extends "nawigacja.html" %}
            {% block bodyContent %}
                <div style="padding-top: 50px">
                    {{ iframe|safe }}
                </div>
            <script type="text/javascript">
                document.body.style.overflow = "hidden";
            </script>
            {% endblock %}
        """,
        iframe=iframe,
    )

@app.route("/wykresPoloczen/<okresCzasu>")
def wykresPoloczenZakres(okresCzasu):
    tabela = request.args.get("tabela", "nginx_logs")
    start_date, end_date = get_date_range(okresCzasu)
    if not start_date or not end_date:
        return "Nieprawidłowy okres czasu", 400

    filtered_logs = get_filtered_logs(start_date, end_date, tabela)
    delta = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days

    if delta == 0:
        group_by = "hour"  
    elif delta == 1:
        group_by = "4hour"  
    else:
        group_by = "day"  

    dates, counts = group_logs(filtered_logs, start_date, end_date, group_by)

    if delta == 0:
        dates = [date for date in dates]

    okresCzasuWykresu = {
        "popTydzien": f"Wykres z tabeli {tabela}: Poprzedni tydzień (poniedziałek-niedziela)",
        "aktTydzien": f"Wykres z tabeli {tabela}: Bieżący tydzień (poniedziałek-dzisiaj)",
        "dzisiaj": f"Wykres z tabeli {tabela}: Dzisiaj"
    }.get(okresCzasu, "Wykres")

    return render_template('wykresPoloczen.html', dates=dates, counts=counts, okresCzasuWykresu=okresCzasuWykresu)

@app.route("/wykresPoloczen", methods=['GET'])
def search():
    tabela = request.args.get('tabela', 'nginx_logs')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if not start_date or not end_date:
        return "Musisz podać zakres dat", 400

    filtered_logs = get_filtered_logs(start_date, end_date, tabela)
    delta = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days

    if delta == 0:
        group_by = "hour"
    elif delta == 1:
        group_by = "4hour"
    else:
        group_by = "day"

    dates, counts = group_logs(filtered_logs, start_date, end_date, group_by)
    return render_template("wykresPoloczen.html", dates=dates, counts=counts)

if __name__ == "__main__":
    synchronizujAdresy()
    app.run(debug=True)
