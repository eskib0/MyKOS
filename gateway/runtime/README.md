# MyKOS Gateway Runtime

Servidor HTTP ligero y anfitrión de plugins nativo en Node.js para **MyKOS Gateway**.

## Inicio rápido

```bash
node mykos-gateway.mjs
```

## Variables de entorno

- `MYKOS_GATEWAY_PORT`: Puerto de escucha (por defecto `3210`).
- `MYKOS_GATEWAY_HOST`: Dirección de escucha (por defecto `127.0.0.1`).
- `MYKOS_GATEWAY_STATE_DIR`: Directorio de estado y almacén SQLite (por defecto `~/.mykos/gateway-state`).
- `MYKOS_GATEWAY_WORKSPACE_DIR`: Directorio de espacio de trabajo (por defecto `~/.mykos/workspace`).
- `MYKOS_GATEWAY_CONFIG`: Ruta al archivo `mykos-gateway.json`.
- `MYKOS_GATEWAY_SHUTDOWN_TIMEOUT_MS`: Tiempo máximo de espera al apagar en milisegundos (por defecto `5000`).
