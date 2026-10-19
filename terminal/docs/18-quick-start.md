# 18. Quick start: the terminal on your own computer

This gets the whole terminal running on one Windows or Mac computer: the
dashboard in your browser at **https://localhost**, and every strategy
instance paper trading on live prices, each with its own `Paper 50K` account.
Nothing here can place a real order: fills are simulated and LIVE execution
does not exist in this version.

Paper trading runs only while the computer is awake and Docker Desktop is
running. A computer that sleeps at night pauses it; it catches up when it wakes.

## What you need

| | |
|---|---|
| Computer | Windows 10/11 or macOS; 8 GB of memory or more; about 5 GB free disk |
| Docker Desktop | Free for personal use: <https://www.docker.com/products/docker-desktop/> |
| The code | GitHub repository `kelnine/k`, branch `claude/epic-gates-fbjol7` |
| Optional | A free OANDA practice account, for gold, silver, FX and indices (step 3) |

## The easy way: let Claude on your computer do it

A Claude session that runs **on your computer** can do every step below for
you; you only approve what it asks and type your own passwords. (Claude in the
cloud cannot reach your computer.)

1. Open the **Claude desktop app**, go to **Code** and start a session on this
   computer (not in the cloud). Pick a folder such as your Documents folder.
2. Paste the prompt below and send it. Approve the steps it asks about.

```text
Set up K Terminal on this computer and start it. It is a paper-trading terminal
(no real orders) from the public GitHub repository kelnine/k, branch
claude/epic-gates-fbjol7. Work in a folder named KTerminal inside the folder of
this session.

1. Download https://github.com/kelnine/k/archive/refs/heads/claude/epic-gates-fbjol7.zip
   and unzip it into KTerminal (the zip holds one top folder; the terminal is its
   "terminal" subfolder). Read terminal/docs/18-quick-start.md and follow it.
2. Check Docker with "docker info". If Docker Desktop is missing, ask me first,
   then install it: Windows "winget install -e --id Docker.DockerDesktop"; Mac
   "brew install --cask docker" if Homebrew is installed, otherwise the Docker.dmg
   for my chip from docs.docker.com. Tell me when a restart is needed (I will
   come back to this session and say "continue"). Have me open Docker Desktop,
   accept its terms and wait for "Engine running", and tick "Start Docker Desktop
   when you sign in" in its settings.
3. Ask me whether I have an OANDA practice API token (for gold, silver, forex and
   indices). If yes, make sure terminal/deploy/secrets/oanda_token exists and open
   it in Notepad (Windows) or TextEdit (Mac) so that I paste the token myself.
   Never ask me to paste the token into this chat and never print that file.
4. In the terminal folder run the start script: Windows
   "powershell -ExecutionPolicy Bypass -File .\start.ps1", Mac "bash start.sh".
   The first build takes 5-10 minutes. If no dashboard login exists, the script
   opens a separate window where I type my username and password myself; wait
   until I say I am done. If no window opened, ask me to run the login command
   the script printed, in a terminal of my own.
5. Open https://localhost in my browser and tell me how to pass the certificate
   warning (the certificate is made by this computer).
6. Ask me whether this computer should stay awake while it is plugged in (paper
   trading pauses while it sleeps); change the power setting only if I agree.

If a step fails, show me the error and the fix from the guide. Do not edit the
files of the terminal and do not run "docker compose down -v".
```

Later, to install a new version, start a session in the same folder and paste:

```text
Update K Terminal in the KTerminal folder to the latest version of branch
claude/epic-gates-fbjol7 of github.com/kelnine/k, following "Installing a new
version" in terminal/docs/18-quick-start.md of the new version: download the
branch zip into a new folder, move terminal/deploy/secrets and terminal/.env (if
present) over from the old folder, end the open paper session, start the new
version with the start script, then delete the old folder only after the new
one runs and I agree.
```

The rest of this page is the same setup done by hand.

## 1. Install Docker Desktop

**Windows:** run the installer, keep the default (WSL 2), restart when asked.
Open Docker Desktop and wait until it shows *Engine running*.

**Mac:** pick the download for your chip (Apple or Intel: Apple menu → About
This Mac), drag Docker to Applications, open it and wait until it shows
*Engine running*.

In Docker Desktop's settings, turn on *Start Docker Desktop when you sign in*:
the terminal then comes back by itself after a restart.

## 2. Get the code

On GitHub, open the repository, switch the branch selector to
`claude/epic-gates-fbjol7`, then **Code → Download ZIP** and unzip it, for
example into your Documents folder. (With git instead:
`git clone -b claude/epic-gates-fbjol7 https://github.com/kelnine/k.git`.)

Inside the unzipped folder is a folder called `terminal`. Every step below
happens there.

## 3. Optional, but best done now: your OANDA token

Crypto prices need no account. Gold, silver, EUR/USD, GBP/USD, NAS100, US30
and US500 come from OANDA, which needs a token. Get it before the first start:
markets added later need a new paper session (see *Adding the token later*).

1. Open a free practice (demo) account at <https://www.oanda.com>.
2. In the account area: **Manage API Access → Generate** and copy the token.
3. Run the start script once (step 4) so that it creates the file
   `terminal/deploy/secrets/oanda_token`, or create that empty file yourself.
4. Open the file in Notepad (Windows) or TextEdit (Mac), paste the token,
   save. Nothing else goes in the file.

