# María · Reclutamiento Inteligente — Backend

API de **Cesar IA / María**, plataforma SaaS multi-tenant de reclutamiento automatizado. Gestiona el ciclo completo de preselección conversacional de candidatos (WhatsApp, Telegram, Email), parsing de CV, evaluación por LLM y scoring estructurado.

- **Stack**: FastAPI + SQLAlchemy 2.x + PostgreSQL, Python 3.12.
- **Despliegue**: Render (free tier), Docker, un único servicio web + una base de datos Postgres.
- **Frontend**: repo hermano `recruitment_bot_frontend` (React/Vite), documentado por separado.
- **Tenant activo en producción**: `cesaria` (cesaria.net).

> Este documento describe el **estado real del código en disco**, verificado directamente (no solo lo planeado). Donde el código y la intención original difieren, se indica explícitamente.

---

## 1. Arquitectura y estructura de carpetas

```
app/
├── main.py              # Punto de entrada FastAPI, monta todos los routers
├── core/                 # Config, sesión de BD, autenticación — LA fuente de verdad
│   ├── config.py          # Settings (pydantic-settings, lee variables de entorno)
│   ├── db.py               # engine, SessionLocal, Base declarativa, get_db()
│   └── security.py         # require_admin_token (autenticación actual, ver §4)
├── models/               # Paquete de modelos SQLAlchemy (uno por dominio)
├── schemas/              # Modelos Pydantic de entrada/salida de la API
├── routers/               # Endpoints HTTP, agrupados por área funcional
├── services/              # Lógica de negocio (lo que de verdad hace el trabajo)
├── channels/              # Integraciones de mensajería (WhatsApp/Twilio, Email/SendGrid)
├── cv_pipeline.py         # Extracción de texto de CV (PDF multipágina, imágenes vía OCR)
├── telegram_api.py        # Cliente ligero de la Bot API de Telegram
├── llm_client.py          # Cliente HTTP directo a la API de OpenAI (sin SDK)
├── logger.py              # log_event(): logging de eventos con sesión de BD propia
├── enums.py                # Enums compartidos (estados, plataformas, clasificación...)
├── static/                 # Página estática mínima servida en `/` (placeholder)
└── utils/                  # Utilidades pequeñas (normalización de teléfono)

sql/            # Migraciones manuales numeradas (001…010) — NO hay Alembic
scripts/         # Scripts de mantenimiento ejecutables por CLI o vía HTTP
docs/            # Documentación puntual de funcionalidades concretas
seeds/           # Datos de siembra
tests/            # pytest (cobertura parcial, ver §7)
patches_backup/  # Parches git (.patch) guardados en vez de aplicados — ver §6
```

**Principio de capas**: `routers/` no debería contener lógica de negocio compleja (aunque `admin.py` ha ido acumulando bastante — ver §8). La lógica vive en `services/`; `models/` son solo el mapeo ORM; `schemas/` son los contratos de entrada/salida de Pydantic.

---

## 2. Cómo arranca la aplicación

`start.sh` es el `ENTRYPOINT` del contenedor Docker. Antes de lanzar uvicorn, revisa variables de entorno opcionales para ejecutar tareas de mantenimiento puntuales **una sola vez** en el arranque (pensado para Render free tier, que no ofrece Shell interactiva):

- `RUN_BACKFILL=dry|1` → ejecuta `backfill_scores.py` (recalcula `score_total` de candidaturas atascadas sin volver a llamar al LLM). Idempotente.
- `REPROCESS_REFERENCE_APPLICATION_ID` + `REPROCESS_APPLY` + `REPROCESS_EXPECTED_COUNT` → ejecuta `scripts/reprocess_completed_cv_evaluations.py` (reprocesa OCR+LLM+scoring de un lote de candidaturas ya completadas). **No es idempotente** — retirar las variables tras usarlas.

**Importante**: estas variables deben **retirarse de Render tras usarlas**, o se repetirán en cada cold-start/redeploy (el free tier duerme el servicio y lo reinicia con cada petición tras inactividad).

