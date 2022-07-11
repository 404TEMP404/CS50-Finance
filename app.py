import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

from datetime import datetime, timezone

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

db.execute("CREATE TABLE IF NOT EXISTS purchases (id INTEGER, user_id NUMERIC NOT NULL, symbol TEXT NOT NULL, shares NUMERIC NOT NULL, price NUMERIC NOT NULL, timestamp TEXT, PRIMARY KEY(id), FOREIGN KEY(user_id) REFERENCES users(id))")
db.execute("CREATE INDEX IF NOT EXISTS purhcases_user_id_intex ON purchases (user_id)")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    stocks = total_shares()
    total = 0
    for symbol, shares in stocks.items():
        result = lookup(symbol)
        name, price = result["name"], result["price"]
        t_price = price * shares
        total += t_price
        stocks[symbol] = (name, shares, usd(price), usd(t_price))
    cash = db.execute("SELECT cash FROM users WHERE id = ? ", session["user_id"])[0]['cash']
    total += cash
    return render_template("index.html", stocks=stocks, cash=usd(cash), total=usd(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "GET":
        return render_template("buy.html")
    # Check validity
    result = lookup(request.form.get("symbol"))
    if not result:
        return apology("Invalid symbol", 400)
    try:
        shares = int(request.form.get("shares"))
    except:
        return apology("Invalid shares", 400)
    if shares <= 0:
        return apology("Invalid shares", 400)

    # Check current cash
    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]

    # Make sure of enough money
    price = shares * result["price"]
    remain = cash - price
    if remain < 0:
        return apology("Insufficient cash", 400)

    # Update user's cash
    db.execute("UPDATE users SET cash = ? WHERE id = ?", remain, session["user_id"])

    # Insert transaction
    db.execute("INSERT INTO purchases (user_id, symbol, shares, price, timestamp) VALUES (?, ?, ?, ?, ?)",
               session["user_id"], result["symbol"], shares, result["price"], current_time())

    return redirect("/")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    rows = db.execute("SELECT symbol, shares, price, timestamp FROM purchases WHERE user_id = ?", session["user_id"])
    return render_template("history.html", rows=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 400)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    if request.method == "POST":
        result = lookup(request.form.get("symbol"))
        if not result:
            return apology("Invalid symbol", 400)
        return render_template("quoted.html", price=usd(result["price"]), name=result["name"], symbol=result["symbol"])
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        # Get username, password, and confirmed password
        name = request.form.get("username")
        password = request.form.get("password")
        CPass = request.form.get("confirmation")

        # Check the validity of the username
        if not name or len(db.execute("SELECT username FROM users WHERE username = ?", name)) > 0:
            return apology("Invalid username", 400)

        # Check the validity of the password
        if not password:
            return apology("Invalid password", 400)

        # Check the validity of the confirmed password
        if not CPass or CPass != password:
            return apology("Passwords must match", 400)

        # Hash the password
        hashed = generate_password_hash(password)

        # Register the user into the database
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", name, hashed)

        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    stocks = total_shares()
    if request.method == "GET":
        return render_template("sell.html", stocks=stocks.keys())

    symbol = request.form.get("symbol")
    shares = int(request.form.get("shares"))
    # check whether there are sufficient shares to sell
    if stocks[symbol] < shares:
        return apology("Insufficient shares", 400)
    # Execute sell transaction: look up sell price, and add fund to cash,
    result = lookup(symbol)
    user_id = session["user_id"]
    cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)[0]['cash']
    price = result["price"]
    remain = cash + price * shares
    db.execute("UPDATE users SET cash = ? WHERE id = ?", remain, user_id)
    # Log the transaction into orders
    db.execute("INSERT INTO purchases (user_id, symbol, shares, price, timestamp) VALUES (?, ?, ?, ?, ?)",
               user_id, symbol, -shares, price, current_time())
    return redirect("/")


def total_shares():
    user_id = session["user_id"]
    t_shares = {}
    query = db.execute("SELECT symbol, shares FROM purchases WHERE user_id = ?", user_id)
    for q in query:
        symbol, shares = q["symbol"], q["shares"]
        t_shares[symbol] = t_shares.setdefault(symbol, 0) + shares
    t_shares = {k: v for k, v in t_shares.items() if v != 0}
    return t_shares


def current_time():
    now_utc = datetime.now(timezone.utc)
    return str(now_utc.date()) + ' @time ' + now_utc.time().strftime("%H:%M:%S")