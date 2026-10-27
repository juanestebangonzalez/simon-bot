# Bot de reservas SIMON 2.0 INDER

Reserva automaticamente canchas de futbol en grama sintetica en
[SIMON 2.0 INDER](https://simon.inder.gov.co) para dos usuarios.

## Que hace

Se ejecuta de madrugada, cuando SIMON libera los cupos, e intenta reservar
el mejor bloque disponible para cada usuario.

| | |
|---|---|
| Escenarios | Moravia, y si no hay, Brasilia |
| Dias a reservar | usuario 2 el martes, usuario 1 el jueves |
| Horario | prioridad 10pm, luego 9pm, luego 8pm |
| Tercios | 1, 2 y 3 en ese orden |
| Participantes | 9 cedulas + quien reserva = 10 (minimo de SIMON) |
| Una por dia | si el usuario 1 aparta un dia, el 2 no repite ese dia |
| Aviso | mensaje de Telegram con el resultado |

Como SIMON solo deja reservar con 2 dias de anticipacion, el cron corre
**sabado** (para el martes) y **lunes** (para el jueves), a las 00:01
hora Colombia. Cada corrida solo alcanza los dias +2 y +3, asi que agregar
un dia en config.py no sirve si ninguna corrida lo alcanza.

Cada usuario tiene su dia asignado en `DIAS_DESEADOS_1` y `DIAS_DESEADOS_2`
(`config.py`): el usuario 1 va por el jueves y el usuario 2 por el martes,
asi que nunca compiten por el mismo cupo. Si aun asi dos coincidieran en un dia,
`UNA_RESERVA_POR_DIA` impide la reserva doble.

## Archivos

```
simon_bot.py        el bot
config.py           escenarios, dias, horas, cedulas, URLs
telegram_notify.py  avisos de Telegram
run_ahora.py        correrlo a mano (usuario 1, 2 o ambos)
.env                credenciales reales (NO se sube a GitHub)
.env.ejemplo        plantilla -> copiar a .env
server/             despliegue en Oracle Cloud
debug/              capturas y HTML de cada corrida
logs/               salida de cada corrida (solo en el servidor)
```

`debug/` y `logs/` se limpian solos: al arrancar, el bot borra todo lo que
tenga mas de 7 dias (`DEBUG_DIAS_RETENCION` en `config.py`), y `run_bot.sh`
hace lo mismo al terminar. Como el bot corre dos veces por semana, siempre
queda la corrida anterior para comparar y nada mas.

**Las credenciales van solo en el `.env`.** `config.py` esta en GitHub y
no tiene valores por defecto: si falta el `.env`, el bot avisa y no corre.
Hay un unico `config.py`, el de la raiz; el servidor usa ese mismo.

## Correrlo en el PC

```bash
pip install playwright python-dotenv
playwright install chromium
copy .env.ejemplo .env      # y llenar los valores
python run_ahora.py
```

## Servidor (Oracle Cloud)

```bash
cd ~/simon_bot
git pull
bash server/setup_oracle.sh   # solo la primera vez
bash server/setup_cron.sh
venv/bin/python telegram_notify.py   # probar el aviso
```

El cron queda como `1 5 * * 1,5`. **Son las 5 UTC, no las 0**: cron en
Ubuntu corre en UTC aunque `timedatectl` diga America/Bogota. 05:01 UTC
son las 00:01 en Colombia.

Ver los logs:

```bash
ls -lt ~/simon_bot/logs/ | head
tail -100 ~/simon_bot/logs/bot_*.log
```

## Como funciona el flujo en SIMON

Esto costo averiguarlo, asi que queda escrito:

1. Login y buscar el escenario en la lista de reservas.
2. Elegir el tercio en **"Selecciona la division a reservar"**.
   El bot no debe tocar nunca ese combobox despues: escribirle encima
   provoca un error 500 del servidor.
3. Clic en un bloque **verde** del calendario
   (`td.fc-timegrid-col[data-date]` -> `a.fc-event.bg-primary`;
   los magenta son `bg-error` = ocupados).
4. Se abre el panel lateral **"Creacion de Reserva"** con la fecha y la
   hora ya puestas y deshabilitadas. No hay nada que escribir ahi.
5. Boton **"Agregar Participantes"** -> dialogo -> se agrega cada cedula.
   Quien reserva ya viene en la tabla.
6. **"Guardar" dentro del panel** -> mete el bloque en el formulario.
7. **"Guardar" al final de la pagina** -> esto es lo que crea la reserva.
   Son dos botones distintos; con solo el primero no queda nada.
8. La reserva aparece en Seguimiento en estado **Pendiente**. Es normal.

## Cosas que rompen la reserva

- **Menos de 10 participantes.** SIMON responde
  "Debe seleccionar al menos 10 participantes". Con 9 cedulas no hay
  margen: si una falla, se pierde la reserva. Usar `CEDULAS_RESERVA_*`
  en `config.py` para tener suplentes.
- **Cedulas no registradas en SIMON.** El bot verifica cada una contra la
  tabla y reintenta una vez, pero si la persona no existe no hay nada
  que hacer.
- **Deteccion anti-bot (Radware).** Por eso el navegador usa un user
  agent real y oculta `navigator.webdriver`. No quitar esa parte.
