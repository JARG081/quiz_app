# Modo en vivo (futuro)

> **Estado:** NO implementar todavía. Este documento describe lo que haría falta para volver a agregar un modo en vivo, en el que el docente marca el ritmo y todo el curso responde la misma pregunta a la vez, **después** de terminar las fases 0 a 7 de `CAMBIOS.txt`.
>
> Última revisión: 2026-10-01.

## 1. Contexto

- La plataforma tuvo un modo en vivo tipo Kahoot (`sessions_app`) y se retiró en la **Fase 2** de `CAMBIOS.txt` para simplificar el producto al quiz normal.
- El código anterior queda en git con la etiqueta **`pre-quiz-normal`** (se crea en la Fase 0). Sirve como referencia para la interfaz: sala de espera, panel del docente, pantalla del estudiante, pausa y expulsión.
  - Para verlo: `git show pre-quiz-normal:backend/sessions_app/views.py`
  - Plantillas: `git show pre-quiz-normal:backend/templates/sessions_app/live_session_docente.html`
- **No restaurar ese código tal cual.** Tenía los errores de la sección 5, que son requisitos obligatorios del rediseño.

## 2. Principios (no negociables)

1. **La nota es el % de aciertos, igual que en el modo normal.** El tiempo de respuesta NUNCA afecta la nota. Así se evitan incoherencias entre modos y en las estadísticas.
2. **No hay un segundo sistema de calificación.** El modo en vivo es otra forma de llenar los mismos `Intento` y `RespuestaIntento` de la app `evaluaciones`. Las estadísticas del docente y del admin, las exportaciones y la revisión del estudiante funcionan sin cambios.
3. **Mismo ciclo de vida:** generar → verificar → publicar → **asignar** (con `modo=VIVO`) → resolver. La verificación y la publicación se exigen igual que en el modo normal.
4. **La respuesta correcta nunca llega al navegador del estudiante** mientras la pregunta esté abierta.

## 3. Puntos de extensión que el modo normal ya deja preparados

Están incluidos en la Fase 1 de `CAMBIOS.txt`. Si alguno no se implementó así, corregirlo primero.

| Punto | Dónde | Uso en el modo en vivo |
|---|---|---|
| `Asignacion.modo` (hoy solo `NORMAL`) | `evaluaciones/models.py` | Agregar `VIVO` a los choices |
| `Intento` / `RespuestaIntento` independientes del modo | `evaluaciones/models.py` | Un intento por estudiante y sesión |
| `guardar_respuesta()`, `enviar_intento()`, `nota_final()` | `evaluaciones/services.py` | Se reutilizan; solo cambia **cuándo** se permite responder |
| `RespuestaIntento.es_correcta` copiada al calificar | `evaluaciones/models.py` | El historial no depende de ediciones futuras |
| Exportación PDF/XLSX por asignación | `evaluaciones/views.py` | Sin cambios |

## 4. Modelo de datos a agregar

App nueva sugerida: `en_vivo` (no reutilizar `sessions_app`, que queda solo con migraciones de borrado).

```
SesionEnVivo
  asignacion        OneToOne Asignacion (modo=VIVO)
  codigo            CharField(8) único (generar con reintento ante colisión)
  estado            ESPERA | EN_CURSO | PAUSADO | FINALIZADO
  pregunta_actual   int (0 = no iniciada, 1..N)
  pregunta_abierta  bool  (True = se aceptan respuestas a la pregunta actual)
  mostrando_resultados bool (se reinicia al avanzar)
  permitir_ingreso  bool
  version           int   (sube en cada cambio de estado; el polling lo usa para saber si algo cambió)
  iniciada_en, finalizada_en

ParticipanteEnVivo
  sesion FK, estudiante FK, intento OneToOne Intento,
  expulsado bool, ultimo_ping DateTime
  unique (sesion, estudiante)
```

- Al **unirse**, se crea el `Intento` del estudiante (número 1). Una asignación `VIVO` permite exactamente 1 intento.
- Al **finalizar** la sesión, se llama a `enviar_intento(intento, automatico=True)` para cada participante. Las preguntas sin responder cuentan como incorrectas.
- Un estudiante expulsado: su intento se envía con lo que tenga y no puede volver a entrar.

## 5. Errores del modo anterior que se convierten en requisitos

| Código | Problema anterior | Requisito en el rediseño |
|---|---|---|
| S1 | APIs de estado, participantes, resultados y ranking sin control de acceso; `results_api` revelaba `es_correcta` de la pregunta en curso | `can_view_session(user, sesion)` en **todas** las vistas y APIs. Al estudiante no se le envía `es_correcta` hasta que `pregunta_abierta=False` y `mostrando_resultados=True` |
| L1 | La pausa se arrastraba a la pregunta siguiente | Si hay temporizador: guardar la pausa por pregunta y reiniciarla al avanzar. Sin temporizador, el problema no existe |
| L2 | Cada polling podía avanzar la pregunta, con carrera | **Solo el docente avanza.** Avance atómico: `filter(pk, pregunta_actual=n).update(pregunta_actual=n+1, version=F('version')+1)` |
| L3 | Doble envío → `IntegrityError` → 500 | `guardar_respuesta()` usa `update_or_create` (ya es así en el modo normal) |
| L4 | `mostrando_resultados` nunca se activaba | Botón "Mostrar resultados" del docente; se reinicia al avanzar |
| L5 | El ranking incluía a los expulsados | El ranking filtra `expulsado=False` |
| L6 | Redirección errónea de una sesión pausada | Una única función `url_para_estado(sesion, rol)` decide a dónde ir |

