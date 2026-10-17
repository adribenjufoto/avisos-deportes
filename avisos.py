#!/usr/bin/env python3
"""Avisos por Telegram de los partidos del FC Barcelona, el CB Canarias y el CD Tenerife.

- Por la mañana: qué partidos hay hoy (dónde, contra quién, a qué hora).
- Barça: aviso una hora antes de cada partido.
- Al acabar cada jornada de liga (o de la fase liga de la Champions): la clasificación.

Uso:
  python3 avisos.py                 -> lo normal (lo lanza GitHub Actions cada 10 minutos)
  python3 avisos.py --prueba        -> enseña en pantalla lo que mandaría ahora (no envía ni guarda)
  python3 avisos.py --muestra       -> enseña un ejemplo de cada tipo de mensaje con los datos de hoy
  python3 avisos.py --test-telegram -> envía un mensaje de prueba
"""
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "datos")
CFG = json.load(open(os.path.join(AQUI, "config.json"), encoding="utf-8"))
ZONA = ZoneInfo(CFG["zona_horaria"])
CANARIAS = ZoneInfo("Atlantic/Canary")
UTC = dt.timezone.utc
AHORA = dt.datetime.now(UTC)
HOY = AHORA.astimezone(ZONA).date()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
PRUEBA = "--prueba" in sys.argv or "--muestra" in sys.argv
ESPN = "https://site.api.espn.com/apis"
ACB_CALENDARIO = "https://acb.com/es/liga/calendario"
ACB_CLASIFICACION = "https://acb.com/es/liga/clasificacion"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- utilidades

def pedir(url, datos=None, json_resp=True, intentos=3):
    cab = {"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"}
    cuerpo = None
    if datos is not None:
        cuerpo = json.dumps(datos).encode()
        cab["Content-Type"] = "application/json"
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, data=cuerpo, headers=cab)
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode("utf-8", "replace")
                return json.loads(txt) if json_resp else txt
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                log(f"  aviso: {url[:80]} respondió {e.code}")
                return None
            log(f"  aviso: fallo {url[:80]} ({e}); reintento {i + 1}")
        except Exception as e:
            log(f"  aviso: fallo {url[:80]} ({e}); reintento {i + 1}")
        time.sleep(3 * (i + 1))
    return None


def leer(nombre, defecto):
    ruta = os.path.join(DATOS, nombre)
    if os.path.exists(ruta):
        return json.load(open(ruta, encoding="utf-8"))
    return defecto