Alternativa más segura para el reprocesado de CV, que **no depende de logs de Render** (el free tier no los expone de forma fiable): los endpoints HTTP `GET/POST /admin/v1/maintenance/cv-reprocess*` (ver §5), que devuelven el resultado directamente en la respuesta.

---

## 3. Modelo de datos (resumen)

Todas las tablas de negocio llevan `tenant_id` (multi-tenant por fila, sin esquemas separados). Sin ORM de migraciones: cada cambio de esquema es un fichero `sql/00N_descripcion.sql` aplicado **a mano** vía `psql` en la consola de Render, en orden, antes de desplegar el código que lo necesita.

| Modelo | Qué representa |
|---|---|
| `Tenant` | Empresa cliente. `settings_json` (JSONB) guarda configuración flexible: modo de conversación, prompts, info institucional, canal de email, `post_completion_mode`. Columnas propias para WhatsApp: `whatsapp_sender_address`, `whatsapp_messaging_service_sid`, `whatsapp_enabled`. |
| `Candidate` | Persona candidata, identificada por teléfono (`phone_e164`) y/o email. |
| `Vacancy` | Vacante. `cv_max_score` + Σ puntos de sus preguntas = presupuesto de 100 puntos. |
| `Application` | Candidatura (candidato × vacante). Lleva `status`, `classification`, `score_rules`, `score_cv`, `score_total`, `origin`, `preferred_platform`. |
| `Answer` | Respuesta de un candidato a una pregunta (de vacante o de tenant). `vacancy_question_id` es nullable para soportar preguntas de tenant. |
| `Question` / `VacancyQuestion` / `TenantQuestion` | Catálogo de preguntas reutilizables + su aplicación a una vacante o a todo el tenant, con `display_condition` para condicionales. |
| `CvDocument` | Fichero de CV: bytes en `content` (BYTEA, backend por defecto) o ruta en disco; texto extraído; metadatos de origen (`source_metadata_json`, incluye `media_url` de Twilio como fallback). |
| `AiEvaluation` | Resultado crudo y parseado de la llamada al LLM sobre un CV. |
| `ScoringRule` | Reglas de puntuación/descalificación configurables por vacante. |
| `ConversationSession` | Estado de la máquina de conversación (`ChatState`) por candidato/canal. Aquí vive el `post_completion_mode`. |
| `ConversationMessage` | Transcripción completa (inbound + outbound) por hilo, para la pantalla de Conversaciones. |
| `OutboundMessage` | Registro de mensajes salientes disparados por el reclutador (carga de CV, etc.). |
| `CvImportJob` / `CvImportJobItem` | Lotes de carga manual de CVs por el reclutador. |
| `User` *(huérfano)* | Modelo de usuario con roles. **Existe en el código pero no está en uso** — ver §6. |

---

## 4. Autenticación (estado actual: simple, de un solo token)

`app/core/security.py` implementa **un único mecanismo**: `require_admin_token`, que compara el `Authorization: Bearer <token>` contra la variable de entorno `ADMIN_TOKEN`. Sin usuarios, sin roles, sin expiración. Todo router que necesita protección declara `dependencies=[Depends(require_admin_token)]` (normalmente a nivel de `APIRouter`, no por endpoint).

Esto es deliberadamente simple hoy: **no existe sistema de alta de usuarios ni login propio en el backend actualmente activo.** El frontend tiene construida la UI para un sistema de roles (login con email+contraseña, alta de administrador inicial, gestión de empresas/usuarios) que habla con endpoints `/auth/*` y `/admin/v1/tenants`, `/admin/v1/users` — **pero esos endpoints no existen en el código desplegado ahora mismo.** Ver §6 y §9 para el porqué y la ruta para reactivarlo.

---

## 5. Inventario de funcionalidades vigentes

