# Guia: Desplegar Bot SIMON en Oracle Cloud Free Tier

## Paso 1: Crear cuenta en Oracle Cloud

1. Ir a https://cloud.oracle.com/
2. Registrarse con "Start for Free" (pide tarjeta pero NO cobra)
3. Elegir region: **Brazil East (Sao Paulo)** o **US East** (la mas cercana a Colombia)

## Paso 2: Crear VM (Always Free)

1. En la consola de Oracle Cloud, ir a **Compute → Instances → Create Instance**
2. Configurar:
   - **Image**: Ubuntu 22.04 (Canonical)
   - **Shape**: VM.Standard.E2.1.Micro (Always Free) o Ampere A1 (ARM, tambien Free)
   - **Networking**: Crear VCN publica con subnet publica
   - **SSH Key**: Generar par de claves o subir tu clave publica
3. Click en **Create**

## Paso 3: Conectarse por SSH

```bash
# Desde tu PC (reemplaza con tu IP y clave)
ssh -i tu_clave_privada.pem ubuntu@<IP_DE_LA_VM>
```

Nota: La IP publica la encuentras en la pagina de la instancia en Oracle Cloud.

## Paso 4: Instalar todo

```bash
# Subir los archivos del bot al servidor
# Opcion A: con scp desde tu PC
scp -i tu_clave_privada.pem -r simon_bot_server/* ubuntu@<IP>:~/simon_bot/

# Opcion B: clonar desde GitHub (si tienes repo)
# git clone https://github.com/tu_usuario/simon_bot.git ~/simon_bot

# Conectarse al servidor
ssh -i tu_clave_privada.pem ubuntu@<IP>

# Ejecutar el script de instalacion
cd ~/simon_bot
chmod +x setup_oracle.sh setup_cron.sh run_bot.sh
./setup_oracle.sh
```

## Paso 5: Configurar credenciales

```bash
# Editar .env con tus credenciales reales
nano ~/simon_bot/.env
```

## Paso 6: Probar manualmente

```bash
cd ~/simon_bot
./run_bot.sh
```

Verificar que el bot corre sin errores. Los logs quedan en `~/simon_bot/logs/`.

## Paso 7: Configurar ejecucion automatica

```bash
./setup_cron.sh
```

Esto configura el cron para ejecutar:
- **Lunes a las 00:05** (reserva con 2 dias de anticipacion)
- **Viernes a las 00:05** (reserva con 2 dias de anticipacion)

## Verificar que funciona

```bash
# Ver cron configurado
crontab -l

# Ver logs despues de una ejecucion
ls -la ~/simon_bot/logs/
tail -50 ~/simon_bot/logs/bot_*.log

# Ver screenshots de debug
ls -la ~/simon_bot/debug/
```

## Comandos utiles

```bash
# Ejecutar manualmente
~/simon_bot/run_bot.sh

# Ver ultimo log
tail -100 $(ls -t ~/simon_bot/logs/bot_*.log | head -1)

# Desactivar cron temporalmente
crontab -l | grep -v simon_bot | crontab -

# Reactivar cron
./setup_cron.sh
```

## Firewall de Oracle Cloud

Si el bot no puede conectarse a simon.inder.gov.co:

```bash
# Verificar conectividad
curl -I https://simon.inder.gov.co

# Si esta bloqueado, agregar regla de egress en Oracle Cloud:
# Network → VCN → Security Lists → Egress Rules → Add:
#   Destination: 0.0.0.0/0
#   Protocol: TCP
#   Port: 443 (HTTPS)
```