The token only downloads prices. Keep it in that file: never paste it into a
chat, an email or a TradingView alert. The file never leaves your computer
(`deploy/secrets/` is excluded from git) and Docker gives it to the engine only.

## 4. Start it

**Windows:** open the `terminal` folder in File Explorer, click the address
bar, type `powershell` and press Enter. In the blue window:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

**Mac:** open the Terminal app, type `cd ` (with a space), drag the `terminal`
folder onto the window, press Enter, then:

```bash
bash start.sh
```

The first start downloads and builds everything: about 5–10 minutes. At the
end it asks for a **username and password** (12 characters or more): that is
your dashboard login. Run the same command again any time to restart the
terminal; your data is kept.

## 5. Open the terminal

Go to **https://localhost** in your browser. The first time, the browser warns
that the connection is not private. The certificate was made by your own
computer, so continue: Chrome or Edge, **Advanced → Continue to localhost**;
Safari, **Show Details → visit this website**. Sign in with the login from
step 4.

## What you will see

| Page | What it shows |
|---|---|
| **Overview** | The paper runtime (*Warming up* or *Running*), all paper accounts together, the kill switch (**Halt all trading**), the data feed of every market, and the leaderboard: every strategy instance ranked by its own recorded trades |
| **Instruments** | Each market and its price feed; click one for its details |
| **Chart** | Candles with the trades of the instances you pick |
| **Trades / Signals** | Every paper trade and every signal, including signals that were skipped and why |
| **System** | Instances and their settings, runs, faults, kill-switch history |

Click a leaderboard row for one account: equity curve, open positions, trades
(each with an *Explain* button) and its signals.

**The first hour.** The runtime starts with *Warming up*: it downloads up to
60 days of 1-minute history per market and runs every strategy over it, so
their indicators are ready before the first live minute. Nothing trades during
warm-up; on a typical computer it takes from several minutes up to about an
hour. Then the status turns to *Running* and every closed minute is processed.

**Reading results.** Every number on the leaderboard comes from the account's
recorded trades. *low n* means fewer than 30 closed trades: too few to judge.
Instance names read *strategy · variant · timeframe*, e.g.
`supertrend_flip_trail_15m`. The two `demo_…` rows are built-in examples, not
your strategies (to drop them, delete their entries in `config/lab.yaml` and
start a new session).

**Markets without prices** show *no provider* in the data feeds with the
reason: no OANDA token yet, or MNQ, which has no free live source. The
instances on those markets wait; everything else trades.

## Everyday use

All commands run in the `terminal` folder (PowerShell on Windows, Terminal on
Mac). `dc` below stands for
`docker compose --project-directory deploy -f deploy/docker-compose.yml`.

| To | Run |
|---|---|
| Start or restart | the start script from step 4 |
| Stop (data is kept) | `dc stop` |
| See what the engine is doing | `dc logs --tail=50 engine` |
| Paper status in text | `dc exec engine kterminal paper status` |
| Which markets have prices | `dc exec engine kterminal data sources` |
| Add another login | `dc exec api kterminal users add NAME --role VIEWER` (or `OPERATOR`, `ADMIN`) |

**Crypto exchange blocked where you live** (Binance is not available in the
US, for example): create a file `terminal/.env` containing

```
KT_MARKETDATA__DISABLED_PROVIDERS=binance_usdm,binance_spot,bybit_linear
```

and run the start script again. BTC, NEAR and SOL then use Coinbase; PUMP has
no other source and waits.

**Adding the token later.** Markets that get prices during a session are not
warmed up, so start a new paper session (this closes the open paper positions
at their last price and starts every account afresh):

```bash
dc stop engine
dc run --rm engine paper end-session
```

then run the start script again.

**Installing a new version.** Your data lives in Docker, not in the folder, so
a new version simply replaces the folder:

1. Download and unzip the new version next to the old folder.
2. Move `terminal/deploy/secrets` (and `terminal/.env`, if you made one) from
   the old folder into the new one.
3. In the new `terminal` folder: `dc stop engine`, then
   `dc run --rm engine paper end-session` (new code cannot continue a session
   that old code started; this closes its paper positions at their last price).
4. Run the start script in the new folder. Delete the old folder once the new
   one runs.

**Start over completely** (deletes every account, trade and login):
`dc down -v`, then the start script.

## When something is wrong

| Symptom | Fix |
|---|---|
| *Docker is not running* | Open Docker Desktop and wait for *Engine running* |
| Port 80 or 443 already in use | Another web server runs on this computer; stop it, or ask for help changing the ports |
| Sign-in page does not load | Wait a minute after the start script finishes; `dc ps` should show `api` as *healthy* |
| Status *Error* on the Overview | The message says why; [16.8](16-running-paper-trading.md#168-when-something-goes-wrong) lists the causes |
| Status *Error: cannot be resumed* after updating the code or the settings | The strategies changed, so the old session cannot continue: `dc exec engine kterminal paper end-session` starts a new one within a minute |
| No login was created (the window was closed, or the start ran without a keyboard) | Windows `powershell -ExecutionPolicy Bypass -File .\start.ps1 -Login`; Mac `bash start.sh --login` |
| Forgot the password | `dc exec api kterminal users set-password NAME` |

Background for the curious: how paper trading works,
[16](16-running-paper-trading.md); the dashboard,
[17](17-dashboard.md); market data, [15](15-market-data.md).
