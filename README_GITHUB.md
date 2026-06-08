# Bot ZEC-MA10 — Freqtrade en Hyperliquid (GitHub → Easypanel)

Bot de trading automático para **ZEC/USDC:USDC** en Hyperliquid.
Estrategia: **toque de MA10 con filtro MA20**, timeframe **1h**, R:R **1:2**, apalancamiento **2x**, margen **aislado**. Solo largos. Notificaciones completas por Telegram.

---

## ⚠️ Antes de nada: seguridad

**NUNCA subas claves a GitHub.** Este repo está diseñado para que el `config.json` no contenga ningún secreto: todo lo sensible se inyecta como variables de entorno en Easypanel. El `.gitignore` ya excluye `.env` y los datos generados. Verifica siempre antes de un `git push` que no hay claves en ningún archivo.

---

## Estructura del repo

```
.
├── config.json                          # Config base (SIN secretos)
├── Dockerfile                           # Imagen basada en freqtrade oficial
├── docker-compose.yml                   # Solo para pruebas locales
├── .gitignore                           # Excluye .env y datos
├── .env.example                         # Plantilla de variables (copiar a .env)
└── user_data/
    └── strategies/
        └── MA10TouchStrategy.py         # La estrategia
```

---

## Cómo se gestionan los secretos y ajustes

Todo se controla con variables de entorno con prefijo `FREQTRADE__`, que **sobreescriben** los valores del `config.json` respetando el tipo. El doble guion bajo (`__`) marca el anidamiento dentro del JSON.

| Variable de entorno | Qué controla |
|---|---|
| `FREQTRADE__EXCHANGE__WALLET_ADDRESS` | Tu wallet principal (master, con 0x) |
| `FREQTRADE__EXCHANGE__PRIVATE_KEY` | Private key de la **API/Agent Wallet** (no la principal) |
| `FREQTRADE__TELEGRAM__TOKEN` | Token del bot de Telegram |
| `FREQTRADE__TELEGRAM__CHAT_ID` | Tu chat_id |
| `FREQTRADE__STAKE_AMOUNT` | Margen por operación (50 = 50 USDC) |
| `FREQTRADE__MAX_OPEN_TRADES` | Operaciones simultáneas |
| `FREQTRADE__DRY_RUN` | `true` = papel, `false` = dinero real |

La ventaja: ajustas el tamaño de operación, pasas de dry-run a live, o cambias las claves **sin tocar el código ni rehacer la imagen**. Solo editas la variable en Easypanel y reinicias el servicio.

---

## Paso 1 — Subir a GitHub

```bash
cd repo/
git init
git add .
git commit -m "Bot ZEC-MA10 Freqtrade Hyperliquid"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

Repo **privado** recomendado, aunque no haya secretos.

**Comprobación de seguridad antes del push:**
```bash
git grep -i "private" -- '*.json'   # no debe devolver claves reales
cat .gitignore | grep env           # confirma que .env esta excluido
```

---

## Paso 2 — Desplegar en Easypanel

1. **Crear servicio** → tipo **App** → fuente **GitHub** → seleccionas tu repo y rama `main`.
2. **Build**: Easypanel detecta el `Dockerfile` automáticamente. Método de build = Dockerfile.
3. **Variables de entorno**: en la sección **Environment**, pega las variables del `.env.example` con tus valores reales:
   ```
   FREQTRADE__EXCHANGE__WALLET_ADDRESS=0x...
   FREQTRADE__EXCHANGE__PRIVATE_KEY=...
   FREQTRADE__TELEGRAM__TOKEN=...
   FREQTRADE__TELEGRAM__CHAT_ID=...
   FREQTRADE__STAKE_AMOUNT=50
   FREQTRADE__MAX_OPEN_TRADES=1
   FREQTRADE__DRY_RUN=true
   ```
4. **Volumen persistente** (IMPORTANTE): en **Mounts/Volumes**, monta un volumen en:
   ```
   /freqtrade/user_data
   ```
   Sin esto, cada redeploy borra el historial de trades (la base de datos sqlite) y los logs.
5. **Sin puertos expuestos**: el `api_server` está desactivado. No publiques ningún puerto a internet.
6. **Deploy**. Revisa los logs: deberías ver el arranque de Freqtrade y un mensaje de inicio en tu Telegram.

---

## Paso 3 — Validar (no te saltes el orden)

1. **Dry-run** (ya activo por defecto): déjalo días, compara las señales de Telegram con lo que harías mirando el gráfico.
2. **Live mínimo**: cuando convenza, cambia en Easypanel `FREQTRADE__DRY_RUN=false` y reinicia. Empieza con `STAKE_AMOUNT` bajo (50).
3. **Escala** poco a poco revisando métricas reales.

Con `STAKE_AMOUNT=50` y leverage 2x → exposición 100 USDC por operación. Stop -4% → pérdida ~4 USDC.

---

## Comandos de Telegram (control desde el móvil)

| Comando | Acción |
|---|---|
| `/status` | Posiciones abiertas |
| `/profit` | Resumen P&L |
| `/balance` | Balance |
| `/forceexit all` | **Botón de pánico**: cierra todo ya |
| `/stopentry` | No abrir nuevas, mantener abiertas |
| `/stop` · `/start` | Parar / arrancar el bot |
| `/reload_config` | Recargar config |

---

## Cómo validar sin arriesgar dinero (dry-run)

El `config.json` arranca por defecto en **dry-run**: usa **precios reales de ZEC en mainnet** y simula las ejecuciones, sin firmar órdenes ni tocar fondos. Es la mejor forma de validar la estrategia, porque los datos son reales.

Plan de validación:
1. **Dry-run** unos días/semanas → compara las señales que te avisa por Telegram con lo que harías tú mirando el gráfico. Si no cuadra, ajustamos parámetros antes de arriesgar nada.
2. **Live con `STAKE_AMOUNT` mínimo** (50) → cuando convenza, cambias `FREQTRADE__DRY_RUN=false` en Easypanel y reinicias. La prueba real con poco dinero.
3. **Escalar** poco a poco revisando métricas reales.

---

## Mantenimiento

- **La API Wallet caduca** (Hyperliquid permite hasta 180 días, a veces menos). Si el bot empieza a avisar de "User or API Wallet does not exist", regenera la API Wallet y actualiza `FREQTRADE__EXCHANGE__PRIVATE_KEY` en Easypanel.
- **Cuenta separada del trading manual**: usa una subcuenta dedicada al bot para no mezclar con tu posición manual de ZEC.

---

## Recordatorio

Esto automatiza la **ejecución**, no el **riesgo**. El tamaño, el apalancamiento y la decisión de apagarlo cuando el mercado se descontrola siguen siendo tuyos. No es asesoramiento financiero.