### 5.1 Flujo conversacional de preselección
- Máquina de estados (`ChatState`) por candidato/canal, orquestada en `services/recruitment.py`.
- Dos modos configurables por tenant (`settings_json.conversation_mode`): **classic** (flujo determinista) y **llm** (María guía la conversación con un LLM, prompts personalizables por tenant en `services/llm_conversation.py`).
- `post_completion_mode` por tenant: `silent_forever` (default — no vuelve a interactuar tras cerrar) o `reopen_next_day` (reabre al día siguiente, hora local RD UTC-4).
- Canales: **WhatsApp** (Twilio), **Telegram** (Bot API propia), **Email** (SendGrid, inbound + outbound) — el canal email está completo en backend pero **oculto en el frontend** por feature flag (`EMAIL_CHANNEL_ENABLED=false`), pendiente de validación end-to-end.
- Normalización de teléfono sin asumir región por defecto (`app/utils/phone.py` + `phonenumbers`), compatible con NANP y otros formatos; Telegram no manda "+" pero sí código de país.

### 5.2 Ingesta y evaluación de CV
- `cv_pipeline.py`: extracción de texto de PDF **multipágina** e imágenes (OCR vía `pytesseract`/`pdf2image`/`poppler`). Reprocesado disponible si se detectan mejoras posteriores (§5.6).
- Almacenamiento configurable (`STORAGE_BACKEND`): `db_blob` (bytes en Postgres, **backend por defecto y el único usado en producción**) o `local_fs`.
- Evaluación por LLM (`llm_client.py`, sin SDK, HTTP directo a OpenAI): perfil, resumen de experiencia, habilidades, red flags, `cv_score_0_10`, recomendación, y **prellenado automático de respuestas** a preguntas de screening cuando el CV ya las contesta (confianza ≥ 0.75, marcadas con `source=llm_cv_prefill`).
- Visor del **CV original** (PDF/imagen) desde el detalle de candidatura: prioriza bytes en BD, con fallback a re-descarga desde Twilio (vía `media_url` guardada) o Telegram (vía `file_id`).

### 5.3 Scoring
- Presupuesto fijo de 100 puntos por vacante: `cv_max_score` (CV) + Σ `max_points` de sus preguntas activas = 100. Validado al crear preguntas y al activar la vacante.
- `score_total = score_rules (preguntas) + score_cv (normalizado)`; clasificación en `shortlist / interview / review / reject` según umbrales de la vacante.
- Índices parciales únicos (no globales) en `(vacancy_id, question_order)` y `(vacancy_id, field_key)` con `WHERE is_active = true`, compatibles con soft-delete.

### 5.4 Preguntas
- **Preguntas de vacante** (específicas del puesto) vs **preguntas de tenant** (comunes a todas las vacantes de la empresa) — ambas comparten el mismo catálogo `Question` pero se aplican distinto.
- Tipos soportados de verdad: `text`, `boolean`, `number` (el frontend muestra otros tipos como "próximamente", deshabilitados).
- Condicionales (`display_condition`): mostrar una pregunta solo si otra anterior (de tipo `boolean`) cumple `equals`/`not_equals`/`exists`/`not_exists`.

### 5.5 Ranking y transcripción
- Endpoint de ranking separa candidaturas **completadas** (con `score_total`) de **incompletas** (aún en el flujo), con el punto exacto del flujo en que quedaron.
- Devuelve `applied_at` y el presupuesto de puntuación de la vacante (`cv_max_score`/`questions_max_score`) para que el frontend pinte "x / máx" sin recalcular nada.
- **Conversaciones**: transcripción completa por hilo (`ConversationMessage`), filtrable por vacante, con envío de mensajes del reclutador al candidato (respeta la ventana de 24h de WhatsApp).

### 5.6 Mantenimiento operativo (pensado para Render free tier, sin Shell ni logs fiables)
- `GET /admin/v1/maintenance/backfill-scores` (dry-run por defecto) — recalcula candidaturas atascadas sin llamar al LLM.
- `GET /admin/v1/maintenance/score-diagnosis/{application_id}` — explica por qué una candidatura no puntúa.
- `GET/POST /admin/v1/maintenance/cv-reprocess-scope` y `/cv-reprocess` — reprocesa OCR+LLM+scoring de un lote de candidaturas completadas (derivado de una candidatura de referencia, con guarda de `expected_count`), devolviendo el resultado **directamente en la respuesta HTTP** (ver `docs/reprocess_completed_cv_evaluations.md` para el detalle). Lógica compartida con el script de CLI `scripts/reprocess_completed_cv_evaluations.py` vía `services/cv_reprocessing.py` — ambos deben mantenerse en sync si se toca uno.

