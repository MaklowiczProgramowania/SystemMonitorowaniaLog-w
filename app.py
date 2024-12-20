from flask import Flask, render_template, render_template_string
import folium, sqlite3, requests, time, logging

# Funkcje do łączenia z bazą danych
logging.basicConfig(level=logging.INFO)

def polaczZBaza():
    return sqlite3.connect('logs_database.db')

def pobierzAdresyZTabel(tabele):
    zapytanie = " UNION ".join([f"SELECT ip FROM {tabela}" for tabela in tabele])
    with polaczZBaza() as baza:
        kursor = baza.cursor()
        return [wiersz[0] for wiersz in kursor.execute(f"SELECT DISTINCT ip FROM ({zapytanie})").fetchall()]

def pobierzPrzetlumaczoneAdresy():
    with polaczZBaza() as baza:
        kursor = baza.cursor()
        return [wiersz[0] for wiersz in kursor.execute("SELECT ip FROM translated_addresses").fetchall()]

def pobierzAdresWykSzer():
    """Pobiera dane z tabeli translated_addresses."""
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

# Ścieżki na stronie
app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/mapaPoloczen")
def mapaPoloczen():
    adresy = pobierzAdresWykSzer()
    if not adresy:
        print("Brak danych do stworzenia mapy.")
        return
    
    mapa = folium.Map(location=[0, 0], width="100vw", height="100vh", position="absolute", top="56px", left="0px", zoom_start=3)
    
    for adres in adresy:
        folium.Marker(
            location=[adres["lat"], adres["lon"]],
            popup=f"IP: {adres['ip']}",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(mapa)

    iframe = mapa.get_root()._repr_html_()

    return render_template_string(
        """
            {% extends "nawigacja.html" %}
            {% block title %} / 🗺️Mapa połączeń{% endblock %}
            {% block content %}
                {{ iframe|safe }}
            {% endblock %}
        """,
        iframe=iframe,
    )

@app.route("/wykresPoloczen")
def wykresPoloczen():
    return render_template("wykresPoloczen.html", okresCzasuWykresu = "Wykres z pełnego zakresu")

@app.route("/wykresPoloczen/<okresCzasu>")
def wykresPoloczenZakres(okresCzasu):
    if okresCzasu == "dzisiaj":
        return render_template("wykresPoloczen.html", okresCzasuWykresu = "Wykres z dzisiaj")
    elif okresCzasu == "aktTydzien":
        return render_template("wykresPoloczen.html", okresCzasuWykresu = "Wykres z aktualnego tygodnia")
    elif okresCzasu == "popTydzien":
        return render_template("wykresPoloczen.html", okresCzasuWykresu = "Wykres z poprzedniego tygodnia")

if __name__ == "__main__":
    # Aktualizuj baze danych
    synchronizujAdresy()
    # Uruchom aplikacje
    app.run(debug=True)