def guardar(nombre, obj):
    os.makedirs(DATOS, exist_ok=True)
    with open(os.path.join(DATOS, nombre), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def fecha_iso(txt):
    """'2026-10-20T19:00Z' o '2026-10-20T19:00:00Z' -> datetime UTC"""
    txt = txt.replace("Z", "+00:00")
    if re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d\+", txt):
        txt = txt[:16] + ":00" + txt[16:]
    return dt.datetime.fromisoformat(txt).astimezone(UTC)


def hora(p):
    if not p["hora_valida"]:
        return "hora por confirmar"
    ini = fecha_iso(p["inicio"])
    txt = ini.astimezone(ZONA).strftime("%H:%M") + " (hora suiza)"
    if p.get("hora_canarias"):
        txt += f" · {ini.astimezone(CANARIAS).strftime('%H:%M')} en Canarias"
    return txt


def dia_bonito(d):
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def e(txt):
    return html.escape(str(txt), quote=False)


# ---------------------------------------------------------------- partidos: ESPN (fútbol)

def nombre_comp(slug, defecto=""):
    return CFG["competiciones"].get(slug, defecto or slug)


def partidos_espn(eq):
    vistos = {}
    for extra in ("", "?fixture=true"):
        d = pedir(f"{ESPN}/site/v2/sports/soccer/all/teams/{eq['espn_id']}/schedule{extra}")
        for ev in (d or {}).get("events", []):
            try:
                c = ev["competitions"][0]
                yo = next(x for x in c["competitors"] if x["team"]["id"] == eq["espn_id"])
                otro = next(x for x in c["competitors"] if x["team"]["id"] != eq["espn_id"])
                local = next(x for x in c["competitors"] if x.get("homeAway") == "home")
                visit = next(x for x in c["competitors"] if x.get("homeAway") == "away")
            except (KeyError, StopIteration, IndexError):
                continue
            st = c.get("status", {}).get("type", {})
            liga = ev.get("league") or {}
            slug = liga.get("slug", "")
            venue = c.get("venue") or {}
            ciudad = (venue.get("address") or {}).get("city", "")
            def goles(x):
                s = x.get("score")
                if isinstance(s, dict):
                    s = s.get("displayValue")
                return s
            p = {
                "id": f"espn:{ev['id']}",
                "equipo": eq["clave"],
                "comp": slug,
                "comp_nombre": nombre_comp(slug, liga.get("name", "")),
                "inicio": ev["date"],
                "hora_valida": ev.get("timeValid", True) is not False,
                "local": local["team"]["displayName"],
                "visitante": visit["team"]["displayName"],
                "rival": otro["team"]["displayName"],
                "en_casa": yo.get("homeAway") == "home",
                "estadio": ", ".join(x for x in (venue.get("fullName"), ciudad) if x),
                "estado": st.get("state", "pre"),
                "goles_local": goles(local),
                "goles_visit": goles(visit),
                "tv": "",
                "hora_canarias": eq.get("hora_canarias", False),
            }
            if p["estado"] == "post" and not st.get("completed", True):
                p["estado"] = "aplazado"  # aplazado / suspendido
            vistos[p["id"]] = p
    return list(vistos.values())


def clasificacion_espn(slug):
    d = pedir(f"{ESPN}/v2/sports/soccer/{slug}/standings")
    filas = []
    for grupo in (d or {}).get("children", []):
        for x in grupo.get("standings", {}).get("entries", []):
            st = {s["name"]: s.get("value") for s in x.get("stats", [])}
            filas.append({
                "pos": int(st.get("rank") or 0),
                "equipo": x["team"]["displayName"],
                "id": x["team"]["id"],
                "pj": int(st.get("gamesPlayed") or 0),
                "g": int(st.get("wins") or 0),
                "e": int(st.get("ties") or 0),
                "p": int(st.get("losses") or 0),
                "dif": int(st.get("pointDifferential") or 0),
                "pts": int(st.get("points") or 0),
            })
    filas.sort(key=lambda f: f["pos"])
    return filas


# ---------------------------------------------------------------- partidos: ACB (baloncesto)

def datos_next(pagina):
    """Las webs de acb.com (Next.js) traen los datos dentro de self.__next_f.push(...)"""
    trozos = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', pagina or "")
    return "".join(json.loads('"' + t + '"') for t in trozos)


def partidos_acb(eq):
    s = datos_next(pedir(ACB_CALENDARIO, json_resp=False))
    i = s.find('"rounds":[')
    j = s.rfind('"teams":[', 0, i)
    if i < 0 or j < 0:
        log("  aviso: no encuentro el calendario en acb.com (¿han cambiado la web?)")
        return None
    dec = json.JSONDecoder()
    jornadas, _ = dec.raw_decode(s[i + 9:])
    equipos, _ = dec.raw_decode(s[j + 8:])

    def equipo(ref):
        if isinstance(ref, dict):
            return ref
        try:
            return equipos[int(str(ref).rsplit(":", 1)[1])]
        except (ValueError, IndexError):
            return {}

    lista = []
    for jor in jornadas:
        for m in jor.get("matches", []):
            loc, vis = equipo(m.get("homeTeam")), equipo(m.get("awayTeam"))
            nombres = (loc.get("fullName"), vis.get("fullName"))
            if eq["acb_nombre"] not in nombres or not m.get("startDateTime"):
                continue
            en_casa = nombres[0] == eq["acb_nombre"]
            tv = [c.get("name") for c in (m.get("broadcastChannels") or {}).get("primary", []) if c.get("name")]
            estado = "post" if m.get("matchStatus") == "FINALIZED" else "pre"
            ini = fecha_iso(m["startDateTime"])
            if estado == "pre" and ini < AHORA:
                estado = "in"
            lista.append({
                "id": f"acb:{m['id']}",
                "equipo": eq["clave"],
                "comp": "acb",
                "comp_nombre": nombre_comp("acb") + f" · jornada {jor.get('roundNumber')}",
                "inicio": m["startDateTime"],
                "hora_valida": True,
                "local": nombres[0],
                "visitante": nombres[1],
                "rival": nombres[1] if en_casa else nombres[0],
                "en_casa": en_casa,
                "estadio": "Santiago Martín, La Laguna" if en_casa else "",
                "estado": estado,
                "goles_local": m.get("homeTeamScore"),
                "goles_visit": m.get("awayTeamScore"),
                "tv": ", ".join(tv[:3]),
                "hora_canarias": eq.get("hora_canarias", False),
            })
    return lista


def clasificacion_acb():
    s = datos_next(pedir(ACB_CLASIFICACION, json_resp=False))
    i = s.find('"standings":[{"team":')
    if i < 0:
        log("  aviso: no encuentro la clasificación en acb.com (¿han cambiado la web?)")
        return []
    tabla_acb, _ = json.JSONDecoder().raw_decode(s[i + 12:])
    raiz = {"standings": tabla_acb}

    def resolver(x):
        # algunos equipos vienen como referencia: "$29:props:data:standings:1:rounds:3:matchData:awayTeam"
        for _ in range(5):
            if not (isinstance(x, str) and ":props:data:" in x):
                return x
            nodo = raiz
            try:
                for paso in x.split(":props:data:", 1)[1].split(":"):
                    nodo = nodo[int(paso)] if isinstance(nodo, list) else nodo[paso]
            except (KeyError, IndexError, ValueError, TypeError):
                return {}
            x = nodo
        return x

    filas = []
    for f in tabla_acb:
        nombre = (resolver(f.get("team")) or {}).get("fullName")
        if not nombre:
            continue
        filas.append({"pos": f["position"], "equipo": nombre, "id": nombre, "pj": f["matchesPlayed"],
                      "g": f["wins"], "e": 0, "p": f["losses"],
                      "dif": f.get("plusMinus", f.get("pointsFor", 0) - f.get("pointsAgainst", 0)),
                      "pts": f["wins"]})
    filas.sort(key=lambda f: f["pos"])
    return filas


# ---------------------------------------------------------------- mensajes

def linea_partido(p, eq):
    if p["en_casa"]:
        donde = "🏠 En casa"
    else:
        donde = "✈️ Fuera"
    txt = (f"{eq['emoji']} <b>{e(eq['nombre'])}</b> · {e(p['comp_nombre'])}\n"
           f"🆚 {e(p['rival'])} ({donde})\n"
           f"🕒 {hora(p)}\n")
    if p["estadio"]:
        txt += f"🏟️ {e(p['estadio'])}\n"
    if p["tv"]:
        txt += f"📺 {e(p['tv'])}\n"
    return txt


def mensaje_manana(partidos):
    txt = f"☀️ <b>Hoy hay partido</b> — {dia_bonito(HOY)}\n"
    for p in sorted(partidos, key=lambda x: x["inicio"]):
        txt += "\n" + linea_partido(p, EQUIPOS[p["equipo"]])
    return txt


def mensaje_antes(p):
    eq = EQUIPOS[p["equipo"]]
    mins = round((fecha_iso(p["inicio"]) - AHORA).total_seconds() / 60)
    cuando = "¡Empieza ya!" if mins <= 5 else (f"en {mins} minutos" if mins < 50 else "en 1 hora")
    return (f"⏰ <b>{e(eq['corto'])} juega {cuando}</b>\n\n"
            f"{e(p['local'])} vs {e(p['visitante'])}\n"
            f"🏆 {e(p['comp_nombre'])}\n"
            f"🕒 {hora(p)}\n" + (f"🏟️ {e(p['estadio'])}\n" if p["estadio"] else ""))


def resultado(p, eq):
    gl, gv = p.get("goles_local"), p.get("goles_visit")
    if gl in (None, "") or gv in (None, ""):
        return ""
    try:
        mio, suyo = (int(gl), int(gv)) if p["en_casa"] else (int(gv), int(gl))
        icono = "✅" if mio > suyo else ("➖" if mio == suyo else "❌")
    except ValueError:
        icono = ""
    return f"{icono} {e(p['local'])} {gl}-{gv} {e(p['visitante'])}"


def corto(nombre, n=16):
    nombre = nombre.replace("Atlético Madrid", "Atlético").replace("Real Sociedad", "R. Sociedad")
    nombre = nombre.replace("La Laguna Tenerife", "Canarias (LLT)").replace("Paris Saint-Germain", "PSG")
    return nombre if len(nombre) <= n else nombre[:n - 1] + "."


def tabla(filas, mio, comp):
    pos_mia = next((f["pos"] for f in filas if f["id"] == mio), 0)
    if comp == "uefa.champions":  # 36 equipos: los 8 primeros y los que están alrededor
        filas = [f for f in filas if f["pos"] <= 8 or abs(f["pos"] - pos_mia) <= 2 or f["pos"] in (24, 25)]
    baloncesto = comp == "acb"
    cab = "    Equipo            PJ   V   D  Dif" if baloncesto else "    Equipo            PJ  Pts  Dif"
    lineas, anterior = [cab], 0
    for f in filas:
        if f["pos"] > anterior + 1:
            lineas.append("    ···")
        anterior = f["pos"]
        marca = "▶" if f["id"] == mio else " "
        dif = f"{f['dif']:+d}"
        if baloncesto:
            lineas.append(f"{marca}{f['pos']:>2} {corto(f['equipo']):<17}{f['pj']:>3}{f['g']:>4}{f['p']:>4}{dif:>5}")
        else:
            lineas.append(f"{marca}{f['pos']:>2} {corto(f['equipo']):<17}{f['pj']:>3}{f['pts']:>5}{dif:>5}")
    return "<pre>" + e("\n".join(lineas)) + "</pre>"


def mensaje_clasificacion(pend, filas, nota=""):
    eq = EQUIPOS[pend["equipo"]]
    mio = next((f for f in filas if f["id"] == pend["mio"]), None)
    comp = pend["comp"]
    titulo = nombre_comp(comp)
    txt = f"📊 <b>Clasificación {e(titulo)}</b> — jornada terminada\n"
    if pend.get("resultado"):
        txt += f"{eq['emoji']} Último partido: {pend['resultado']}\n"
    if mio:
        if comp == "acb":
            txt += f"👉 <b>{e(eq['corto'])}: {mio['pos']}.º</b> ({mio['g']} {'victoria' if mio['g'] == 1 else 'victorias'}, {mio['p']} {'derrota' if mio['p'] == 1 else 'derrotas'})\n"
        else:
            txt += f"👉 <b>{e(eq['corto'])}: {mio['pos']}.º con {mio['pts']} puntos</b>\n"
    if nota:
        txt += f"<i>{e(nota)}</i>\n"
    txt += "\n" + tabla(filas, pend["mio"], comp)
    if comp == "uefa.champions":
        txt += "\n<i>1-8: directos a octavos · 9-24: eliminatoria previa</i>"
    return txt


# ---------------------------------------------------------------- Telegram
# El ID del chat se guarda cifrado con el propio token del bot: el repositorio es público
# y así nadie puede ver a quién escribe el bot.

def _xor(datos, token):
    clave = hashlib.sha256(("avisos-deportes" + token).encode()).digest()
    return bytes(b ^ clave[i % len(clave)] for i, b in enumerate(datos))


def cifrar(chat, token):
    return base64.b64encode(_xor(str(chat).encode(), token)).decode()


def descifrar(txt, token):
    try:
        return _xor(base64.b64decode(txt), token).decode()
    except Exception:
        return None


def destinatarios(token, estado, buscar_nuevos=False):
    chats = {c for c in (descifrar(x, token) for x in estado.get("chats", [])) if c and re.fullmatch(r"-?\d+", c)}
    if chats and not buscar_nuevos:
        return sorted(chats)
    yo = pedir(f"https://api.telegram.org/bot{token}/getMe")
    if not (yo or {}).get("ok"):
        log("El TELEGRAM_TOKEN no es válido (Telegram lo rechaza): revisa el secret en GitHub.")
        return sorted(chats)
    r = pedir(f"https://api.telegram.org/bot{token}/getUpdates?limit=100")
    if r is None:  # suele ser un webhook antiguo que impide leer los mensajes: lo quitamos y reintentamos
        pedir(f"https://api.telegram.org/bot{token}/deleteWebhook")
        r = pedir(f"https://api.telegram.org/bot{token}/getUpdates?limit=100")
    antes = len(chats)
    for u in (r or {}).get("result", []):
        chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat") or {}
        if chat.get("id"):
            chats.add(str(chat["id"]))
    if len(chats) != antes:
        log(f"  Telegram: {len(chats) - antes} chat(s) nuevo(s)")
    estado["chats"] = sorted(cifrar(c, token) for c in chats)
    return sorted(chats)


def enviar(texto, estado):
    if PRUEBA:
        print("\n" + "─" * 60 + "\n" + re.sub(r"</?(b|i|pre)>", "", html.unescape(texto)))
        return True
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        log("No hay TELEGRAM_TOKEN configurado; muestro el mensaje:\n" + texto)
        return False
    chats = destinatarios(token, estado)
    if not chats:
        log("Nadie ha escrito todavía al bot de Telegram: no sé a quién enviar. Escríbele cualquier cosa.")
        return False
    ok = True
    for chat in chats:
        r = pedir(f"https://api.telegram.org/bot{token}/sendMessage", datos={
            "chat_id": chat, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True},
            intentos=2)
        if not (r or {}).get("ok"):
            log("  error enviando a Telegram")
            ok = False
        time.sleep(1)
    return ok


# ---------------------------------------------------------------- lógica principal

EQUIPOS = {eq["clave"]: eq for eq in CFG["equipos"]}


def cargar_partidos(estado):
    todos = []
    for eq in CFG["equipos"]:
        if eq["fuente"] == "espn":
            lista = partidos_espn(eq)
        else:
            lista = cargar_acb(eq, estado)
        log(f"  {eq['nombre']}: {len(lista or [])} partidos")
        todos += lista or []
    return todos


def cargar_acb(eq, estado):
    """La web de la ACB pesa mucho: solo la descargamos una vez al día, y cada 10 min solo
    los días en que el Canarias ya ha empezado a jugar y falta saber el resultado."""
    cache = estado.get("cache_acb") or {}
    lista = cache.get("partidos") or []
    hace_falta = cache.get("fecha") != HOY.isoformat() or not lista
    for p in lista:
        ini = fecha_iso(p["inicio"])
        if p["estado"] != "post" and AHORA - dt.timedelta(days=2) < ini <= AHORA:
            hace_falta = True
    if any(x["comp"] == "acb" for x in estado.get("pendientes", [])):
        hace_falta = True
    if hace_falta:
        nueva = partidos_acb(eq)
        if nueva:
            lista = nueva
            estado["cache_acb"] = {"fecha": HOY.isoformat(), "partidos": nueva}
    return lista


_tablas = {}


def clasificacion(comp):
    if comp not in _tablas:
        _tablas[comp] = clasificacion_acb() if comp == "acb" else clasificacion_espn(comp)
    return _tablas[comp]


def id_en_tabla(equipo, comp):
    eq = EQUIPOS[equipo]
    return eq["acb_nombre"] if comp == "acb" else eq["espn_id"]


def pj_en_tabla(equipo, comp):
    mio = id_en_tabla(equipo, comp)
    return next((f["pj"] for f in clasificacion(comp) if f["id"] == mio), None)


def resumen_manana(partidos, estado):
    local = AHORA.astimezone(ZONA)
    if estado.get("resumen_dia") == HOY.isoformat() or local.strftime("%H:%M") < CFG["hora_resumen"]:
        return
    de_hoy = [p for p in partidos if fecha_iso(p["inicio"]).astimezone(ZONA).date() == HOY
              and p["estado"] in ("pre", "in")]
    if de_hoy:
        if enviar(mensaje_manana(de_hoy), estado):
            estado["resumen_dia"] = HOY.isoformat()
    else:
        estado["resumen_dia"] = HOY.isoformat()
    # apuntamos cuántos partidos lleva cada uno en la tabla antes de jugar (sirve para saber
    # luego si el partido era de liga o de una eliminatoria)
    for p in de_hoy:
        if p["comp"] in CFG["con_clasificacion"]:
            pj = pj_en_tabla(p["equipo"], p["comp"])
            if pj is not None:
                estado.setdefault("pj", {})[f"{p['equipo']}|{p['comp']}"] = pj


def avisos_antes(partidos, estado):
    hechos = estado.setdefault("avisados", [])
    for p in partidos:
        minutos = EQUIPOS[p["equipo"]].get("aviso_antes_min") or 0
        if not minutos or p["estado"] != "pre" or not p["hora_valida"] or p["id"] in hechos:
            continue
        falta = (fecha_iso(p["inicio"]) - AHORA).total_seconds() / 60
        if -10 < falta <= minutos + 8:
            if enviar(mensaje_antes(p), estado):
                hechos.append(p["id"])
    estado["avisados"] = hechos[-60:]


def partidos_terminados(partidos, estado):
    hechos = estado.setdefault("terminados", [])
    for p in partidos:
        if p["estado"] != "post" or p["id"] in hechos:
            continue
        hechos.append(p["id"])
        if fecha_iso(p["inicio"]) < AHORA - dt.timedelta(days=3):
            continue  # partido antiguo (p. ej. la primera vez que se ejecuta)
        if p["comp"] not in CFG["con_clasificacion"]:
            continue  # copa, amistoso…: no hay tabla
        estado.setdefault("pendientes", []).append({
            "equipo": p["equipo"], "comp": p["comp"], "partido": p["id"], "inicio": p["inicio"],
            "resultado": resultado(p, EQUIPOS[p["equipo"]]),
            "pj_antes": (estado.get("pj") or {}).get(f"{p['equipo']}|{p['comp']}"),
            "mio": id_en_tabla(p["equipo"], p["comp"]),
        })
        log(f"  terminado: {p['local']} - {p['visitante']} ({p['comp']}): espero a que acabe la jornada")
    estado["terminados"] = hechos[-120:]


def jornadas_terminadas(estado):
    quedan = []
    for pend in estado.get("pendientes", []):
        horas = (AHORA - fecha_iso(pend["inicio"])).total_seconds() / 3600
        filas = clasificacion(pend["comp"])
        if not filas:
            quedan.append(pend)
            continue
        mio = next((f for f in filas if f["id"] == pend["mio"]), None)
        if not mio:
            log(f"  {pend['equipo']} no aparece en la tabla de {pend['comp']}: lo dejo")
            continue
        if pend.get("pj_antes") is not None and mio["pj"] <= pend["pj_antes"]:
            if horas > 10:
                log(f"  {pend['partido']} no ha contado para la tabla (eliminatoria/copa): sin clasificación")
            else:
                quedan.append(pend)  # la tabla aún no se ha actualizado
            continue
        jugados = mio["pj"]
        faltan = [f for f in filas if f["pj"] < jugados]
        nota = ""
        if faltan:
            if len(faltan) <= 2 and horas >= 36:
                nota = "Queda algún partido aplazado de esta jornada."
            elif horas < 24 * 5:
                quedan.append(pend)
                continue
            else:
                nota = "Algunos equipos todavía no han jugado este partido."
        if enviar(mensaje_clasificacion(pend, filas, nota), estado):
            estado.setdefault("pj", {})[f"{pend['equipo']}|{pend['comp']}"] = jugados
        else:
            quedan.append(pend)
    estado["pendientes"] = quedan


def muestra(partidos):
    """Para comprobar a mano cómo quedan todos los mensajes."""
    print("== PRÓXIMOS PARTIDOS ==")
    for eq in CFG["equipos"]:
        prox = sorted((p for p in partidos if p["equipo"] == eq["clave"] and p["estado"] == "pre"),
                      key=lambda p: p["inicio"])[:3]
        for p in prox:
            print(f"  {fecha_iso(p['inicio']).astimezone(ZONA):%a %d/%m %H:%M}  {p['local']} - {p['visitante']}  [{p['comp_nombre']}]")
    prox = sorted((p for p in partidos if p["estado"] == "pre"), key=lambda p: p["inicio"])
    if prox:
        enviar(mensaje_manana([prox[0]] + [p for p in prox[1:3] if p["equipo"] != prox[0]["equipo"]]), {})
    barca = [p for p in prox if p["equipo"] == "barca"]
    if barca:
        enviar(mensaje_antes(barca[0]), {})
    for eq in CFG["equipos"]:
        hechos = sorted((p for p in partidos if p["equipo"] == eq["clave"] and p["estado"] == "post"
                         and p["comp"] in CFG["con_clasificacion"]), key=lambda p: p["inicio"])
        if hechos:
            p = hechos[-1]
            pend = {"equipo": p["equipo"], "comp": p["comp"], "resultado": resultado(p, eq),
                    "mio": id_en_tabla(p["equipo"], p["comp"])}
            enviar(mensaje_clasificacion(pend, clasificacion(p["comp"])), {})
    p = next((p for p in partidos if p["equipo"] == "barca" and p["comp"] == "uefa.champions"), None)
    if p:
        enviar(mensaje_clasificacion({"equipo": "barca", "comp": "uefa.champions", "mio": "83"},
                                     clasificacion("uefa.champions")), {})


def principal():
    estado = leer("estado.json", {})
    if "--test-telegram" in sys.argv:
        token = os.environ.get("TELEGRAM_TOKEN", "")
        if token:
            destinatarios(token, estado, buscar_nuevos=True)
        enviar("✅ Prueba: el bot de avisos del Barça, el Canarias y el Tenerife ya está conectado a este chat.", estado)
        guardar("estado.json", estado)
        return
    partidos = cargar_partidos(estado)
    if "--muestra" in sys.argv:
        muestra(partidos)
        return
    primera_vez = "terminados" not in estado
    if primera_vez:  # no mandamos clasificaciones de partidos que ya pasaron
        estado["terminados"] = [p["id"] for p in partidos if p["estado"] == "post"]
    if os.environ.get("TELEGRAM_TOKEN") and estado.get("resumen_dia") != HOY.isoformat():
        destinatarios(os.environ["TELEGRAM_TOKEN"], estado, buscar_nuevos=True)  # una vez al día
    resumen_manana(partidos, estado)
    avisos_antes(partidos, estado)
    partidos_terminados(partidos, estado)
    jornadas_terminadas(estado)
    if not PRUEBA:
        guardar("estado.json", estado)


if __name__ == "__main__":
    principal()