### 5.7 Multi-tenant — estado real
- Aislamiento por `tenant_id` en cada tabla y cada query: sí, robusto.
- **Alta de nuevas empresas**: actualmente **solo por INSERT SQL manual**. No existe endpoint activo para crear tenants (existió, se retiró — ver §6/§9).
- Número de WhatsApp remitente configurable por tenant desde el Perfil de la empresa (`whatsapp_sender_address`), con prioridad sobre el Messaging Service global de Twilio cuando la empresa tiene número propio.

---

## 6. Elementos legacy y código muerto (verificado en disco)

### 6.1 Capa monolítica original — pendiente de borrado físico
Estos ficheros son restos de la arquitectura previa a la migración a `app/core/`, `app/models/` (paquete) y `app/routers/`. **Ninguno se importa desde el código vivo** (verificado por grafo de imports). Existe un parche ya preparado para eliminarlos (`patches_backup/0003-Eliminar-capa-monol-tica-muerta-sin-referencias-desd.patch`) que **aún no se ha aplicado**:

```
app/api_admin.py          (vacío)
app/api_webhooks.py       (router monolítico antiguo, X-Admin-Token propio)
app/config.py             (Settings antiguo → vivo: app/core/config.py)
app/core.py               (shim de "compatibilidad hacia atrás" — su propio docstring lo admite)
app/database.py           (engine/sesión antiguos → vivo: app/core/db.py)
app/models_enums.py       (→ vivo: app/enums.py)
app/models_monolithic.py  (modelos todo-en-uno → vivo: paquete app/models/)
app/recruitment_service.py (vacío)
app/scoring.py            (raíz — → vivo: app/services/scoring.py y app/services/recruitment.py)
```

**Acción pendiente**: aplicar el parche o ejecutar directamente:
```
git rm app/api_admin.py app/api_webhooks.py app/config.py app/core.py app/database.py app/models_enums.py app/models_monolithic.py app/recruitment_service.py app/scoring.py
```

### 6.2 Sistema de roles — implementado, revertido, guardado como parche
Se construyó un sistema completo de usuarios/roles (superadmin vs company) con login propio, JWT-like firmado por HMAC, y gestión de empresas/usuarios vía API. **Se revirtió intencionalmente** en el backend (petición explícita: "no quiero que implementes el sistema de roles ahora") tras un incidente de despliegue, dejando la autenticación en el mecanismo simple de un solo token (§4).

**No se perdió**: existe íntegro en `patches_backup/0002-added-roles-managing-feature.patch` (9 ficheros, 462 líneas), listo para aplicarse con `git am patches_backup/0002-added-roles-managing-feature.patch` cuando se decida retomarlo. Incluye: `app/models/user.py`, `app/routers/auth.py`, ampliación de `app/core/security.py` (hash de contraseñas PBKDF2, tokens firmados HMAC, `AuthPrincipal`, `require_superadmin`), y endpoints de gestión de tenants/usuarios en `admin.py`.

**Ficheros huérfanos actuales** (no importados por nada, pero presentes en disco tras la reversión parcial):
```
app/models/user.py     — modelo SQLAlchemy del usuario, inerte
app/routers/auth.py    — router de /auth/*, inerte (no montado en main.py)
```
No rompen nada estando así, pero conviene decidir: aplicar el parche completo, o `git rm` de estos dos si se descarta definitivamente por ahora.

### 6.3 Frontend legacy con el que este backend convive
El repo del frontend **ya tiene construida** toda la UI de ese sistema de roles (login con email+contraseña, alta de administrador inicial, panel de Administración, dropdown de cambio de empresa) apuntando a los endpoints `/auth/*` que hoy no existen en el backend. Esas pantallas fallan de forma controlada (login cae al modo de token legado; el resto muestra errores en vez de romper), pero es deuda visible. Ver el README del frontend, §6.