## 6. Flujo

**Docente**
1. En un quiz publicado y verificado: "Asignar" → modo **En vivo** → crea `Asignacion(modo=VIVO)` + `SesionEnVivo(ESPERA)` con su código.
2. **Sala de espera:** ve a los participantes conectados, cierra el ingreso, expulsa y pulsa **Iniciar**.
3. **Por pregunta:** abre la pregunta → ve "N de M respondieron" → **Cerrar pregunta** → **Mostrar resultados** (distribución por opción y la correcta) → **Siguiente**.
4. **Pausar** congela la pantalla de los estudiantes y bloquea las respuestas.
5. **Finalizar:** envía todos los intentos y lleva a los resultados de la asignación (la misma vista del modo normal).

**Estudiante**
1. Panel → "Unirse con código" (solo si tiene inscripción `APROBADA` en el curso).
2. Sala de espera → pregunta actual (sin temporizador o con temporizador solo de ritmo, ver 7.1) → puede cambiar su respuesta mientras la pregunta esté abierta → ve si acertó cuando el docente muestra los resultados.
3. Al finalizar ve su revisión según `mostrar_respuestas`. En vivo se recomienda `AL_ENVIAR`.

## 7. Decisiones pendientes

1. **Ritmo:**
   - **(Recomendado)** el docente avanza manualmente, sin temporizador. Es lo más simple y elimina L1 y L2.
   - Temporizador por pregunta **solo para marcar el ritmo**: al llegar a 0 se cierra la pregunta. No afecta la nota y nunca avanza solo; el docente sigue pulsando "Siguiente".
2. **Ranking:**
   - Sin ranking.
   - Ranking por número de aciertos, con empates en la misma posición (sin desempate por tiempo).
   - Mostrar solo el top 5, o también la posición propia a cada estudiante.
3. **¿Puede el estudiante cambiar su respuesta** mientras la pregunta está abierta? Recomendado: sí.
4. **¿Puede el docente reabrir una pregunta** ya cerrada? Recomendado: no.

## 8. Transporte en tiempo real

- **Fase inicial (recomendada): polling.**
  - Un solo endpoint `GET en_vivo/<id>/estado/?v=<version>`. Si `version` no cambió, devuelve `{"sin_cambios": true}` (respuesta mínima).
  - El estudiante consulta cada 2 s y el docente cada 1–2 s.
  - Con unos 40 estudiantes son unas 20 peticiones por segundo de consultas simples, aceptable para gunicorn con 3 workers.
  - El endpoint **nunca modifica estado**; el modo anterior sí lo hacía y de ahí venía L2.
- **Más adelante (opcional): WebSockets con Django Channels.**
  - Requiere ASGI (daphne o uvicorn), Redis como channel layer, un servicio Redis en `docker-compose.yml` y ajustar `nginx.conf` para `Upgrade`.
  - Solo vale la pena si hay más de unos 100 estudiantes simultáneos o el polling se nota lento.

## 9. Endpoints

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| POST | `quizzes/<id>/asignar/` (modo=VIVO) | Docente | Crea la asignación y la sesión |
| GET | `en_vivo/<id>/docente/` | Docente dueño | Panel (sala de espera y en curso) |
| POST | `en_vivo/<id>/iniciar/` · `abrir/` · `cerrar-pregunta/` · `mostrar-resultados/` · `siguiente/` · `pausar/` · `reanudar/` · `finalizar/` · `cerrar-ingreso/` | Docente dueño | Transiciones de estado (todas atómicas y validando el estado de origen) |
| POST | `en_vivo/<id>/expulsar/<estudiante_id>/` | Docente dueño | Expulsar |
| POST | `en_vivo/unirse/` | Estudiante | Unirse por código |
| GET | `en_vivo/<id>/` | Participante | Pantalla del estudiante |
| GET | `en_vivo/<id>/estado/?v=` | Docente o participante | Estado (sin efectos secundarios) |
| POST | `en_vivo/<id>/responder/` | Participante | Usa `guardar_respuesta()`; solo si `EN_CURSO` y `pregunta_abierta` |
| GET | `en_vivo/<id>/resultados-pregunta/<n>/` | Docente o participante | Distribución; la correcta solo si `mostrando_resultados` |

## 10. Criterios de aceptación

- Un usuario anónimo o un estudiante no participante recibe 302 o 403 en **todas** las rutas de `en_vivo/`.
- La respuesta JSON al estudiante no contiene la opción correcta mientras `pregunta_abierta=True`.
- Dos POST simultáneos a `siguiente/` avanzan una sola pregunta.
- `estado/` no modifica la base de datos (verificarlo con `assertNumQueries` o comprobando `version`).
- Un doble POST a `responder/` nunca da 500.
- Al finalizar, cada participante tiene un `Intento` ENVIADO y su nota es el % de aciertos.
- Dos estudiantes con las mismas respuestas y tiempos distintos obtienen la misma nota y la misma posición en el ranking.
- Los resultados en vivo aparecen en las estadísticas del docente y del admin sin cambiar el código de `analytics`.
- Un expulsado no aparece en el ranking y no puede volver a entrar.

## 11. Estimación y orden sugerido

1. Modelos, servicios de transición y pruebas (sin interfaz).
2. Endpoints y control de acceso.
3. Interfaz del docente y del estudiante, adaptando las plantillas de la etiqueta `pre-quiz-normal`.
4. Ranking (si se decide) y pulido.
5. (Opcional) Migrar a WebSockets.

Con el modo normal ya terminado, esfuerzo **medio**: lo más costoso es la interfaz; la calificación y las estadísticas ya existen.
