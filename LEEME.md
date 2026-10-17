# Avisos de partidos: Barça, Canarias y Tenerife

Bot de Telegram que avisa automáticamente (GitHub Actions, cada 10 minutos):

| Equipo | Mañana del partido (09:00) | 1 hora antes | Clasificación al acabar la jornada |
|---|---|---|---|
| 🔵🔴 FC Barcelona (todas las competiciones) | ✅ | ✅ | LaLiga y fase liga de Champions |
| 🏀 CB Canarias (La Laguna Tenerife, ACB) | ✅ | — | Liga Endesa |
| 💙🤍 CD Tenerife | ✅ | — | LaLiga Hypermotion |

El aviso de la mañana dice contra quién, dónde, a qué hora (hora suiza, y para los canarios también la de Canarias) y la tele si se sabe.
La clasificación llega cuando han jugado todos los equipos de la jornada (si hay algún aplazado, se manda igualmente al día siguiente y medio).
En copa o eliminatorias de Champions no hay tabla, así que solo hay aviso del partido.

Fuentes: ESPN (fútbol) y acb.com (baloncesto). Gratis y sin registro.

## Cambiar algo
Todo está en `config.json` (hora del resumen, minutos del aviso previo, equipos). Pídeselo a Claude.

## Lanzarlo a mano
En GitHub: pestaña **Actions** → «Avisos de partidos» → **Run workflow** (marca «Solo probar Telegram» para comprobar el bot).

El repositorio es público para que GitHub Actions sea gratis sin límite de minutos. No contiene nada privado:
el token del bot está en los *secrets* y el chat de Telegram se guarda cifrado.
