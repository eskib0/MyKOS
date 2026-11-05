# Guía de Contribución a MyKOS Ecosystem (v2.0.0)

¡Gracias por tu interés en colaborar con **MyKOS**!  
MyKOS es un ecosistema soberano de inteligencia artificial de código abierto diseñado bajo principios de **cero dependencias opacas**, **auditoría transparente** y **seguridad de grado defensivo**.

---

## 🏛️ Filosofía y Arquitectura Modular

A partir de la versión **v2.0.0**, el repositorio está estructurado en módulos cohesivos y desacoplados:

- **`gateway/runtime/`**: Pasarela en Node.js que gestiona las 93 rutas API, 42 políticas HMAC (`policy.js`), almacén transaccional ACID (`store.js`) y bucle de chat local.
- **`gateway/app/tools/`**: Sub-paquete modular de herramientas (11 módulos especializados):
  - `schemas.py`: Catálogo formal de esquemas JSON y herramientas sensibles.
  - `filesystem.py`, `shell.py`, `git_tools.py`, `system.py`, `documents.py`, `web.py`, `memory.py`, `ollama.py`.
- **`gateway/app/core/`**: Sub-paquete de servicios del servidor backend:
  - `activity.py`: Seguimiento efímero de actividad y control de servidores locales.
  - `benchmark.py`: Suite de perfiles de rendimiento y telemetría.
  - `claude.py`: Integración con Claude CLI / suscripción claude.ai.
  - `integrity.py`: Guardia de integridad contra alucinaciones de acciones.
  - `ollama_catalog.py`: Integración con el catálogo público y descargas en segundo plano.
  - `providers.py`: Conectores y gestión de credenciales de proveedores remotos.
  - `runners.py`: Bucle universal de herramientas y runners de inferencia.
  - `uploads.py`: Gestión y saneamiento de archivos temporales multipart.
- **`tests/`**: Suite de pruebas unitarias de seguridad en la raíz del repositorio.

---

## 🛠️ Cómo Añadir una Nueva Herramienta en 3 Pasos (~20 líneas)

Para añadir una herramienta a MyKOS, sigue este flujo estándar:

### 1. Definir la función en el módulo adecuado
Crea o amplía un módulo dentro de `gateway/app/tools/` (por ejemplo, `gateway/app/tools/system.py`):

```python
# gateway/app/tools/system.py
def execute_mi_herramienta(args: dict[str, Any]) -> dict[str, Any]:
    parametro = str(args.get("parametro", "")).strip()
    # Tu lógica aquí...
    return {"ok": True, "resultado": f"Procesado: {parametro}"}
```

### 2. Registrar el esquema JSON en `schemas.py`
Añade la definición formal a `TOOL_SCHEMAS` en `gateway/app/tools/schemas.py`:

```python
{
    "type": "function",
    "function": {
        "name": "mi_herramienta",
        "description": "Descripción clara de lo que hace la herramienta para los modelos de IA.",
        "parameters": {
            "type": "object",
            "properties": {
                "parametro": {"type": "string", "description": "Parámetro de entrada"}
            },
            "required": ["parametro"]
        }
    }
}
```
*Si la herramienta realiza modificaciones en el disco o en el sistema, añade su nombre al conjunto `SENSITIVE_TOOL_NAMES` en el mismo archivo.*

### 3. Conectar el despachador en `gateway/app/tools/__init__.py`
Agrega el caso en la función `execute_tool`:

```python
elif name == "mi_herramienta":
    return execute_mi_herramienta(arguments)
```

---

## 🚦 Semáforo de Riesgo y Seguridad Proactiva

MyKOS implementa un semáforo heurístico en `gateway/app/tools/shell.py` (`analyze_action_risk`):
- 🟢 **Normal (Bajo Riesgo):** Lecturas de archivos, búsquedas, inspección de hardware, Git log.
- 🟡 **Warning (Riesgo Medio):** Modificación o creación de archivos en el área de trabajo (`workspace`).
- 🔴 **Critical (Alto Riesgo):** Comandos destructivos de terminal (`rm -rf`, `dd`, `mkfs`), llamadas a `sudo`, tuberías remotas a bash (`curl | sh`) o modificación de archivos del propio MyKOS (`mykos`).

Cualquier nueva herramienta que altere el estado del sistema debe respetar el semáforo y requerir aprobación en modo supervisado.

---

## 🧪 Ejecución de Pruebas

Antes de enviar cualquier Pull Request o realizar un commit, ejecuta la batería unificada de pruebas:

```bash
./bin/mykos test
```

La suite comprobará automáticamente:
1. Las 160 comprobaciones de integridad del Gateway (rutas, políticas HMAC, transacciones ACID, bucle de voz y control de procesos).
2. Las pruebas unitarias de aislamiento y seguridad (`tests/test_security_audit.py`):
   - Bloqueo estricto contra Path Traversal (`../`).
   - Transparencia en `allowed_roots.json`.
   - Heurísticas de riesgo y alertas anti-rubber-stamping.
   - Integridad estructural de los sub-paquetes `tools` y `core`.

---

## 📜 Reglas de Estilo y Compromisos

- **Sin regresiones:** Todas las pruebas deben pasar al 100%.
- **Zero-Trust:** Las herramientas de lectura se ejecutan en modo seguro; las de escritura pasan siempre por el flujo de autorizaciones del Gateway.
- **Commits semánticos:** Usa prefijos claros como `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- **Licencia:** MyKOS se distribuye bajo la licencia MIT. Todo código aportado debe ser compatible con dicha licencia.