### 6.4 Duplicado de `sql/011_users.sql`
El parche del §6.2 incluye `sql/011_users.sql` (tabla `users`). **No está aplicado a la base de datos actual** (se comprobó que el fichero no existe en `sql/` en disco — el parche lo crearía al aplicarse). Si se aplica el parche de código sin aplicar antes esta migración, el arranque fallará al intentar `SELECT` sobre una tabla inexistente en cuanto se ejercite `/auth/*`.

---

## 7. Tests

`tests/` tiene cobertura parcial: `test_api.py` (contra `app.main.app` con BD de test), `test_question_service.py`, `test_vacancy_service.py`. No cubren: canal email, reprocesado de CV, ranking, conversaciones, ni el flujo LLM. Ejecutar con `pytest` desde la raíz (requiere una `DATABASE_URL` de test válida en `.env`).

---

## 8. Deuda técnica conocida (más allá de lo "legacy")

- **`app/routers/admin.py` ha crecido mucho** (flujo de conversación, perfil de empresa, mantenimiento/reprocesado de CV, conversaciones/transcripción, ranking, detalle de candidatura, fichero de CV — todo en un solo fichero). Buen candidato a dividirse en varios routers por dominio cuando se retome trabajo estructural.
- Variables de entorno del canal email (`SENDGRID_API_KEY`, `EMAIL_DEFAULT_FROM`, `EMAIL_INBOUND_DOMAIN`, etc.) **no están declaradas en `render.yaml`** — se gestionan manualmente en el dashboard de Render, fuera de IaC. Mismo patrón detectado para el propio `DATABASE_URL` tras la migración de instancia de Postgres (causa raíz de un incidente de despliegue reciente).
- `render.yaml` declara el servicio con `fromDatabase`, pero el servicio real en Render **no parece gestionarse como Blueprint sincronizado** (el log de deploy muestra clonado directo de GitHub) — es decir, cambios en `render.yaml` no se reflejan automáticamente en las variables de entorno reales del servicio.

---

## 9. Ruta a seguir: sign up / login propio de entrada a producción + creación de nuevos clientes

Esta es la pieza que falta para dejar de depender de un único `ADMIN_TOKEN` compartido y para poder dar de alta clientes sin tocar SQL a mano. **Gran parte ya está construida** (§6.2); esto es una ruta de reactivación y cierre, no de invención desde cero.

### Paso 1 — Reactivar el sistema de roles ya construido
1. Aplicar la migración `sql/011_users.sql` (tabla `users`, roles `superadmin`/`company`) en la consola psql de Render **antes** de desplegar código nuevo.
2. Aplicar el parche `patches_backup/0002-added-roles-managing-feature.patch` (`git am ...`), o reconstruirlo si el árbol ha divergido demasiado para aplicarse en limpio.
3. Verificar en local (`py_compile` de los ficheros tocados como mínimo) antes de `git push`.
4. Definir `AUTH_SECRET` en Render (secreto de firma de tokens; si no se define, cae a `ADMIN_TOKEN` como fallback — funciona, pero mejor tener uno dedicado).
5. Desplegar y ejecutar `POST /auth/bootstrap` (o vía la pantalla de alta del frontend) para crear el primer superadmin — **solo funciona una vez, con la tabla vacía**.

### Paso 2 — Endurecer para producción real
El sistema reactivado es funcional pero pensado como MVP interno; antes de considerarlo "listo para producción" con clientes externos, conviene:
- **Expiración/refresco de sesión**: los tokens actuales caducan a los 7 días sin mecanismo de refresco — decidir si eso es aceptable o si hace falta refresh token.
- **Recuperación de contraseña**: no existe today (ni en el parche). Necesario antes de dar acceso a usuarios finales de cliente.
- **Rate limiting** en `/auth/login` y `/auth/bootstrap` (hoy sin límite — expuesto a fuerza bruta).
- **Auditoría**: registrar altas/bajas de usuarios y cambios de empresa en `system_logs` (la tabla ya existe y se usa para otros eventos).
- **Invitación por email** en vez de que el superadmin cree la contraseña directamente — mejor práctica y evita contraseñas compartidas por canales inseguros.
- Decidir si el `ADMIN_TOKEN` legado se **retira** una vez el sistema de roles esté maduro, o se mantiene indefinidamente para integraciones de servicio (cron, scripts). El código actual ya soporta ambos simultáneamente sin conflicto.

