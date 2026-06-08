# Dockerfile para el bot ZEC-MA10 en Freqtrade
# Basado en la imagen oficial estable de Freqtrade.

FROM freqtradeorg/freqtrade:stable

# Copiamos el config y la estrategia dentro de la imagen.
# Los SECRETOS no van aqui: se inyectan como variables de entorno
# FREQTRADE__... en Easypanel en tiempo de ejecucion.
COPY config.json /freqtrade/config.json
COPY user_data/strategies/ /freqtrade/user_data/strategies/

# Comando de arranque: modo trade con nuestra estrategia.
# El historial de trades (sqlite) y los logs se persisten via volumen
# montado en /freqtrade/user_data (ver docker-compose / Easypanel).
ENTRYPOINT ["freqtrade"]
CMD ["trade", "--config", "/freqtrade/config.json", "--strategy", "MA10TouchStrategy"]
