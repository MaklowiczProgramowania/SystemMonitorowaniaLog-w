from flask import Flask, redirect, url_for, render_template, request
app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/mapaPoloczen")
def mapaPoloczen():
    return render_template("mapaPoloczen.html")

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
    app.run(debug=True)