### Paso 3 — Creación de nuevos clientes (empresas) de forma autoservicio
El parche del §6.2 ya incluye `POST /admin/v1/tenants` (solo superadmin) para crear una empresa desde el panel, con slug autogenerado. Pendiente de decidir y construir, según qué tan autoservicio se quiera:
- **Alta con datos mínimos vs. wizard completo**: hoy el endpoint solo pide nombre; el Perfil de la empresa (28+ campos) se rellena después manualmente. Si se quiere un alta guiada de cliente nuevo, construir un wizard que encadene: crear tenant → invitar primer usuario `company` → guiar por Perfil de empresa → configurar canal (WhatsApp/número, o email) → crear primera vacante.
- **Aprovisionamiento de canal por cliente nuevo**: WhatsApp ya soporta número por tenant (§5.7); falta decidir el flujo operativo para dar de alta el número en Twilio (fuera del alcance de este backend, es gestión en la consola de Twilio) antes de que el cliente pueda usarlo.
- **Planes/límites por cliente**: no existe hoy ningún control de cuota (número de vacantes, candidaturas, usuarios) por tenant. Si el modelo de negocio lo requiere, es una capa nueva sobre `Tenant.settings_json` o una tabla dedicada.
- **Facturación**: fuera del alcance actual del código; no hay integración con ningún proveedor de pagos.

### Orden recomendado
1. Reactivar roles (Paso 1) — desbloquea todo lo demás y es prácticamente "copiar y pegar" lo ya construido.
2. Cerrar los huecos de seguridad mínimos de producción (Paso 2: recuperación de contraseña + rate limiting, como mínimo).
3. Construir el wizard de alta de cliente (Paso 3) — puede iterarse: primero el alta mínima ya cubierta por el parche, después ir añadiendo guía y aprovisionamiento de canal según haga falta.

---

## 10. Variables de entorno (referencia rápida)

Definidas en `app/core/config.py` (pydantic-settings, lee `.env` en local). Las marcadas `sync: false` en `render.yaml` se configuran a mano en el dashboard de Render.

| Variable | Uso |
|---|---|
| `DATABASE_URL` | Conexión Postgres (auto-generada por Render si se usa Blueprint) |
| `ADMIN_TOKEN` | Token único de autenticación actual (§4) |
| `LLM_API_KEY` / `OPENAI_API_KEY` | Clave de OpenAI para evaluación de CV y flujo LLM |
| `STORAGE_BACKEND` | `db_blob` (default) o `local_fs` |
| `DEFAULT_PHONE_REGION` | Región por defecto para parseo de teléfono ambiguo |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Credenciales Twilio (WhatsApp) |
| `TWILIO_WHATSAPP_MESSAGING_SERVICE_SID` / `TWILIO_WHATSAPP_FROM_ADDRESS` | Envío WhatsApp por defecto (global; cada tenant puede tener número propio) |
| `SENDGRID_API_KEY`, `EMAIL_DEFAULT_FROM`, `EMAIL_INBOUND_DOMAIN`, `EMAIL_INBOUND_ADDRESS`, `EMAIL_DEFAULT_TENANT_SLUG` | Canal email (backend activo, frontend oculto tras feature flag) |
| `PUBLIC_BASE_URL` | URL pública del servicio (usada en construcción de enlaces) |
| `AUTH_SECRET` *(pendiente de reintroducir con el Paso 1 de §9)* | Secreto de firma de tokens de usuario cuando se reactive el sistema de roles |

---

## 11. Puesta en marcha local

```bash
python -m venv .venv && source .venv/bin/activate   # o .venv\Scripts\activate en Windows
pip install -r requirements.txt
cp .env.example .env   # si existe; si no, crear .env con al menos DATABASE_URL y ADMIN_TOKEN
uvicorn app.main:app --reload
```

Aplicar migraciones manualmente en orden (`sql/001_...sql` → `sql/010_...sql`) contra la base de datos local antes del primer arranque.
